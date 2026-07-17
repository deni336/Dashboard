"""Secure storage and service logic for outbound workstation telemetry agents."""

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


MAX_SNAPSHOT_BYTES = 64 * 1024
PAIRING_TTL_SECONDS = 10 * 60
PAIRING_MAX_ATTEMPTS = 5
CAPTURE_MAX_AGE_SECONDS = 24 * 60 * 60
CAPTURE_FUTURE_SKEW_SECONDS = 5 * 60
ONLINE_SECONDS = 30
STALE_SECONDS = 120
MAX_HISTORY_POINTS = 500
MAX_DISKS = 32
MAX_GPUS = 8
MAX_CAPABILITIES = 32
MAX_SQLITE_INTEGER = (1 << 63) - 1
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class WorkstationError(Exception):
    """Base class for errors that are safe to translate at the HTTP boundary."""


class ValidationError(WorkstationError):
    pass


class PayloadTooLargeError(ValidationError):
    pass


class AuthenticationError(WorkstationError):
    pass


class PairingConflictError(WorkstationError):
    pass


class ReplayError(WorkstationError):
    pass


class NotFoundError(WorkstationError):
    pass


class RateLimitError(WorkstationError):
    def __init__(self, retry_after):
        super().__init__("Telemetry is arriving too quickly")
        self.retry_after = max(1, int(math.ceil(retry_after)))


def _environment_int(name, default, minimum, maximum):
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _environment_float(name, default, minimum, maximum):
    try:
        value = float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(maximum, max(minimum, value))


def _iso_timestamp(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value, field_name):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 40
        or not RFC3339_PATTERN.fullmatch(value)
    ):
        raise ValidationError(f"{field_name} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field_name} must include a time zone")
    return parsed.astimezone(UTC).timestamp()


def _clean_string(value, field_name, *, maximum, allow_empty=False):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    value = value.strip()
    if (not value and not allow_empty) or len(value) > maximum:
        raise ValidationError(f"{field_name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError(f"{field_name} contains unsupported characters")
    return value


def _strict_object(value, field_name, required, optional=()):
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ValidationError(f"{field_name} contains an invalid field name")
    required = set(required)
    allowed = required | set(optional)
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise ValidationError(f"{field_name} is missing {sorted(missing)[0]}")
    if unknown:
        raise ValidationError(f"{field_name} contains unsupported field {sorted(unknown)[0]}")
    return value


def _number(
    value,
    field_name,
    *,
    minimum=0,
    maximum=None,
    integer=False,
    allow_none=True,
):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name} must be a number")
    if integer and not isinstance(value, int):
        raise ValidationError(f"{field_name} must be an integer")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValidationError(f"{field_name} must be finite")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{field_name} is outside the supported range")
    return value


def _percentage(value, field_name):
    return _number(value, field_name, minimum=0, maximum=100)


def _counter(value, field_name):
    return _number(
        value,
        field_name,
        minimum=0,
        maximum=MAX_SQLITE_INTEGER,
        integer=True,
    )


def _rate(value, field_name):
    return _number(value, field_name, minimum=0, maximum=1_000_000_000_000_000)


def _validate_capabilities(value):
    if not isinstance(value, list) or len(value) > MAX_CAPABILITIES:
        raise ValidationError("capabilities must be a short array")
    capabilities = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not CAPABILITY_PATTERN.fullmatch(item):
            raise ValidationError("capabilities contains an invalid value")
        if item not in seen:
            capabilities.append(item)
            seen.add(item)
    return capabilities


def validate_pair_request(payload):
    payload = _strict_object(
        payload,
        "request",
        {"pairing_id", "code", "display_name", "agent_version", "platform", "capabilities"},
    )
    pairing_id = _clean_string(payload["pairing_id"], "pairing_id", maximum=128)
    if not IDENTIFIER_PATTERN.fullmatch(pairing_id):
        raise ValidationError("pairing_id is invalid")
    code = _clean_string(payload["code"], "code", maximum=128)
    if len(code) < 20:
        raise ValidationError("code is invalid")
    return {
        "pairing_id": pairing_id,
        "code": code,
        "display_name": _clean_string(payload["display_name"], "display_name", maximum=80),
        "agent_version": _clean_string(payload["agent_version"], "agent_version", maximum=32),
        "platform": _clean_string(payload["platform"], "platform", maximum=160),
        "capabilities": _validate_capabilities(payload["capabilities"]),
    }


def validate_snapshot(payload, *, now_epoch=None):
    """Validate and normalize the complete version-one telemetry document."""
    if not isinstance(payload, dict):
        raise ValidationError("snapshot must be an object")
    try:
        encoded_size = len(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError("snapshot must contain valid JSON values") from exc
    if encoded_size > MAX_SNAPSHOT_BYTES:
        raise ValidationError("snapshot exceeds the 64 KiB limit")

    top = _strict_object(
        payload,
        "snapshot",
        {
            "schema_version",
            "sequence",
            "captured_at",
            "system",
            "cpu",
            "memory",
            "disks",
            "disk_io",
            "network",
            "battery",
            "gpus",
        },
    )
    if top["schema_version"] != 1 or isinstance(top["schema_version"], bool):
        raise ValidationError("schema_version is not supported")
    sequence = _number(
        top["sequence"],
        "sequence",
        minimum=0,
        maximum=MAX_SQLITE_INTEGER,
        integer=True,
        allow_none=False,
    )
    captured_epoch = _parse_timestamp(top["captured_at"], "captured_at")
    reference_epoch = (
        datetime.now(UTC).timestamp() if now_epoch is None else float(now_epoch)
    )
    if captured_epoch > reference_epoch + CAPTURE_FUTURE_SKEW_SECONDS:
        raise ValidationError("captured_at is too far in the future")
    if captured_epoch < reference_epoch - CAPTURE_MAX_AGE_SECONDS:
        raise ValidationError("captured_at is too old")

    system = _strict_object(top["system"], "system", {"uptime_seconds"})
    normalized_system = {
        "uptime_seconds": _number(
            system["uptime_seconds"],
            "system.uptime_seconds",
            minimum=0,
            maximum=100 * 366 * 24 * 60 * 60,
        )
    }

    cpu = _strict_object(
        top["cpu"],
        "cpu",
        {"percent", "physical_count", "logical_count", "frequency_mhz"},
    )
    normalized_cpu = {
        "percent": _percentage(cpu["percent"], "cpu.percent"),
        "physical_count": _number(
            cpu["physical_count"], "cpu.physical_count", minimum=1, maximum=1024, integer=True
        ),
        "logical_count": _number(
            cpu["logical_count"], "cpu.logical_count", minimum=1, maximum=4096, integer=True
        ),
        "frequency_mhz": _number(
            cpu["frequency_mhz"], "cpu.frequency_mhz", minimum=0, maximum=100_000
        ),
    }

    memory = _strict_object(
        top["memory"],
        "memory",
        {"total_bytes", "available_bytes", "used_bytes", "percent"},
    )
    normalized_memory = {
        "total_bytes": _counter(memory["total_bytes"], "memory.total_bytes"),
        "available_bytes": _counter(memory["available_bytes"], "memory.available_bytes"),
        "used_bytes": _counter(memory["used_bytes"], "memory.used_bytes"),
        "percent": _percentage(memory["percent"], "memory.percent"),
    }
    total_memory = normalized_memory["total_bytes"]
    if total_memory is not None:
        for field in ("available_bytes", "used_bytes"):
            value = normalized_memory[field]
            if value is not None and value > total_memory:
                raise ValidationError(f"memory.{field} cannot exceed memory.total_bytes")

    if not isinstance(top["disks"], list) or len(top["disks"]) > MAX_DISKS:
        raise ValidationError("disks must be an array with no more than 32 entries")
    normalized_disks = []
    for index, disk_value in enumerate(top["disks"]):
        prefix = f"disks[{index}]"
        disk = _strict_object(
            disk_value,
            prefix,
            {"name", "filesystem", "total_bytes", "used_bytes", "free_bytes", "percent"},
        )
        normalized_disk = {
            "name": _clean_string(disk["name"], f"{prefix}.name", maximum=64),
            "filesystem": _clean_string(
                disk["filesystem"], f"{prefix}.filesystem", maximum=32, allow_empty=True
            ),
            "total_bytes": _counter(disk["total_bytes"], f"{prefix}.total_bytes"),
            "used_bytes": _counter(disk["used_bytes"], f"{prefix}.used_bytes"),
            "free_bytes": _counter(disk["free_bytes"], f"{prefix}.free_bytes"),
            "percent": _percentage(disk["percent"], f"{prefix}.percent"),
        }
        disk_total = normalized_disk["total_bytes"]
        if disk_total is not None:
            for field in ("used_bytes", "free_bytes"):
                value = normalized_disk[field]
                if value is not None and value > disk_total:
                    raise ValidationError(f"{prefix}.{field} cannot exceed {prefix}.total_bytes")
        normalized_disks.append(normalized_disk)

    disk_io = _strict_object(
        top["disk_io"],
        "disk_io",
        {"read_bytes_total", "write_bytes_total", "read_bps", "write_bps"},
    )
    normalized_disk_io = {
        "read_bytes_total": _counter(disk_io["read_bytes_total"], "disk_io.read_bytes_total"),
        "write_bytes_total": _counter(disk_io["write_bytes_total"], "disk_io.write_bytes_total"),
        "read_bps": _rate(disk_io["read_bps"], "disk_io.read_bps"),
        "write_bps": _rate(disk_io["write_bps"], "disk_io.write_bps"),
    }

    network = _strict_object(
        top["network"],
        "network",
        {"received_bytes_total", "sent_bytes_total", "received_bps", "sent_bps"},
    )
    normalized_network = {
        "received_bytes_total": _counter(
            network["received_bytes_total"], "network.received_bytes_total"
        ),
        "sent_bytes_total": _counter(network["sent_bytes_total"], "network.sent_bytes_total"),
        "received_bps": _rate(network["received_bps"], "network.received_bps"),
        "sent_bps": _rate(network["sent_bps"], "network.sent_bps"),
    }

    battery_value = top["battery"]
    if battery_value is None:
        normalized_battery = None
    else:
        battery = _strict_object(
            battery_value, "battery", {"percent", "plugged", "seconds_left"}
        )
        if battery["plugged"] is not None and not isinstance(battery["plugged"], bool):
            raise ValidationError("battery.plugged must be true, false, or null")
        normalized_battery = {
            "percent": _percentage(battery["percent"], "battery.percent"),
            "plugged": battery["plugged"],
            "seconds_left": _number(
                battery["seconds_left"],
                "battery.seconds_left",
                minimum=0,
                maximum=366 * 24 * 60 * 60,
                integer=True,
            ),
        }

    if not isinstance(top["gpus"], list) or len(top["gpus"]) > MAX_GPUS:
        raise ValidationError("gpus must be an array with no more than 8 entries")
    normalized_gpus = []
    for item_index, gpu_value in enumerate(top["gpus"]):
        prefix = f"gpus[{item_index}]"
        gpu = _strict_object(
            gpu_value,
            prefix,
            {
                "index",
                "name",
                "utilization_percent",
                "memory_used_bytes",
                "memory_total_bytes",
                "temperature_c",
                "power_w",
            },
        )
        normalized_gpu = {
            "index": _number(
                gpu["index"], f"{prefix}.index", minimum=0, maximum=31, integer=True, allow_none=False
            ),
            "name": _clean_string(gpu["name"], f"{prefix}.name", maximum=160),
            "utilization_percent": _percentage(
                gpu["utilization_percent"], f"{prefix}.utilization_percent"
            ),
            "memory_used_bytes": _counter(
                gpu["memory_used_bytes"], f"{prefix}.memory_used_bytes"
            ),
            "memory_total_bytes": _counter(
                gpu["memory_total_bytes"], f"{prefix}.memory_total_bytes"
            ),
            "temperature_c": _number(
                gpu["temperature_c"], f"{prefix}.temperature_c", minimum=-50, maximum=250
            ),
            "power_w": _number(gpu["power_w"], f"{prefix}.power_w", minimum=0, maximum=10_000),
        }
        if (
            normalized_gpu["memory_used_bytes"] is not None
            and normalized_gpu["memory_total_bytes"] is not None
            and normalized_gpu["memory_used_bytes"] > normalized_gpu["memory_total_bytes"]
        ):
            raise ValidationError(f"{prefix}.memory_used_bytes cannot exceed memory_total_bytes")
        normalized_gpus.append(normalized_gpu)

    return {
        "schema_version": 1,
        "sequence": sequence,
        "captured_at": _iso_timestamp(captured_epoch),
        "system": normalized_system,
        "cpu": normalized_cpu,
        "memory": normalized_memory,
        "disks": normalized_disks,
        "disk_io": normalized_disk_io,
        "network": normalized_network,
        "battery": normalized_battery,
        "gpus": normalized_gpus,
    }


class WorkstationMonitor:
    """Per-owner pairing, telemetry ingestion, retention, and query service."""

    def __init__(self, dashboard_store, *, clock=None):
        self.store = dashboard_store
        self.db_path = dashboard_store.db_path
        self.fernet = dashboard_store.fernet
        self.lookup_key = dashboard_store.lookup_key
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())
        self.retention_hours = _environment_int(
            "KASUGAI_WORKSTATION_RETENTION_HOURS", 24, 1, 168
        )
        self.max_agents = _environment_int("KASUGAI_WORKSTATION_MAX_AGENTS", 8, 1, 64)
        self.min_ingest_seconds = _environment_float(
            "KASUGAI_WORKSTATION_MIN_INGEST_SECONDS", 1.0, 0.0, 5.0
        )
        self.interval_seconds = _environment_int(
            "KASUGAI_WORKSTATION_INTERVAL_SECONDS", 10, 5, 60
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
                CREATE TABLE IF NOT EXISTS workstation_pairings (
                    pairing_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    used_at REAL
                );
                CREATE INDEX IF NOT EXISTS workstation_pairings_owner_idx
                    ON workstation_pairings(owner_key, created_at DESC);

                CREATE TABLE IF NOT EXISTS workstation_agents (
                    agent_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    paired_at REAL NOT NULL,
                    last_seen_at REAL,
                    last_sequence INTEGER NOT NULL DEFAULT -1,
                    revoked_at REAL
                );
                CREATE INDEX IF NOT EXISTS workstation_agents_owner_idx
                    ON workstation_agents(owner_key, revoked_at, paired_at DESC);

                CREATE TABLE IF NOT EXISTS workstation_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    captured_at REAL NOT NULL,
                    received_at REAL NOT NULL,
                    cpu_percent REAL,
                    memory_percent REAL,
                    gpu_percent REAL,
                    disk_percent REAL,
                    network_received_bps REAL,
                    network_sent_bps REAL,
                    payload_encrypted TEXT NOT NULL,
                    FOREIGN KEY(agent_id) REFERENCES workstation_agents(agent_id) ON DELETE CASCADE,
                    UNIQUE(agent_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS workstation_snapshots_agent_received_idx
                    ON workstation_snapshots(agent_id, received_at DESC, snapshot_id DESC);
                CREATE INDEX IF NOT EXISTS workstation_snapshots_received_idx
                    ON workstation_snapshots(received_at);
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
        serialized = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self.fernet.encrypt(serialized).decode("ascii")

    def _decrypt_payload(self, encrypted):
        try:
            return json.loads(self.fernet.decrypt(str(encrypted).encode("ascii")))
        except Exception as exc:
            raise WorkstationError("Stored workstation telemetry could not be decrypted") from exc

    def create_pairing(self, owner_key):
        owner_key = _clean_string(str(owner_key), "owner", maximum=256)
        now = self._now()
        pairing_id = secrets.token_urlsafe(18)
        code = secrets.token_urlsafe(24)
        code_hash = self._secret_hash("workstation-pairing-v1", pairing_id, code)
        expires_at = now + PAIRING_TTL_SECONDS
        with self._connect(immediate=True) as connection:
            # Only the newest unused code should remain usable for an owner.
            connection.execute(
                """UPDATE workstation_pairings SET used_at = ?
                   WHERE owner_key = ? AND used_at IS NULL""",
                (now, owner_key),
            )
            connection.execute(
                """INSERT INTO workstation_pairings
                   (pairing_id, owner_key, code_hash, expires_at, attempt_count,
                    max_attempts, created_at, used_at)
                   VALUES (?, ?, ?, ?, 0, ?, ?, NULL)""",
                (
                    pairing_id,
                    owner_key,
                    code_hash,
                    expires_at,
                    PAIRING_MAX_ATTEMPTS,
                    now,
                ),
            )
            connection.execute(
                """DELETE FROM workstation_pairings
                   WHERE created_at < ? AND (used_at IS NOT NULL OR expires_at < ?)""",
                (now - 7 * 24 * 60 * 60, now),
            )
        return {
            "pairing_id": pairing_id,
            "code": code,
            "expires_at": _iso_timestamp(expires_at),
        }

    def pair_agent(self, payload):
        request_data = validate_pair_request(payload)
        now = self._now()
        pairing_id = request_data["pairing_id"]
        invalid_code = False
        result = None
        with self._connect(immediate=True) as connection:
            pairing = connection.execute(
                "SELECT * FROM workstation_pairings WHERE pairing_id = ?", (pairing_id,)
            ).fetchone()
            if (
                pairing is None
                or pairing["used_at"] is not None
                or pairing["expires_at"] <= now
                or pairing["attempt_count"] >= pairing["max_attempts"]
            ):
                raise AuthenticationError("Pairing code is invalid or expired")

            supplied_hash = self._secret_hash(
                "workstation-pairing-v1", pairing_id, request_data["code"]
            )
            if not hmac.compare_digest(pairing["code_hash"], supplied_hash):
                connection.execute(
                    "UPDATE workstation_pairings SET attempt_count = attempt_count + 1 WHERE pairing_id = ?",
                    (pairing_id,),
                )
                invalid_code = True
            else:
                active_count = connection.execute(
                    """SELECT COUNT(*) FROM workstation_agents
                       WHERE owner_key = ? AND revoked_at IS NULL""",
                    (pairing["owner_key"],),
                ).fetchone()[0]
                if active_count >= self.max_agents:
                    raise PairingConflictError("The workstation limit has been reached")

                agent_id = secrets.token_urlsafe(18)
                token = secrets.token_urlsafe(32)
                token_hash = self._secret_hash("workstation-token-v1", agent_id, token)
                connection.execute(
                    """INSERT INTO workstation_agents
                       (agent_id, owner_key, token_hash, display_name, platform,
                        agent_version, capabilities_json, paired_at, last_seen_at,
                        last_sequence, revoked_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, -1, NULL)""",
                    (
                        agent_id,
                        pairing["owner_key"],
                        token_hash,
                        request_data["display_name"],
                        request_data["platform"],
                        request_data["agent_version"],
                        json.dumps(request_data["capabilities"], separators=(",", ":")),
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE workstation_pairings SET used_at = ? WHERE pairing_id = ?",
                    (now, pairing_id),
                )
                result = {
                    "agent_id": agent_id,
                    "token": token,
                    "interval_seconds": self.interval_seconds,
                }
        if invalid_code:
            raise AuthenticationError("Pairing code is invalid or expired")
        return result

    def ingest_snapshot(self, agent_id, token, payload):
        if not isinstance(agent_id, str) or not IDENTIFIER_PATTERN.fullmatch(agent_id):
            raise AuthenticationError("Agent credentials are invalid")
        if not isinstance(token, str) or not token or len(token) > 256:
            raise AuthenticationError("Agent credentials are invalid")
        now = self._now()
        token_hash = self._secret_hash("workstation-token-v1", agent_id, token)
        # Authenticate before doing the comparatively expensive full document
        # validation. The token is checked again under the write lock so a
        # concurrent revocation cannot race a successful ingest.
        with self._connect() as connection:
            authenticated = connection.execute(
                """SELECT token_hash, revoked_at FROM workstation_agents
                   WHERE agent_id = ?""",
                (agent_id,),
            ).fetchone()
            if (
                authenticated is None
                or authenticated["revoked_at"] is not None
                or not hmac.compare_digest(authenticated["token_hash"], token_hash)
            ):
                raise AuthenticationError("Agent credentials are invalid")
        snapshot = validate_snapshot(payload, now_epoch=now)
        with self._connect(immediate=True) as connection:
            agent = connection.execute(
                "SELECT * FROM workstation_agents WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if (
                agent is None
                or agent["revoked_at"] is not None
                or not hmac.compare_digest(agent["token_hash"], token_hash)
            ):
                raise AuthenticationError("Agent credentials are invalid")
            if snapshot["sequence"] <= agent["last_sequence"]:
                raise ReplayError("Snapshot sequence has already been used")
            if (
                agent["last_seen_at"] is not None
                and now - agent["last_seen_at"] < self.min_ingest_seconds
            ):
                raise RateLimitError(self.min_ingest_seconds - (now - agent["last_seen_at"]))

            gpu_percent = (
                snapshot["gpus"][0]["utilization_percent"] if snapshot["gpus"] else None
            )
            disk_percent = snapshot["disks"][0]["percent"] if snapshot["disks"] else None
            try:
                connection.execute(
                    """INSERT INTO workstation_snapshots
                       (agent_id, sequence, captured_at, received_at, cpu_percent,
                        memory_percent, gpu_percent, disk_percent,
                        network_received_bps, network_sent_bps, payload_encrypted)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        agent_id,
                        snapshot["sequence"],
                        _parse_timestamp(snapshot["captured_at"], "captured_at"),
                        now,
                        snapshot["cpu"]["percent"],
                        snapshot["memory"]["percent"],
                        gpu_percent,
                        disk_percent,
                        snapshot["network"]["received_bps"],
                        snapshot["network"]["sent_bps"],
                        self._encrypt_payload(snapshot),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ReplayError("Snapshot sequence has already been used") from exc
            connection.execute(
                """UPDATE workstation_agents
                   SET last_seen_at = ?, last_sequence = ? WHERE agent_id = ?""",
                (now, snapshot["sequence"], agent_id),
            )
            cutoff = now - self.retention_hours * 60 * 60
            connection.execute(
                """DELETE FROM workstation_snapshots WHERE snapshot_id IN (
                       SELECT snapshot_id FROM workstation_snapshots
                       WHERE received_at < ? ORDER BY received_at LIMIT 1000
                   )""",
                (cutoff,),
            )
        return {
            "accepted": True,
            "sequence": snapshot["sequence"],
            "received_at": _iso_timestamp(now),
        }

    @staticmethod
    def status_for(last_seen_at, now):
        if last_seen_at is None:
            return "offline"
        age = max(0, now - float(last_seen_at))
        if age <= ONLINE_SECONDS:
            return "online"
        if age <= STALE_SECONDS:
            return "stale"
        return "offline"

    def _latest_summary(self, connection, agent_id):
        row = connection.execute(
            """SELECT captured_at, received_at, cpu_percent, memory_percent,
                      gpu_percent, disk_percent, network_received_bps,
                      network_sent_bps
               FROM workstation_snapshots WHERE agent_id = ?
               ORDER BY sequence DESC LIMIT 1""",
            (agent_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "captured_at": _iso_timestamp(row["captured_at"]),
            "received_at": _iso_timestamp(row["received_at"]),
            "cpu_percent": row["cpu_percent"],
            "memory_percent": row["memory_percent"],
            "gpu_percent": row["gpu_percent"],
            "disk_percent": row["disk_percent"],
            "network_received_bps": row["network_received_bps"],
            "network_sent_bps": row["network_sent_bps"],
        }

    def _public_agent(self, connection, row, now):
        try:
            capabilities = json.loads(row["capabilities_json"])
        except (TypeError, ValueError):
            capabilities = []
        return {
            "id": row["agent_id"],
            "display_name": row["display_name"],
            "platform": row["platform"],
            "agent_version": row["agent_version"],
            "capabilities": capabilities if isinstance(capabilities, list) else [],
            "paired_at": _iso_timestamp(row["paired_at"]),
            "last_seen_at": _iso_timestamp(row["last_seen_at"]),
            "status": self.status_for(row["last_seen_at"], now),
            "latest_summary": self._latest_summary(connection, row["agent_id"]),
        }

    def list_workstations(self, owner_key):
        now = self._now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM workstation_agents
                   WHERE owner_key = ? AND revoked_at IS NULL
                   ORDER BY display_name COLLATE NOCASE, paired_at DESC""",
                (owner_key,),
            ).fetchall()
            workstations = [self._public_agent(connection, row, now) for row in rows]
        return {"workstations": workstations}

    def latest(self, owner_key, agent_id):
        now = self._now()
        with self._connect() as connection:
            agent = connection.execute(
                """SELECT * FROM workstation_agents
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (owner_key, agent_id),
            ).fetchone()
            if agent is None:
                raise NotFoundError("Workstation not found")
            row = connection.execute(
                """SELECT received_at, payload_encrypted FROM workstation_snapshots
                   WHERE agent_id = ? ORDER BY sequence DESC LIMIT 1""",
                (agent_id,),
            ).fetchone()
            workstation = self._public_agent(connection, agent, now)
            snapshot = None
            if row:
                snapshot = self._decrypt_payload(row["payload_encrypted"])
                snapshot["received_at"] = _iso_timestamp(row["received_at"])
        return {"workstation": workstation, "snapshot": snapshot}

    def history(self, owner_key, agent_id, *, minutes=60, bucket_seconds=60):
        try:
            minutes = int(minutes)
            bucket_seconds = int(bucket_seconds)
        except (TypeError, ValueError) as exc:
            raise ValidationError("History window must contain integers") from exc
        minutes = min(24 * 60, max(1, minutes))
        bucket_seconds = min(60 * 60, max(5, bucket_seconds))
        window_seconds = minutes * 60
        bucket_seconds = max(bucket_seconds, int(math.ceil(window_seconds / MAX_HISTORY_POINTS)))
        now = self._now()
        cutoff = now - window_seconds
        with self._connect() as connection:
            exists = connection.execute(
                """SELECT 1 FROM workstation_agents
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (owner_key, agent_id),
            ).fetchone()
            if not exists:
                raise NotFoundError("Workstation not found")
            rows = connection.execute(
                """SELECT received_at, cpu_percent, memory_percent, gpu_percent,
                          disk_percent, network_received_bps, network_sent_bps
                   FROM workstation_snapshots
                   WHERE agent_id = ? AND received_at >= ?
                   ORDER BY received_at""",
                (agent_id, cutoff),
            ).fetchall()

        fields = (
            "cpu_percent",
            "memory_percent",
            "gpu_percent",
            "disk_percent",
            "network_received_bps",
            "network_sent_bps",
        )
        buckets = {}
        for row in rows:
            bucket_epoch = math.floor(row["received_at"] / bucket_seconds) * bucket_seconds
            bucket = buckets.setdefault(bucket_epoch, {field: [] for field in fields})
            bucket["count"] = bucket.get("count", 0) + 1
            for field in fields:
                if row[field] is not None:
                    bucket[field].append(row[field])
        points = []
        for bucket_epoch, values in sorted(buckets.items()):
            point = {
                "at": _iso_timestamp(bucket_epoch),
                "count": values["count"],
            }
            for field in fields:
                point[field] = (
                    sum(values[field]) / len(values[field]) if values[field] else None
                )
            points.append(point)
        return {
            "workstation_id": agent_id,
            "minutes": minutes,
            "bucket_seconds": bucket_seconds,
            "points": points[-MAX_HISTORY_POINTS:],
        }

    def rename(self, owner_key, agent_id, display_name):
        display_name = _clean_string(display_name, "display_name", maximum=80)
        with self._connect(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE workstation_agents SET display_name = ?
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (display_name, owner_key, agent_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Workstation not found")
        return {"id": agent_id, "display_name": display_name}

    def revoke(self, owner_key, agent_id, *, delete_history=True):
        now = self._now()
        with self._connect(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE workstation_agents
                   SET revoked_at = ?, token_hash = ?
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (
                    now,
                    self._secret_hash("workstation-revoked-v1", agent_id, secrets.token_urlsafe(16)),
                    owner_key,
                    agent_id,
                ),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Workstation not found")
            if delete_history:
                connection.execute(
                    "DELETE FROM workstation_snapshots WHERE agent_id = ?", (agent_id,)
                )
