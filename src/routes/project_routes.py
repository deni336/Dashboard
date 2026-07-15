import re
import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from src.global_logger import GlobalLogger
from src.project_manager import ProjectStore
from src.project_ai import ProjectAIError, ProjectAssistant, secret_value, sign_proposal, verify_proposal


project_bp = Blueprint("project_bp", __name__)
logger = GlobalLogger.get_logger("ProjectRoutes")
store = None
config = None

PROJECT_STATUSES = {"planned", "active", "on_hold", "completed", "archived"}
PRIORITIES = {"low", "medium", "high", "critical"}
HEALTH_VALUES = {"on_track", "at_risk", "off_track"}
RECORD_KINDS = {"task", "milestone", "risk", "assumption", "issue", "dependency", "decision"}
RECORD_STATUSES = {"open", "in_progress", "blocked", "monitoring", "resolved", "done"}
INFLUENCE_VALUES = {"low", "medium", "high"}
ENGAGEMENT_VALUES = {"unaware", "resistant", "neutral", "supportive", "leading"}
PROVIDERS = {"github", "gmail", "calendar", "drive", "teams", "slack", "jira", "notion", "other"}
SHARE_ROLES = {"viewer", "editor"}
AI_PROJECT_FIELDS = {"status", "priority", "health", "progress", "target_date", "manager", "sponsor", "description"}
AI_RECORD_FIELDS = {"kind", "title", "details", "owner", "status", "priority", "due_date", "resolution"}
AI_MEETING_FIELDS = {"title", "held_on", "attendees", "notes", "decisions", "action_items", "next_steps"}
PROJECT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,15}$")
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
INVITATION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
OPENAI_API_KEY_MAX_LENGTH = 4096
AI_RATE_LIMIT = 10
AI_RATE_WINDOW_SECONDS = 600
AI_MAX_CONCURRENT_PREVIEWS = 2
PROJECT_JSON_MAX_BYTES = 256 * 1024
AI_PROPOSAL_LIFETIME = timedelta(minutes=15)
_ai_requests = defaultdict(deque)
_ai_requests_lock = threading.Lock()
_ai_preview_slots = threading.BoundedSemaphore(AI_MAX_CONCURRENT_PREVIEWS)
_ai_preview_users = set()
_ai_preview_lock = threading.Lock()


class ProjectAIRateLimit(Exception):
    pass


class ProjectAIBusy(Exception):
    pass


class ProjectRequestTooLarge(Exception):
    pass


def init_project_routes(config_handler):
    global config, store
    config = config_handler
    store = ProjectStore(config_handler)


@project_bp.after_request
def project_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _owner_key():
    profile = session.get("profile") or {}
    value = profile.get("id") or profile.get("email")
    if not value:
        abort(401)
    return str(value).strip().lower()


def _owner_email():
    profile = session.get("profile") or {}
    value = str(profile.get("email") or "").strip().lower()
    if not value or not EMAIL.fullmatch(value):
        abort(400)
    return value


def _deployment_ai_key():
    allowed_users = {
        item.strip().lower()
        for item in os.getenv("KASUGAI_AI_ALLOWED_USERS", "").split(",")
        if item.strip()
    }
    profile = session.get("profile") or {}
    candidates = {
        str(profile.get("id") or "").strip().lower(),
        str(profile.get("email") or "").strip().lower(),
    }
    if not allowed_users.intersection(candidates):
        return ""
    try:
        return secret_value("OPENAI_API_KEY")
    except ProjectAIError:
        return ""


def _personal_ai_key():
    try:
        return store.openai_api_key(_owner_key())
    except ValueError as exc:
        raise ProjectAIError(
            "Your stored OpenAI API key could not be read. Replace it in AI settings."
        ) from exc


def _resolved_ai_key():
    personal_key = _personal_ai_key()
    if personal_key:
        return personal_key, "personal"
    deployment_key = _deployment_ai_key()
    if deployment_key:
        return deployment_key, "deployment"
    return "", None


def _ai_access_allowed():
    try:
        api_key, _source = _resolved_ai_key()
    except ProjectAIError:
        return False
    return bool(api_key)


def _ai_source_access_allowed():
    allowed_users = {
        item.strip().lower()
        for item in os.getenv("KASUGAI_AI_SOURCE_ALLOWED_USERS", "").split(",")
        if item.strip()
    }
    profile = session.get("profile") or {}
    candidates = {
        str(profile.get("id") or "").strip().lower(),
        str(profile.get("email") or "").strip().lower(),
    }
    return bool(allowed_users.intersection(candidates))


def _require_ai_access():
    api_key, source = _resolved_ai_key()
    if not api_key:
        raise PermissionError(
            "Add your OpenAI API key in AI settings to use the project copilot"
        )
    return api_key, source


def _ai_settings_response():
    try:
        status = store.openai_credential_status(_owner_key())
        credential_error = False
    except ValueError:
        status = {
            "personal_key_configured": True,
            "updated_at": None,
        }
        credential_error = True
    deployment_available = bool(_deployment_ai_key())
    if credential_error:
        source = None
    elif status["personal_key_configured"]:
        source = "personal"
    else:
        source = "deployment" if deployment_available else None
    assistant_model = os.getenv("OPENAI_MODEL", "").strip() or config.get(
        "AI", "model", fallback="gpt-5.6-sol"
    )
    return {
        **status,
        "configured": bool(source),
        "credential_source": source,
        "deployment_key_available": deployment_available,
        "credential_error": credential_error,
        "model": assistant_model,
    }


def _enforce_ai_rate_limit():
    now = time.monotonic()
    key = _owner_key()
    with _ai_requests_lock:
        requests = _ai_requests[key]
        while requests and requests[0] <= now - AI_RATE_WINDOW_SECONDS:
            requests.popleft()
        if len(requests) >= AI_RATE_LIMIT:
            raise ProjectAIRateLimit("AI request limit reached; try again in a few minutes")
        requests.append(now)


@contextmanager
def _ai_preview_slot():
    """Keep slow upstream work from occupying every Waitress request thread."""
    key = _owner_key()
    with _ai_preview_lock:
        if key in _ai_preview_users:
            raise ProjectAIRateLimit(
                "An AI preview is already running for this account"
            )
        if not _ai_preview_slots.acquire(blocking=False):
            raise ProjectAIBusy(
                "The AI copilot is busy; try again in a few seconds"
            )
        _ai_preview_users.add(key)
    try:
        yield
    finally:
        with _ai_preview_lock:
            _ai_preview_users.discard(key)
            _ai_preview_slots.release()


def _assistant_history(data):
    history = data.get("history", [])
    if not isinstance(history, list) or len(history) > 12:
        raise ValueError("history must contain at most 12 messages")
    result = []
    for item in history:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            raise ValueError("history contains an invalid message")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 5000:
            raise ValueError("history messages must contain 1-5000 characters")
        result.append({"role": item["role"], "content": content.strip()})
    return result


def _json_body():
    request.max_content_length = PROJECT_JSON_MAX_BYTES
    if request.content_length is not None and request.content_length > PROJECT_JSON_MAX_BYTES:
        raise ProjectRequestTooLarge("Request body must be 256 KB or smaller")
    try:
        value = request.get_json(silent=True)
    except RequestEntityTooLarge as exc:
        raise ProjectRequestTooLarge("Request body must be 256 KB or smaller") from exc
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


def _openai_api_key_value(data):
    value = data.get("api_key")
    if not isinstance(value, str):
        raise ValueError("api_key must be a string")
    if value != value.strip():
        raise ValueError("api_key cannot begin or end with whitespace")
    if not value:
        raise ValueError("api_key is required")
    if len(value) > OPENAI_API_KEY_MAX_LENGTH:
        raise ValueError(f"api_key must be {OPENAI_API_KEY_MAX_LENGTH} characters or fewer")
    if any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise ValueError("api_key must contain only printable characters without spaces")
    return value


def _require_same_origin():
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return
    supplied = urlsplit(origin)
    expected = urlsplit(request.host_url)
    if supplied.scheme != expected.scheme or supplied.netloc != expected.netloc:
        raise PermissionError("Credential changes require a same-origin request")


def _enum(data, key, allowed, *, default=None, required=False):
    value = _text(data, key, required=required, maximum=40, default=default)
    if value is None:
        return None
    value = value.lower()
    if value not in allowed:
        raise ValueError(f"{key} must be one of {', '.join(sorted(allowed))}")
    return value


def _boolean(data, key, *, default=False):
    if key not in data:
        return default
    if type(data[key]) is not bool:
        raise ValueError(f"{key} must be true or false")
    return data[key]


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


def _share_values(data):
    email = _text(data, "email", required=True, maximum=254).lower()
    if not EMAIL.fullmatch(email):
        raise ValueError("email must be a valid address")
    return {
        "email": email,
        "role": _enum(data, "role", SHARE_ROLES, default="viewer"),
    }


def _invitation_url(token):
    path = url_for("project_bp.project_invitation", token=token)
    public_url = config.get("WebServer", "publicurl", fallback="").strip().rstrip("/")
    return f"{public_url}{path}" if public_url else url_for(
        "project_bp.project_invitation",
        token=token,
        _external=True,
    )


@project_bp.errorhandler(KeyError)
def project_not_found(error):
    return jsonify({"error": str(error.args[0])}), 404


@project_bp.errorhandler(ValueError)
def invalid_project_request(error):
    return jsonify({"error": str(error)}), 400


@project_bp.errorhandler(ProjectAIError)
def project_ai_error(error):
    return jsonify({"error": str(error)}), 502


@project_bp.errorhandler(ProjectAIRateLimit)
def project_ai_rate_limit(error):
    return jsonify({"error": str(error)}), 429


@project_bp.errorhandler(ProjectAIBusy)
def project_ai_busy(error):
    response = jsonify({"error": str(error)})
    response.status_code = 503
    response.headers["Retry-After"] = "5"
    return response


@project_bp.errorhandler(ProjectRequestTooLarge)
def project_request_too_large(error):
    return jsonify({"error": str(error)}), 413


@project_bp.errorhandler(PermissionError)
def project_permission_denied(error):
    return jsonify({"error": str(error)}), 403


@project_bp.route("/projects")
def workspace_page():
    return render_template("project_manager.html", user=session.get("profile", {}))


@project_bp.route("/projects/invitations/<token>", methods=["GET", "POST"])
def project_invitation(token):
    if not INVITATION_TOKEN.fullmatch(token):
        return render_template(
            "project_invitation.html",
            invitation=None,
            error="This project invitation is invalid.",
            user=session.get("profile", {}),
        ), 404
    try:
        invitation = store.invitation(token, _owner_email())
    except KeyError as error:
        return render_template(
            "project_invitation.html",
            invitation=None,
            error=str(error.args[0]),
            user=session.get("profile", {}),
        ), 404
    if request.method == "POST":
        project_id = store.accept_invitation(token, _owner_key(), _owner_email())
        return redirect(url_for("project_bp.workspace_page", project=project_id))
    return render_template(
        "project_invitation.html",
        invitation=invitation,
        error=None,
        user=session.get("profile", {}),
    )


@project_bp.route("/api/projects/portfolio")
def get_portfolio():
    return jsonify(store.portfolio(_owner_key()))


@project_bp.route("/api/project-ai/settings", methods=["GET", "PUT", "DELETE"])
def project_ai_settings():
    owner_key = _owner_key()
    if request.method == "PUT":
        _require_same_origin()
        store.set_openai_api_key(owner_key, _openai_api_key_value(_json_body()))
    elif request.method == "DELETE":
        _require_same_origin()
        store.delete_openai_api_key(owner_key)
    return jsonify(_ai_settings_response())


@project_bp.route("/api/projects", methods=["POST"])
def create_project():
    project = store.create_project(_owner_key(), _project_values(_json_body()))
    return jsonify(project), 201


@project_bp.route("/api/projects/<int:project_id>")
def get_project(project_id):
    workspace = store.workspace(_owner_key(), project_id)
    workspace["capabilities"] = {
        "ai_copilot": _ai_access_allowed(),
        "ai_sources": _ai_source_access_allowed()
        and workspace.get("permissions", {}).get("can_share", False),
    }
    return jsonify(workspace)


@project_bp.route("/api/projects/<int:project_id>/assistant/preview", methods=["POST"])
def project_assistant_preview(project_id):
    data = _json_body()
    prompt = _text(data, "message", required=True, maximum=5000)
    workspace = store.workspace(_owner_key(), project_id)
    if not workspace.get("permissions", {}).get("can_edit"):
        raise PermissionError("Editor access is required to propose project changes")
    api_key, _credential_source = _require_ai_access()
    with _ai_preview_slot():
        _enforce_ai_rate_limit()
        assistant_model = os.getenv("OPENAI_MODEL", "").strip() or config.get(
            "AI", "model", fallback="gpt-5.6-sol"
        )
        assistant = ProjectAssistant(assistant_model, api_key=api_key)
        can_use_sources = (
            workspace.get("permissions", {}).get("can_share", False)
            and _ai_source_access_allowed()
        )
        safety_identifier = hmac.new(
            str(current_app.secret_key).encode("utf-8"),
            f"Kasugai/OpenAI safety identifier/v1\0{_owner_key()}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        proposal = dict(assistant.propose(
            prompt,
            workspace,
            workspace.get("connections", []) if can_use_sources else [],
            include_github=_boolean(data, "include_github", default=True)
            and can_use_sources,
            include_email=_boolean(data, "include_email", default=True)
            and can_use_sources,
            safety_identifier=safety_identifier,
            history=_assistant_history(data),
        ))
    record_versions = {
        item["id"]: item.get("updated_at") for item in workspace.get("records", [])
    }
    proposal["expires_at"] = (datetime.now(UTC) + AI_PROPOSAL_LIFETIME).isoformat()
    proposal["expected_state"] = {
        "project_updated_at": workspace["project"]["updated_at"],
        "workspace_version": ProjectStore.ai_workspace_version(workspace),
        "records_updated_at": {
            str(action.get("record_id")): record_versions[action["record_id"]]
            for action in proposal.get("actions", [])
            if isinstance(action, dict)
            and action.get("type") == "update_record"
            and action.get("record_id") in record_versions
        },
    }
    signature = sign_proposal(current_app.secret_key, _owner_key(), project_id, proposal)
    return jsonify({"proposal": proposal, "signature": signature})


@project_bp.route("/api/projects/<int:project_id>/assistant/apply", methods=["POST"])
def project_assistant_apply(project_id):
    data = _json_body()
    proposal = data.get("proposal")
    signature = data.get("signature", "")
    if not isinstance(proposal, dict) or not verify_proposal(
        current_app.secret_key, _owner_key(), project_id, proposal, signature
    ):
        raise ValueError("The assistant proposal is invalid or has been changed")
    workspace = store.workspace(_owner_key(), project_id)
    if not workspace.get("permissions", {}).get("can_edit"):
        raise PermissionError("Editor access is required to apply project changes")

    proposal_actions = proposal.get("actions", [])
    if not isinstance(proposal_actions, list):
        raise ValueError("The assistant proposal contains invalid actions")
    selected_actions = data.get("selected_actions")
    if selected_actions is None:
        selected_actions = list(range(len(proposal_actions)))
    elif not isinstance(selected_actions, list):
        raise ValueError("selected_actions must be a list of action indexes")
    if proposal_actions and not selected_actions:
        raise ValueError("Select at least one assistant action to apply")
    if any(type(index) is not int for index in selected_actions):
        raise ValueError("selected_actions must contain integer action indexes")
    if len(set(selected_actions)) != len(selected_actions):
        raise ValueError("selected_actions must not contain duplicate indexes")
    if any(index < 0 or index >= len(proposal_actions) for index in selected_actions):
        raise ValueError("selected_actions contains an invalid action index")
    selected_actions.sort()

    record_ids = {item["id"] for item in workspace.get("records", [])}
    validated = []
    write_targets = set()
    for index in selected_actions:
        action = proposal_actions[index]
        if not isinstance(action, dict) or not isinstance(action.get("fields"), dict):
            raise ValueError("The assistant proposal contains an invalid action")
        action_type = action.get("type")
        fields = {key: value for key, value in action["fields"].items() if value is not None}
        if action_type == "update_project":
            if not set(fields).issubset(AI_PROJECT_FIELDS):
                raise ValueError("Assistant proposal contains unsupported project fields")
            values = _project_values(fields, partial=True)
        elif action_type == "create_record":
            if not set(fields).issubset(AI_RECORD_FIELDS):
                raise ValueError("Assistant proposal contains unsupported record fields")
            values = _record_values(fields)
        elif action_type == "update_record":
            if not set(fields).issubset(AI_RECORD_FIELDS):
                raise ValueError("Assistant proposal contains unsupported record fields")
            record_id = action.get("record_id")
            if not isinstance(record_id, int) or record_id not in record_ids:
                raise ValueError("Assistant proposal references a record outside this project")
            values = _record_values(fields, partial=True)
        elif action_type == "create_meeting":
            if not set(fields).issubset(AI_MEETING_FIELDS):
                raise ValueError("Assistant proposal contains unsupported meeting fields")
            values = _meeting_values(fields)
        else:
            raise ValueError("The assistant proposal contains an unsupported action")
        if not values:
            raise ValueError("Assistant action contains no project fields")
        targets = set()
        if action_type == "update_project":
            targets = {("project", project_id, field) for field in values}
        elif action_type == "update_record":
            targets = {("record", action.get("record_id"), field) for field in values}
        if write_targets.intersection(targets):
            raise ValueError("Assistant proposal contains conflicting updates to the same field")
        write_targets.update(targets)
        validated.append((action_type, action.get("record_id"), values))

    results = store.apply_ai_actions(
        _owner_key(), project_id, proposal, signature, validated, selected_actions
    )
    return jsonify({"applied": len(results), "results": results})


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


@project_bp.route("/api/projects/<int:project_id>/shares", methods=["POST"])
def create_project_share(project_id):
    values = _share_values(_json_body())
    result = store.create_share(
        _owner_key(),
        _owner_email(),
        project_id,
        values["email"],
        values["role"],
    )
    payload = {"share": result["share"], "invitationUrl": None}
    if result["token"]:
        payload["invitationUrl"] = _invitation_url(result["token"])
    return jsonify(payload), 201


@project_bp.route("/api/project-shares/<int:share_id>", methods=["PATCH"])
def update_project_share(share_id):
    role = _enum(_json_body(), "role", SHARE_ROLES, required=True)
    return jsonify(store.update_share(_owner_key(), share_id, role))


@project_bp.route("/api/project-shares/<int:share_id>", methods=["DELETE"])
def delete_project_share(share_id):
    store.delete_share(_owner_key(), share_id)
    return "", 204
