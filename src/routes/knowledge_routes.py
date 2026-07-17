"""Authenticated browser routes for the encrypted Knowledge Vault."""

import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.knowledge_vault import (
    CapacityError,
    ConflictError,
    KnowledgeVault,
    NotFoundError,
    StorageError,
    ValidationError,
    VaultError,
)
from src.personal_dashboard import PersonalDashboardStore


knowledge_bp = Blueprint("knowledge_bp", __name__)
vault = None
MAX_WRITE_BODY_BYTES = 96 * 1024


class _PayloadTooLargeError(Exception):
    pass


def init_knowledge_routes(
    config=None,
    dashboard_store=None,
    *,
    clock=None,
    id_factory=None,
):
    """Initialize the vault over the shared PersonalDashboardStore."""

    global vault
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    vault = KnowledgeVault(
        dashboard_store,
        clock=clock,
        id_factory=id_factory,
    )
    return vault


def _enabled():
    return os.getenv("KASUGAI_KNOWLEDGE_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _owner_key():
    profile = session.get("profile") or {}
    value = profile.get("id") or profile.get("email")
    if not value:
        abort(401)
    return str(value).strip().lower()


def _require_browser_access():
    configured = {
        item.strip().lower()
        for item in os.getenv("KASUGAI_KNOWLEDGE_ALLOWED_USERS", "").split(",")
        if item.strip()
    }
    if not configured:
        return
    profile = session.get("profile") or {}
    candidates = {
        str(profile.get("id") or "").strip().lower(),
        str(profile.get("email") or "").strip().lower(),
    }
    if not configured.intersection(candidates):
        abort(403)


def _require_csrf():
    expected = str(session.get("csrf_token") or "")
    supplied = str(request.headers.get("X-Kasugai-CSRF") or "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(403)


def _json_body(maximum_bytes):
    encoding = request.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in {"", "identity"}:
        raise ValidationError("Compressed request bodies are not supported")
    if request.content_length is not None and request.content_length > maximum_bytes:
        raise _PayloadTooLargeError("Request body is too large")
    raw = request.get_data(cache=True)
    if len(raw) > maximum_bytes:
        raise _PayloadTooLargeError("Request body is too large")
    if not request.is_json:
        raise ValidationError("Request body must be JSON")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    return payload


def _no_query():
    if request.args:
        raise ValidationError("This endpoint does not accept query parameters")


def _translate_error(exc):
    if isinstance(exc, _PayloadTooLargeError):
        return jsonify({"error": str(exc)}), 413
    if isinstance(exc, ValidationError):
        return jsonify({"error": str(exc)}), 400
    if isinstance(exc, NotFoundError):
        return jsonify({"error": str(exc)}), 404
    if isinstance(exc, ConflictError):
        payload = {"error": str(exc)}
        if exc.current_version is not None:
            payload["current_version"] = exc.current_version
        return jsonify(payload), 409
    if isinstance(exc, CapacityError):
        return jsonify({"error": str(exc)}), 409
    if isinstance(exc, StorageError):
        return jsonify({"error": "Knowledge data is unavailable"}), 500
    return jsonify({"error": "Knowledge request could not be completed"}), 500


@knowledge_bp.before_request
def protect_knowledge_routes():
    if vault is None or not _enabled():
        abort(404)
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_csrf()


@knowledge_bp.after_request
def knowledge_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@knowledge_bp.get("/api/knowledge")
def list_knowledge():
    try:
        allowed = {"kind", "q", "tag", "pinned"}
        unknown = set(request.args) - allowed
        if unknown:
            raise ValidationError(
                f"Query contains unsupported parameter {sorted(unknown)[0]}"
            )
        for name in allowed:
            if len(request.args.getlist(name)) > 1:
                raise ValidationError("Knowledge query parameters may not be repeated")
        pinned_value = request.args.get("pinned")
        if pinned_value is None:
            pinned = None
        elif pinned_value == "true":
            pinned = True
        elif pinned_value == "false":
            pinned = False
        else:
            raise ValidationError("pinned filter must be true or false")
        return jsonify(
            vault.list(
                _owner_key(),
                kind=request.args.get("kind", "all"),
                q=request.args.get("q", ""),
                tag=request.args.get("tag", ""),
                pinned=pinned,
            )
        )
    except VaultError as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@knowledge_bp.get("/api/knowledge/<item_id>")
def get_knowledge(item_id):
    try:
        _no_query()
        return jsonify(vault.get(_owner_key(), item_id))
    except VaultError as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@knowledge_bp.post("/api/knowledge")
def create_knowledge():
    try:
        _no_query()
        return jsonify(vault.create(_owner_key(), _json_body(MAX_WRITE_BODY_BYTES))), 201
    except (VaultError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@knowledge_bp.patch("/api/knowledge/<item_id>")
def update_knowledge(item_id):
    try:
        _no_query()
        return jsonify(
            vault.update(_owner_key(), item_id, _json_body(MAX_WRITE_BODY_BYTES))
        )
    except (VaultError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@knowledge_bp.delete("/api/knowledge/<item_id>")
def delete_knowledge(item_id):
    try:
        _no_query()
        payload = _json_body(1024)
        if set(payload) != {"version"}:
            missing = "version" not in payload
            if missing:
                raise ValidationError("version is required")
            raise ValidationError(
                f"Request contains unsupported field {sorted(set(payload) - {'version'})[0]}"
            )
        vault.delete(_owner_key(), item_id, payload["version"])
        return "", 204
    except (VaultError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@knowledge_bp.post("/api/knowledge/<item_id>/duplicate")
def duplicate_knowledge(item_id):
    try:
        _no_query()
        payload = _json_body(1024)
        if payload:
            raise ValidationError("Duplicate request does not accept fields")
        return jsonify(vault.duplicate(_owner_key(), item_id)), 201
    except (VaultError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)
