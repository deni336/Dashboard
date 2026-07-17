"""Owner-scoped, declarative automation rules for the personal dashboard.

Rules can observe only a fixed set of dashboard events and encrypted telemetry
metrics.  Actions can create a dashboard notification or select an opaque,
locally-approved launcher task.  There is deliberately no expression language,
URL fetch, SQL, executable, command line, path, or arbitrary action payload.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from src.global_logger import GlobalLogger


MAX_RULES_PER_OWNER = 100
MAX_RUNS_PER_OWNER = 500
RUN_RETENTION_SECONDS = 30 * 24 * 60 * 60
CLAIM_TTL_SECONDS = 60
RULE_FIELDS = {"name", "enabled", "trigger", "action", "cooldown_minutes"}
SEVERITIES = {"info", "success", "warning", "error"}
EVENT_SOURCES = {"developer", "workstation", "homelab", "launcher", "automation"}
METRIC_OPERATORS = ("gt", "gte", "lt", "lte", "eq")
METRIC_CATALOG = (
    {
        "id": "workstation.cpu_percent",
        "label": "Workstation CPU usage",
        "unit": "%",
        "operators": list(METRIC_OPERATORS),
    },
    {
        "id": "workstation.memory_percent",
        "label": "Workstation memory usage",
        "unit": "%",
        "operators": list(METRIC_OPERATORS),
    },
    {
        "id": "workstation.disk_percent",
        "label": "Workstation disk usage",
        "unit": "%",
        "operators": list(METRIC_OPERATORS),
    },
    {
        "id": "homelab.containers_unhealthy",
        "label": "Unhealthy containers",
        "unit": "containers",
        "operators": list(METRIC_OPERATORS),
    },
    {
        "id": "homelab.health_checks_down",
        "label": "Failed health checks",
        "unit": "checks",
        "operators": list(METRIC_OPERATORS),
    },
    {
        "id": "homelab.updates_available",
        "label": "Container updates available",
        "unit": "updates",
        "operators": list(METRIC_OPERATORS),
    },
)
METRIC_IDS = {item["id"] for item in METRIC_CATALOG}
LAUNCHER_TASK_ID = re.compile(r"^[a-f0-9]{32}$")


class AutomationError(Exception):
    """Base error safe to translate at the browser boundary."""


class ValidationError(AutomationError):
    pass


class NotFoundError(AutomationError):
    pass


class ConflictError(AutomationError):
    pass


class PermissionDeniedError(AutomationError):
    pass


class StorageError(AutomationError):
    pass


def _environment_int(name, default, minimum, maximum):
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _environment_enabled(name, default=False):
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _iso_timestamp(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), UTC).isoformat().replace("+00:00", "Z")


def _strict_object(value, field_name, required=(), optional=()):
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be an object")
    required = set(required)
    allowed = required | set(optional)
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise ValidationError(f"{field_name} is missing {sorted(missing)[0]}")
    if unknown:
        raise ValidationError(f"{field_name} contains unsupported field {sorted(unknown)[0]}")
    return value


def _clean_text(value, field_name, *, maximum, allow_empty=False):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError(f"{field_name} contains unsupported characters")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ValidationError(f"{field_name} is required")
    if len(cleaned) > maximum:
        raise ValidationError(f"{field_name} is too long")
    return cleaned


def _integer(value, field_name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field_name} must be an integer")
    if value < minimum or value > maximum:
        raise ValidationError(f"{field_name} is outside the supported range")
    return value


def validate_trigger(value):
    if not isinstance(value, dict):
        raise ValidationError("trigger must be an object")
    trigger_type = value.get("type")
    if trigger_type == "interval":
        _strict_object(value, "trigger", {"type", "minutes"})
        return {
            "type": "interval",
            "minutes": _integer(value["minutes"], "trigger.minutes", 1, 10080),
        }
    if trigger_type == "daily":
        _strict_object(value, "trigger", {"type", "time"})
        time_value = _clean_text(value["time"], "trigger.time", maximum=5)
        if len(time_value) != 5 or time_value[2] != ":":
            raise ValidationError("trigger.time must use HH:MM")
        try:
            hour, minute = (int(item) for item in time_value.split(":"))
        except ValueError as exc:
            raise ValidationError("trigger.time must use HH:MM") from exc
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValidationError("trigger.time must use HH:MM")
        return {"type": "daily", "time": f"{hour:02d}:{minute:02d}"}
    if trigger_type == "event":
        _strict_object(value, "trigger", {"type", "source", "severity"})
        source = value["source"]
        severity = value["severity"]
        if source not in EVENT_SOURCES:
            raise ValidationError("trigger.source is unsupported")
        if severity not in SEVERITIES:
            raise ValidationError("trigger.severity is unsupported")
        return {"type": "event", "source": source, "severity": severity}
    if trigger_type == "metric":
        _strict_object(value, "trigger", {"type", "metric", "operator", "threshold"})
        metric = value["metric"]
        operator = value["operator"]
        threshold = value["threshold"]
        if metric not in METRIC_IDS:
            raise ValidationError("trigger.metric is unsupported")
        if operator not in METRIC_OPERATORS:
            raise ValidationError("trigger.operator is unsupported")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValidationError("trigger.threshold must be a number")
        threshold = float(threshold)
        if not math.isfinite(threshold) or not -1_000_000_000 <= threshold <= 1_000_000_000:
            raise ValidationError("trigger.threshold is outside the supported range")
        return {
            "type": "metric",
            "metric": metric,
            "operator": operator,
            "threshold": threshold,
        }
    raise ValidationError("trigger.type is unsupported")


def validate_action(value):
    if not isinstance(value, dict):
        raise ValidationError("action must be an object")
    action_type = value.get("type")
    if action_type == "notify":
        _strict_object(value, "action", {"type", "title", "body", "severity"})
        severity = value["severity"]
        if severity not in SEVERITIES:
            raise ValidationError("action.severity is unsupported")
        return {
            "type": "notify",
            "title": _clean_text(value["title"], "action.title", maximum=120),
            "body": _clean_text(value["body"], "action.body", maximum=1000, allow_empty=True),
            "severity": severity,
        }
    if action_type == "launcher_task":
        _strict_object(value, "action", {"type", "task_id"})
        task_id = _clean_text(value["task_id"], "action.task_id", maximum=128)
        if not LAUNCHER_TASK_ID.fullmatch(task_id):
            raise ValidationError("action.task_id is invalid")
        return {"type": "launcher_task", "task_id": task_id}
    raise ValidationError("action.type is unsupported")


def validate_rule(value):
    _strict_object(value, "rule", RULE_FIELDS)
    enabled = value["enabled"]
    if not isinstance(enabled, bool):
        raise ValidationError("enabled must be true or false")
    return {
        "name": _clean_text(value["name"], "name", maximum=100),
        "enabled": enabled,
        "trigger": validate_trigger(value["trigger"]),
        "action": validate_action(value["action"]),
        "cooldown_minutes": _integer(
            value["cooldown_minutes"], "cooldown_minutes", 0, 10080
        ),
    }


class AutomationEngine:
    """Encrypted rules, atomic trigger claims, and fixed action execution."""

    def __init__(self, dashboard_store, *, launcher_runner=None, clock=None, timezone=None):
        self.store = dashboard_store
        self.db_path = dashboard_store.db_path
        self.fernet = dashboard_store.fernet
        self.launcher_runner = launcher_runner
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())
        self.timezone = timezone or datetime.now().astimezone().tzinfo or UTC
        self.logger = GlobalLogger.get_logger("AutomationEngine")
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
                CREATE TABLE IF NOT EXISTS automation_rules (
                    rule_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    payload_encrypted TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    next_run_at REAL,
                    last_run_at REAL,
                    event_cursor INTEGER NOT NULL DEFAULT 0,
                    metric_matched INTEGER NOT NULL DEFAULT 0 CHECK (metric_matched IN (0, 1)),
                    claim_token TEXT,
                    claim_run_id TEXT,
                    claim_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS automation_rules_owner_idx
                    ON automation_rules(owner_key, enabled, next_run_at, created_at);

                CREATE TABLE IF NOT EXISTS automation_runs (
                    run_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','skipped')),
                    triggered_at REAL NOT NULL,
                    completed_at REAL,
                    details_encrypted TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS automation_runs_owner_idx
                    ON automation_runs(owner_key, triggered_at DESC);
                CREATE INDEX IF NOT EXISTS automation_runs_rule_idx
                    ON automation_runs(rule_id, triggered_at DESC);
                """
            )

    def _now(self):
        value = self.clock()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).timestamp()
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("clock returned a non-finite value")
        return value

    def _encrypt(self, value):
        try:
            serialized = json.dumps(
                value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            return self.fernet.encrypt(serialized).decode("ascii")
        except (TypeError, ValueError) as exc:
            raise StorageError("Automation data could not be encrypted") from exc

    def _decrypt(self, value):
        try:
            decoded = self.fernet.decrypt(str(value).encode("ascii"))
            payload = json.loads(decoded.decode("utf-8"))
        except Exception as exc:
            raise StorageError("Stored automation data could not be decrypted") from exc
        if not isinstance(payload, dict):
            raise StorageError("Stored automation data is invalid")
        return payload

    @staticmethod
    def _rule_payload(document):
        return {
            "name": document["name"],
            "trigger": document["trigger"],
            "action": document["action"],
            "cooldown_minutes": document["cooldown_minutes"],
        }

    def _next_daily(self, now, time_value):
        hour, minute = (int(item) for item in time_value.split(":"))
        local_now = datetime.fromtimestamp(now, self.timezone)
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate.timestamp() <= now:
            candidate += timedelta(days=1)
        return candidate.timestamp()

    def _next_schedule(self, trigger, now):
        if trigger["type"] == "interval":
            return now + trigger["minutes"] * 60
        if trigger["type"] == "daily":
            return self._next_daily(now, trigger["time"])
        return None

    @staticmethod
    def _advance_schedule(trigger, scheduled_at, now, next_daily):
        if trigger["type"] == "interval":
            interval = trigger["minutes"] * 60
            scheduled_at = float(scheduled_at if scheduled_at is not None else now)
            missed = max(1, int(math.floor((now - scheduled_at) / interval)) + 1)
            return scheduled_at + missed * interval
        if trigger["type"] == "daily":
            return next_daily(now, trigger["time"])
        return None

    def _current_event_cursor(self, connection, owner_key):
        row = connection.execute(
            "SELECT COALESCE(MAX(id), 0) AS cursor FROM dashboard_events WHERE owner_key = ?",
            (owner_key,),
        ).fetchone()
        return int(row["cursor"] if row else 0)

    def _launcher_tasks(self, owner_key):
        if self.launcher_runner is None:
            return []
        try:
            catalog = self.launcher_runner.catalog(owner_key)
        except Exception:
            return []
        tasks = []
        for item in catalog.get("tasks", []):
            if not isinstance(item, dict) or item.get("requires_confirmation") is not False:
                continue
            task_id = item.get("id")
            title = item.get("title")
            agent_name = item.get("agent_name")
            if not all(isinstance(value, str) and value for value in (task_id, title, agent_name)):
                continue
            tasks.append(
                {"id": task_id[:128], "title": title[:120], "agent_name": agent_name[:80]}
            )
        tasks.sort(key=lambda item: (item["agent_name"].casefold(), item["title"].casefold()))
        return tasks

    def _require_launcher_task(self, owner_key, task_id):
        if not any(item["id"] == task_id for item in self._launcher_tasks(owner_key)):
            raise ValidationError("The launcher task is unavailable or requires confirmation")

    def catalog(self, owner_key):
        return {
            "metrics": [dict(item, operators=list(item["operators"])) for item in METRIC_CATALOG],
            "launcher_tasks": self._launcher_tasks(owner_key),
        }

    def create_rule(self, owner_key, value):
        owner_key = _clean_text(str(owner_key), "owner", maximum=256)
        document = validate_rule(value)
        if document["action"]["type"] == "launcher_task":
            self._require_launcher_task(owner_key, document["action"]["task_id"])
        now = self._now()
        rule_id = secrets.token_urlsafe(18)
        with self._connect(immediate=True) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM automation_rules WHERE owner_key = ?", (owner_key,)
            ).fetchone()[0]
            if count >= MAX_RULES_PER_OWNER:
                raise ConflictError("The automation rule limit has been reached")
            cursor = (
                self._current_event_cursor(connection, owner_key)
                if document["trigger"]["type"] == "event"
                else 0
            )
            connection.execute(
                """INSERT INTO automation_rules
                   (rule_id, owner_key, payload_encrypted, enabled, next_run_at,
                    last_run_at, event_cursor, metric_matched, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, 0, ?, ?)""",
                (
                    rule_id,
                    owner_key,
                    self._encrypt(self._rule_payload(document)),
                    int(document["enabled"]),
                    self._next_schedule(document["trigger"], now),
                    cursor,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM automation_rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
        return self._public_rule(row)

    def _owned_rule(self, connection, owner_key, rule_id):
        row = connection.execute(
            "SELECT * FROM automation_rules WHERE owner_key = ? AND rule_id = ?",
            (owner_key, rule_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Automation rule not found")
        return row

    def update_rule(self, owner_key, rule_id, changes):
        if not isinstance(changes, dict) or not changes:
            raise ValidationError("At least one rule field is required")
        unknown = set(changes) - RULE_FIELDS
        if unknown:
            raise ValidationError(f"rule contains unsupported field {sorted(unknown)[0]}")
        now = self._now()
        with self._connect(immediate=True) as connection:
            row = self._owned_rule(connection, owner_key, rule_id)
            current_payload = self._decrypt(row["payload_encrypted"])
            document = {
                **current_payload,
                "enabled": bool(row["enabled"]),
                **changes,
            }
            document = validate_rule(document)
            action_changed = "action" in changes
            if action_changed and document["action"]["type"] == "launcher_task":
                self._require_launcher_task(owner_key, document["action"]["task_id"])
            trigger_changed = "trigger" in changes
            enabling = "enabled" in changes and document["enabled"] and not bool(row["enabled"])
            next_run_at = row["next_run_at"]
            event_cursor = row["event_cursor"]
            metric_matched = row["metric_matched"]
            if trigger_changed or enabling:
                next_run_at = self._next_schedule(document["trigger"], now)
            if trigger_changed:
                event_cursor = (
                    self._current_event_cursor(connection, owner_key)
                    if document["trigger"]["type"] == "event"
                    else 0
                )
                metric_matched = 0
            connection.execute(
                """UPDATE automation_rules
                   SET payload_encrypted = ?, enabled = ?, next_run_at = ?,
                       event_cursor = ?, metric_matched = ?, updated_at = ?
                   WHERE owner_key = ? AND rule_id = ?""",
                (
                    self._encrypt(self._rule_payload(document)),
                    int(document["enabled"]),
                    next_run_at,
                    event_cursor,
                    metric_matched,
                    now,
                    owner_key,
                    rule_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM automation_rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
        return self._public_rule(updated)

    def delete_rule(self, owner_key, rule_id):
        with self._connect(immediate=True) as connection:
            cursor = connection.execute(
                "DELETE FROM automation_rules WHERE owner_key = ? AND rule_id = ?",
                (owner_key, rule_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Automation rule not found")

    def _public_rule(self, row):
        payload = self._decrypt(row["payload_encrypted"])
        return {
            "id": row["rule_id"],
            "name": payload["name"],
            "enabled": bool(row["enabled"]),
            "trigger": payload["trigger"],
            "action": payload["action"],
            "cooldown_minutes": payload["cooldown_minutes"],
            "last_run_at": _iso_timestamp(row["last_run_at"]),
            "next_run_at": _iso_timestamp(row["next_run_at"]),
            "created_at": _iso_timestamp(row["created_at"]),
            "updated_at": _iso_timestamp(row["updated_at"]),
        }

    def _public_run(self, row):
        details = self._decrypt(row["details_encrypted"])
        return {
            "id": row["run_id"],
            "rule_id": row["rule_id"],
            "rule_name": details["rule_name"],
            "status": row["status"],
            "triggered_at": _iso_timestamp(row["triggered_at"]),
            "completed_at": _iso_timestamp(row["completed_at"]),
            "summary": details.get("summary", ""),
        }

    def list(self, owner_key):
        with self._connect(immediate=True) as connection:
            self._purge_runs(connection, owner_key, self._now())
            rules = connection.execute(
                """SELECT * FROM automation_rules WHERE owner_key = ?
                   ORDER BY created_at, rule_id""",
                (owner_key,),
            ).fetchall()
            runs = connection.execute(
                """SELECT * FROM automation_runs WHERE owner_key = ?
                   ORDER BY triggered_at DESC, run_id DESC LIMIT 100""",
                (owner_key,),
            ).fetchall()
        public_rules = [self._public_rule(row) for row in rules]
        public_rules.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        return {"rules": public_rules, "runs": [self._public_run(row) for row in runs]}

    def _purge_runs(self, connection, owner_key, now):
        connection.execute(
            "DELETE FROM automation_runs WHERE owner_key = ? AND triggered_at < ?",
            (owner_key, now - RUN_RETENTION_SECONDS),
        )
        connection.execute(
            """DELETE FROM automation_runs WHERE run_id IN (
                   SELECT run_id FROM automation_runs WHERE owner_key = ?
                   ORDER BY triggered_at DESC LIMIT -1 OFFSET ?
               )""",
            (owner_key, MAX_RUNS_PER_OWNER),
        )

    @staticmethod
    def _compare_metric(value, operator, threshold):
        if operator == "gt":
            return value > threshold
        if operator == "gte":
            return value >= threshold
        if operator == "lt":
            return value < threshold
        if operator == "lte":
            return value <= threshold
        return value == threshold

    @staticmethod
    def _finite_metric(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        return value if math.isfinite(value) else None

    def _metric_value(self, connection, owner_key, metric):
        try:
            if metric.startswith("workstation."):
                row = connection.execute(
                    """SELECT s.payload_encrypted FROM workstation_snapshots s
                       JOIN workstation_agents a ON a.agent_id = s.agent_id
                       WHERE a.owner_key = ? AND a.revoked_at IS NULL
                       ORDER BY s.received_at DESC, s.snapshot_id DESC LIMIT 1""",
                    (owner_key,),
                ).fetchone()
                if row is None:
                    return None
                payload = self._decrypt(row["payload_encrypted"])
                if metric == "workstation.cpu_percent":
                    return self._finite_metric((payload.get("cpu") or {}).get("percent"))
                if metric == "workstation.memory_percent":
                    return self._finite_metric((payload.get("memory") or {}).get("percent"))
                percentages = [
                    self._finite_metric(item.get("percent"))
                    for item in payload.get("disks", [])
                    if isinstance(item, dict)
                ]
                percentages = [value for value in percentages if value is not None]
                return max(percentages) if percentages else None

            rows = connection.execute(
                """SELECT latest_payload_encrypted FROM homelab_agents
                   WHERE owner_key = ? AND revoked_at IS NULL
                         AND latest_payload_encrypted IS NOT NULL""",
                (owner_key,),
            ).fetchall()
            if not rows:
                return None
            total = 0
            for row in rows:
                payload = self._decrypt(row["latest_payload_encrypted"])
                containers = payload.get("containers") or []
                checks = payload.get("health_checks") or []
                if metric == "homelab.containers_unhealthy":
                    total += sum(
                        1 for item in containers
                        if isinstance(item, dict) and item.get("health") == "unhealthy"
                    )
                elif metric == "homelab.health_checks_down":
                    total += sum(
                        1 for item in checks
                        if isinstance(item, dict) and item.get("status") == "down"
                    )
                else:
                    total += sum(
                        1 for item in containers
                        if isinstance(item, dict)
                        and isinstance(item.get("image_update"), dict)
                        and item["image_update"].get("status") == "available"
                    )
            return float(total)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise

    def _automatic_decision(self, connection, row, payload, now):
        trigger = payload["trigger"]
        cooldown = payload["cooldown_minutes"] * 60
        in_cooldown = row["last_run_at"] is not None and now < row["last_run_at"] + cooldown
        updates = {}
        cause = trigger["type"]

        if trigger["type"] in {"interval", "daily"}:
            if row["next_run_at"] is None or row["next_run_at"] > now:
                return False, cause, updates
            updates["next_run_at"] = self._advance_schedule(
                trigger, row["next_run_at"], now, self._next_daily
            )
            return not in_cooldown, cause, updates

        if trigger["type"] == "event":
            event = connection.execute(
                """SELECT MAX(id) AS event_id FROM dashboard_events
                   WHERE owner_key = ? AND id > ? AND source = ? AND severity = ?
                         AND NOT (source = 'automation' AND kind IN ('notification','rule_failure'))""",
                (row["owner_key"], row["event_cursor"], trigger["source"], trigger["severity"]),
            ).fetchone()
            event_id = int(event["event_id"] or 0)
            if not event_id:
                return False, cause, updates
            updates["event_cursor"] = event_id
            return not in_cooldown, cause, updates

        value = self._metric_value(connection, row["owner_key"], trigger["metric"])
        matched = value is not None and self._compare_metric(
            value, trigger["operator"], trigger["threshold"]
        )
        updates["metric_matched"] = int(matched)
        became_true = matched and not bool(row["metric_matched"])
        return became_true and not in_cooldown, cause, updates

    def _apply_state_updates(self, connection, rule_id, updates):
        if not updates:
            return
        allowed = {"next_run_at", "event_cursor", "metric_matched"}
        if set(updates) - allowed:
            raise StorageError("Automation state update is invalid")
        assignments = ", ".join(f"{field} = ?" for field in sorted(updates))
        values = [updates[field] for field in sorted(updates)]
        connection.execute(
            f"UPDATE automation_rules SET {assignments} WHERE rule_id = ?",  # noqa: S608 - fixed allowlist
            (*values, rule_id),
        )

    def _expire_claim(self, connection, row, now):
        if not row["claim_token"] or row["claim_until"] is None or row["claim_until"] > now:
            return row
        if row["claim_run_id"]:
            run = connection.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?", (row["claim_run_id"],)
            ).fetchone()
            if run is not None and run["status"] == "running":
                details = self._decrypt(run["details_encrypted"])
                details["summary"] = "The automation action did not finish before its lease expired."
                connection.execute(
                    """UPDATE automation_runs SET status = 'failed', completed_at = ?,
                           details_encrypted = ? WHERE run_id = ? AND status = 'running'""",
                    (now, self._encrypt(details), run["run_id"]),
                )
        connection.execute(
            """UPDATE automation_rules SET claim_token = NULL, claim_run_id = NULL,
                   claim_until = NULL WHERE rule_id = ? AND claim_token = ?""",
            (row["rule_id"], row["claim_token"]),
        )
        return connection.execute(
            "SELECT * FROM automation_rules WHERE rule_id = ?", (row["rule_id"],)
        ).fetchone()

    def _claim(self, rule_id, *, owner_key=None, automatic):
        now = self._now()
        with self._connect(immediate=True) as connection:
            if owner_key is None:
                row = connection.execute(
                    "SELECT * FROM automation_rules WHERE rule_id = ?", (rule_id,)
                ).fetchone()
            else:
                row = self._owned_rule(connection, owner_key, rule_id)
            if row is None:
                return None
            row = self._expire_claim(connection, row, now)
            if row["claim_token"]:
                if automatic:
                    return None
                raise ConflictError("This automation rule is already running")
            if automatic and not bool(row["enabled"]):
                return None
            payload = self._decrypt(row["payload_encrypted"])
            cause = "manual"
            if automatic:
                due, cause, updates = self._automatic_decision(connection, row, payload, now)
                self._apply_state_updates(connection, rule_id, updates)
                if not due:
                    return None
            run_id = secrets.token_urlsafe(18)
            claim_token = secrets.token_urlsafe(18)
            details = {"rule_name": payload["name"], "summary": "", "cause": cause}
            connection.execute(
                """INSERT INTO automation_runs
                   (run_id, rule_id, owner_key, status, triggered_at, completed_at,
                    details_encrypted)
                   VALUES (?, ?, ?, 'running', ?, NULL, ?)""",
                (
                    run_id,
                    rule_id,
                    row["owner_key"],
                    now,
                    self._encrypt(details),
                ),
            )
            updated = connection.execute(
                """UPDATE automation_rules
                   SET claim_token = ?, claim_run_id = ?, claim_until = ?, last_run_at = ?,
                       updated_at = ?
                   WHERE rule_id = ? AND claim_token IS NULL""",
                (claim_token, run_id, now + CLAIM_TTL_SECONDS, now, now, rule_id),
            )
            if updated.rowcount != 1:
                raise ConflictError("This automation rule is already running")
            self._purge_runs(connection, row["owner_key"], now)
        return {
            "rule_id": rule_id,
            "owner_key": row["owner_key"],
            "rule_name": payload["name"],
            "action": payload["action"],
            "run_id": run_id,
            "claim_token": claim_token,
        }

    def _insert_event(self, owner_key, *, kind, severity, title, body, dedupe_key, now):
        if severity not in SEVERITIES:
            raise ValidationError("Event severity is unsupported")
        title = _clean_text(title, "event title", maximum=120)
        body = _clean_text(body, "event body", maximum=1000, allow_empty=True)
        with self._connect(immediate=True) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO dashboard_events
                   (owner_key, source, kind, severity, title, body, resource_url,
                    dedupe_key, occurred_at, created_at)
                   VALUES (?, 'automation', ?, ?, ?, ?, '#automationModule', ?, ?, ?)""",
                (
                    owner_key,
                    kind,
                    severity,
                    title,
                    body,
                    dedupe_key,
                    _iso_timestamp(now),
                    _iso_timestamp(now),
                ),
            )

    def _execute_launcher(self, owner_key, action):
        if not _environment_enabled("KASUGAI_AUTOMATION_TASKS_ENABLED", False):
            raise PermissionDeniedError("Automated launcher tasks are disabled")
        if self.launcher_runner is None:
            raise PermissionDeniedError("The launcher runner is unavailable")
        task = next(
            (item for item in self._launcher_tasks(owner_key) if item["id"] == action["task_id"]),
            None,
        )
        if task is None:
            raise PermissionDeniedError("The launcher task is unavailable or requires confirmation")
        result = self.launcher_runner.queue_run(owner_key, action["task_id"], {})
        if not isinstance(result, dict) or result.get("queued") is not True:
            raise PermissionDeniedError("The launcher task requires interactive confirmation")
        return f"Queued launcher task: {task['title']}."

    def _finish(self, claim, status, summary):
        now = self._now()
        summary = _clean_text(summary, "run summary", maximum=500, allow_empty=True)
        with self._connect(immediate=True) as connection:
            run = connection.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?", (claim["run_id"],)
            ).fetchone()
            if run is None:
                raise StorageError("Automation run was not found")
            details = self._decrypt(run["details_encrypted"])
            details["summary"] = summary
            connection.execute(
                """UPDATE automation_runs SET status = ?, completed_at = ?, details_encrypted = ?
                   WHERE run_id = ? AND status = 'running'""",
                (status, now, self._encrypt(details), claim["run_id"]),
            )
            connection.execute(
                """UPDATE automation_rules SET claim_token = NULL, claim_run_id = NULL,
                       claim_until = NULL
                   WHERE rule_id = ? AND claim_token = ? AND claim_run_id = ?""",
                (claim["rule_id"], claim["claim_token"], claim["run_id"]),
            )
            completed = connection.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?", (claim["run_id"],)
            ).fetchone()
        return self._public_run(completed)

    def _execute(self, claim):
        try:
            action = claim["action"]
            if action["type"] == "notify":
                self._insert_event(
                    claim["owner_key"],
                    kind="notification",
                    severity=action["severity"],
                    title=action["title"],
                    body=action["body"],
                    dedupe_key=f"automation-run:{claim['run_id']}",
                    now=self._now(),
                )
                summary = "Dashboard notification created."
            else:
                summary = self._execute_launcher(claim["owner_key"], action)
            return self._finish(claim, "succeeded", summary)
        except Exception:
            summary = "The configured automation action could not be completed."
            try:
                run = self._finish(claim, "failed", summary)
                self._insert_event(
                    claim["owner_key"],
                    kind="rule_failure",
                    severity="error",
                    title=f"Automation failed: {claim['rule_name']}",
                    body=summary,
                    dedupe_key=f"automation-failure:{claim['run_id']}",
                    now=self._now(),
                )
                return run
            except Exception as finish_error:
                self.logger.error(
                    "Automation run %s could not be finalized: %s",
                    claim["run_id"],
                    type(finish_error).__name__,
                )
                raise StorageError("Automation run could not be finalized") from finish_error

    def run_rule(self, owner_key, rule_id):
        claim = self._claim(rule_id, owner_key=owner_key, automatic=False)
        return self._execute(claim)

    def _record_evaluation_failure(self, rule_id):
        now = self._now()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT owner_key, payload_encrypted FROM automation_rules WHERE rule_id = ?",
                    (rule_id,),
                ).fetchone()
            if row is None:
                return
            payload = self._decrypt(row["payload_encrypted"])
            self._insert_event(
                row["owner_key"],
                kind="rule_failure",
                severity="error",
                title=f"Automation evaluation failed: {payload['name']}",
                body="The rule could not be evaluated and other automations continued.",
                dedupe_key=f"automation-evaluation:{rule_id}:{int(now // 60)}",
                now=now,
            )
        except Exception:
            self.logger.error("Automation evaluation failure could not be recorded")

    def evaluate_due(self):
        """Atomically claim and execute all rules due at the injected clock time."""

        if not _environment_enabled("KASUGAI_AUTOMATION_ENABLED", True):
            return {"evaluated": 0, "triggered": 0, "failed": 0}
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT rule_id FROM automation_rules WHERE enabled = 1
                   ORDER BY COALESCE(next_run_at, created_at), rule_id"""
            ).fetchall()
        triggered = 0
        failed = 0
        for row in rows:
            rule_id = row["rule_id"]
            try:
                claim = self._claim(rule_id, automatic=True)
                if claim is None:
                    continue
                triggered += 1
                run = self._execute(claim)
                if run["status"] == "failed":
                    failed += 1
            except Exception:
                failed += 1
                self._record_evaluation_failure(rule_id)
        return {"evaluated": len(rows), "triggered": triggered, "failed": failed}


class AutomationScheduler:
    """Bounded daemon wrapper; tests can use AutomationEngine without starting it."""

    def __init__(self, engine, *, interval_seconds=None):
        self.engine = engine
        self.interval_seconds = interval_seconds or _environment_int(
            "KASUGAI_AUTOMATION_SCHEDULER_SECONDS", 15, 5, 300
        )
        self.logger = GlobalLogger.get_logger("AutomationScheduler")
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="kasugai-automation-scheduler", daemon=True
        )
        self._thread.start()
        return True

    def _run(self):
        while not self._stop.wait(self.interval_seconds):
            if not _environment_enabled("KASUGAI_AUTOMATION_ENABLED", True):
                continue
            try:
                self.engine.evaluate_due()
            except Exception as exc:
                self.logger.error("Automation scheduler cycle failed: %s", type(exc).__name__)

    def stop(self, timeout=5.0):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(5.0, max(0.0, float(timeout))))
        stopped = thread is None or not thread.is_alive()
        if stopped:
            self._thread = None
        return stopped
