"""Browser and outbound-agent HTTP routes for workstation monitoring."""

import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.personal_dashboard import PersonalDashboardStore
from src.workstation_monitor import (
    MAX_SNAPSHOT_BYTES,
    AuthenticationError,
    NotFoundError,
    PairingConflictError,
    PayloadTooLargeError,
    RateLimitError,
    ReplayError,
    ValidationError,
    WorkstationError,
    WorkstationMonitor,
)


workstation_bp = Blueprint("workstation_bp", __name__)
monitor = None


def init_workstation_routes(config=None, dashboard_store=None):
    """Initialize routes, accepting an injected shared dashboard store."""
    global monitor
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    monitor = WorkstationMonitor(dashboard_store)
    return monitor


def _enabled():
    return os.getenv("KASUGAI_WORKSTATION_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _agent_endpoint():
    return request.endpoint in {
        "workstation_bp.pair_workstation_agent",
        "workstation_bp.ingest_workstation_snapshot",
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
        for item in os.getenv("KASUGAI_WORKSTATION_ALLOWED_USERS", "").split(",")
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


def _require_browser_csrf():
    expected = str(session.get("csrf_token") or "")
    supplied = str(request.headers.get("X-Kasugai-CSRF") or "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(403)


def _json_body(maximum_bytes):
    if request.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
        raise ValidationError("Compressed request bodies are not supported")
    if request.content_length is not None and request.content_length > maximum_bytes:
        raise PayloadTooLargeError("Request body is too large")
    raw = request.get_data(cache=True)
    if len(raw) > maximum_bytes:
        raise PayloadTooLargeError("Request body is too large")
    if not request.is_json:
        raise ValidationError("Request body must be JSON")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    return payload


def _bearer_token():
    header = request.headers.get("Authorization", "")
    scheme, separator, value = header.partition(" ")
    if not separator or scheme.lower() != "bearer" or not value.strip():
        raise AuthenticationError("Agent credentials are invalid")
    if len(value.strip()) > 256:
        raise AuthenticationError("Agent credentials are invalid")
    return value.strip()


@workstation_bp.before_request
def protect_workstation_routes():
    if monitor is None or not _enabled():
        abort(404)
    if _agent_endpoint():
        return
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_browser_csrf()


@workstation_bp.after_request
def workstation_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@workstation_bp.post("/api/workstations/pairings")
def create_workstation_pairing():
    try:
        payload = _json_body(1024)
        if payload:
            raise ValidationError("Pairing request does not accept fields")
        return jsonify(monitor.create_pairing(_owner_key())), 201
    except PayloadTooLargeError as exc:
        return jsonify({"error": str(exc)}), 413
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400


@workstation_bp.get("/api/workstations")
def list_workstations():
    return jsonify(monitor.list_workstations(_owner_key()))


@workstation_bp.get("/api/workstations/<agent_id>/latest")
def latest_workstation_snapshot(agent_id):
    try:
        return jsonify(monitor.latest(_owner_key(), agent_id))
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except WorkstationError:
        return jsonify({"error": "Stored workstation telemetry is unavailable"}), 500


@workstation_bp.get("/api/workstations/<agent_id>/history")
def workstation_history(agent_id):
    try:
        return jsonify(
            monitor.history(
                _owner_key(),
                agent_id,
                minutes=request.args.get("minutes", 60),
                bucket_seconds=request.args.get("bucket_seconds", 60),
            )
        )
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


@workstation_bp.patch("/api/workstations/<agent_id>")
def rename_workstation(agent_id):
    try:
        payload = _json_body(2048)
        if set(payload) != {"display_name"}:
            raise ValidationError("Only display_name may be changed")
        return jsonify(monitor.rename(_owner_key(), agent_id, payload["display_name"]))
    except PayloadTooLargeError as exc:
        return jsonify({"error": str(exc)}), 413
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


@workstation_bp.delete("/api/workstations/<agent_id>")
def revoke_workstation(agent_id):
    try:
        payload = _json_body(1024)
        if set(payload) - {"delete_history"}:
            raise ValidationError("Request contains unsupported fields")
        delete_history = payload.get("delete_history", True)
        if not isinstance(delete_history, bool):
            raise ValidationError("delete_history must be true or false")
        monitor.revoke(_owner_key(), agent_id, delete_history=delete_history)
        return "", 204
    except PayloadTooLargeError as exc:
        return jsonify({"error": str(exc)}), 413
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


@workstation_bp.post("/api/workstation-agent/v1/pair")
def pair_workstation_agent():
    try:
        result = monitor.pair_agent(_json_body(16 * 1024))
        return jsonify(result), 201
    except PayloadTooLargeError as exc:
        return jsonify({"error": str(exc)}), 413
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except AuthenticationError as exc:
        return jsonify({"error": str(exc)}), 401
    except PairingConflictError as exc:
        return jsonify({"error": str(exc)}), 409


@workstation_bp.post("/api/workstation-agent/v1/agents/<agent_id>/snapshots")
def ingest_workstation_snapshot(agent_id):
    try:
        result = monitor.ingest_snapshot(
            agent_id,
            _bearer_token(),
            _json_body(MAX_SNAPSHOT_BYTES),
        )
        return jsonify(result), 202
    except PayloadTooLargeError as exc:
        return jsonify({"error": str(exc)}), 413
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except AuthenticationError as exc:
        return jsonify({"error": str(exc)}), 401
    except ReplayError as exc:
        return jsonify({"error": str(exc)}), 409
    except RateLimitError as exc:
        response = jsonify({"error": str(exc)})
        response.status_code = 429
        response.headers["Retry-After"] = str(exc.retry_after)
        return response
