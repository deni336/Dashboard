"""Authenticated browser routes for the local-only AI Toolbox."""

import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.local_ai_toolbox import (
    AIToolboxError,
    BusyError,
    CapacityError,
    ConflictError,
    EndpointError,
    LocalAIToolbox,
    NotFoundError,
    StorageError,
    ValidationError,
)
from src.personal_dashboard import PersonalDashboardStore


ai_toolbox_bp = Blueprint("ai_toolbox_bp", __name__)
toolbox = None
MAX_CREATE_BODY_BYTES = 2048
MAX_MESSAGE_BODY_BYTES = 20 * 1024
MAX_DELETE_BODY_BYTES = 1024


class _PayloadTooLargeError(Exception):
    pass


def init_ai_toolbox_routes(
    config=None,
    dashboard_store=None,
    *,
    completion_client=None,
    clock=None,
    id_factory=None,
    global_concurrency=4,
):
    global toolbox
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    toolbox = LocalAIToolbox(
        dashboard_store,
        completion_client=completion_client,
        clock=clock,
        id_factory=id_factory,
        global_concurrency=global_concurrency,
    )
    return toolbox


def _enabled():
    return os.getenv("KASUGAI_AI_TOOLBOX_ENABLED", "true").strip().lower() in {
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
        for item in os.getenv("KASUGAI_AI_TOOLBOX_ALLOWED_USERS", "").split(",")
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
    if isinstance(exc, BusyError):
        response = jsonify({"error": "Local AI is busy; try again shortly"})
        response.status_code = 429
        response.headers["Retry-After"] = "2"
        return response
    if isinstance(exc, EndpointError):
        return jsonify({"error": "Local AI is unavailable"}), 503
    if isinstance(exc, StorageError):
        return jsonify({"error": "AI session data is unavailable"}), 500
    return jsonify({"error": "AI Toolbox request could not be completed"}), 500


@ai_toolbox_bp.before_request
def protect_ai_toolbox_routes():
    if toolbox is None or not _enabled():
        abort(404)
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_csrf()


@ai_toolbox_bp.after_request
def ai_toolbox_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@ai_toolbox_bp.get("/api/ai-toolbox")
def list_ai_toolbox():
    try:
        _no_query()
        return jsonify(toolbox.list(_owner_key()))
    except AIToolboxError as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@ai_toolbox_bp.post("/api/ai-toolbox/sessions")
def create_ai_session():
    try:
        _no_query()
        return jsonify(toolbox.create(_owner_key(), _json_body(MAX_CREATE_BODY_BYTES))), 201
    except (AIToolboxError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@ai_toolbox_bp.get("/api/ai-toolbox/sessions/<session_id>")
def get_ai_session(session_id):
    try:
        _no_query()
        return jsonify(toolbox.get(_owner_key(), session_id))
    except AIToolboxError as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@ai_toolbox_bp.post("/api/ai-toolbox/sessions/<session_id>/messages")
def create_ai_message(session_id):
    try:
        _no_query()
        return jsonify(
            toolbox.message(
                _owner_key(), session_id, _json_body(MAX_MESSAGE_BODY_BYTES)
            )
        )
    except (AIToolboxError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@ai_toolbox_bp.delete("/api/ai-toolbox/sessions/<session_id>")
def delete_ai_session(session_id):
    try:
        _no_query()
        payload = _json_body(MAX_DELETE_BODY_BYTES)
        if set(payload) != {"version"}:
            if "version" not in payload:
                raise ValidationError("version is required")
            raise ValidationError(
                f"Request contains unsupported field {sorted(set(payload) - {'version'})[0]}"
            )
        toolbox.delete(_owner_key(), session_id, payload["version"])
        return "", 204
    except (AIToolboxError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)

