"""Authenticated, read-only routes for the Network & Security Center."""

import os

from flask import Blueprint, abort, current_app, jsonify, request, session

from src.personal_dashboard import PersonalDashboardStore
from src.security_center import SecurityCenter


security_bp = Blueprint("security_bp", __name__)
security_center = None


def init_security_routes(
    config=None,
    dashboard_store=None,
    *,
    workstation_monitor=None,
    homelab_monitor=None,
    launcher_runner=None,
    clock=None,
):
    """Initialize the read-only center over existing owner-scoped monitors."""
    global security_center
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    security_center = SecurityCenter(
        dashboard_store,
        workstation_monitor=workstation_monitor,
        homelab_monitor=homelab_monitor,
        launcher_runner=launcher_runner,
        clock=clock,
    )
    return security_center


def _environment_enabled(name, default=False):
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _enabled():
    return _environment_enabled("KASUGAI_SECURITY_ENABLED", True)


def _owner_key():
    profile = session.get("profile") or {}
    value = profile.get("id") or profile.get("email")
    if not value:
        abort(401)
    return str(value).strip().lower()


def _require_browser_access():
    configured = {
        item.strip().lower()
        for item in os.getenv("KASUGAI_SECURITY_ALLOWED_USERS", "").split(",")
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


@security_bp.before_request
def protect_security_routes():
    if security_center is None or not _enabled():
        abort(404)
    _require_browser_access()
    _owner_key()


@security_bp.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@security_bp.get("/api/security/overview")
def security_overview():
    if request.args:
        return jsonify({"error": "Security overview does not accept query parameters"}), 400
    try:
        return jsonify(
            security_center.overview(
                _owner_key(),
                secure_cookie=bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
                trust_proxy=_environment_enabled("KASUGAI_TRUST_PROXY", False),
            )
        )
    except Exception:
        return jsonify({"error": "Security overview is unavailable"}), 500


__all__ = ["init_security_routes", "security_bp"]
