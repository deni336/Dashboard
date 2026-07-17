"""Strict, local-only policy for the homelab agent.

The dashboard cannot modify this file.  Inventory and every active operation
default to disabled, so pairing an agent never grants Docker access by itself.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_CONFIG_BYTES = 64 * 1024
MAX_HEALTH_CHECKS = 32


class ConfigError(RuntimeError):
    """A safe-to-display local policy error."""


@dataclass(frozen=True)
class HealthCheck:
    name: str
    url: str
    timeout_seconds: float
    expected_statuses: tuple[int, ...]


@dataclass(frozen=True)
class HomelabConfig:
    inventory_enabled: bool = False
    allow_logs: bool = False
    allow_restart: bool = False
    health_checks: tuple[HealthCheck, ...] = ()

    @property
    def capabilities(self) -> list[str]:
        # Capabilities describe compiled protocol support, not current grants.
        # Effective access remains the intersection of this local policy and a
        # freshly revalidated container label, reported in every snapshot.
        return ["inventory", "read_logs", "restart"]


def default_config_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise ConfigError("LOCALAPPDATA is not available for local homelab policy")
    return Path(local_app_data) / "Kasugai" / "homelab-agent" / "config.json"


def _plain_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError("health check names must be text")
    name = value.strip()
    if not name or len(name) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ConfigError("health check names must contain 1 to 80 printable characters")
    return name


def _health_url(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ConfigError("health check URL is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ConfigError("health check URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise ConfigError("health check URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError("health checks must use an explicit HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ConfigError("health check URLs cannot contain credentials, queries, or fragments")
    try:
        parsed.port
    except ValueError as exc:
        raise ConfigError("health check URL has an invalid port") from exc
    if len(parsed.path) > 512:
        raise ConfigError("health check URL path is too long")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _expected_statuses(value: Any) -> tuple[int, ...]:
    if value is None:
        return tuple(range(200, 400))
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 16
        or any(not isinstance(item, int) or isinstance(item, bool) or not 100 <= item <= 599 for item in value)
    ):
        raise ConfigError("health check expected_statuses must be 1 to 16 HTTP status codes")
    return tuple(sorted(set(value)))


def _parse_health_check(value: Any) -> HealthCheck:
    if not isinstance(value, dict) or set(value) - {
        "name",
        "url",
        "timeout_seconds",
        "expected_statuses",
    }:
        raise ConfigError("health check entries contain unsupported fields")
    timeout = value.get("timeout_seconds", 3)
    if isinstance(timeout, bool):
        raise ConfigError("health check timeout is invalid")
    try:
        parsed_timeout = float(timeout)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConfigError("health check timeout is invalid") from exc
    if not 0.5 <= parsed_timeout <= 10:
        raise ConfigError("health check timeout must be between 0.5 and 10 seconds")
    return HealthCheck(
        name=_plain_name(value.get("name")),
        url=_health_url(value.get("url")),
        timeout_seconds=parsed_timeout,
        expected_statuses=_expected_statuses(value.get("expected_statuses")),
    )


def load_config(path: Path | str | None = None) -> HomelabConfig:
    config_path = Path(path) if path is not None else default_config_path()
    try:
        size = config_path.stat().st_size
        if size <= 0 or size > MAX_CONFIG_BYTES:
            raise ConfigError("homelab policy has an invalid size")
        raw = config_path.read_bytes()
        if len(raw) > MAX_CONFIG_BYTES:
            raise ConfigError("homelab policy has an invalid size")
        payload = json.loads(raw.decode("utf-8"))
    except ConfigError:
        raise
    except FileNotFoundError:
        return HomelabConfig()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError("homelab policy is corrupt or unavailable") from exc

    if not isinstance(payload, dict) or set(payload) - {
        "version",
        "inventory_enabled",
        "grants",
        "health_checks",
    }:
        raise ConfigError("homelab policy contains unsupported fields")
    if payload.get("version") != 1:
        raise ConfigError("homelab policy version is unsupported")
    inventory_enabled = payload.get("inventory_enabled", False)
    grants = payload.get("grants", {})
    checks = payload.get("health_checks", [])
    if not isinstance(inventory_enabled, bool):
        raise ConfigError("inventory_enabled must be true or false")
    if not isinstance(grants, dict) or set(grants) - {"read_logs", "restart"}:
        raise ConfigError("homelab grants contain unsupported fields")
    if any(not isinstance(grants.get(name, False), bool) for name in ("read_logs", "restart")):
        raise ConfigError("homelab grants must be true or false")
    if not isinstance(checks, list) or len(checks) > MAX_HEALTH_CHECKS:
        raise ConfigError(f"no more than {MAX_HEALTH_CHECKS} health checks are allowed")
    parsed_checks = tuple(_parse_health_check(item) for item in checks)
    if len({item.name.casefold() for item in parsed_checks}) != len(parsed_checks):
        raise ConfigError("health check names must be unique")
    return HomelabConfig(
        inventory_enabled=inventory_enabled,
        allow_logs=grants.get("read_logs", False),
        allow_restart=grants.get("restart", False),
        health_checks=parsed_checks,
    )


def default_config_document() -> str:
    return json.dumps(
        {
            "version": 1,
            "inventory_enabled": False,
            "grants": {"read_logs": False, "restart": False},
            "health_checks": [],
        },
        indent=2,
    ) + "\n"


__all__ = [
    "ConfigError",
    "HealthCheck",
    "HomelabConfig",
    "default_config_document",
    "default_config_path",
    "load_config",
]
