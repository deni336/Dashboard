"""Owner-scoped browser and outbound-agent routes for homelab monitoring."""

import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.homelab_monitor import (
    MAX_RESULT_BYTES,
    MAX_SNAPSHOT_BYTES,
    AuthenticationError,
    ConflictError,
    ExpiredError,
    HomelabError,
    HomelabMonitor,
    NotFoundError,
    PairingConflictError,
    PayloadTooLargeError,
    PermissionDeniedError,
    RateLimitError,
    ReplayError,
    ValidationError,
)
from src.personal_dashboard import PersonalDashboardStore


homelab_bp = Blueprint("homelab_bp", __name__)
monitor = None


def init_homelab_routes(config=None, dashboard_store=None):
    """Initialize the module with the shared personal-dashboard database."""
    global monitor
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    monitor = HomelabMonitor(dashboard_store)
    return monitor


def _enabled():
    return os.getenv("KASUGAI_HOMELAB_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _agent_endpoint():
    return request.endpoint in {
        "homelab_bp.pair_homelab_agent",
        "homelab_bp.ingest_homelab_snapshot",
        "homelab_bp.claim_homelab_action",
        "homelab_bp.submit_homelab_action_result",
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
        for item in os.getenv("KASUGAI_HOMELAB_ALLOWED_USERS", "").split(",")
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
    if not separator or scheme.lower() != "bearer" or not value.strip() or len(value.strip()) > 256:
        raise AuthenticationError("Agent credentials are invalid")
    return value.strip()


def _json_error(exc, status):
    return jsonify({"error": str(exc)}), status


def _translate_common_error(exc):
    if isinstance(exc, PayloadTooLargeError):
        return _json_error(exc, 413)
    if isinstance(exc, ValidationError):
        return _json_error(exc, 400)
    if isinstance(exc, AuthenticationError):
        return _json_error(exc, 401)
    if isinstance(exc, PermissionDeniedError):
        return _json_error(exc, 403)
    if isinstance(exc, NotFoundError):
        return _json_error(exc, 404)
    if isinstance(exc, (ReplayError, ConflictError, ExpiredError)):
        return _json_error(exc, 409)
    if isinstance(exc, PairingConflictError):
        return _json_error(exc, 409)
    if isinstance(exc, RateLimitError):
        response = jsonify({"error": str(exc)})
        response.status_code = 429
        response.headers["Retry-After"] = str(exc.retry_after)
        return response
    return jsonify({"error": "Homelab data is unavailable"}), 500


@homelab_bp.before_request
def protect_homelab_routes():
    if monitor is None or not _enabled():
        abort(404)
    if _agent_endpoint():
        return
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_browser_csrf()


@homelab_bp.after_request
def homelab_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@homelab_bp.post("/api/homelab/pairings")
def create_homelab_pairing():
    try:
        payload = _json_body(1024)
        if payload:
            raise ValidationError("Pairing request does not accept fields")
        return jsonify(monitor.create_pairing(_owner_key())), 201
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.get("/api/homelab/agents")
def list_homelab_agents():
    try:
        return jsonify(monitor.list_agents(_owner_key()))
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.get("/api/homelab/agents/<agent_id>/latest")
def latest_homelab_snapshot(agent_id):
    try:
        return jsonify(monitor.latest(_owner_key(), agent_id))
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.get("/api/homelab/agents/<agent_id>/history")
def homelab_history(agent_id):
    try:
        return jsonify(monitor.history(_owner_key(), agent_id, hours=request.args.get("hours", 24)))
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.patch("/api/homelab/agents/<agent_id>")
def rename_homelab_agent(agent_id):
    try:
        payload = _json_body(2048)
        if set(payload) != {"display_name"}:
            raise ValidationError("Only display_name may be changed")
        return jsonify(monitor.rename(_owner_key(), agent_id, payload["display_name"]))
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.delete("/api/homelab/agents/<agent_id>")
def revoke_homelab_agent(agent_id):
    try:
        payload = _json_body(1024)
        if set(payload) - {"delete_history"}:
            raise ValidationError("Request contains unsupported fields")
        delete_history = payload.get("delete_history", True)
        if not isinstance(delete_history, bool):
            raise ValidationError("delete_history must be true or false")
        monitor.revoke(_owner_key(), agent_id, delete_history=delete_history)
        return "", 204
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.post("/api/homelab/agents/<agent_id>/actions")
def create_homelab_action(agent_id):
    """Queue read_logs, or preview/confirm the more disruptive restart action."""
    try:
        result = monitor.queue_action(_owner_key(), agent_id, _json_body(4096))
        return jsonify(result), 202 if result.get("queued") else 200
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.get("/api/homelab/agents/<agent_id>/actions")
def list_homelab_actions(agent_id):
    try:
        return jsonify(
            monitor.list_actions(_owner_key(), agent_id, limit=request.args.get("limit", 50))
        )
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.get("/api/homelab/agents/<agent_id>/actions/<action_id>")
def get_homelab_action(agent_id, action_id):
    try:
        return jsonify(monitor.get_action(_owner_key(), agent_id, action_id))
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.post("/api/homelab-agent/v1/pair")
def pair_homelab_agent():
    try:
        return jsonify(monitor.pair_agent(_json_body(16 * 1024))), 201
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.post("/api/homelab-agent/v1/agents/<agent_id>/snapshots")
def ingest_homelab_snapshot(agent_id):
    try:
        result = monitor.ingest_snapshot(agent_id, _bearer_token(), _json_body(MAX_SNAPSHOT_BYTES))
        return jsonify(result), 202
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.post("/api/homelab-agent/v1/agents/<agent_id>/actions/claim")
def claim_homelab_action(agent_id):
    try:
        result = monitor.claim_action(agent_id, _bearer_token(), _json_body(1024))
        if result is None:
            return "", 204
        return jsonify(result)
    except HomelabError as exc:
        return _translate_common_error(exc)


@homelab_bp.post("/api/homelab-agent/v1/agents/<agent_id>/actions/<action_id>/result")
def submit_homelab_action_result(agent_id, action_id):
    try:
        result = monitor.submit_result(
            agent_id, _bearer_token(), action_id, _json_body(MAX_RESULT_BYTES)
        )
        return jsonify(result), 202
    except HomelabError as exc:
        return _translate_common_error(exc)

