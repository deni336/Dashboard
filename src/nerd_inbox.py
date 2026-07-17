"""Unified, owner-scoped inbox over local dashboard and live connector data.

The inbox is deliberately an aggregation and local-overlay layer.  It never
marks GitHub notifications read, changes agents, or mutates any source record.
Only local read/archive/pin/snooze state is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import sqlite3
import threading
import urllib.parse
from contextlib import contextmanager
from datetime import UTC, datetime

from src.personal_dashboard import DeveloperCockpit


MAX_PUBLIC_ITEMS = 250
MAX_SOURCE_ITEMS = 250
ORPHAN_RETENTION_SECONDS = 90 * 24 * 60 * 60
PUBLIC_ID = re.compile(r"^[0-9a-f]{32}$")
INTERNAL_FRAGMENT = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]{0,79}$")
GITHUB_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
GITHUB_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
GITHUB_CACHE_SECONDS = 45
SOURCES = (
    ("github", "GitHub"),
    ("developer", "Developer"),
    ("workstation", "Workstation"),
    ("homelab", "Homelab"),
    ("launcher", "Launcher"),
    ("automation", "Automation"),
    ("system", "System"),
)
SOURCE_IDS = {item[0] for item in SOURCES}
SEVERITIES = {"info", "success", "warning", "error"}
KINDS = {
    "notification",
    "event",
    "agent_offline",
    "agent_stale",
    "container_unhealthy",
    "health_check_down",
    "image_update",
    "task_run",
    "rule_failure",
}
BASE_STATES = {"unread", "read", "archived"}
FILTER_STATES = {"active", "unread", "read", "snoozed", "archived", "all"}
CONNECTOR_MESSAGES = {
    "system": "Dashboard activity is temporarily unavailable.",
    "workstation": "Workstation status is temporarily unavailable.",
    "homelab": "Homelab status is temporarily unavailable.",
    "launcher": "Launcher status is temporarily unavailable.",
    "github": "GitHub notifications are temporarily unavailable.",
}
EVENT_DESTINATIONS = {
    "developer": "#developerCockpit",
    "workstation": "#workstationMonitor",
    "homelab": "#homelabDashboard",
    "launcher": "#launcherModule",
    "automation": "#automationModule",
    "github": "",
    "system": "",
}


class InboxError(Exception):
    """Base error safe to expose at the browser boundary."""


class ValidationError(InboxError):
    pass


class NotFoundError(InboxError):
    pass


class StorageError(InboxError):
    pass


def _iso_timestamp(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value, field_name, *, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValidationError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field_name} must include a timezone")
    epoch = parsed.astimezone(UTC).timestamp()
    if not math.isfinite(epoch):
        raise ValidationError(f"{field_name} is invalid")
    return epoch


def _bounded_text(value, maximum, *, fallback=""):
    if not isinstance(value, (str, int, float)):
        return fallback
    text = str(value).replace("\x00", " ")
    text = " ".join(text.split()).strip()
    return (text[:maximum] if text else fallback)[:maximum]


def validate_public_url(value):
    """Return a permitted local fragment or credential-free GitHub HTTPS URL."""

    if value in {None, ""}:
        return ""
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValidationError("Inbox URL is invalid")
    if value != value.strip():
        raise ValidationError("Inbox URL is invalid")
    if INTERNAL_FRAGMENT.fullmatch(value):
        return value
    try:
        parsed = urllib.parse.urlsplit(value)
        # Accessing ``port`` deliberately rejects malformed bracket/port forms.
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Inbox URL is invalid") from exc
    path_segments = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or port is not None
        or parsed.query
        or parsed.fragment
        or len(path_segments) != 3
        or path_segments[0] != ""
        or not GITHUB_OWNER.fullmatch(path_segments[1])
        or not GITHUB_REPOSITORY.fullmatch(path_segments[2])
        or path_segments[2] in {".", ".."}
        or "%" in parsed.path
        or "\\" in parsed.path
    ):
        raise ValidationError("Inbox URL is not permitted")
    return value


def validate_state_patch(value):
    if not isinstance(value, dict) or not value:
        raise ValidationError("At least one inbox state field is required")
    allowed = {"state", "pinned", "snoozed_until"}
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(f"Request contains unsupported field {sorted(unknown)[0]}")
    result = {}
    if "state" in value:
        if value["state"] not in BASE_STATES:
            raise ValidationError("state is unsupported")
        result["state"] = value["state"]
    if "pinned" in value:
        if not isinstance(value["pinned"], bool):
            raise ValidationError("pinned must be true or false")
        result["pinned"] = value["pinned"]
    if "snoozed_until" in value:
        result["snoozed_until"] = _parse_timestamp(
            value["snoozed_until"], "snoozed_until", allow_none=True
        )
    return result


class NerdInbox:
    def __init__(
        self,
        dashboard_store,
        *,
        developer_cockpit=None,
        workstation_monitor=None,
        homelab_monitor=None,
        launcher_runner=None,
        clock=None,
    ):
        self.store = dashboard_store
        self.db_path = dashboard_store.db_path
        self.lookup_key = dashboard_store.lookup_key
        self.developer_cockpit = developer_cockpit or DeveloperCockpit(dashboard_store)
        self.workstation_monitor = workstation_monitor
        self.homelab_monitor = homelab_monitor
        self.launcher_runner = launcher_runner
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())
        self._github_cache = {}
        self._github_cache_lock = threading.Lock()
        self._github_owner_locks = {}
        self._initialize()

    @contextmanager
    def _connect(self, *, immediate=False):
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
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
                CREATE TABLE IF NOT EXISTS inbox_states (
                    owner_key TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'unread'
                        CHECK (state IN ('unread','read','archived')),
                    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
                    snoozed_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    PRIMARY KEY(owner_key, item_id)
                );
                CREATE INDEX IF NOT EXISTS inbox_states_seen_idx
                    ON inbox_states(last_seen_at);
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
            raise ValueError("clock returned an invalid value")
        return value

    def _item_id(self, owner_key, source, stable_key):
        message = "\x00".join(
            ("nerd-inbox-v1", str(owner_key), str(source), str(stable_key))
        ).encode("utf-8", "replace")
        return hmac.new(self.lookup_key, message, hashlib.sha256).hexdigest()[:32]

    @staticmethod
    def _safe_url(value):
        try:
            return validate_public_url(value)
        except ValidationError:
            return ""

    @staticmethod
    def _occurred(value, fallback):
        try:
            return _parse_timestamp(value, "occurred_at")
        except ValidationError:
            return fallback

    def _item(
        self,
        owner_key,
        *,
        stable_key,
        source,
        kind,
        severity,
        title,
        body="",
        url="",
        occurred_at=None,
        live,
        now,
    ):
        if source not in SOURCE_IDS:
            source = "system"
        if kind not in KINDS:
            kind = "event"
        if severity not in SEVERITIES:
            severity = "info"
        occurred_epoch = self._occurred(occurred_at, now)
        return {
            "id": self._item_id(owner_key, source, stable_key),
            "source": source,
            "kind": kind,
            "severity": severity,
            "title": _bounded_text(title, 160, fallback="Dashboard activity"),
            "body": _bounded_text(body, 1000),
            "url": self._safe_url(url),
            "occurred_at": _iso_timestamp(occurred_epoch),
            "state": "unread",
            "pinned": False,
            "snoozed_until": None,
            "live": bool(live),
            "_occurred_epoch": occurred_epoch,
            "_base_state": "unread",
        }

    @staticmethod
    def _event_kind(source, kind):
        if source == "launcher" and kind == "task_run":
            return "task_run"
        if source == "automation" and kind == "rule_failure":
            return "rule_failure"
        if kind == "notification":
            return "notification"
        return "event"

    def _collect_events(self, owner_key, now):
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, source, kind, severity, title, body, resource_url,
                          occurred_at, created_at
                   FROM dashboard_events WHERE owner_key = ?
                   ORDER BY id DESC LIMIT ?""",
                (owner_key, MAX_SOURCE_ITEMS),
            ).fetchall()
        items = []
        for row in rows:
            source = row["source"] if row["source"] in SOURCE_IDS else "system"
            items.append(
                self._item(
                    owner_key,
                    stable_key=f"event:{row['id']}",
                    source=source,
                    kind=self._event_kind(source, row["kind"]),
                    severity=row["severity"],
                    title=row["title"],
                    body=row["body"],
                    # Event URLs are stored as plaintext and may predate the
                    # inbox's navigation policy.  Never relay them verbatim.
                    url=EVENT_DESTINATIONS[source],
                    occurred_at=row["occurred_at"] or row["created_at"],
                    live=False,
                    now=now,
                )
            )
        return items

    def _same_database_connector(self, connector):
        return getattr(connector, "db_path", None) == self.db_path

    @staticmethod
    def _agents(payload, field):
        if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
            raise StorageError("Connector returned an invalid response")
        return payload[field]

    def _agent_health_item(self, owner_key, agent, source, url, now):
        if not isinstance(agent, dict):
            return None
        agent_id = agent.get("id")
        status = agent.get("status")
        if (
            not isinstance(agent_id, str)
            or not agent_id
            or len(agent_id) > 256
            or status not in {"offline", "stale"}
        ):
            return None
        name = _bounded_text(agent.get("display_name"), 100, fallback=source.title())
        kind = "agent_offline" if status == "offline" else "agent_stale"
        severity = "error" if status == "offline" else "warning"
        last_seen = agent.get("last_seen_at") or agent.get("paired_at")
        return self._item(
            owner_key,
            stable_key=f"agent:{agent_id}",
            source=source,
            kind=kind,
            severity=severity,
            title=f"{name} is {status}",
            body=(
                "The companion agent is not reporting."
                if status == "offline"
                else "The companion agent has not reported recently."
            ),
            url=url,
            occurred_at=last_seen,
            live=True,
            now=now,
        )

    def _collect_workstations(self, owner_key, now):
        if self.workstation_monitor is None:
            return []
        agents = self._agents(
            self.workstation_monitor.list_workstations(owner_key), "workstations"
        )
        items = []
        for agent in agents[:MAX_SOURCE_ITEMS]:
            item = self._agent_health_item(
                owner_key, agent, "workstation", "#workstationMonitor", now
            )
            if item:
                items.append(item)
        return items

    def _collect_homelab(self, owner_key, now):
        if self.homelab_monitor is None:
            return []
        partial_error = False
        snapshots = {}
        if self._same_database_connector(self.homelab_monitor):
            # The normal list method decrypts every latest snapshot.  Reading
            # rows separately keeps one damaged encrypted payload from hiding
            # healthy agents and their status.
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT agent_id, display_name, paired_at, last_seen_at,
                              latest_payload_encrypted
                       FROM homelab_agents
                       WHERE owner_key = ? AND revoked_at IS NULL
                       ORDER BY display_name COLLATE NOCASE, paired_at DESC
                       LIMIT ?""",
                    (owner_key, MAX_SOURCE_ITEMS),
                ).fetchall()
            agents = []
            for row in rows:
                agents.append(
                    {
                        "id": row["agent_id"],
                        "display_name": row["display_name"],
                        "paired_at": _iso_timestamp(row["paired_at"]),
                        "last_seen_at": _iso_timestamp(row["last_seen_at"]),
                        "status": self.homelab_monitor.status_for(row["last_seen_at"], now),
                    }
                )
                encrypted = row["latest_payload_encrypted"]
                if encrypted:
                    try:
                        snapshot = self.homelab_monitor._decrypt_payload(  # noqa: SLF001
                            encrypted
                        )
                        if not isinstance(snapshot, dict):
                            raise ValueError("Stored snapshot is not an object")
                        snapshots[row["agent_id"]] = snapshot
                    except Exception:
                        partial_error = True
        else:
            agents = self._agents(self.homelab_monitor.list_agents(owner_key), "agents")
        items = []
        for agent in agents[:MAX_SOURCE_ITEMS]:
            if len(items) >= MAX_SOURCE_ITEMS:
                break
            health_item = self._agent_health_item(
                owner_key, agent, "homelab", "#homelabDashboard", now
            )
            if health_item:
                items.append(health_item)
            if (
                not isinstance(agent, dict)
                or not isinstance(agent.get("id"), str)
                or not agent["id"]
                or len(agent["id"]) > 256
            ):
                continue
            if self._same_database_connector(self.homelab_monitor):
                snapshot = snapshots.get(agent["id"])
            else:
                try:
                    latest = self.homelab_monitor.latest(owner_key, agent["id"])
                    snapshot = latest.get("snapshot") if isinstance(latest, dict) else None
                except Exception:
                    partial_error = True
                    continue
            if not isinstance(snapshot, dict):
                continue
            captured_at = snapshot.get("captured_at")
            containers = snapshot.get("containers")
            checks = snapshot.get("health_checks")
            if not isinstance(containers, list):
                containers = []
                partial_error = True
            if not isinstance(checks, list):
                checks = []
                partial_error = True
            for container in containers[:MAX_SOURCE_ITEMS]:
                if len(items) >= MAX_SOURCE_ITEMS:
                    break
                if not isinstance(container, dict):
                    continue
                resource_key = container.get("key")
                if (
                    not isinstance(resource_key, str)
                    or not resource_key
                    or len(resource_key) > 256
                ):
                    continue
                name = _bounded_text(container.get("name"), 100, fallback="Container")
                if container.get("health") == "unhealthy":
                    items.append(
                        self._item(
                            owner_key,
                            stable_key=f"container-unhealthy:{agent['id']}:{resource_key}",
                            source="homelab",
                            kind="container_unhealthy",
                            severity="error",
                            title=f"{name} is unhealthy",
                            body="Docker reports that this container health check is failing.",
                            url="#homelabDashboard",
                            occurred_at=captured_at,
                            live=True,
                            now=now,
                        )
                    )
                update = container.get("image_update")
                if (
                    len(items) < MAX_SOURCE_ITEMS
                    and isinstance(update, dict)
                    and update.get("status") == "available"
                ):
                    image = _bounded_text(container.get("image"), 160)
                    items.append(
                        self._item(
                            owner_key,
                            stable_key=f"image-update:{agent['id']}:{resource_key}",
                            source="homelab",
                            kind="image_update",
                            severity="info",
                            title=f"Update available for {name}",
                            body=f"A newer image is available{f' for {image}' if image else ''}.",
                            url="#homelabDashboard",
                            occurred_at=update.get("checked_at") or captured_at,
                            live=True,
                            now=now,
                        )
                    )
            for check in checks[:MAX_SOURCE_ITEMS]:
                if len(items) >= MAX_SOURCE_ITEMS:
                    break
                if not isinstance(check, dict):
                    continue
                check_key = check.get("key")
                if (
                    not isinstance(check_key, str)
                    or not check_key
                    or len(check_key) > 256
                    or check.get("status") != "down"
                ):
                    continue
                name = _bounded_text(check.get("name"), 100, fallback="Service")
                items.append(
                    self._item(
                        owner_key,
                        stable_key=f"health-down:{agent['id']}:{check_key}",
                        source="homelab",
                        kind="health_check_down",
                        severity="error",
                        title=f"{name} is down",
                        body="The configured homelab health check is failing.",
                        url="#homelabDashboard",
                        occurred_at=check.get("checked_at") or captured_at,
                        live=True,
                        now=now,
                    )
                )
        return items[:MAX_SOURCE_ITEMS], partial_error

    def _collect_launchers(self, owner_key, now):
        if self.launcher_runner is None:
            return []
        if self._same_database_connector(self.launcher_runner):
            # Catalog contents are irrelevant to inbox health.  Avoid
            # decrypting them so a damaged catalog cannot suppress all agents.
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT agent_id, display_name, paired_at, last_seen_at
                       FROM launcher_agents
                       WHERE owner_key = ? AND revoked_at IS NULL
                       ORDER BY display_name COLLATE NOCASE, paired_at
                       LIMIT ?""",
                    (owner_key, MAX_SOURCE_ITEMS),
                ).fetchall()
            agents = [
                {
                    "id": row["agent_id"],
                    "display_name": row["display_name"],
                    "paired_at": _iso_timestamp(row["paired_at"]),
                    "last_seen_at": _iso_timestamp(row["last_seen_at"]),
                    "status": self.launcher_runner._status(row["last_seen_at"], now),  # noqa: SLF001
                }
                for row in rows
            ]
        else:
            agents = self._agents(self.launcher_runner.list_agents(owner_key), "agents")
        items = []
        for agent in agents[:MAX_SOURCE_ITEMS]:
            item = self._agent_health_item(
                owner_key, agent, "launcher", "#launcherModule", now
            )
            if item:
                items.append(item)
        return items

    def _github_payload(self, owner_key, now):
        with self._github_cache_lock:
            cached = self._github_cache.get(owner_key)
            if cached is not None and cached[0] > now:
                return cached[1]
            owner_lock = self._github_owner_locks.setdefault(owner_key, threading.Lock())
        # Keep the connector call outside every SQLite transaction.  The
        # per-owner lock also prevents duplicate simultaneous refreshes.
        with owner_lock:
            with self._github_cache_lock:
                cached = self._github_cache.get(owner_key)
                if cached is not None and cached[0] > now:
                    return cached[1]
            payload = self.developer_cockpit.github_notifications(owner_key)
            with self._github_cache_lock:
                self._github_cache[owner_key] = (now + GITHUB_CACHE_SECONDS, payload)
            return payload

    def _collect_github(self, owner_key, now):
        payload = self._github_payload(owner_key, now)
        if not isinstance(payload, dict):
            raise StorageError("GitHub returned an invalid response")
        if not payload.get("configured"):
            return []
        notifications = payload.get("notifications")
        if not isinstance(notifications, list):
            raise StorageError("GitHub returned an invalid response")
        account = payload.get("account")
        account = account if isinstance(account, dict) else {}
        account_id = _bounded_text(account.get("account_id"), 64)
        login = _bounded_text(account.get("login"), 100)
        if account_id:
            account_identity = f"id:{account_id}"
        elif login:
            account_identity = f"login:{login.casefold()}"
        else:
            # Owner identity remains in the HMAC input, so this fallback stays
            # isolated between owners even for legacy connector records.
            account_identity = "legacy"
        items = []
        for notification in notifications[:MAX_SOURCE_ITEMS]:
            if not isinstance(notification, dict) or notification.get("unread") is not True:
                continue
            notification_id = notification.get("id")
            if (
                not isinstance(notification_id, str)
                or not notification_id
                or len(notification_id) > 256
            ):
                continue
            repository = _bounded_text(notification.get("repository"), 160)
            reason = _bounded_text(notification.get("reason"), 80)
            subject_type = _bounded_text(notification.get("type"), 80)
            details = " · ".join(item for item in (repository, subject_type, reason) if item)
            items.append(
                self._item(
                    owner_key,
                    stable_key=f"notification:{account_identity}:{notification_id}",
                    source="github",
                    kind="notification",
                    severity="info",
                    title=notification.get("title") or "GitHub notification",
                    body=details,
                    url=notification.get("repository_url"),
                    occurred_at=notification.get("updated_at"),
                    live=True,
                    now=now,
                )
            )
        return items

    @staticmethod
    def _effective_state(base_state, snoozed_until, now):
        if base_state == "archived":
            return "archived"
        if snoozed_until is not None and float(snoozed_until) > now:
            return "snoozed"
        return base_state

    def _read_overlay(self, owner_key, items, now):
        ids = [item["id"] for item in items]
        with self._connect() as connection:
            if ids:
                placeholders = ",".join("?" for _item in ids)
                rows = connection.execute(
                    f"""SELECT item_id, state, pinned, snoozed_until FROM inbox_states
                        WHERE owner_key = ? AND item_id IN ({placeholders})""",  # noqa: S608 - placeholders only
                    (owner_key, *ids),
                ).fetchall()
            else:
                rows = []
        overlay = {row["item_id"]: row for row in rows}
        for item in items:
            state = overlay.get(item["id"])
            base_state = state["state"] if state is not None else "unread"
            snoozed_until = state["snoozed_until"] if state is not None else None
            item["_base_state"] = base_state
            item["state"] = self._effective_state(base_state, snoozed_until, now)
            item["pinned"] = bool(state["pinned"]) if state is not None else False
            item["snoozed_until"] = _iso_timestamp(snoozed_until)
        return items

    @staticmethod
    def _cleanup_overlay(connection, owner_key, current_ids, now):
        parameters = [owner_key, now - ORPHAN_RETENTION_SECONDS]
        sql = "DELETE FROM inbox_states WHERE owner_key = ? AND last_seen_at < ?"
        if current_ids:
            placeholders = ",".join("?" for _item in current_ids)
            sql += f" AND item_id NOT IN ({placeholders})"  # noqa: S608 - placeholders only
            parameters.extend(current_ids)
        connection.execute(sql, parameters)

    def _snapshot(self, owner_key):
        now = self._now()
        items = []
        errors = []
        collectors = (
            ("system", self._collect_events),
            ("workstation", self._collect_workstations),
            ("homelab", self._collect_homelab),
            ("launcher", self._collect_launchers),
            ("github", self._collect_github),
        )
        for source, collector in collectors:
            try:
                collected = collector(owner_key, now)
                if isinstance(collected, tuple):
                    source_items, partial_error = collected
                    items.extend(source_items)
                    if partial_error:
                        errors.append(
                            {"source": source, "message": CONNECTOR_MESSAGES[source]}
                        )
                else:
                    items.extend(collected)
            except Exception:
                errors.append({"source": source, "message": CONNECTOR_MESSAGES[source]})
        deduplicated = {}
        for item in items:
            deduplicated.setdefault(item["id"], item)
        candidates = list(deduplicated.values())
        self._read_overlay(owner_key, candidates, now)
        candidates.sort(
            key=lambda item: (
                not item["pinned"],
                -float(item["_occurred_epoch"]),
                item["id"],
            )
        )
        return candidates, errors, now

    @staticmethod
    def _matches_state(item, state):
        if state == "all":
            return True
        if state == "active":
            return item["state"] in {"unread", "read"}
        return item["state"] == state

    @staticmethod
    def _public_item(item):
        return {
            "id": item["id"],
            "source": item["source"],
            "kind": item["kind"],
            "severity": item["severity"],
            "title": item["title"],
            "body": item["body"],
            "url": item["url"],
            "occurred_at": item["occurred_at"],
            "state": item["state"],
            "pinned": item["pinned"],
            "snoozed_until": item["snoozed_until"],
            "live": item["live"],
        }

    def get(self, owner_key, *, state="active", source=None):
        if state not in FILTER_STATES:
            raise ValidationError("state filter is unsupported")
        if source is None:
            source = None
        elif source not in SOURCE_IDS:
            raise ValidationError("source filter is unsupported")
        items, errors, now = self._snapshot(owner_key)
        active = [item for item in items if item["state"] in {"unread", "read"}]
        counts = {
            "unread": sum(1 for item in active if item["state"] == "unread"),
            "total": len(active),
            "pinned": sum(1 for item in active if item["pinned"]),
        }
        sources = [
            {
                "id": source_id,
                "label": label,
                "count": sum(1 for item in active if item["source"] == source_id),
            }
            for source_id, label in SOURCES
        ]
        filtered = [
            item
            for item in items
            if self._matches_state(item, state) and (source is None or item["source"] == source)
        ][:MAX_PUBLIC_ITEMS]
        return {
            "items": [self._public_item(item) for item in filtered],
            "counts": counts,
            "sources": sources,
            "refreshed_at": _iso_timestamp(now),
            "connector_errors": errors,
        }

    def patch_state(self, owner_key, item_id, changes):
        if not isinstance(item_id, str) or not PUBLIC_ID.fullmatch(item_id):
            raise NotFoundError("Inbox item not found")
        changes = validate_state_patch(changes)
        items, _errors, now = self._snapshot(owner_key)
        current = next((item for item in items if item["id"] == item_id), None)
        if current is None:
            raise NotFoundError("Inbox item not found")
        state = changes.get("state", current["_base_state"])
        pinned = changes.get("pinned", current["pinned"])
        snoozed_until = (
            changes["snoozed_until"]
            if "snoozed_until" in changes
            else _parse_timestamp(current["snoozed_until"], "snoozed_until", allow_none=True)
        )
        with self._connect(immediate=True) as connection:
            connection.execute(
                """INSERT INTO inbox_states
                       (owner_key, item_id, state, pinned, snoozed_until,
                        created_at, updated_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(owner_key, item_id) DO UPDATE SET
                       state = excluded.state,
                       pinned = excluded.pinned,
                       snoozed_until = excluded.snoozed_until,
                       updated_at = excluded.updated_at,
                       last_seen_at = excluded.last_seen_at""",
                (
                    owner_key,
                    item_id,
                    state,
                    int(pinned),
                    snoozed_until,
                    now,
                    now,
                    now,
                ),
            )
            self._cleanup_overlay(connection, owner_key, [item["id"] for item in items], now)
        return {
            "id": item_id,
            "state": self._effective_state(state, snoozed_until, now),
            "pinned": bool(pinned),
            "snoozed_until": _iso_timestamp(snoozed_until),
        }

    def mark_all_read(self, owner_key, *, source=None):
        if source is None:
            source = None
        elif source not in SOURCE_IDS:
            raise ValidationError("source is unsupported")
        items, _errors, now = self._snapshot(owner_key)
        selected = [
            item
            for item in items
            if item["_base_state"] == "unread"
            and (source is None or item["source"] == source)
        ]
        with self._connect(immediate=True) as connection:
            if selected:
                connection.executemany(
                    """INSERT INTO inbox_states
                           (owner_key, item_id, state, pinned, snoozed_until,
                            created_at, updated_at, last_seen_at)
                       VALUES (?, ?, 'read', ?, ?, ?, ?, ?)
                       ON CONFLICT(owner_key, item_id) DO UPDATE SET
                           state = 'read',
                           updated_at = excluded.updated_at,
                           last_seen_at = excluded.last_seen_at""",
                    (
                        (
                            owner_key,
                            item["id"],
                            int(item["pinned"]),
                            _parse_timestamp(
                                item["snoozed_until"], "snoozed_until", allow_none=True
                            ),
                            now,
                            now,
                            now,
                        )
                        for item in selected
                    ),
                )
            self._cleanup_overlay(connection, owner_key, [item["id"] for item in items], now)
        return {"updated": len(selected)}
