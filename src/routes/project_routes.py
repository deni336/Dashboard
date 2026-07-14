import re
from datetime import date
from urllib.parse import urlsplit

from flask import Blueprint, abort, jsonify, render_template, request, session

from src.global_logger import GlobalLogger
from src.project_manager import ProjectStore


project_bp = Blueprint("project_bp", __name__)
logger = GlobalLogger.get_logger("ProjectRoutes")
store = None

PROJECT_STATUSES = {"planned", "active", "on_hold", "completed", "archived"}
PRIORITIES = {"low", "medium", "high", "critical"}
HEALTH_VALUES = {"on_track", "at_risk", "off_track"}
RECORD_KINDS = {"task", "milestone", "risk", "assumption", "issue", "dependency", "decision"}
RECORD_STATUSES = {"open", "in_progress", "blocked", "monitoring", "resolved", "done"}
INFLUENCE_VALUES = {"low", "medium", "high"}
ENGAGEMENT_VALUES = {"unaware", "resistant", "neutral", "supportive", "leading"}
PROVIDERS = {"github", "gmail", "calendar", "drive", "teams", "slack", "jira", "notion", "other"}
PROJECT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,15}$")
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def init_project_routes(config):
    global store
    store = ProjectStore(config)


def _owner_key():
    profile = session.get("profile") or {}
    value = profile.get("id") or profile.get("email")
    if not value:
        abort(401)
    return str(value).strip().lower()


def _json_body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")
    return value


def _text(data, key, *, required=False, maximum=5000, default=None):
    if key not in data:
        if required:
            raise ValueError(f"{key} is required")
        return default
    value = data[key]
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{key} is required")
    if len(value) > maximum:
        raise ValueError(f"{key} must be {maximum} characters or fewer")
    return value


def _enum(data, key, allowed, *, default=None, required=False):
    value = _text(data, key, required=required, maximum=40, default=default)
    if value is None:
        return None
    value = value.lower()
    if value not in allowed:
        raise ValueError(f"{key} must be one of {', '.join(sorted(allowed))}")
    return value


def _date(data, key, *, default=None, required=False):
    if key not in data and default is not None:
        value = default
    else:
        value = _text(data, key, required=required, maximum=10, default=default)
    if not value:
        return None if not required else value
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{key} must be a valid ISO date") from exc


def _integer(data, key, *, default=None, minimum=0, maximum=100):
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _money(data, key, *, default=None):
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not 0 <= value <= 1_000_000_000_000:
        raise ValueError(f"{key} must be between 0 and 1000000000000")
    return round(value, 2)


def _project_values(data, partial=False):
    values = {}
    if not partial or "name" in data:
        values["name"] = _text(data, "name", required=True, maximum=160)
    if not partial or "code" in data:
        code = _text(data, "code", required=True, maximum=16).upper()
        if not PROJECT_CODE.fullmatch(code):
            raise ValueError("code must contain 2-16 uppercase letters, numbers, underscores, or hyphens")
        values["code"] = code
    text_fields = {
        "description": 10000,
        "manager": 160,
        "sponsor": 160,
    }
    for key, maximum in text_fields.items():
        if not partial or key in data:
            values[key] = _text(data, key, maximum=maximum, default="")
    enum_fields = {
        "status": (PROJECT_STATUSES, "planned"),
        "priority": (PRIORITIES, "medium"),
        "health": (HEALTH_VALUES, "on_track"),
    }
    for key, (allowed, default) in enum_fields.items():
        if not partial or key in data:
            values[key] = _enum(data, key, allowed, default=default)
    for key in ("start_date", "target_date"):
        if not partial or key in data:
            values[key] = _date(data, key)
    if not partial or "budget" in data:
        values["budget"] = _money(data, "budget", default=0)
    if not partial or "progress" in data:
        values["progress"] = _integer(data, "progress", default=0)
    start = values.get("start_date")
    target = values.get("target_date")
    if start and target and target < start:
        raise ValueError("target_date cannot be before start_date")
    return values


def _record_values(data, partial=False):
    values = {}
    if not partial or "kind" in data:
        values["kind"] = _enum(data, "kind", RECORD_KINDS, required=True)
    if not partial or "title" in data:
        values["title"] = _text(data, "title", required=True, maximum=200)
    for key, maximum in (("details", 12000), ("owner", 160), ("resolution", 12000)):
        if not partial or key in data:
            values[key] = _text(data, key, maximum=maximum, default="")
    if not partial or "status" in data:
        values["status"] = _enum(data, "status", RECORD_STATUSES, default="open")
    if not partial or "priority" in data:
        values["priority"] = _enum(data, "priority", PRIORITIES, default="medium")
    if not partial or "due_date" in data:
        values["due_date"] = _date(data, "due_date")
    return values


def _meeting_values(data, partial=False):
    values = {}
    if not partial or "title" in data:
        values["title"] = _text(data, "title", required=True, maximum=200)
    if not partial or "held_on" in data:
        values["held_on"] = _date(
            data,
            "held_on",
            default=date.today().isoformat(),
            required=True,
        )
    for key, maximum in (
        ("attendees", 5000),
        ("notes", 30000),
        ("decisions", 20000),
        ("action_items", 20000),
        ("next_steps", 20000),
    ):
        if not partial or key in data:
            values[key] = _text(data, key, maximum=maximum, default="")
    return values


def _stakeholder_values(data, partial=False):
    values = {}
    if not partial or "name" in data:
        values["name"] = _text(data, "name", required=True, maximum=160)
    for key, maximum in (("role", 160), ("notes", 10000)):
        if not partial or key in data:
            values[key] = _text(data, key, maximum=maximum, default="")
    if not partial or "email" in data:
        email = _text(data, "email", maximum=254, default="")
        if email and not EMAIL.fullmatch(email):
            raise ValueError("email must be a valid address")
        values["email"] = email
    if not partial or "influence" in data:
        values["influence"] = _enum(data, "influence", INFLUENCE_VALUES, default="medium")
    if not partial or "engagement" in data:
        values["engagement"] = _enum(data, "engagement", ENGAGEMENT_VALUES, default="neutral")
    return values


def _connection_values(data, partial=False):
    values = {}
    if not partial or "provider" in data:
        values["provider"] = _enum(data, "provider", PROVIDERS, default="other")
    if not partial or "label" in data:
        values["label"] = _text(data, "label", required=True, maximum=120)
    if not partial or "account" in data:
        values["account"] = _text(data, "account", maximum=254, default="")
    if not partial or "url" in data:
        url = _text(data, "url", required=True, maximum=2048)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("url must be an HTTP or HTTPS address without embedded credentials")
        values["url"] = url
    if not partial or "project_id" in data:
        raw = data.get("project_id")
        if raw in (None, ""):
            values["project_id"] = None
        else:
            try:
                project_id = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("project_id must be an integer or null") from exc
            if project_id <= 0:
                raise ValueError("project_id must be positive")
            values["project_id"] = project_id
    return values


@project_bp.errorhandler(KeyError)
def project_not_found(error):
    return jsonify({"error": str(error.args[0])}), 404


@project_bp.errorhandler(ValueError)
def invalid_project_request(error):
    return jsonify({"error": str(error)}), 400


@project_bp.route("/projects")
def workspace_page():
    return render_template("project_manager.html", user=session.get("profile", {}))


@project_bp.route("/api/projects/portfolio")
def get_portfolio():
    return jsonify(store.portfolio(_owner_key()))


@project_bp.route("/api/projects", methods=["POST"])
def create_project():
    project = store.create_project(_owner_key(), _project_values(_json_body()))
    return jsonify(project), 201


@project_bp.route("/api/projects/<int:project_id>")
def get_project(project_id):
    return jsonify(store.workspace(_owner_key(), project_id))


@project_bp.route("/api/projects/<int:project_id>", methods=["PATCH"])
def update_project(project_id):
    values = _project_values(_json_body(), partial=True)
    if not values:
        raise ValueError("No project fields were supplied")
    return jsonify(store.update_project(_owner_key(), project_id, values))


@project_bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
def delete_project(project_id):
    store.delete_project(_owner_key(), project_id)
    return "", 204


@project_bp.route("/api/projects/<int:project_id>/records", methods=["POST"])
def create_record(project_id):
    return jsonify(store.create_record(_owner_key(), project_id, _record_values(_json_body()))), 201


@project_bp.route("/api/project-records/<int:record_id>", methods=["PATCH"])
def update_record(record_id):
    values = _record_values(_json_body(), partial=True)
    if not values:
        raise ValueError("No record fields were supplied")
    return jsonify(store.update_record(_owner_key(), record_id, values))


@project_bp.route("/api/project-records/<int:record_id>", methods=["DELETE"])
def delete_record(record_id):
    store.delete_record(_owner_key(), record_id)
    return "", 204


@project_bp.route("/api/projects/<int:project_id>/meetings", methods=["POST"])
def create_meeting(project_id):
    return jsonify(store.create_meeting(_owner_key(), project_id, _meeting_values(_json_body()))), 201


@project_bp.route("/api/project-meetings/<int:meeting_id>", methods=["PATCH"])
def update_meeting(meeting_id):
    values = _meeting_values(_json_body(), partial=True)
    if not values:
        raise ValueError("No meeting fields were supplied")
    return jsonify(store.update_meeting(_owner_key(), meeting_id, values))


@project_bp.route("/api/project-meetings/<int:meeting_id>", methods=["DELETE"])
def delete_meeting(meeting_id):
    store.delete_meeting(_owner_key(), meeting_id)
    return "", 204


@project_bp.route("/api/projects/<int:project_id>/stakeholders", methods=["POST"])
def create_stakeholder(project_id):
    values = _stakeholder_values(_json_body())
    return jsonify(store.create_stakeholder(_owner_key(), project_id, values)), 201


@project_bp.route("/api/project-stakeholders/<int:stakeholder_id>", methods=["PATCH"])
def update_stakeholder(stakeholder_id):
    values = _stakeholder_values(_json_body(), partial=True)
    if not values:
        raise ValueError("No stakeholder fields were supplied")
    return jsonify(store.update_stakeholder(_owner_key(), stakeholder_id, values))


@project_bp.route("/api/project-stakeholders/<int:stakeholder_id>", methods=["DELETE"])
def delete_stakeholder(stakeholder_id):
    store.delete_stakeholder(_owner_key(), stakeholder_id)
    return "", 204


@project_bp.route("/api/project-connections", methods=["POST"])
def create_connection():
    return jsonify(store.create_connection(_owner_key(), _connection_values(_json_body()))), 201


@project_bp.route("/api/project-connections/<int:connection_id>", methods=["PATCH"])
def update_connection(connection_id):
    values = _connection_values(_json_body(), partial=True)
    if not values:
        raise ValueError("No connection fields were supplied")
    return jsonify(store.update_connection(_owner_key(), connection_id, values))


@project_bp.route("/api/project-connections/<int:connection_id>", methods=["DELETE"])
def delete_connection(connection_id):
    store.delete_connection(_owner_key(), connection_id)
    return "", 204
