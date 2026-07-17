"""Owner-scoped catalog and queue for the outbound launcher companion.

The dashboard never stores an executable, argv, environment, or working
directory.  Those details live in the companion's local policy.  Browser
requests can only select a server-issued opaque task ID.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime


MAX_CATALOG_BYTES = 128 * 1024
MAX_RESULT_BYTES = 80 * 1024
MAX_TASKS = 128
MAX_OUTPUT_CHARACTERS = 64 * 1024
PAIRING_TTL_SECONDS = 10 * 60
PAIRING_MAX_ATTEMPTS = 5
RUN_TTL_SECONDS = 2 * 60
CLAIM_TTL_SECONDS = 5 * 60
RESULT_RETENTION_SECONDS = 14 * 24 * 60 * 60
CATALOG_MAX_AGE_SECONDS = 90
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
TASK_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
PUBLIC_TASK_PATTERN = re.compile(r"^[a-f0-9]{32}$")
ICON_PATTERN = re.compile(r"^[a-z0-9-]{1,40}$")
CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
TERMINAL_STATES = {"succeeded", "failed", "rejected"}
RESULT_CODES = {
    "ok",
    "exit_nonzero",
    "policy_denied",
    "task_missing",
    "timed_out",
    "output_limit",
    "execution_failed",
}


class LauncherError(Exception):
    pass


class ValidationError(LauncherError):
    pass


class PayloadTooLargeError(ValidationError):
    pass


class AuthenticationError(LauncherError):
    pass


class PairingConflictError(LauncherError):
    pass


class ReplayError(LauncherError):
    pass


class NotFoundError(LauncherError):
    pass


class PermissionDeniedError(LauncherError):
    pass


class ConflictError(LauncherError):
    pass


class ExpiredError(ConflictError):
    pass


class RateLimitError(LauncherError):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = max(1, int(math.ceil(float(retry_after))))


def _environment_int(name, default, minimum, maximum):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _environment_float(name, default, minimum, maximum):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(max(value, minimum), maximum)


def _iso_timestamp(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value, field_name):
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValidationError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC).timestamp()


def _strict_object(value, field_name, required, optional=()):
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be an object")
    required = set(required)
    allowed = required | set(optional)
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise ValidationError(f"{field_name} is missing required fields")
    if unknown:
        raise ValidationError(f"{field_name} contains unsupported fields")
    return value


def _clean_string(value, field_name, *, maximum, allow_empty=False):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError(f"{field_name} contains control characters")
    cleaned = " ".join(value.strip().split())
    if not cleaned and not allow_empty:
        raise ValidationError(f"{field_name} is required")
    if len(cleaned) > maximum:
        raise ValidationError(f"{field_name} is too long")
    return cleaned


def validate_pair_request(payload):
    payload = _strict_object(
        payload,
        "request",
        {"pairing_id", "code", "display_name", "platform", "agent_version", "capabilities"},
    )
    pairing_id = payload["pairing_id"]
    code = payload["code"]
    if not isinstance(pairing_id, str) or not IDENTIFIER_PATTERN.fullmatch(pairing_id):
        raise ValidationError("pairing_id is invalid")
    if not isinstance(code, str) or not 20 <= len(code) <= 128:
        raise ValidationError("pairing code is invalid")
    capabilities = payload["capabilities"]
    if (
        not isinstance(capabilities, list)
        or len(capabilities) > 16
        or any(not isinstance(item, str) or not CAPABILITY_PATTERN.fullmatch(item) for item in capabilities)
        or len(set(capabilities)) != len(capabilities)
    ):
        raise ValidationError("capabilities are invalid")
    if "run_tasks" not in capabilities:
        raise ValidationError("run_tasks capability is required")
    return {
        "pairing_id": pairing_id,
        "code": code,
        "display_name": _clean_string(payload["display_name"], "display_name", maximum=80),
        "platform": _clean_string(payload["platform"], "platform", maximum=160),
        "agent_version": _clean_string(payload["agent_version"], "agent_version", maximum=32),
        "capabilities": capabilities,
    }


def validate_catalog(payload, *, now_epoch):
    payload = _strict_object(payload, "catalog", {"schema_version", "sequence", "captured_at", "tasks"})
    if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
        raise ValidationError("schema_version is not supported")
    sequence = payload["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= 2**63 - 1:
        raise ValidationError("sequence is invalid")
    captured = _parse_timestamp(payload["captured_at"], "captured_at")
    if captured > now_epoch + 60 or captured < now_epoch - 10 * 60:
        raise ValidationError("captured_at is outside the accepted window")
    values = payload["tasks"]
    if not isinstance(values, list) or len(values) > MAX_TASKS:
        raise ValidationError(f"tasks must contain at most {MAX_TASKS} items")
    tasks = []
    seen = set()
    for index, raw in enumerate(values):
        item = _strict_object(
            raw,
            f"tasks[{index}]",
            {"key", "title", "description", "category", "icon", "requires_confirmation"},
        )
        key = item["key"]
        if not isinstance(key, str) or not TASK_KEY_PATTERN.fullmatch(key) or key in seen:
            raise ValidationError(f"tasks[{index}].key is invalid or duplicated")
        seen.add(key)
        icon = item["icon"]
        if not isinstance(icon, str) or not ICON_PATTERN.fullmatch(icon):
            raise ValidationError(f"tasks[{index}].icon is invalid")
        confirmation = item["requires_confirmation"]
        if not isinstance(confirmation, bool):
            raise ValidationError(f"tasks[{index}].requires_confirmation must be true or false")
        tasks.append(
            {
                "key": key,
                "title": _clean_string(item["title"], f"tasks[{index}].title", maximum=120),
                "description": _clean_string(
                    item["description"], f"tasks[{index}].description", maximum=240, allow_empty=True
                ),
                "category": _clean_string(item["category"], f"tasks[{index}].category", maximum=48),
                "icon": icon,
                "requires_confirmation": confirmation,
            }
        )
    return {
        "schema_version": 1,
        "sequence": sequence,
        "captured_at": _iso_timestamp(captured),
        "tasks": tasks,
    }


def validate_claim_request(payload):
    payload = _strict_object(payload, "request", {"schema_version"})
    if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
        raise ValidationError("schema_version is not supported")
    return payload


def validate_result(payload):
    payload = _strict_object(
        payload,
        "result",
        {
            "schema_version",
            "claim_token",
            "completed_at",
            "status",
            "code",
            "summary",
            "output",
            "truncated",
        },
    )
    if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
        raise ValidationError("schema_version is not supported")
    claim_token = payload["claim_token"]
    if not isinstance(claim_token, str) or not 20 <= len(claim_token) <= 256:
        raise ValidationError("claim_token is invalid")
    status = payload["status"]
    if status not in TERMINAL_STATES:
        raise ValidationError("status is invalid")
    code = payload["code"]
    if code not in RESULT_CODES:
        raise ValidationError("code is invalid")
    if status == "succeeded" and code != "ok":
        raise ValidationError("successful results must use the ok code")
    if status != "succeeded" and code == "ok":
        raise ValidationError("unsuccessful results cannot use the ok code")
    output = payload["output"]
    if not isinstance(output, str) or len(output) > MAX_OUTPUT_CHARACTERS:
        raise ValidationError("output is invalid or too long")
    if any(character == "\x00" for character in output):
        raise ValidationError("output contains unsupported characters")
    truncated = payload["truncated"]
    if not isinstance(truncated, bool):
        raise ValidationError("truncated must be true or false")
    return {
        "schema_version": 1,
        "claim_token": claim_token,
        "completed_at": _iso_timestamp(_parse_timestamp(payload["completed_at"], "completed_at")),
        "status": status,
        "code": code,
        "summary": _clean_string(payload["summary"], "summary", maximum=1000, allow_empty=True),
        "output": output,
        "truncated": truncated,
    }


class LauncherRunner:
    """Pairing, catalog, confirmation, and one-shot run state machine."""

    def __init__(self, dashboard_store, *, clock=None):
        self.store = dashboard_store
        self.db_path = dashboard_store.db_path
        self.fernet = dashboard_store.fernet
        self.lookup_key = dashboard_store.lookup_key
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())
        self.max_agents = _environment_int("KASUGAI_LAUNCHER_MAX_AGENTS", 8, 1, 64)
        self.catalog_interval_seconds = _environment_int(
            "KASUGAI_LAUNCHER_CATALOG_INTERVAL_SECONDS", 30, 10, 3600
        )
        self.poll_interval_seconds = _environment_int("KASUGAI_LAUNCHER_POLL_SECONDS", 5, 2, 60)
        self.min_catalog_seconds = _environment_float(
            "KASUGAI_LAUNCHER_MIN_CATALOG_SECONDS", 2.0, 0.0, 60.0
        )
        self.min_claim_seconds = _environment_float(
            "KASUGAI_LAUNCHER_MIN_CLAIM_SECONDS", 1.0, 0.0, 30.0
        )
        self.min_run_seconds = _environment_float(
            "KASUGAI_LAUNCHER_MIN_RUN_SECONDS", 2.0, 0.0, 60.0
        )
        self._initialize()

    @contextmanager
    def _connect(self, *, immediate=False):
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connect(immediate=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS launcher_pairings (
                    pairing_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    used_at REAL
                );
                CREATE INDEX IF NOT EXISTS launcher_pairings_owner_idx
                    ON launcher_pairings(owner_key, created_at DESC);

                CREATE TABLE IF NOT EXISTS launcher_agents (
                    agent_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    paired_at REAL NOT NULL,
                    last_seen_at REAL,
                    last_catalog_at REAL,
                    last_claim_at REAL,
                    last_run_at REAL,
                    last_sequence INTEGER NOT NULL DEFAULT -1,
                    catalog_captured_at REAL,
                    catalog_encrypted TEXT,
                    revoked_at REAL
                );
                CREATE INDEX IF NOT EXISTS launcher_agents_owner_idx
                    ON launcher_agents(owner_key, revoked_at, paired_at DESC);

                CREATE TABLE IF NOT EXISTS launcher_previews (
                    preview_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed_at REAL,
                    FOREIGN KEY(agent_id) REFERENCES launcher_agents(agent_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS launcher_runs (
                    run_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    payload_encrypted TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('queued','claimed','succeeded','failed','rejected',
                                  'expired','cancelled','unknown')
                    ),
                    requested_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    claimed_at REAL,
                    completion_deadline REAL,
                    completed_at REAL,
                    claim_token_hash TEXT,
                    result_hash TEXT,
                    result_status TEXT,
                    result_code TEXT,
                    result_encrypted TEXT,
                    purge_after REAL NOT NULL,
                    FOREIGN KEY(agent_id) REFERENCES launcher_agents(agent_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS launcher_runs_agent_state_idx
                    ON launcher_runs(agent_id, state, requested_at);
                CREATE INDEX IF NOT EXISTS launcher_runs_owner_idx
                    ON launcher_runs(owner_key, requested_at DESC);
                """
            )

    def _now(self):
        value = self.clock()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).timestamp()
        return float(value)

    def _secret_hash(self, purpose, *values):
        message = "\x00".join((purpose, *(str(value) for value in values))).encode("utf-8")
        return hmac.new(self.lookup_key, message, hashlib.sha256).hexdigest()

    def _encrypt_payload(self, payload):
        raw = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self.fernet.encrypt(raw).decode("ascii")

    def _decrypt_payload(self, encrypted):
        try:
            return json.loads(self.fernet.decrypt(str(encrypted).encode("ascii")))
        except Exception as exc:
            raise LauncherError("Stored launcher data could not be decrypted") from exc

    def _authenticate(self, connection, agent_id, token):
        if not isinstance(agent_id, str) or not IDENTIFIER_PATTERN.fullmatch(agent_id):
            raise AuthenticationError("Agent credentials are invalid")
        if not isinstance(token, str) or not token or len(token) > 256:
            raise AuthenticationError("Agent credentials are invalid")
        row = connection.execute(
            "SELECT * FROM launcher_agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        supplied = self._secret_hash("launcher-token-v1", agent_id, token)
        if (
            row is None
            or row["revoked_at"] is not None
            or not hmac.compare_digest(row["token_hash"], supplied)
        ):
            raise AuthenticationError("Agent credentials are invalid")
        return row

    def create_pairing(self, owner_key):
        owner_key = _clean_string(str(owner_key), "owner", maximum=256)
        now = self._now()
        pairing_id = secrets.token_urlsafe(18)
        code = secrets.token_urlsafe(24)
        with self._connect(immediate=True) as connection:
            connection.execute(
                "UPDATE launcher_pairings SET used_at = ? WHERE owner_key = ? AND used_at IS NULL",
                (now, owner_key),
            )
            connection.execute(
                """INSERT INTO launcher_pairings
                   (pairing_id, owner_key, code_hash, expires_at, attempt_count,
                    max_attempts, created_at, used_at)
                   VALUES (?, ?, ?, ?, 0, ?, ?, NULL)""",
                (
                    pairing_id,
                    owner_key,
                    self._secret_hash("launcher-pairing-v1", pairing_id, code),
                    now + PAIRING_TTL_SECONDS,
                    PAIRING_MAX_ATTEMPTS,
                    now,
                ),
            )
        return {
            "pairing_id": pairing_id,
            "code": code,
            "expires_at": _iso_timestamp(now + PAIRING_TTL_SECONDS),
        }

    def pair_agent(self, payload):
        request_data = validate_pair_request(payload)
        now = self._now()
        invalid_code = False
        result = None
        with self._connect(immediate=True) as connection:
            pairing = connection.execute(
                "SELECT * FROM launcher_pairings WHERE pairing_id = ?",
                (request_data["pairing_id"],),
            ).fetchone()
            if (
                pairing is None
                or pairing["used_at"] is not None
                or pairing["expires_at"] <= now
                or pairing["attempt_count"] >= pairing["max_attempts"]
            ):
                raise AuthenticationError("Pairing code is invalid or expired")
            supplied = self._secret_hash(
                "launcher-pairing-v1", request_data["pairing_id"], request_data["code"]
            )
            if not hmac.compare_digest(pairing["code_hash"], supplied):
                connection.execute(
                    "UPDATE launcher_pairings SET attempt_count = attempt_count + 1 WHERE pairing_id = ?",
                    (request_data["pairing_id"],),
                )
                invalid_code = True
            else:
                active = connection.execute(
                    "SELECT COUNT(*) FROM launcher_agents WHERE owner_key = ? AND revoked_at IS NULL",
                    (pairing["owner_key"],),
                ).fetchone()[0]
                if active >= self.max_agents:
                    raise PairingConflictError("The launcher agent limit has been reached")
                agent_id = secrets.token_urlsafe(18)
                token = secrets.token_urlsafe(32)
                connection.execute(
                    """INSERT INTO launcher_agents
                       (agent_id, owner_key, token_hash, display_name, platform,
                        agent_version, capabilities_json, paired_at, last_sequence)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, -1)""",
                    (
                        agent_id,
                        pairing["owner_key"],
                        self._secret_hash("launcher-token-v1", agent_id, token),
                        request_data["display_name"],
                        request_data["platform"],
                        request_data["agent_version"],
                        json.dumps(request_data["capabilities"], separators=(",", ":")),
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE launcher_pairings SET used_at = ? WHERE pairing_id = ?",
                    (now, request_data["pairing_id"]),
                )
                result = {
                    "agent_id": agent_id,
                    "token": token,
                    "catalog_interval_seconds": self.catalog_interval_seconds,
                    "poll_interval_seconds": self.poll_interval_seconds,
                }
        if invalid_code:
            raise AuthenticationError("Pairing code is invalid or expired")
        return result

    def ingest_catalog(self, agent_id, token, payload):
        now = self._now()
        catalog = validate_catalog(payload, now_epoch=now)
        with self._connect(immediate=True) as connection:
            agent = self._authenticate(connection, agent_id, token)
            if catalog["sequence"] <= agent["last_sequence"]:
                raise ReplayError("Catalog sequence has already been used")
            if agent["last_catalog_at"] is not None and now - agent["last_catalog_at"] < self.min_catalog_seconds:
                raise RateLimitError(
                    "Catalog updates are arriving too quickly",
                    self.min_catalog_seconds - (now - agent["last_catalog_at"]),
                )
            connection.execute(
                """UPDATE launcher_agents SET last_seen_at = ?, last_catalog_at = ?,
                       last_sequence = ?, catalog_captured_at = ?, catalog_encrypted = ?
                   WHERE agent_id = ?""",
                (
                    now,
                    now,
                    catalog["sequence"],
                    _parse_timestamp(catalog["captured_at"], "captured_at"),
                    self._encrypt_payload(catalog),
                    agent_id,
                ),
            )
            self._expire_runs(connection, now)
            self._purge(connection, now)
        return {"accepted": True, "sequence": catalog["sequence"], "received_at": _iso_timestamp(now)}

    def _runs_enabled(self):
        return os.getenv("KASUGAI_LAUNCHER_RUNS_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _task_id(self, agent_id, task_key):
        return self._secret_hash("launcher-public-task-v1", agent_id, task_key)[:32]

    @staticmethod
    def _status(last_seen_at, now):
        if last_seen_at is None:
            return "offline"
        age = max(0, now - float(last_seen_at))
        if age <= CATALOG_MAX_AGE_SECONDS:
            return "online"
        if age <= 5 * CATALOG_MAX_AGE_SECONDS:
            return "stale"
        return "offline"

    def _public_agent(self, row, now):
        catalog = self._decrypt_payload(row["catalog_encrypted"]) if row["catalog_encrypted"] else {"tasks": []}
        status = self._status(row["last_seen_at"], now)
        return {
            "id": row["agent_id"],
            "display_name": row["display_name"],
            "platform": row["platform"],
            "agent_version": row["agent_version"],
            "paired_at": _iso_timestamp(row["paired_at"]),
            "last_seen_at": _iso_timestamp(row["last_seen_at"]),
            "status": status,
            "online": status == "online",
            "task_count": len(catalog.get("tasks", [])),
        }

    def list_agents(self, owner_key):
        now = self._now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM launcher_agents
                   WHERE owner_key = ? AND revoked_at IS NULL
                   ORDER BY display_name COLLATE NOCASE, paired_at""",
                (owner_key,),
            ).fetchall()
        return {"agents": [self._public_agent(row, now) for row in rows]}

    def catalog(self, owner_key):
        now = self._now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM launcher_agents
                   WHERE owner_key = ? AND revoked_at IS NULL
                   ORDER BY display_name COLLATE NOCASE, paired_at""",
                (owner_key,),
            ).fetchall()
        agents = [self._public_agent(row, now) for row in rows]
        agent_public = {item["id"]: item for item in agents}
        tasks = []
        enabled = self._runs_enabled()
        for row in rows:
            if not row["catalog_encrypted"]:
                continue
            catalog = self._decrypt_payload(row["catalog_encrypted"])
            available = enabled and agent_public[row["agent_id"]]["online"]
            for task in catalog.get("tasks", []):
                tasks.append(
                    {
                        "id": self._task_id(row["agent_id"], task["key"]),
                        "title": task["title"],
                        "description": task["description"],
                        "category": task["category"],
                        "icon": task["icon"],
                        "requires_confirmation": task["requires_confirmation"],
                        "agent_id": row["agent_id"],
                        "agent_name": row["display_name"],
                        "available": available,
                        "disabled_reason": (
                            "" if available else "Task execution is disabled" if not enabled else "Runner is offline"
                        ),
                    }
                )
        tasks.sort(key=lambda item: (item["category"].lower(), item["title"].lower(), item["id"]))
        return {"agents": agents, "tasks": tasks, "runs_enabled": enabled}

    def rename(self, owner_key, agent_id, display_name):
        display_name = _clean_string(display_name, "display_name", maximum=80)
        with self._connect(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE launcher_agents SET display_name = ?
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (display_name, owner_key, agent_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Launcher agent not found")
            row = connection.execute(
                "SELECT * FROM launcher_agents WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        return self._public_agent(row, self._now())

    def revoke(self, owner_key, agent_id):
        now = self._now()
        with self._connect(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE launcher_agents
                   SET revoked_at = ?, token_hash = ?, catalog_encrypted = NULL
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (now, self._secret_hash("launcher-revoked-v1", agent_id, secrets.token_urlsafe(24)), owner_key, agent_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Launcher agent not found")
            connection.execute(
                """UPDATE launcher_runs SET state = 'cancelled', completed_at = ?, claim_token_hash = NULL
                   WHERE agent_id = ? AND state IN ('queued','claimed')""",
                (now, agent_id),
            )
            connection.execute(
                "UPDATE launcher_previews SET consumed_at = ? WHERE agent_id = ? AND consumed_at IS NULL",
                (now, agent_id),
            )

    def _resolve_task(self, connection, owner_key, task_id, now):
        if not isinstance(task_id, str) or not PUBLIC_TASK_PATTERN.fullmatch(task_id):
            raise NotFoundError("Launcher task not found")
        rows = connection.execute(
            """SELECT * FROM launcher_agents
               WHERE owner_key = ? AND revoked_at IS NULL""",
            (owner_key,),
        ).fetchall()
        for agent in rows:
            if not agent["catalog_encrypted"]:
                continue
            catalog = self._decrypt_payload(agent["catalog_encrypted"])
            for task in catalog.get("tasks", []):
                if hmac.compare_digest(self._task_id(agent["agent_id"], task["key"]), task_id):
                    if agent["last_seen_at"] is None or now - agent["last_seen_at"] > CATALOG_MAX_AGE_SECONDS:
                        raise ConflictError("The runner catalog is too old")
                    return agent, task
        raise NotFoundError("Launcher task not found")

    def _preview(self, connection, owner_key, agent_id, task_id, now):
        token = secrets.token_urlsafe(32)
        preview_id = secrets.token_urlsafe(18)
        expires_at = now + 60
        connection.execute(
            """INSERT INTO launcher_previews
               (preview_id, owner_key, agent_id, task_id, token_hash, created_at, expires_at, consumed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                preview_id,
                owner_key,
                agent_id,
                task_id,
                self._secret_hash("launcher-confirmation-v1", preview_id, token),
                now,
                expires_at,
            ),
        )
        return token, expires_at

    def _consume_preview(self, connection, owner_key, agent_id, task_id, token, now):
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            raise AuthenticationError("Confirmation token is invalid")
        rows = connection.execute(
            """SELECT * FROM launcher_previews
               WHERE owner_key = ? AND agent_id = ? AND task_id = ?
                     AND consumed_at IS NULL AND expires_at > ?
               ORDER BY created_at DESC""",
            (owner_key, agent_id, task_id, now),
        ).fetchall()
        for row in rows:
            supplied = self._secret_hash("launcher-confirmation-v1", row["preview_id"], token)
            if hmac.compare_digest(row["token_hash"], supplied):
                updated = connection.execute(
                    "UPDATE launcher_previews SET consumed_at = ? WHERE preview_id = ? AND consumed_at IS NULL",
                    (now, row["preview_id"]),
                )
                if updated.rowcount == 1:
                    return
        raise AuthenticationError("Confirmation token is invalid or expired")

    def queue_run(self, owner_key, task_id, payload):
        payload = _strict_object(payload, "request", set(), {"confirmation_token"})
        if not self._runs_enabled():
            raise PermissionDeniedError("Launcher task execution is disabled by the server")
        now = self._now()
        with self._connect(immediate=True) as connection:
            agent, task = self._resolve_task(connection, owner_key, task_id, now)
            if agent["last_run_at"] is not None and now - agent["last_run_at"] < self.min_run_seconds:
                raise RateLimitError(
                    "Tasks are being queued too quickly", self.min_run_seconds - (now - agent["last_run_at"])
                )
            active = connection.execute(
                "SELECT 1 FROM launcher_runs WHERE agent_id = ? AND state IN ('queued','claimed') LIMIT 1",
                (agent["agent_id"],),
            ).fetchone()
            if active:
                raise ConflictError("This runner already has an active task")
            token = payload.get("confirmation_token")
            if task["requires_confirmation"] and token is None:
                token, expires_at = self._preview(
                    connection, owner_key, agent["agent_id"], task_id, now
                )
                return {
                    "queued": False,
                    "preview": {
                        "confirmation_token": token,
                        "expires_at": _iso_timestamp(expires_at),
                        "title": task["title"],
                        "description": task["description"],
                    },
                }
            if task["requires_confirmation"]:
                self._consume_preview(
                    connection, owner_key, agent["agent_id"], task_id, token, now
                )
            elif token is not None:
                raise ValidationError("This task does not accept a confirmation token")
            run_id = secrets.token_urlsafe(18)
            run_payload = {
                "task_key": task["key"],
                "task_title": task["title"],
                "agent_name": agent["display_name"],
            }
            connection.execute(
                """INSERT INTO launcher_runs
                   (run_id, owner_key, agent_id, task_id, payload_encrypted, state,
                    requested_at, expires_at, purge_after)
                   VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                (
                    run_id,
                    owner_key,
                    agent["agent_id"],
                    task_id,
                    self._encrypt_payload(run_payload),
                    now,
                    now + RUN_TTL_SECONDS,
                    now + RESULT_RETENTION_SECONDS,
                ),
            )
            connection.execute(
                "UPDATE launcher_agents SET last_run_at = ? WHERE agent_id = ?",
                (now, agent["agent_id"]),
            )
            row = connection.execute(
                "SELECT * FROM launcher_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return {"queued": True, "run": self._public_run(row)}

    def _expire_runs(self, connection, now):
        connection.execute(
            """UPDATE launcher_runs SET state = 'expired', completed_at = ?, claim_token_hash = NULL
               WHERE state = 'queued' AND expires_at <= ?""",
            (now, now),
        )
        connection.execute(
            """UPDATE launcher_runs SET state = 'unknown', completed_at = ?
               WHERE state = 'claimed' AND completion_deadline <= ?""",
            (now, now),
        )

    def _purge(self, connection, now):
        connection.execute(
            "DELETE FROM launcher_runs WHERE purge_after <= ? AND state NOT IN ('queued','claimed')",
            (now,),
        )
        connection.execute(
            "DELETE FROM launcher_previews WHERE expires_at < ?",
            (now - 3600,),
        )

    def claim_run(self, agent_id, token, payload):
        validate_claim_request(payload)
        now = self._now()
        with self._connect(immediate=True) as connection:
            agent = self._authenticate(connection, agent_id, token)
            if not self._runs_enabled():
                connection.execute(
                    """UPDATE launcher_runs SET state = 'cancelled', completed_at = ?
                       WHERE agent_id = ? AND state = 'queued'""",
                    (now, agent_id),
                )
                return None
            if agent["last_claim_at"] is not None and now - agent["last_claim_at"] < self.min_claim_seconds:
                raise RateLimitError(
                    "Task polling is too frequent", self.min_claim_seconds - (now - agent["last_claim_at"])
                )
            connection.execute(
                "UPDATE launcher_agents SET last_claim_at = ?, last_seen_at = ? WHERE agent_id = ?",
                (now, now, agent_id),
            )
            self._expire_runs(connection, now)
            self._purge(connection, now)
            row = connection.execute(
                """SELECT * FROM launcher_runs
                   WHERE agent_id = ? AND state = 'queued' AND expires_at > ?
                   ORDER BY requested_at, run_id LIMIT 1""",
                (agent_id, now),
            ).fetchone()
            if row is None:
                return None
            claim_token = secrets.token_urlsafe(32)
            deadline = min(row["expires_at"] + CLAIM_TTL_SECONDS, now + CLAIM_TTL_SECONDS)
            updated = connection.execute(
                """UPDATE launcher_runs SET state = 'claimed', claimed_at = ?,
                       completion_deadline = ?, claim_token_hash = ?
                   WHERE run_id = ? AND state = 'queued'""",
                (
                    now,
                    deadline,
                    self._secret_hash("launcher-claim-v1", row["run_id"], claim_token),
                    row["run_id"],
                ),
            )
            if updated.rowcount != 1:
                return None
            run_payload = self._decrypt_payload(row["payload_encrypted"])
        return {
            "schema_version": 1,
            "run_id": row["run_id"],
            "claim_token": claim_token,
            "task_key": run_payload["task_key"],
            "expires_at": _iso_timestamp(deadline),
        }

    def submit_result(self, agent_id, token, run_id, payload):
        result = validate_result(payload)
        now = self._now()
        completed_at = _parse_timestamp(result["completed_at"], "completed_at")
        if completed_at > now + 60 or completed_at < now - 10 * 60:
            raise ValidationError("completed_at is outside the accepted window")
        canonical = dict(result)
        claim_token = canonical.pop("claim_token")
        result_hash = self._secret_hash(
            "launcher-result-v1",
            run_id,
            json.dumps(canonical, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")),
        )
        with self._connect(immediate=True) as connection:
            self._authenticate(connection, agent_id, token)
            row = connection.execute(
                "SELECT * FROM launcher_runs WHERE run_id = ? AND agent_id = ?",
                (run_id, agent_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Task run not found")
            supplied = self._secret_hash("launcher-claim-v1", run_id, claim_token)
            if row["claim_token_hash"] is None or not hmac.compare_digest(row["claim_token_hash"], supplied):
                raise AuthenticationError("Task claim token is invalid")
            if row["state"] in TERMINAL_STATES:
                if row["result_hash"] and hmac.compare_digest(row["result_hash"], result_hash):
                    return {
                        "accepted": True,
                        "idempotent": True,
                        "run_id": run_id,
                        "state": row["state"],
                    }
                raise ReplayError("A different result was already submitted")
            if row["state"] != "claimed":
                raise ConflictError("Task run is not awaiting a result")
            if row["completion_deadline"] <= now:
                connection.execute(
                    "UPDATE launcher_runs SET state = 'unknown', completed_at = ? WHERE run_id = ?",
                    (now, run_id),
                )
                raise ExpiredError("Task claim has expired")
            if completed_at + 60 < row["claimed_at"]:
                raise ValidationError("completed_at precedes the task claim")
            connection.execute(
                """UPDATE launcher_runs SET state = ?, completed_at = ?, result_hash = ?,
                       result_status = ?, result_code = ?, result_encrypted = ?
                   WHERE run_id = ? AND state = 'claimed'""",
                (
                    result["status"],
                    completed_at,
                    result_hash,
                    result["status"],
                    result["code"],
                    self._encrypt_payload(canonical),
                    run_id,
                ),
            )
            run_payload = self._decrypt_payload(row["payload_encrypted"])
            severity = "success" if result["status"] == "succeeded" else "error"
            connection.execute(
                """INSERT OR IGNORE INTO dashboard_events
                   (owner_key, source, kind, severity, title, body, resource_url,
                    dedupe_key, occurred_at, created_at)
                   VALUES (?, 'launcher', 'task_run', ?, ?, ?, '#launcherModule', ?, ?, ?)""",
                (
                    row["owner_key"],
                    severity,
                    f"{run_payload['task_title']} {result['status']}",
                    result["summary"],
                    f"launcher-run:{run_id}",
                    _iso_timestamp(completed_at),
                    _iso_timestamp(now),
                ),
            )
        return {"accepted": True, "idempotent": False, "run_id": run_id, "state": result["status"]}

    def _public_run(self, row, *, include_output=False):
        payload = self._decrypt_payload(row["payload_encrypted"])
        result = self._decrypt_payload(row["result_encrypted"]) if row["result_encrypted"] else None
        public = {
            "id": row["run_id"],
            "task_id": row["task_id"],
            "task_title": payload["task_title"],
            "agent_id": row["agent_id"],
            "agent_name": payload["agent_name"],
            "state": row["state"],
            "requested_at": _iso_timestamp(row["requested_at"]),
            "claimed_at": _iso_timestamp(row["claimed_at"]),
            "completed_at": _iso_timestamp(row["completed_at"]),
            "result_status": row["result_status"],
            "result_code": row["result_code"],
            "summary": result.get("summary", "") if result else "",
        }
        if include_output:
            public["result"] = result
        return public

    def list_runs(self, owner_key, *, limit=50):
        try:
            limit = min(100, max(1, int(limit)))
        except (TypeError, ValueError) as exc:
            raise ValidationError("limit must be an integer") from exc
        now = self._now()
        with self._connect(immediate=True) as connection:
            self._expire_runs(connection, now)
            self._purge(connection, now)
            rows = connection.execute(
                """SELECT * FROM launcher_runs WHERE owner_key = ?
                   ORDER BY requested_at DESC LIMIT ?""",
                (owner_key, limit),
            ).fetchall()
        return {"runs": [self._public_run(row) for row in rows]}

    def get_run(self, owner_key, run_id):
        with self._connect() as connection:
            row = connection.execute(
                """SELECT r.* FROM launcher_runs r
                   JOIN launcher_agents a ON a.agent_id = r.agent_id
                   WHERE r.owner_key = ? AND r.run_id = ? AND a.owner_key = ?
                         AND a.revoked_at IS NULL""",
                (owner_key, run_id, owner_key),
            ).fetchone()
        if row is None:
            raise NotFoundError("Task run not found")
        return self._public_run(row, include_output=True)
