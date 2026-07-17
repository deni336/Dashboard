"""Secure storage and protocol logic for outbound homelab inventory agents.

The dashboard never talks to a Docker daemon.  A separately paired companion
agent sends a deliberately small inventory document and claims fixed, locally
authorized actions from an outbound queue.
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


MAX_SNAPSHOT_BYTES = 256 * 1024
MAX_RESULT_BYTES = 72 * 1024
PAIRING_TTL_SECONDS = 10 * 60
PAIRING_MAX_ATTEMPTS = 5
CAPTURE_MAX_AGE_SECONDS = 24 * 60 * 60
CAPTURE_FUTURE_SKEW_SECONDS = 5 * 60
ACTION_INVENTORY_MAX_AGE_SECONDS = 45
ACTION_TTL_SECONDS = 2 * 60
ACTION_CLAIM_SECONDS = 60
CONFIRMATION_TTL_SECONDS = 60
ONLINE_SECONDS = 45
STALE_SECONDS = 180
MAX_CONTAINERS = 100
MAX_HEALTH_CHECKS = 64
MAX_STORAGE = 8
MAX_PORTS = 32
MAX_SQLITE_INTEGER = (1 << 63) - 1

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
ANSI_PATTERN = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

CAPABILITIES = frozenset({"inventory", "read_logs", "restart"})
ACTIONS = frozenset({"read_logs", "restart"})
CONTAINER_STATES = frozenset(
    {"created", "running", "paused", "restarting", "removing", "exited", "dead", "unknown"}
)
HEALTH_STATES = frozenset({"healthy", "unhealthy", "starting", "none", "unknown"})
ENGINE_ERRORS = frozenset(
    {
        "not_installed",
        "daemon_unavailable",
        "context_not_local",
        "timed_out",
        "permission_denied",
        "protocol_error",
    }
)
CHECK_ERRORS = frozenset(
    {
        "timeout",
        "dns_failed",
        "connection_refused",
        "tls_failed",
        "unexpected_status",
        "protocol_error",
    }
)
RESULT_CODES = frozenset(
    {
        "ok",
        "policy_denied",
        "resource_missing",
        "invalid_state",
        "docker_unavailable",
        "timed_out",
        "command_failed",
        "output_unavailable",
    }
)
TERMINAL_ACTION_STATES = frozenset(
    {"succeeded", "failed", "rejected", "expired", "cancelled", "unknown"}
)


class HomelabError(Exception):
    """Base error safe to translate at the HTTP boundary."""


class ValidationError(HomelabError):
    pass


class PayloadTooLargeError(ValidationError):
    pass


class AuthenticationError(HomelabError):
    pass


class PairingConflictError(HomelabError):
    pass


class ReplayError(HomelabError):
    pass


class NotFoundError(HomelabError):
    pass


class PermissionDeniedError(HomelabError):
    pass


class ConflictError(HomelabError):
    pass


class ExpiredError(ConflictError):
    pass


class RateLimitError(HomelabError):
    def __init__(self, message, retry_after):
        super().__init__(message)
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
    if not isinstance(value, str) or len(value) > 40 or not RFC3339_PATTERN.fullmatch(value):
        raise ValidationError(f"{field_name} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field_name} must include a time zone")
    return parsed.astimezone(UTC).timestamp()


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


def _clean_string(value, field_name, *, maximum, allow_empty=False, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    value = value.strip()
    if (not value and not allow_empty) or len(value) > maximum:
        raise ValidationError(f"{field_name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError(f"{field_name} contains unsupported characters")
    return value


def _enum(value, field_name, allowed, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(f"{field_name} is not supported")
    return value


def _number(value, field_name, *, minimum=0, maximum=None, integer=False, nullable=True):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name} must be a number")
    if integer and not isinstance(value, int):
        raise ValidationError(f"{field_name} must be an integer")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{field_name} is outside the supported range")
    return value


def _counter(value, field_name, *, maximum=MAX_SQLITE_INTEGER, nullable=True):
    return _number(
        value, field_name, minimum=0, maximum=maximum, integer=True, nullable=nullable
    )


def _boolean(value, field_name):
    if not isinstance(value, bool):
        raise ValidationError(f"{field_name} must be true or false")
    return value


def _resource_key(value, field_name):
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValidationError(f"{field_name} is invalid")
    return value


def _unique_enums(value, field_name, allowed, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValidationError(f"{field_name} must be a short array")
    result = []
    seen = set()
    for item in value:
        item = _enum(item, field_name, allowed)
        if item in seen:
            raise ValidationError(f"{field_name} contains a duplicate value")
        seen.add(item)
        result.append(item)
    return result


def _encoded_size(payload, field_name):
    try:
        return len(
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError(f"{field_name} must contain valid JSON values") from exc


def validate_pair_request(payload):
    payload = _strict_object(
        payload,
        "request",
        {"pairing_id", "code", "display_name", "agent_version", "platform", "capabilities"},
    )
    pairing_id = _resource_key(payload["pairing_id"], "pairing_id")
    code = _clean_string(payload["code"], "code", maximum=128)
    if len(code) < 20:
        raise ValidationError("code is invalid")
    capabilities = _unique_enums(payload["capabilities"], "capabilities", CAPABILITIES, 8)
    if "inventory" not in capabilities:
        raise ValidationError("capabilities must include inventory")
    return {
        "pairing_id": pairing_id,
        "code": code,
        "display_name": _clean_string(payload["display_name"], "display_name", maximum=80),
        "agent_version": _clean_string(payload["agent_version"], "agent_version", maximum=32),
        "platform": _clean_string(payload["platform"], "platform", maximum=160),
        "capabilities": capabilities,
    }


def _validate_policy(value):
    value = _strict_object(
        value,
        "policy",
        {"revision", "inventory_scope", "logs_enabled", "allowed_actions", "image_updates_enabled"},
    )
    return {
        "revision": _clean_string(value["revision"], "policy.revision", maximum=128),
        "inventory_scope": _enum(value["inventory_scope"], "policy.inventory_scope", {"labeled", "all"}),
        "logs_enabled": _boolean(value["logs_enabled"], "policy.logs_enabled"),
        "allowed_actions": _unique_enums(
            value["allowed_actions"], "policy.allowed_actions", {"restart"}, 1
        ),
        "image_updates_enabled": _boolean(
            value["image_updates_enabled"], "policy.image_updates_enabled"
        ),
    }


def _validate_engine(value):
    value = _strict_object(
        value,
        "engine",
        {
            "available", "key", "kind", "server_version", "operating_system", "os_type",
            "architecture", "cpu_count", "memory_bytes", "container_counts", "image_count",
            "volume_count", "network_count", "checked_at", "error_code",
        },
    )
    available = _boolean(value["available"], "engine.available")
    key = value["key"]
    if key is not None:
        key = _resource_key(key, "engine.key")
    if available and key is None:
        raise ValidationError("engine.key is required when the engine is available")
    error_code = _enum(value["error_code"], "engine.error_code", ENGINE_ERRORS, nullable=True)
    if available and error_code is not None:
        raise ValidationError("engine.error_code must be null when the engine is available")
    if not available and error_code is None:
        raise ValidationError("engine.error_code is required when the engine is unavailable")
    counts = _strict_object(
        value["container_counts"],
        "engine.container_counts",
        {"total", "running", "paused", "stopped"},
    )
    normalized_counts = {
        key_name: _counter(
            counts[key_name], f"engine.container_counts.{key_name}", maximum=MAX_CONTAINERS, nullable=False
        )
        for key_name in ("total", "running", "paused", "stopped")
    }
    if sum(normalized_counts[name] for name in ("running", "paused", "stopped")) > normalized_counts["total"]:
        raise ValidationError("engine.container_counts exceeds total")
    return {
        "available": available,
        "key": key,
        "kind": _enum(value["kind"], "engine.kind", {"docker"}),
        "server_version": _clean_string(
            value["server_version"], "engine.server_version", maximum=64, allow_empty=not available
        ),
        "operating_system": _clean_string(
            value["operating_system"], "engine.operating_system", maximum=128, allow_empty=not available
        ),
        "os_type": _clean_string(value["os_type"], "engine.os_type", maximum=32, allow_empty=not available),
        "architecture": _clean_string(
            value["architecture"], "engine.architecture", maximum=32, allow_empty=not available
        ),
        "cpu_count": _counter(value["cpu_count"], "engine.cpu_count", maximum=4096),
        "memory_bytes": _counter(value["memory_bytes"], "engine.memory_bytes"),
        "container_counts": normalized_counts,
        "image_count": _counter(value["image_count"], "engine.image_count", maximum=1_000_000, nullable=False),
        "volume_count": _counter(value["volume_count"], "engine.volume_count", maximum=1_000_000, nullable=False),
        "network_count": _counter(value["network_count"], "engine.network_count", maximum=1_000_000, nullable=False),
        "checked_at": _iso_timestamp(_parse_timestamp(value["checked_at"], "engine.checked_at")),
        "error_code": error_code,
    }


def _validate_storage(values):
    if not isinstance(values, list) or len(values) > MAX_STORAGE:
        raise ValidationError("storage must contain no more than 8 entries")
    result = []
    kinds = set()
    for index, item in enumerate(values):
        prefix = f"storage[{index}]"
        item = _strict_object(
            item, prefix, {"kind", "total_count", "active_count", "size_bytes", "reclaimable_bytes"}
        )
        kind = _enum(item["kind"], f"{prefix}.kind", {"images", "containers", "volumes", "build_cache"})
        if kind in kinds:
            raise ValidationError("storage contains a duplicate kind")
        kinds.add(kind)
        total_count = _counter(item["total_count"], f"{prefix}.total_count", maximum=1_000_000, nullable=False)
        active_count = _counter(item["active_count"], f"{prefix}.active_count", maximum=1_000_000, nullable=False)
        if active_count > total_count:
            raise ValidationError(f"{prefix}.active_count cannot exceed total_count")
        size_bytes = _counter(item["size_bytes"], f"{prefix}.size_bytes")
        reclaimable_bytes = _counter(item["reclaimable_bytes"], f"{prefix}.reclaimable_bytes")
        if size_bytes is not None and reclaimable_bytes is not None and reclaimable_bytes > size_bytes:
            raise ValidationError(f"{prefix}.reclaimable_bytes cannot exceed size_bytes")
        result.append(
            {
                "kind": kind,
                "total_count": total_count,
                "active_count": active_count,
                "size_bytes": size_bytes,
                "reclaimable_bytes": reclaimable_bytes,
            }
        )
    return result


def _validate_containers(values):
    if not isinstance(values, list) or len(values) > MAX_CONTAINERS:
        raise ValidationError("containers must contain no more than 100 entries")
    result = []
    keys = set()
    for index, item in enumerate(values):
        prefix = f"containers[{index}]"
        item = _strict_object(
            item,
            prefix,
            {
                "key", "name", "image", "compose_project", "compose_service", "state", "health",
                "created_at", "cpu_percent", "memory_usage_bytes", "memory_limit_bytes",
                "memory_percent", "network_rx_bytes", "network_tx_bytes", "block_read_bytes",
                "block_write_bytes", "pids", "ports", "image_update", "grants",
            },
        )
        key = _resource_key(item["key"], f"{prefix}.key")
        if key in keys:
            raise ValidationError("containers contains a duplicate key")
        keys.add(key)
        ports = item["ports"]
        if not isinstance(ports, list) or len(ports) > MAX_PORTS:
            raise ValidationError(f"{prefix}.ports must contain no more than 32 entries")
        normalized_ports = []
        port_keys = set()
        for port_index, port in enumerate(ports):
            port_prefix = f"{prefix}.ports[{port_index}]"
            port = _strict_object(port, port_prefix, {"container_port", "host_port", "protocol"})
            normalized_port = {
                "container_port": _counter(
                    port["container_port"], f"{port_prefix}.container_port", maximum=65535, nullable=False
                ),
                "host_port": _counter(port["host_port"], f"{port_prefix}.host_port", maximum=65535),
                "protocol": _enum(port["protocol"], f"{port_prefix}.protocol", {"tcp", "udp", "sctp"}),
            }
            if normalized_port["container_port"] < 1 or (
                normalized_port["host_port"] is not None and normalized_port["host_port"] < 1
            ):
                raise ValidationError(f"{port_prefix} contains an invalid port")
            port_key = tuple(normalized_port.values())
            if port_key in port_keys:
                raise ValidationError(f"{prefix}.ports contains a duplicate")
            port_keys.add(port_key)
            normalized_ports.append(normalized_port)
        image_update = _strict_object(item["image_update"], f"{prefix}.image_update", {"status", "checked_at"})
        image_checked = image_update["checked_at"]
        if image_checked is not None:
            image_checked = _iso_timestamp(_parse_timestamp(image_checked, f"{prefix}.image_update.checked_at"))
        grants = _strict_object(item["grants"], f"{prefix}.grants", {"logs", "actions"})
        created_at = item["created_at"]
        if created_at is not None:
            created_at = _iso_timestamp(_parse_timestamp(created_at, f"{prefix}.created_at"))
        memory_usage = _counter(item["memory_usage_bytes"], f"{prefix}.memory_usage_bytes")
        memory_limit = _counter(item["memory_limit_bytes"], f"{prefix}.memory_limit_bytes")
        if memory_usage is not None and memory_limit is not None and memory_usage > memory_limit:
            raise ValidationError(f"{prefix}.memory_usage_bytes cannot exceed memory_limit_bytes")
        result.append(
            {
                "key": key,
                "name": _clean_string(item["name"], f"{prefix}.name", maximum=128),
                "image": _clean_string(item["image"], f"{prefix}.image", maximum=512),
                "compose_project": _clean_string(
                    item["compose_project"], f"{prefix}.compose_project", maximum=128, nullable=True
                ),
                "compose_service": _clean_string(
                    item["compose_service"], f"{prefix}.compose_service", maximum=128, nullable=True
                ),
                "state": _enum(item["state"], f"{prefix}.state", CONTAINER_STATES),
                "health": _enum(item["health"], f"{prefix}.health", HEALTH_STATES),
                "created_at": created_at,
                "cpu_percent": _number(item["cpu_percent"], f"{prefix}.cpu_percent", maximum=100_000),
                "memory_usage_bytes": memory_usage,
                "memory_limit_bytes": memory_limit,
                "memory_percent": _number(item["memory_percent"], f"{prefix}.memory_percent", maximum=100_000),
                "network_rx_bytes": _counter(item["network_rx_bytes"], f"{prefix}.network_rx_bytes"),
                "network_tx_bytes": _counter(item["network_tx_bytes"], f"{prefix}.network_tx_bytes"),
                "block_read_bytes": _counter(item["block_read_bytes"], f"{prefix}.block_read_bytes"),
                "block_write_bytes": _counter(item["block_write_bytes"], f"{prefix}.block_write_bytes"),
                "pids": _counter(item["pids"], f"{prefix}.pids", maximum=1_000_000),
                "ports": normalized_ports,
                "image_update": {
                    "status": _enum(
                        image_update["status"], f"{prefix}.image_update.status", {"unknown", "current", "available"}
                    ),
                    "checked_at": image_checked,
                },
                "grants": {
                    "logs": _boolean(grants["logs"], f"{prefix}.grants.logs"),
                    "actions": _unique_enums(
                        grants["actions"], f"{prefix}.grants.actions", {"restart"}, 1
                    ),
                },
            }
        )
    return result


def _validate_health_checks(values):
    if not isinstance(values, list) or len(values) > MAX_HEALTH_CHECKS:
        raise ValidationError("health_checks must contain no more than 64 entries")
    result = []
    keys = set()
    for index, item in enumerate(values):
        prefix = f"health_checks[{index}]"
        item = _strict_object(
            item,
            prefix,
            {
                "key", "name", "kind", "status", "checked_at", "latency_ms", "http_status",
                "tls_expires_in_days", "consecutive_failures", "error_code",
            },
        )
        key = _resource_key(item["key"], f"{prefix}.key")
        if key in keys:
            raise ValidationError("health_checks contains a duplicate key")
        keys.add(key)
        checked_at = item["checked_at"]
        if checked_at is not None:
            checked_at = _iso_timestamp(_parse_timestamp(checked_at, f"{prefix}.checked_at"))
        http_status = _counter(item["http_status"], f"{prefix}.http_status", maximum=599)
        if http_status is not None and http_status < 100:
            raise ValidationError(f"{prefix}.http_status is invalid")
        result.append(
            {
                "key": key,
                "name": _clean_string(item["name"], f"{prefix}.name", maximum=128),
                "kind": _enum(item["kind"], f"{prefix}.kind", {"http", "tcp"}),
                "status": _enum(item["status"], f"{prefix}.status", {"up", "down", "degraded", "unknown", "paused"}),
                "checked_at": checked_at,
                "latency_ms": _number(item["latency_ms"], f"{prefix}.latency_ms", maximum=3_600_000),
                "http_status": http_status,
                "tls_expires_in_days": _number(
                    item["tls_expires_in_days"], f"{prefix}.tls_expires_in_days", minimum=-3650, maximum=36500
                ),
                "consecutive_failures": _counter(
                    item["consecutive_failures"], f"{prefix}.consecutive_failures", maximum=1_000_000, nullable=False
                ),
                "error_code": _enum(item["error_code"], f"{prefix}.error_code", CHECK_ERRORS, nullable=True),
            }
        )
    return result


def validate_snapshot(payload, *, now_epoch=None):
    """Validate and normalize the strict homelab-agent v1 inventory document."""
    if not isinstance(payload, dict):
        raise ValidationError("snapshot must be an object")
    if _encoded_size(payload, "snapshot") > MAX_SNAPSHOT_BYTES:
        raise PayloadTooLargeError("snapshot exceeds the 256 KiB limit")
    payload = _strict_object(
        payload,
        "snapshot",
        {"schema_version", "sequence", "captured_at", "policy", "engine", "storage", "containers", "health_checks", "truncated"},
    )
    if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
        raise ValidationError("schema_version is not supported")
    sequence = _counter(payload["sequence"], "sequence", nullable=False)
    captured_epoch = _parse_timestamp(payload["captured_at"], "captured_at")
    now_epoch = datetime.now(UTC).timestamp() if now_epoch is None else float(now_epoch)
    if captured_epoch > now_epoch + CAPTURE_FUTURE_SKEW_SECONDS:
        raise ValidationError("captured_at is too far in the future")
    if captured_epoch < now_epoch - CAPTURE_MAX_AGE_SECONDS:
        raise ValidationError("captured_at is too old")
    truncated = _strict_object(
        payload["truncated"], "truncated", {"containers", "storage", "health_checks"}
    )
    normalized = {
        "schema_version": 1,
        "sequence": sequence,
        "captured_at": _iso_timestamp(captured_epoch),
        "policy": _validate_policy(payload["policy"]),
        "engine": _validate_engine(payload["engine"]),
        "storage": _validate_storage(payload["storage"]),
        "containers": _validate_containers(payload["containers"]),
        "health_checks": _validate_health_checks(payload["health_checks"]),
        "truncated": {
            field: _boolean(truncated[field], f"truncated.{field}")
            for field in ("containers", "storage", "health_checks")
        },
    }
    resource_keys = [item["key"] for item in normalized["containers"]]
    resource_keys.extend(item["key"] for item in normalized["health_checks"])
    if len(resource_keys) != len(set(resource_keys)):
        raise ValidationError("resource keys must be unique across the snapshot")
    if not normalized["engine"]["available"] and (
        normalized["containers"] or normalized["storage"]
    ):
        raise ValidationError("unavailable engines cannot report Docker resources")
    return normalized


def validate_action_request(payload):
    payload = _strict_object(
        payload, "request", {"operation", "resource_key"}, {"confirmation_token"}
    )
    confirmation = payload.get("confirmation_token")
    if confirmation is not None:
        confirmation = _clean_string(confirmation, "confirmation_token", maximum=300)
    return {
        "operation": _enum(payload["operation"], "operation", ACTIONS),
        "resource_key": _resource_key(payload["resource_key"], "resource_key"),
        "confirmation_token": confirmation,
    }


def validate_result(payload, operation):
    if _encoded_size(payload, "result") > MAX_RESULT_BYTES:
        raise PayloadTooLargeError("result exceeds the supported limit")
    payload = _strict_object(
        payload,
        "result",
        {"schema_version", "claim_token", "completed_at", "status", "code", "observed_state", "log_excerpt", "truncated"},
    )
    if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
        raise ValidationError("schema_version is not supported")
    claim_token = _clean_string(payload["claim_token"], "claim_token", maximum=256)
    if len(claim_token) < 20:
        raise ValidationError("claim_token is invalid")
    status = _enum(payload["status"], "status", {"succeeded", "failed", "rejected"})
    code = _enum(payload["code"], "code", RESULT_CODES)
    if (status == "succeeded") != (code == "ok"):
        raise ValidationError("status and code do not agree")
    observed_state = _enum(
        payload["observed_state"], "observed_state", CONTAINER_STATES, nullable=True
    )
    truncated = _boolean(payload["truncated"], "truncated")
    excerpt = payload["log_excerpt"]
    if excerpt is not None:
        if operation != "read_logs" or not isinstance(excerpt, str):
            raise ValidationError("log_excerpt is only supported for read_logs")
        excerpt = ANSI_PATTERN.sub("", excerpt).replace("\x00", "")
        encoded = excerpt.encode("utf-8")
        if len(encoded) > 64 * 1024 or len(excerpt.splitlines()) > 200:
            raise PayloadTooLargeError("log_excerpt exceeds the 64 KiB or 200 line limit")
    elif operation == "restart" and truncated:
        raise ValidationError("restart results cannot be truncated")
    return {
        "schema_version": 1,
        "claim_token": claim_token,
        "completed_at": _iso_timestamp(_parse_timestamp(payload["completed_at"], "completed_at")),
        "status": status,
        "code": code,
        "observed_state": observed_state,
        "log_excerpt": excerpt,
        "truncated": truncated,
    }


class HomelabMonitor:
    """Pairing, inventory, history, and fixed-action state machine."""

    def __init__(self, dashboard_store, *, clock=None):
        self.store = dashboard_store
        self.db_path = dashboard_store.db_path
        self.fernet = dashboard_store.fernet
        self.lookup_key = dashboard_store.lookup_key
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())
        self.max_agents = _environment_int("KASUGAI_HOMELAB_MAX_AGENTS", 8, 1, 64)
        self.interval_seconds = _environment_int("KASUGAI_HOMELAB_INTERVAL_SECONDS", 15, 5, 3600)
        self.action_poll_interval_seconds = _environment_int(
            "KASUGAI_HOMELAB_ACTION_POLL_SECONDS", 5, 2, 60
        )
        self.retention_hours = _environment_int(
            "KASUGAI_HOMELAB_SAMPLE_RETENTION_HOURS", 168, 1, 24 * 365
        )
        self.min_ingest_seconds = _environment_float(
            "KASUGAI_HOMELAB_MIN_INGEST_SECONDS", 1.0, 0.0, 60.0
        )
        self.min_claim_seconds = _environment_float(
            "KASUGAI_HOMELAB_MIN_CLAIM_SECONDS", 1.0, 0.0, 30.0
        )
        self.min_action_seconds = _environment_float(
            "KASUGAI_HOMELAB_MIN_ACTION_SECONDS", 2.0, 0.0, 60.0
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
                CREATE TABLE IF NOT EXISTS homelab_pairings (
                    pairing_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    used_at REAL
                );
                CREATE INDEX IF NOT EXISTS homelab_pairings_owner_idx
                    ON homelab_pairings(owner_key, created_at DESC);

                CREATE TABLE IF NOT EXISTS homelab_agents (
                    agent_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    paired_at REAL NOT NULL,
                    last_seen_at REAL,
                    last_ingest_at REAL,
                    last_claim_at REAL,
                    last_sequence INTEGER NOT NULL DEFAULT -1,
                    latest_captured_at REAL,
                    latest_payload_encrypted TEXT,
                    revoked_at REAL
                );
                CREATE INDEX IF NOT EXISTS homelab_agents_owner_idx
                    ON homelab_agents(owner_key, revoked_at, paired_at DESC);

                CREATE TABLE IF NOT EXISTS homelab_samples (
                    agent_id TEXT NOT NULL,
                    bucket_at REAL NOT NULL,
                    received_at REAL NOT NULL,
                    engine_available INTEGER NOT NULL,
                    containers_total INTEGER NOT NULL,
                    containers_running INTEGER NOT NULL,
                    containers_unhealthy INTEGER NOT NULL,
                    health_checks_down INTEGER NOT NULL,
                    updates_available INTEGER NOT NULL,
                    PRIMARY KEY(agent_id, bucket_at),
                    FOREIGN KEY(agent_id) REFERENCES homelab_agents(agent_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS homelab_samples_received_idx
                    ON homelab_samples(received_at);

                CREATE TABLE IF NOT EXISTS homelab_action_previews (
                    preview_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    operation TEXT NOT NULL CHECK (operation = 'restart'),
                    resource_hash TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    payload_encrypted TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed_at REAL,
                    FOREIGN KEY(agent_id) REFERENCES homelab_agents(agent_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS homelab_actions (
                    action_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    resource_hash TEXT NOT NULL,
                    operation TEXT NOT NULL CHECK (operation IN ('read_logs', 'restart')),
                    payload_encrypted TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('queued', 'claimed', 'succeeded', 'failed', 'rejected',
                                  'expired', 'cancelled', 'unknown')
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
                    result_payload_encrypted TEXT,
                    purge_after REAL NOT NULL,
                    FOREIGN KEY(agent_id) REFERENCES homelab_agents(agent_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS homelab_actions_agent_state_idx
                    ON homelab_actions(agent_id, state, requested_at);
                CREATE INDEX IF NOT EXISTS homelab_actions_owner_idx
                    ON homelab_actions(owner_key, requested_at DESC);
                CREATE INDEX IF NOT EXISTS homelab_actions_purge_idx
                    ON homelab_actions(purge_after);
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
            raise HomelabError("Stored homelab data could not be decrypted") from exc

    def _authenticate(self, connection, agent_id, token):
        if not isinstance(agent_id, str) or not IDENTIFIER_PATTERN.fullmatch(agent_id):
            raise AuthenticationError("Agent credentials are invalid")
        if not isinstance(token, str) or not token or len(token) > 256:
            raise AuthenticationError("Agent credentials are invalid")
        row = connection.execute(
            "SELECT * FROM homelab_agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        supplied = self._secret_hash("homelab-token-v1", agent_id, token)
        if row is None or row["revoked_at"] is not None or not hmac.compare_digest(row["token_hash"], supplied):
            raise AuthenticationError("Agent credentials are invalid")
        return row

    def create_pairing(self, owner_key):
        owner_key = _clean_string(str(owner_key), "owner", maximum=256)
        now = self._now()
        pairing_id = secrets.token_urlsafe(18)
        code = secrets.token_urlsafe(24)
        code_hash = self._secret_hash("homelab-pairing-v1", pairing_id, code)
        with self._connect(immediate=True) as connection:
            connection.execute(
                "UPDATE homelab_pairings SET used_at = ? WHERE owner_key = ? AND used_at IS NULL",
                (now, owner_key),
            )
            connection.execute(
                """INSERT INTO homelab_pairings
                   (pairing_id, owner_key, code_hash, expires_at, attempt_count,
                    max_attempts, created_at, used_at)
                   VALUES (?, ?, ?, ?, 0, ?, ?, NULL)""",
                (pairing_id, owner_key, code_hash, now + PAIRING_TTL_SECONDS, PAIRING_MAX_ATTEMPTS, now),
            )
            connection.execute(
                "DELETE FROM homelab_pairings WHERE created_at < ? AND (used_at IS NOT NULL OR expires_at < ?)",
                (now - 7 * 24 * 60 * 60, now),
            )
        return {
            "pairing_id": pairing_id,
            "code": code,
            "expires_at": _iso_timestamp(now + PAIRING_TTL_SECONDS),
        }

    def pair_agent(self, payload):
        request_data = validate_pair_request(payload)
        now = self._now()
        pairing_id = request_data["pairing_id"]
        invalid_code = False
        result = None
        with self._connect(immediate=True) as connection:
            pairing = connection.execute(
                "SELECT * FROM homelab_pairings WHERE pairing_id = ?", (pairing_id,)
            ).fetchone()
            if (
                pairing is None or pairing["used_at"] is not None or pairing["expires_at"] <= now
                or pairing["attempt_count"] >= pairing["max_attempts"]
            ):
                raise AuthenticationError("Pairing code is invalid or expired")
            supplied = self._secret_hash("homelab-pairing-v1", pairing_id, request_data["code"])
            if not hmac.compare_digest(pairing["code_hash"], supplied):
                connection.execute(
                    "UPDATE homelab_pairings SET attempt_count = attempt_count + 1 WHERE pairing_id = ?",
                    (pairing_id,),
                )
                invalid_code = True
            else:
                active = connection.execute(
                    "SELECT COUNT(*) FROM homelab_agents WHERE owner_key = ? AND revoked_at IS NULL",
                    (pairing["owner_key"],),
                ).fetchone()[0]
                if active >= self.max_agents:
                    raise PairingConflictError("The homelab agent limit has been reached")
                agent_id = secrets.token_urlsafe(18)
                token = secrets.token_urlsafe(32)
                connection.execute(
                    """INSERT INTO homelab_agents
                       (agent_id, owner_key, token_hash, display_name, platform,
                        agent_version, capabilities_json, paired_at, last_sequence)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, -1)""",
                    (
                        agent_id, pairing["owner_key"],
                        self._secret_hash("homelab-token-v1", agent_id, token),
                        request_data["display_name"], request_data["platform"],
                        request_data["agent_version"],
                        json.dumps(request_data["capabilities"], separators=(",", ":")), now,
                    ),
                )
                connection.execute(
                    "UPDATE homelab_pairings SET used_at = ? WHERE pairing_id = ?", (now, pairing_id)
                )
                result = {
                    "agent_id": agent_id,
                    "token": token,
                    "interval_seconds": self.interval_seconds,
                    "action_poll_interval_seconds": self.action_poll_interval_seconds,
                }
        if invalid_code:
            raise AuthenticationError("Pairing code is invalid or expired")
        return result

    def ingest_snapshot(self, agent_id, token, payload):
        now = self._now()
        with self._connect() as connection:
            self._authenticate(connection, agent_id, token)
        snapshot = validate_snapshot(payload, now_epoch=now)
        with self._connect(immediate=True) as connection:
            agent = self._authenticate(connection, agent_id, token)
            if snapshot["sequence"] <= agent["last_sequence"]:
                raise ReplayError("Snapshot sequence has already been used")
            if agent["last_ingest_at"] is not None and now - agent["last_ingest_at"] < self.min_ingest_seconds:
                raise RateLimitError(
                    "Inventory is arriving too quickly",
                    self.min_ingest_seconds - (now - agent["last_ingest_at"]),
                )
            captured_at = _parse_timestamp(snapshot["captured_at"], "captured_at")
            encrypted = self._encrypt_payload(snapshot)
            connection.execute(
                """UPDATE homelab_agents
                   SET last_seen_at = ?, last_ingest_at = ?, last_sequence = ?,
                       latest_captured_at = ?, latest_payload_encrypted = ?
                   WHERE agent_id = ?""",
                (now, now, snapshot["sequence"], captured_at, encrypted, agent_id),
            )
            bucket_at = math.floor(captured_at / 60) * 60
            containers = snapshot["containers"]
            unhealthy = sum(1 for item in containers if item["health"] == "unhealthy")
            down = sum(1 for item in snapshot["health_checks"] if item["status"] == "down")
            updates = sum(1 for item in containers if item["image_update"]["status"] == "available")
            connection.execute(
                """INSERT INTO homelab_samples
                   (agent_id, bucket_at, received_at, engine_available, containers_total,
                    containers_running, containers_unhealthy, health_checks_down, updates_available)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, bucket_at) DO UPDATE SET
                    received_at=excluded.received_at,
                    engine_available=excluded.engine_available,
                    containers_total=excluded.containers_total,
                    containers_running=excluded.containers_running,
                    containers_unhealthy=excluded.containers_unhealthy,
                    health_checks_down=excluded.health_checks_down,
                    updates_available=excluded.updates_available""",
                (
                    agent_id, bucket_at, now, int(snapshot["engine"]["available"]), len(containers),
                    sum(1 for item in containers if item["state"] == "running"), unhealthy, down, updates,
                ),
            )
            connection.execute(
                "DELETE FROM homelab_samples WHERE received_at < ?",
                (now - self.retention_hours * 3600,),
            )
            self._expire_actions(connection, now)
            self._purge_actions(connection, now)
        return {"accepted": True, "sequence": snapshot["sequence"], "received_at": _iso_timestamp(now)}

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

    def _snapshot_summary(self, payload):
        if not payload:
            return None
        containers = payload.get("containers") or []
        checks = payload.get("health_checks") or []
        return {
            "captured_at": payload.get("captured_at"),
            "engine_available": bool((payload.get("engine") or {}).get("available")),
            "containers_total": len(containers),
            "containers_running": sum(1 for item in containers if item.get("state") == "running"),
            "containers_unhealthy": sum(1 for item in containers if item.get("health") == "unhealthy"),
            "health_checks_down": sum(1 for item in checks if item.get("status") == "down"),
            "updates_available": sum(
                1 for item in containers if (item.get("image_update") or {}).get("status") == "available"
            ),
        }

    def _public_agent(self, row, now, latest=None):
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
            "latest_summary": self._snapshot_summary(latest),
        }

    @staticmethod
    def _derive_stacks(containers):
        stacks = {}
        for container in containers:
            name = container.get("compose_project")
            if not name:
                continue
            stack = stacks.setdefault(
                name,
                {"name": name, "containers_total": 0, "containers_running": 0, "containers_unhealthy": 0},
            )
            stack["containers_total"] += 1
            stack["containers_running"] += int(container.get("state") == "running")
            stack["containers_unhealthy"] += int(container.get("health") == "unhealthy")
        return sorted(stacks.values(), key=lambda item: item["name"].casefold())

    def list_agents(self, owner_key):
        now = self._now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM homelab_agents
                   WHERE owner_key = ? AND revoked_at IS NULL
                   ORDER BY display_name COLLATE NOCASE, paired_at DESC""",
                (owner_key,),
            ).fetchall()
            agents = []
            for row in rows:
                latest = self._decrypt_payload(row["latest_payload_encrypted"]) if row["latest_payload_encrypted"] else None
                agents.append(self._public_agent(row, now, latest))
        return {"agents": agents}

    def latest(self, owner_key, agent_id):
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM homelab_agents
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (owner_key, agent_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Homelab agent not found")
            snapshot = self._decrypt_payload(row["latest_payload_encrypted"]) if row["latest_payload_encrypted"] else None
            agent = self._public_agent(row, now, snapshot)
        if snapshot is not None:
            snapshot["stacks"] = self._derive_stacks(snapshot.get("containers") or [])
        return {"agent": agent, "snapshot": snapshot}

    def history(self, owner_key, agent_id, *, hours=24):
        try:
            hours = int(hours)
        except (TypeError, ValueError) as exc:
            raise ValidationError("hours must be an integer") from exc
        hours = min(self.retention_hours, max(1, hours))
        now = self._now()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM homelab_agents WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL",
                (owner_key, agent_id),
            ).fetchone()
            if not exists:
                raise NotFoundError("Homelab agent not found")
            rows = connection.execute(
                """SELECT * FROM homelab_samples WHERE agent_id = ? AND bucket_at >= ?
                   ORDER BY bucket_at""",
                (agent_id, now - hours * 3600),
            ).fetchall()
        return {
            "agent_id": agent_id,
            "hours": hours,
            "points": [
                {
                    "at": _iso_timestamp(row["bucket_at"]),
                    "received_at": _iso_timestamp(row["received_at"]),
                    "engine_available": bool(row["engine_available"]),
                    "containers_total": row["containers_total"],
                    "containers_running": row["containers_running"],
                    "containers_unhealthy": row["containers_unhealthy"],
                    "health_checks_down": row["health_checks_down"],
                    "updates_available": row["updates_available"],
                }
                for row in rows
            ],
        }

    def rename(self, owner_key, agent_id, display_name):
        display_name = _clean_string(display_name, "display_name", maximum=80)
        with self._connect(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE homelab_agents SET display_name = ?
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (display_name, owner_key, agent_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Homelab agent not found")
        return {"id": agent_id, "display_name": display_name}

    def revoke(self, owner_key, agent_id, *, delete_history=True):
        now = self._now()
        with self._connect(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE homelab_agents SET revoked_at = ?, token_hash = ?,
                       latest_payload_encrypted = NULL, latest_captured_at = NULL
                   WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
                (
                    now,
                    self._secret_hash("homelab-revoked-v1", agent_id, secrets.token_urlsafe(16)),
                    owner_key,
                    agent_id,
                ),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Homelab agent not found")
            connection.execute(
                """UPDATE homelab_actions SET state = 'cancelled', completed_at = ?,
                       claim_token_hash = NULL
                   WHERE agent_id = ? AND state IN ('queued', 'claimed')""",
                (now, agent_id),
            )
            connection.execute(
                "UPDATE homelab_action_previews SET consumed_at = ? WHERE agent_id = ? AND consumed_at IS NULL",
                (now, agent_id),
            )
            if delete_history:
                connection.execute("DELETE FROM homelab_samples WHERE agent_id = ?", (agent_id,))

    def _owned_agent_snapshot(self, connection, owner_key, agent_id, now):
        row = connection.execute(
            """SELECT * FROM homelab_agents
               WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL""",
            (owner_key, agent_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Homelab agent not found")
        if row["latest_payload_encrypted"] is None:
            raise ConflictError("The agent has not sent an inventory yet")
        if row["last_seen_at"] is None or now - row["last_seen_at"] > ACTION_INVENTORY_MAX_AGE_SECONDS:
            raise ConflictError("The latest inventory is too old for an action")
        return row, self._decrypt_payload(row["latest_payload_encrypted"])

    @staticmethod
    def _find_resource(snapshot, resource_key):
        return next((item for item in snapshot.get("containers", []) if item.get("key") == resource_key), None)

    @staticmethod
    def _has_grant(snapshot, resource, operation):
        policy = snapshot.get("policy") or {}
        grants = resource.get("grants") or {}
        if operation == "read_logs":
            return bool(policy.get("logs_enabled") and grants.get("logs"))
        return operation in (policy.get("allowed_actions") or []) and operation in (grants.get("actions") or [])

    def _resource_hash(self, agent_id, resource_key):
        return self._secret_hash("homelab-resource-v1", agent_id, resource_key)

    def _verify_action_target(self, connection, owner_key, agent_id, request_data, now):
        agent, snapshot = self._owned_agent_snapshot(connection, owner_key, agent_id, now)
        operation = request_data["operation"]
        capabilities = json.loads(agent["capabilities_json"])
        if operation not in capabilities:
            raise PermissionDeniedError("The paired agent does not support this operation")
        if not snapshot["engine"]["available"]:
            raise ConflictError("The Docker engine is unavailable")
        resource = self._find_resource(snapshot, request_data["resource_key"])
        if resource is None:
            raise NotFoundError("Container not found in the latest inventory")
        if not self._has_grant(snapshot, resource, operation):
            raise PermissionDeniedError("The host policy does not grant this operation")
        return agent, snapshot, resource

    def _actions_enabled(self):
        return os.getenv("KASUGAI_HOMELAB_ACTIONS_ENABLED", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }

    def preview_restart(self, owner_key, agent_id, request_data):
        if not self._actions_enabled():
            raise PermissionDeniedError("Homelab actions are disabled by the server")
        now = self._now()
        with self._connect(immediate=True) as connection:
            _, _, resource = self._verify_action_target(connection, owner_key, agent_id, request_data, now)
            preview_id = secrets.token_urlsafe(18)
            token_secret = secrets.token_urlsafe(24)
            token_hash = self._secret_hash("homelab-confirmation-v1", preview_id, token_secret)
            public_resource = {
                "key": resource["key"], "name": resource["name"], "image": resource["image"],
                "state": resource["state"], "kind": "container",
            }
            connection.execute(
                """INSERT INTO homelab_action_previews
                   (preview_id, agent_id, owner_key, operation, resource_hash, token_hash,
                    payload_encrypted, created_at, expires_at)
                   VALUES (?, ?, ?, 'restart', ?, ?, ?, ?, ?)""",
                (
                    preview_id, agent_id, owner_key,
                    self._resource_hash(agent_id, resource["key"]), token_hash,
                    self._encrypt_payload(public_resource), now, now + CONFIRMATION_TTL_SECONDS,
                ),
            )
            connection.execute(
                "DELETE FROM homelab_action_previews WHERE expires_at < ? AND created_at < ?",
                (now, now - 3600),
            )
        return {
            "confirmation_required": True,
            "confirmation_token": f"{preview_id}.{token_secret}",
            "expires_at": _iso_timestamp(now + CONFIRMATION_TTL_SECONDS),
            "operation": "restart",
            "resource": public_resource,
        }

    def _consume_confirmation(self, connection, owner_key, agent_id, resource_key, token, now):
        preview_id, separator, secret = str(token or "").partition(".")
        if not separator or not IDENTIFIER_PATTERN.fullmatch(preview_id) or len(secret) < 20:
            raise AuthenticationError("Confirmation token is invalid or expired")
        row = connection.execute(
            "SELECT * FROM homelab_action_previews WHERE preview_id = ?", (preview_id,)
        ).fetchone()
        supplied = self._secret_hash("homelab-confirmation-v1", preview_id, secret)
        expected_resource = self._resource_hash(agent_id, resource_key)
        if (
            row is None or row["owner_key"] != owner_key or row["agent_id"] != agent_id
            or row["operation"] != "restart" or row["consumed_at"] is not None or row["expires_at"] <= now
            or not hmac.compare_digest(row["token_hash"], supplied)
            or not hmac.compare_digest(row["resource_hash"], expected_resource)
        ):
            raise AuthenticationError("Confirmation token is invalid or expired")
        connection.execute(
            "UPDATE homelab_action_previews SET consumed_at = ? WHERE preview_id = ?", (now, preview_id)
        )

    def queue_action(self, owner_key, agent_id, payload):
        request_data = validate_action_request(payload)
        if not self._actions_enabled():
            raise PermissionDeniedError("Homelab actions are disabled by the server")
        if request_data["operation"] == "restart" and not request_data["confirmation_token"]:
            return {"preview": self.preview_restart(owner_key, agent_id, request_data), "queued": False}
        if request_data["operation"] == "read_logs" and request_data["confirmation_token"]:
            raise ValidationError("read_logs does not accept a confirmation token")
        now = self._now()
        with self._connect(immediate=True) as connection:
            _, _, resource = self._verify_action_target(connection, owner_key, agent_id, request_data, now)
            resource_hash = self._resource_hash(agent_id, resource["key"])
            if request_data["operation"] == "restart":
                self._consume_confirmation(
                    connection, owner_key, agent_id, resource["key"], request_data["confirmation_token"], now
                )
            self._expire_actions(connection, now)
            active = connection.execute(
                """SELECT 1 FROM homelab_actions
                   WHERE agent_id = ? AND resource_hash = ? AND state IN ('queued', 'claimed')""",
                (agent_id, resource_hash),
            ).fetchone()
            if active:
                raise ConflictError("An action is already active for this resource")
            last = connection.execute(
                "SELECT MAX(requested_at) FROM homelab_actions WHERE owner_key = ?", (owner_key,)
            ).fetchone()[0]
            if last is not None and now - last < self.min_action_seconds:
                raise RateLimitError(
                    "Actions are being requested too quickly", self.min_action_seconds - (now - last)
                )
            action_id = secrets.token_urlsafe(18)
            action_payload = {
                "schema_version": 1,
                "operation": request_data["operation"],
                "resource_key": resource["key"],
            }
            connection.execute(
                """INSERT INTO homelab_actions
                   (action_id, agent_id, owner_key, resource_hash, operation, payload_encrypted,
                    state, requested_at, expires_at, purge_after)
                   VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                (
                    action_id, agent_id, owner_key, resource_hash, request_data["operation"],
                    self._encrypt_payload(action_payload), now, now + ACTION_TTL_SECONDS,
                    now + 7 * 24 * 3600,
                ),
            )
        return {"queued": True, "action": self.get_action(owner_key, agent_id, action_id)}

    def _expire_actions(self, connection, now):
        connection.execute(
            """UPDATE homelab_actions SET state = 'expired', completed_at = ?, claim_token_hash = NULL
               WHERE state = 'queued' AND expires_at <= ?""",
            (now, now),
        )
        connection.execute(
            """UPDATE homelab_actions SET state = 'unknown', completed_at = ?
               WHERE state = 'claimed' AND completion_deadline <= ?""",
            (now, now),
        )

    def _purge_actions(self, connection, now):
        connection.execute(
            "DELETE FROM homelab_actions WHERE purge_after <= ? AND state NOT IN ('queued', 'claimed')", (now,)
        )

    def claim_action(self, agent_id, token, payload):
        payload = _strict_object(payload, "request", {"schema_version"})
        if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
            raise ValidationError("schema_version is not supported")
        now = self._now()
        with self._connect(immediate=True) as connection:
            agent = self._authenticate(connection, agent_id, token)
            if not self._actions_enabled():
                # The deployment kill switch is checked again at delivery time,
                # so disabling actions also prevents previously queued work from
                # reaching an agent.
                connection.execute(
                    """UPDATE homelab_actions
                       SET state = 'cancelled', completed_at = ?
                       WHERE agent_id = ? AND state = 'queued'""",
                    (now, agent_id),
                )
                return None
            if agent["last_claim_at"] is not None and now - agent["last_claim_at"] < self.min_claim_seconds:
                raise RateLimitError(
                    "Action polling is too frequent", self.min_claim_seconds - (now - agent["last_claim_at"])
                )
            connection.execute("UPDATE homelab_agents SET last_claim_at = ? WHERE agent_id = ?", (now, agent_id))
            self._expire_actions(connection, now)
            self._purge_actions(connection, now)
            row = connection.execute(
                """SELECT * FROM homelab_actions
                   WHERE agent_id = ? AND state = 'queued' AND expires_at > ?
                   ORDER BY requested_at, action_id LIMIT 1""",
                (agent_id, now),
            ).fetchone()
            if row is None:
                return None
            claim_token = secrets.token_urlsafe(32)
            deadline = min(row["expires_at"], now + ACTION_CLAIM_SECONDS)
            updated = connection.execute(
                """UPDATE homelab_actions SET state = 'claimed', claimed_at = ?,
                       completion_deadline = ?, claim_token_hash = ?
                   WHERE action_id = ? AND state = 'queued'""",
                (
                    now, deadline,
                    self._secret_hash("homelab-action-claim-v1", row["action_id"], claim_token),
                    row["action_id"],
                ),
            )
            if updated.rowcount != 1:
                return None
            action_payload = self._decrypt_payload(row["payload_encrypted"])
        return {
            "schema_version": 1,
            "action_id": row["action_id"],
            "claim_token": claim_token,
            "operation": action_payload["operation"],
            "resource_key": action_payload["resource_key"],
            "expires_at": _iso_timestamp(deadline),
        }

    def submit_result(self, agent_id, token, action_id, payload):
        now = self._now()
        with self._connect() as connection:
            self._authenticate(connection, agent_id, token)
            row = connection.execute(
                "SELECT operation FROM homelab_actions WHERE action_id = ? AND agent_id = ?",
                (action_id, agent_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Action not found")
        result = validate_result(payload, row["operation"])
        completed_at = _parse_timestamp(result["completed_at"], "completed_at")
        if completed_at > now + CAPTURE_FUTURE_SKEW_SECONDS or completed_at < now - CAPTURE_MAX_AGE_SECONDS:
            raise ValidationError("completed_at is outside the accepted window")
        canonical = dict(result)
        claim_token = canonical.pop("claim_token")
        result_hash = self._secret_hash(
            "homelab-result-v1",
            action_id,
            json.dumps(canonical, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")),
        )
        with self._connect(immediate=True) as connection:
            self._authenticate(connection, agent_id, token)
            action = connection.execute(
                "SELECT * FROM homelab_actions WHERE action_id = ? AND agent_id = ?",
                (action_id, agent_id),
            ).fetchone()
            if action is None:
                raise NotFoundError("Action not found")
            supplied_claim = self._secret_hash("homelab-action-claim-v1", action_id, claim_token)
            if action["claim_token_hash"] is None or not hmac.compare_digest(action["claim_token_hash"], supplied_claim):
                raise AuthenticationError("Action claim token is invalid")
            if action["state"] in {"succeeded", "failed", "rejected"}:
                if action["result_hash"] and hmac.compare_digest(action["result_hash"], result_hash):
                    return {
                        "accepted": True, "idempotent": True, "action_id": action_id,
                        "state": action["state"], "completed_at": _iso_timestamp(action["completed_at"]),
                    }
                raise ReplayError("A different result was already submitted")
            if action["state"] != "claimed":
                raise ConflictError("Action is not awaiting a result")
            if action["completion_deadline"] <= now:
                connection.execute(
                    "UPDATE homelab_actions SET state = 'unknown', completed_at = ? WHERE action_id = ?",
                    (now, action_id),
                )
                raise ExpiredError("Action claim has expired")
            if completed_at + CAPTURE_FUTURE_SKEW_SECONDS < action["claimed_at"]:
                raise ValidationError("completed_at precedes the action claim")
            connection.execute(
                """UPDATE homelab_actions
                   SET state = ?, completed_at = ?, result_hash = ?, result_status = ?,
                       result_code = ?, result_payload_encrypted = ?, purge_after = ?
                   WHERE action_id = ? AND state = 'claimed'""",
                (
                    result["status"], completed_at, result_hash, result["status"], result["code"],
                    self._encrypt_payload(canonical),
                    now + (3600 if action["operation"] == "read_logs" else 7 * 24 * 3600),
                    action_id,
                ),
            )
        return {
            "accepted": True, "idempotent": False, "action_id": action_id,
            "state": result["status"], "completed_at": _iso_timestamp(completed_at),
        }

    def _public_action(self, row, *, include_result=False):
        result = {
            "id": row["action_id"],
            "agent_id": row["agent_id"],
            "operation": row["operation"],
            "state": row["state"],
            "requested_at": _iso_timestamp(row["requested_at"]),
            "expires_at": _iso_timestamp(row["expires_at"]),
            "claimed_at": _iso_timestamp(row["claimed_at"]),
            "completed_at": _iso_timestamp(row["completed_at"]),
            "result_status": row["result_status"],
            "result_code": row["result_code"],
        }
        payload = self._decrypt_payload(row["payload_encrypted"])
        result["resource_key"] = payload["resource_key"]
        if include_result:
            result["result"] = (
                self._decrypt_payload(row["result_payload_encrypted"])
                if row["result_payload_encrypted"] else None
            )
        return result

    def list_actions(self, owner_key, agent_id, *, limit=50):
        try:
            limit = min(100, max(1, int(limit)))
        except (TypeError, ValueError) as exc:
            raise ValidationError("limit must be an integer") from exc
        now = self._now()
        with self._connect(immediate=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM homelab_agents WHERE owner_key = ? AND agent_id = ? AND revoked_at IS NULL",
                (owner_key, agent_id),
            ).fetchone()
            if not exists:
                raise NotFoundError("Homelab agent not found")
            self._expire_actions(connection, now)
            self._purge_actions(connection, now)
            rows = connection.execute(
                """SELECT * FROM homelab_actions WHERE owner_key = ? AND agent_id = ?
                   ORDER BY requested_at DESC LIMIT ?""",
                (owner_key, agent_id, limit),
            ).fetchall()
        return {"actions": [self._public_action(row) for row in rows]}

    def get_action(self, owner_key, agent_id, action_id):
        now = self._now()
        with self._connect(immediate=True) as connection:
            self._expire_actions(connection, now)
            self._purge_actions(connection, now)
            row = connection.execute(
                """SELECT a.* FROM homelab_actions a
                   JOIN homelab_agents h ON h.agent_id = a.agent_id
                   WHERE a.owner_key = ? AND a.agent_id = ? AND a.action_id = ?
                         AND h.owner_key = ? AND h.revoked_at IS NULL""",
                (owner_key, agent_id, action_id, owner_key),
            ).fetchone()
            if row is None:
                raise NotFoundError("Action not found")
        return self._public_action(row, include_result=True)
