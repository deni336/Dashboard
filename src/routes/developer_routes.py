import hmac
import os

from flask import Blueprint, abort, jsonify, request, session

from src.global_logger import GlobalLogger
from src.personal_dashboard import DeveloperCockpit, PersonalDashboardStore


developer_bp = Blueprint("developer_bp", __name__)
logger = GlobalLogger.get_logger("DeveloperRoutes")
store = None
cockpit = None


def init_developer_routes(config=None, dashboard_store=None):
    global store, cockpit
    if dashboard_store is None:
        if config is None:
            raise ValueError("config or dashboard_store is required")
        dashboard_store = PersonalDashboardStore(config)
    store = dashboard_store
    cockpit = DeveloperCockpit(store)
    return cockpit


def _owner_key():
    profile = session.get("profile") or {}
    value = profile.get("id") or profile.get("email")
    if not value:
        abort(401)
    return str(value).strip().lower()


def _require_developer_access():
    configured = {
        item.strip().lower()
        for item in os.getenv("KASUGAI_DEVELOPER_ALLOWED_USERS", "").split(",")
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


def _require_mutation():
    if not request.is_json:
        abort(415)
    expected = str(session.get("csrf_token") or "")
    supplied = str(request.headers.get("X-Kasugai-CSRF") or "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(403)


def _request_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)
    return data


@developer_bp.before_request
def protect_developer_routes():
    _require_developer_access()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_mutation()


@developer_bp.after_request
def developer_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@developer_bp.get("/api/developer/overview")
def developer_overview():
    owner_key = _owner_key()
    try:
        depth = request.args.get("depth", "4")
        return jsonify(cockpit.overview(owner_key, depth))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Unable to build developer overview: %s", exc)
        return jsonify({"error": "Unable to inspect repositories right now"}), 500


@developer_bp.get("/api/developer/roots")
def list_developer_roots():
    return jsonify(cockpit.public_roots(_owner_key()))


@developer_bp.post("/api/developer/roots")
def add_developer_root():
    data = _request_object()
    try:
        root = cockpit.add_root(_owner_key(), data.get("path"), data.get("label"))
        return jsonify(cockpit.public_root(root, available=True)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@developer_bp.delete("/api/developer/roots/<int:root_id>")
def delete_developer_root(root_id):
    try:
        cockpit.remove_root(_owner_key(), root_id)
    except KeyError as exc:
        return jsonify({"error": str(exc.args[0])}), 404
    return "", 204


@developer_bp.put("/api/developer/repositories/<repository_key>/favorite")
def favorite_repository(repository_key):
    data = _request_object()
    if not isinstance(data.get("favorite"), bool):
        return jsonify({"error": "favorite must be true or false"}), 400
    try:
        cockpit.set_favorite(_owner_key(), repository_key, data["favorite"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": repository_key, "favorite": data["favorite"]})


@developer_bp.route("/api/developer/github/settings", methods=["GET", "PUT", "DELETE"])
def github_settings():
    owner_key = _owner_key()
    if request.method == "GET":
        return jsonify(store.connector_status(owner_key, "github"))
    if request.method == "DELETE":
        store.delete_connector(owner_key, "github")
        return "", 204
    data = _request_object()
    try:
        return jsonify(cockpit.configure_github(owner_key, data.get("token")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502


@developer_bp.get("/api/developer/github/notifications")
def github_notifications():
    try:
        return jsonify(cockpit.github_notifications(_owner_key()))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
