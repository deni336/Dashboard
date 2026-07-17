"""Strict local-only policy for the launcher agent.

The dashboard cannot create or edit this file.  Execution details are loaded
from disk immediately before every run and are never included in a catalog.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_CONFIG_BYTES = 256 * 1024
MAX_TASKS = 128
MAX_ARGUMENTS = 64
MAX_TIMEOUT_SECONDS = 300
_LOCAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_CATEGORY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_ICON = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


class ConfigError(RuntimeError):
    """A local configuration error safe to show without execution details."""


def _printable(value: Any, label: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be text")
    result = value.strip()
    if (not result and not allow_empty) or len(result) > maximum:
        raise ConfigError(f"{label} has an invalid length")
    if any(ord(character) < 32 or ord(character) == 127 for character in result):
        raise ConfigError(f"{label} contains control characters")
    return result


def _absolute_path(value: Any, label: str) -> str:
    result = _printable(value, label, maximum=2048)
    path = Path(result).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{label} must be an absolute path")
    # Do not resolve here: existence and link targets are revalidated directly
    # before execution, after a claim has arrived.
    return os.path.abspath(os.fspath(path))


@dataclass(frozen=True)
class LocalTask:
    local_id: str
    title: str
    description: str
    category: str
    icon: str
    requires_confirmation: bool
    executable: str
    arguments: tuple[str, ...]
    cwd: str | None
    timeout_seconds: int


@dataclass(frozen=True)
class LauncherPolicy:
    enabled: bool
    tasks: tuple[LocalTask, ...]


def default_config_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise ConfigError("LOCALAPPDATA is unavailable for launcher configuration")
    return Path(local_app_data) / "Kasugai" / "launcher-agent" / "policy.json"


def default_config_document() -> str:
    return json.dumps(
        {"schema_version": 1, "enabled": False, "tasks": []},
        indent=2,
    ) + "\n"


def initialize_config(path: Path | str | None = None, *, force: bool = False) -> Path:
    target = Path(path) if path is not None else default_config_path()
    if target.exists() and not force:
        raise ConfigError("launcher policy already exists; use --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="policy-",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            handle.write(default_config_document())
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, target)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ConfigError("launcher policy could not be written") from exc
    return target


def _strict_object(value: Any, label: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ConfigError(f"{label} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _parse_task(value: Any, index: int) -> LocalTask:
    item = _strict_object(
        value,
        f"tasks[{index}]",
        {
            "id",
            "title",
            "description",
            "category",
            "icon",
            "requires_confirmation",
            "executable",
            "args",
            "cwd",
            "timeout_seconds",
        },
    )
    local_id = _printable(item["id"], f"tasks[{index}].id", maximum=80)
    if not _LOCAL_ID.fullmatch(local_id):
        raise ConfigError(f"tasks[{index}].id is invalid")
    category = _printable(item["category"], f"tasks[{index}].category", maximum=32)
    icon = _printable(item["icon"], f"tasks[{index}].icon", maximum=40)
    if not _CATEGORY.fullmatch(category) or not _ICON.fullmatch(icon):
        raise ConfigError(f"tasks[{index}] has invalid presentation metadata")
    if not isinstance(item["requires_confirmation"], bool):
        raise ConfigError(f"tasks[{index}].requires_confirmation must be true or false")
    arguments = item["args"]
    if not isinstance(arguments, list) or len(arguments) > MAX_ARGUMENTS:
        raise ConfigError(f"tasks[{index}].args must be a bounded list")
    parsed_arguments = tuple(
        _printable(argument, f"tasks[{index}].args", maximum=2048, allow_empty=True)
        for argument in arguments
    )
    cwd = item["cwd"]
    if cwd is not None:
        cwd = _absolute_path(cwd, f"tasks[{index}].cwd")
    timeout = item["timeout_seconds"]
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or not 1 <= timeout <= MAX_TIMEOUT_SECONDS
    ):
        raise ConfigError(f"tasks[{index}].timeout_seconds must be between 1 and 300")
    return LocalTask(
        local_id=local_id,
        title=_printable(item["title"], f"tasks[{index}].title", maximum=120),
        description=_printable(
            item["description"], f"tasks[{index}].description", maximum=240, allow_empty=True
        ),
        category=category,
        icon=icon,
        requires_confirmation=item["requires_confirmation"],
        executable=_absolute_path(item["executable"], f"tasks[{index}].executable"),
        arguments=parsed_arguments,
        cwd=cwd,
        timeout_seconds=timeout,
    )


def parse_config(payload: Any) -> LauncherPolicy:
    root = _strict_object(payload, "launcher policy", {"schema_version", "enabled", "tasks"})
    if root["schema_version"] != 1 or isinstance(root["schema_version"], bool):
        raise ConfigError("launcher policy schema_version is unsupported")
    if not isinstance(root["enabled"], bool):
        raise ConfigError("launcher policy enabled must be true or false")
    if not isinstance(root["tasks"], list) or len(root["tasks"]) > MAX_TASKS:
        raise ConfigError("launcher policy has too many tasks")
    tasks = tuple(_parse_task(item, index) for index, item in enumerate(root["tasks"]))
    identifiers = [task.local_id for task in tasks]
    if len(identifiers) != len(set(identifiers)):
        raise ConfigError("launcher task IDs must be unique")
    return LauncherPolicy(enabled=root["enabled"], tasks=tasks)


def load_config(path: Path | str | None = None) -> LauncherPolicy:
    target = Path(path) if path is not None else default_config_path()
    try:
        size = target.stat().st_size
        if size <= 0 or size > MAX_CONFIG_BYTES:
            raise ConfigError("launcher policy has an invalid size")
        raw = target.read_bytes()
        if len(raw) > MAX_CONFIG_BYTES:
            raise ConfigError("launcher policy has an invalid size")
        return parse_config(json.loads(raw.decode("utf-8")))
    except ConfigError:
        raise
    except FileNotFoundError as exc:
        raise ConfigError("launcher policy does not exist; initialize it first") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError("launcher policy is invalid or unavailable") from exc


__all__ = [
    "ConfigError",
    "LauncherPolicy",
    "LocalTask",
    "default_config_document",
    "default_config_path",
    "initialize_config",
    "load_config",
    "parse_config",
]
