"""Authenticated browser routes for the unified nerd inbox."""

import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.nerd_inbox import (
    SOURCE_IDS,
    InboxError,
    NerdInbox,
    NotFoundError,
    StorageError,
    ValidationError,
)
from src.personal_dashboard import PersonalDashboardStore


inbox_bp = Blueprint("inbox_bp", __name__)
inbox = None


class _PayloadTooLargeError(Exception):
    """Internal request-boundary error used to return HTTP 413."""


def init_inbox_routes(
    config=None,
    dashboard_store=None,
    *,
    developer_cockpit=None,
    workstation_monitor=None,
    homelab_monitor=None,
    launcher_runner=None,
    clock=None,
):
    """Initialize the inbox over the shared personal-dashboard store."""

    global inbox
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    inbox = NerdInbox(
        dashboard_store,
        developer_cockpit=developer_cockpit,
        workstation_monitor=workstation_monitor,
        homelab_monitor=homelab_monitor,
        launcher_runner=launcher_runner,
        clock=clock,
    )
    return inbox


def _enabled():
    return os.getenv("KASUGAI_INBOX_ENABLED", "true").strip().lower() in {
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
        for item in os.getenv("KASUGAI_INBOX_ALLOWED_USERS", "").split(",")
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


def _translate_error(exc):
    if isinstance(exc, _PayloadTooLargeError):
        return jsonify({"error": str(exc)}), 413
    if isinstance(exc, ValidationError):
        return jsonify({"error": str(exc)}), 400
    if isinstance(exc, NotFoundError):
        return jsonify({"error": str(exc)}), 404
    if isinstance(exc, StorageError):
        return jsonify({"error": "Inbox data is unavailable"}), 500
    return jsonify({"error": "Inbox request could not be completed"}), 500


@inbox_bp.before_request
def protect_inbox_routes():
    if inbox is None or not _enabled():
        abort(404)
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_csrf()


@inbox_bp.after_request
def inbox_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@inbox_bp.get("/api/inbox")
def get_inbox():
    try:
        unknown = set(request.args) - {"state", "source"}
        if unknown:
            raise ValidationError(
                f"Query contains unsupported parameter {sorted(unknown)[0]}"
            )
        if len(request.args.getlist("state")) > 1 or len(
            request.args.getlist("source")
        ) > 1:
            raise ValidationError("Inbox query parameters may not be repeated")
        return jsonify(
            inbox.get(
                _owner_key(),
                state=request.args.get("state", "active"),
                source=request.args.get("source"),
            )
        )
    except InboxError as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@inbox_bp.patch("/api/inbox/<item_id>")
def patch_inbox_item(item_id):
    try:
        return jsonify(inbox.patch_state(_owner_key(), item_id, _json_body(4 * 1024)))
    except (InboxError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)


@inbox_bp.post("/api/inbox/mark-all-read")
def mark_all_inbox_read():
    try:
        payload = _json_body(1024)
        unknown = set(payload) - {"source"}
        if unknown:
            raise ValidationError(
                f"Request contains unsupported field {sorted(unknown)[0]}"
            )
        source = payload.get("source")
        if "source" in payload and source not in SOURCE_IDS:
            raise ValidationError("source is unsupported")
        return jsonify(inbox.mark_all_read(_owner_key(), source=source))
    except (InboxError, _PayloadTooLargeError) as exc:
        return _translate_error(exc)
    except Exception as exc:
        return _translate_error(exc)
