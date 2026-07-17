"""Authenticated browser routes for declarative dashboard automations."""

import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.automation_engine import (
    AutomationEngine,
    AutomationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    StorageError,
    ValidationError,
)
from src.personal_dashboard import PersonalDashboardStore


automation_bp = Blueprint("automation_bp", __name__)
engine = None


def init_automation_routes(
    config=None,
    dashboard_store=None,
    *,
    launcher_runner=None,
    clock=None,
    timezone=None,
):
    global engine
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    engine = AutomationEngine(
        dashboard_store,
        launcher_runner=launcher_runner,
        clock=clock,
        timezone=timezone,
    )
    return engine


def _enabled():
    return os.getenv("KASUGAI_AUTOMATION_ENABLED", "true").strip().lower() in {
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
        for item in os.getenv("KASUGAI_AUTOMATION_ALLOWED_USERS", "").split(",")
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
    if request.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
        raise ValidationError("Compressed request bodies are not supported")
    if request.content_length is not None and request.content_length > maximum_bytes:
        raise ValidationError("Request body is too large")
    raw = request.get_data(cache=True)
    if len(raw) > maximum_bytes:
        raise ValidationError("Request body is too large")
    if not request.is_json:
        raise ValidationError("Request body must be JSON")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    return payload


def _translate_error(exc):
    if isinstance(exc, ValidationError):
        status = 413 if str(exc) == "Request body is too large" else 400
        return jsonify({"error": str(exc)}), status
    if isinstance(exc, NotFoundError):
        return jsonify({"error": str(exc)}), 404
    if isinstance(exc, PermissionDeniedError):
        return jsonify({"error": str(exc)}), 403
    if isinstance(exc, ConflictError):
        return jsonify({"error": str(exc)}), 409
    if isinstance(exc, StorageError):
        return jsonify({"error": "Automation data is unavailable"}), 500
    return jsonify({"error": "Automation request could not be completed"}), 500


@automation_bp.before_request
def protect_automation_routes():
    if engine is None or not _enabled():
        abort(404)
    _require_browser_access()
    _owner_key()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_csrf()


@automation_bp.after_request
def automation_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@automation_bp.get("/api/automations")
def list_automations():
    try:
        return jsonify(engine.list(_owner_key()))
    except AutomationError as exc:
        return _translate_error(exc)


@automation_bp.get("/api/automations/catalog")
def automation_catalog():
    try:
        return jsonify(engine.catalog(_owner_key()))
    except AutomationError as exc:
        return _translate_error(exc)


@automation_bp.post("/api/automations")
def create_automation():
    try:
        return jsonify(engine.create_rule(_owner_key(), _json_body(16 * 1024))), 201
    except AutomationError as exc:
        return _translate_error(exc)


@automation_bp.patch("/api/automations/<rule_id>")
def update_automation(rule_id):
    try:
        return jsonify(engine.update_rule(_owner_key(), rule_id, _json_body(16 * 1024)))
    except AutomationError as exc:
        return _translate_error(exc)


@automation_bp.delete("/api/automations/<rule_id>")
def delete_automation(rule_id):
    try:
        if request.content_length not in {None, 0} or request.get_data(cache=False):
            raise ValidationError("Delete request does not accept a body")
        engine.delete_rule(_owner_key(), rule_id)
        return "", 204
    except AutomationError as exc:
        return _translate_error(exc)


@automation_bp.post("/api/automations/<rule_id>/run")
def run_automation(rule_id):
    try:
        payload = _json_body(1024)
        if payload:
            raise ValidationError("Run request does not accept fields")
        return jsonify(engine.run_rule(_owner_key(), rule_id))
    except AutomationError as exc:
        return _translate_error(exc)
