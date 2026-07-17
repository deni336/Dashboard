"""Authenticated browser routes for the encrypted Personal Hub."""

import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.personal_dashboard import PersonalDashboardStore
from src.personal_hub import (
    CapacityError,
    ConflictError,
    HubError,
    NotFoundError,
    PersonalHub,
    StorageError,
    ValidationError,
)


personal_hub_bp = Blueprint("personal_hub_bp", __name__)
hub = None
MAX_WRITE_BODY_BYTES = 16 * 1024


class _PayloadTooLargeError(Exception):
    pass


def init_personal_hub_routes(
    config=None,
    dashboard_store=None,
    *,
    clock=None,
    id_factory=None,
):
    """Initialize the Personal Hub over the shared PersonalDashboardStore."""

    global hub
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    hub = PersonalHub(dashboard_store, clock=clock, id_factory=id_factory)
    return hub


def _enabled():
    return os.getenv("KASUGAI_PERSONAL_HUB_ENABLED", "true").strip().lower() in {
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
        for item in os.getenv("KASUGAI_PERSONAL_HUB_ALLOWED_USERS", "").split(",")
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
        return jsonify({"error": "Personal Hub data is unavailable"}), 500
    return jsonify({"error": "Personal Hub request could not be completed"}), 500


@personal_hub_bp.before_request
def protect_personal_hub_routes():
    if hub is None or not _enabled():
        abort(404)
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_csrf()


@personal_hub_bp.after_request
def personal_hub_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@personal_hub_bp.get("/api/personal-hub")
def list_personal_hub():
    try:
        _no_query()
        return jsonify(hub.list(_owner_key()))
    except HubError as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@personal_hub_bp.post("/api/personal-hub/items")
def create_personal_hub_item():
    try:
        _no_query()
        return jsonify(
            hub.create(_owner_key(), _json_body(MAX_WRITE_BODY_BYTES))
        ), 201
    except (HubError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@personal_hub_bp.get("/api/personal-hub/items/<item_id>")
def get_personal_hub_item(item_id):
    try:
        _no_query()
        return jsonify(hub.get(_owner_key(), item_id))
    except HubError as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@personal_hub_bp.patch("/api/personal-hub/items/<item_id>")
def update_personal_hub_item(item_id):
    try:
        _no_query()
        return jsonify(
            hub.update(_owner_key(), item_id, _json_body(MAX_WRITE_BODY_BYTES))
        )
    except (HubError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@personal_hub_bp.delete("/api/personal-hub/items/<item_id>")
def delete_personal_hub_item(item_id):
    try:
        _no_query()
        payload = _json_body(1024)
        if set(payload) != {"version"}:
            if "version" not in payload:
                raise ValidationError("version is required")
            raise ValidationError(
                f"Request contains unsupported field {sorted(set(payload) - {'version'})[0]}"
            )
        hub.delete(_owner_key(), item_id, payload["version"])
        return "", 204
    except (HubError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@personal_hub_bp.post("/api/personal-hub/items/<item_id>/check-in")
def toggle_personal_hub_checkin(item_id):
    try:
        _no_query()
        return jsonify(hub.toggle_checkin(_owner_key(), item_id, _json_body(2048)))
    except (HubError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)
