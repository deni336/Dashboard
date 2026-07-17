"""Browser and outbound-agent routes for the safe launcher runner."""

import hmac
import os
import re

from flask import Blueprint, abort, jsonify, request, session

from src.launcher_runner import (
    MAX_CATALOG_BYTES,
    MAX_RESULT_BYTES,
    AuthenticationError,
    ConflictError,
    ExpiredError,
    LauncherError,
    LauncherRunner,
    NotFoundError,
    PairingConflictError,
    PayloadTooLargeError,
    PermissionDeniedError,
    RateLimitError,
    ReplayError,
    ValidationError,
)
from src.personal_dashboard import PersonalDashboardStore


launcher_bp = Blueprint("launcher_bp", __name__)
runner = None


def init_launcher_routes(config=None, dashboard_store=None):
    global runner
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    runner = LauncherRunner(dashboard_store)
    return runner


def _enabled():
    return os.getenv("KASUGAI_LAUNCHER_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _agent_endpoint():
    return request.endpoint in {
        "launcher_bp.pair_launcher_agent",
        "launcher_bp.ingest_launcher_catalog",
        "launcher_bp.claim_launcher_run",
        "launcher_bp.submit_launcher_result",
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
        for item in os.getenv("KASUGAI_LAUNCHER_ALLOWED_USERS", "").split(",")
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


def _translate_error(exc):
    if isinstance(exc, PayloadTooLargeError):
        return jsonify({"error": str(exc)}), 413
    if isinstance(exc, ValidationError):
        return jsonify({"error": str(exc)}), 400
    if isinstance(exc, AuthenticationError):
        return jsonify({"error": str(exc)}), 401
    if isinstance(exc, PermissionDeniedError):
        return jsonify({"error": str(exc)}), 403
    if isinstance(exc, NotFoundError):
        return jsonify({"error": str(exc)}), 404
    if isinstance(exc, (ReplayError, ConflictError, ExpiredError, PairingConflictError)):
        return jsonify({"error": str(exc)}), 409
    if isinstance(exc, RateLimitError):
        response = jsonify({"error": str(exc)})
        response.status_code = 429
        response.headers["Retry-After"] = str(exc.retry_after)
        return response
    return jsonify({"error": "Launcher data is unavailable"}), 500


@launcher_bp.before_request
def protect_launcher_routes():
    if runner is None or not _enabled():
        abort(404)
    if _agent_endpoint():
        return
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_browser_csrf()


@launcher_bp.after_request
def launcher_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@launcher_bp.post("/api/launcher/pairings")
def create_launcher_pairing():
    try:
        payload = _json_body(1024)
        if payload:
            raise ValidationError("Pairing request does not accept fields")
        result = runner.create_pairing(_owner_key())
        origin = request.url_root.rstrip("/")
        # Host is ultimately request metadata. Keep the copy/paste command free
        # of shell metacharacters even when a deployment accepts an unusual
        # Host header; users can replace the placeholder with their URL.
        if not re.fullmatch(r"https?://[A-Za-z0-9.\-:\[\]/_~%]+", origin):
            origin = "<dashboard-url>"
        result["command"] = (
            f'python -m launcher_agent pair --server "{origin}" '
            f"--pairing-id {result['pairing_id']}"
        )
        return jsonify(result), 201
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.get("/api/launcher/agents")
def list_launcher_agents():
    try:
        return jsonify(runner.list_agents(_owner_key()))
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.patch("/api/launcher/agents/<agent_id>")
def rename_launcher_agent(agent_id):
    try:
        payload = _json_body(2048)
        if set(payload) != {"display_name"}:
            raise ValidationError("Only display_name may be changed")
        return jsonify(runner.rename(_owner_key(), agent_id, payload["display_name"]))
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.delete("/api/launcher/agents/<agent_id>")
def revoke_launcher_agent(agent_id):
    try:
        payload = _json_body(1024)
        if payload:
            raise ValidationError("Revocation request does not accept fields")
        runner.revoke(_owner_key(), agent_id)
        return "", 204
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.get("/api/launcher/catalog")
def launcher_catalog():
    try:
        return jsonify(runner.catalog(_owner_key()))
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.post("/api/launcher/tasks/<task_id>/runs")
def create_launcher_run(task_id):
    try:
        result = runner.queue_run(_owner_key(), task_id, _json_body(2048))
        return jsonify(result), 202 if result.get("queued") else 200
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.get("/api/launcher/runs")
def list_launcher_runs():
    try:
        return jsonify(runner.list_runs(_owner_key(), limit=request.args.get("limit", 50)))
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.get("/api/launcher/runs/<run_id>")
def get_launcher_run(run_id):
    try:
        return jsonify(runner.get_run(_owner_key(), run_id))
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.post("/api/launcher-agent/v1/pair")
def pair_launcher_agent():
    try:
        return jsonify(runner.pair_agent(_json_body(16 * 1024))), 201
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.post("/api/launcher-agent/v1/agents/<agent_id>/catalog")
def ingest_launcher_catalog(agent_id):
    try:
        result = runner.ingest_catalog(
            agent_id, _bearer_token(), _json_body(MAX_CATALOG_BYTES)
        )
        return jsonify(result), 202
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.post("/api/launcher-agent/v1/agents/<agent_id>/runs/claim")
def claim_launcher_run(agent_id):
    try:
        result = runner.claim_run(agent_id, _bearer_token(), _json_body(1024))
        if result is None:
            return "", 204
        return jsonify(result)
    except LauncherError as exc:
        return _translate_error(exc)


@launcher_bp.post("/api/launcher-agent/v1/agents/<agent_id>/runs/<run_id>/result")
def submit_launcher_result(agent_id, run_id):
    try:
        result = runner.submit_result(
            agent_id, _bearer_token(), run_id, _json_body(MAX_RESULT_BYTES)
        )
        return jsonify(result), 202
    except LauncherError as exc:
        return _translate_error(exc)
