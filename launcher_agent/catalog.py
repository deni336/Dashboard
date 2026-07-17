"""Build a public catalog without exposing local execution details."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

from . import SCHEMA_VERSION
from .config import LauncherPolicy, LocalTask


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def task_key(secret: str, local_id: str) -> str:
    digest = hmac.new(
        secret.encode("ascii"),
        b"Kasugai/launcher-task/v1\x00" + local_id.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return "tsk_" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")[:32]


def task_map(policy: LauncherPolicy, secret: str) -> dict[str, LocalTask]:
    return {task_key(secret, task.local_id): task for task in policy.tasks}


def build_catalog(policy: LauncherPolicy, secret: str, sequence: int) -> dict:
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ValueError("catalog sequence is invalid")
    tasks = []
    if policy.enabled:
        for key, task in task_map(policy, secret).items():
            tasks.append(
                {
                    "key": key,
                    "title": task.title,
                    "description": task.description,
                    "category": task.category,
                    "icon": task.icon,
                    "requires_confirmation": task.requires_confirmation,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "captured_at": utc_now(),
        "tasks": tasks,
    }


__all__ = ["build_catalog", "task_key", "task_map", "utc_now"]
