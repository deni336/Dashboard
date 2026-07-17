"""Fail-closed execution of the two locally authorized Docker operations."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from . import ACTION_SCHEMA_VERSION
from .client import ClaimedAction
from .collector import DockerCommandError, DockerInventoryCollector
from .config import HomelabConfig


_STATES = {"created", "running", "paused", "restarting", "removing", "exited", "dead", "unknown"}
_ANSI = re.compile(r"\x1b(?:[@-_]|\[[0-?]*[ -/]*[@-~])")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:password|passwd|token|api[_-]?key|secret)\s*[:=]\s*)[^\s,;]+"),
)
MAX_LOG_BYTES = 64 * 1024
MAX_LOG_LINES = 200


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def uncertain_result(claim: ClaimedAction) -> dict[str, Any]:
    """Journaled before execution; sent after a crash instead of repeating work."""

    return {
        "schema_version": ACTION_SCHEMA_VERSION,
        "claim_token": claim.claim_token,
        "completed_at": utc_now(),
        "status": "failed",
        "code": "command_failed",
        "observed_state": None,
        "log_excerpt": None,
        "truncated": False,
    }


def _result(
    claim: ClaimedAction,
    status: str,
    code: str,
    *,
    observed_state: str | None = None,
    log_excerpt: str | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    if observed_state not in _STATES:
        observed_state = None
    return {
        "schema_version": ACTION_SCHEMA_VERSION,
        "claim_token": claim.claim_token,
        "completed_at": utc_now(),
        "status": status,
        "code": code,
        "observed_state": observed_state,
        "log_excerpt": log_excerpt,
        "truncated": bool(truncated),
    }


def _redact_logs(value: str) -> tuple[str, bool]:
    sanitized = _ANSI.sub("", value.replace("\x00", ""))
    sanitized = "".join(
        character
        for character in sanitized
        if character in "\n\t" or ord(character) >= 32 and ord(character) != 127
    )
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub(r"\1<redacted>", sanitized)
    lines = sanitized.splitlines()
    truncated = len(lines) > MAX_LOG_LINES
    result = "\n".join(lines[-MAX_LOG_LINES:])
    encoded = result.encode("utf-8")
    if len(encoded) > MAX_LOG_BYTES:
        truncated = True
        encoded = encoded[-MAX_LOG_BYTES:]
        while encoded and encoded[0] & 0xC0 == 0x80:
            encoded = encoded[1:]
        result = encoded.decode("utf-8", errors="ignore")
    return result, truncated


class ActionExecutor:
    def __init__(
        self,
        docker: DockerInventoryCollector,
        config_loader: Callable[[], HomelabConfig],
    ):
        self.docker = docker
        self.config_loader = config_loader

    def execute(self, claim: ClaimedAction) -> dict[str, Any]:
        if claim.operation not in {"read_logs", "restart"}:
            return _result(claim, "rejected", "policy_denied")
        try:
            expires = datetime.fromisoformat(
                claim.expires_at[:-1] + "+00:00"
                if claim.expires_at.endswith("Z")
                else claim.expires_at
            )
        except ValueError:
            return _result(claim, "rejected", "invalid_state")
        if expires.tzinfo is None or expires.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            return _result(claim, "rejected", "invalid_state")
        try:
            config = self.config_loader()
        except RuntimeError:
            return _result(claim, "rejected", "policy_denied")

        required_global_grant = (
            config.allow_logs if claim.operation == "read_logs" else config.allow_restart
        )
        if not config.inventory_enabled or not required_global_grant:
            return _result(claim, "rejected", "policy_denied")

        # Rebuild the opaque-key map entirely from local inventory, then inspect
        # the matched local ID immediately before the fixed operation argv.
        engine, _storage, _containers, _truncated = self.docker.collect(config)
        if not engine.get("available"):
            code = "timed_out" if engine.get("error_code") == "timed_out" else "docker_unavailable"
            return _result(claim, "failed", code)
        fresh = self.docker.revalidate(claim.resource_key)
        if fresh is None:
            return _result(claim, "rejected", "resource_missing")
        state = str(fresh.get("state") or "unknown").lower()
        if state not in _STATES:
            state = "unknown"
        try:
            current_config = self.config_loader()
        except RuntimeError:
            return _result(claim, "rejected", "policy_denied", observed_state=state)
        current_global_grant = (
            current_config.allow_logs
            if claim.operation == "read_logs"
            else current_config.allow_restart
        )
        if not current_config.inventory_enabled or not current_global_grant:
            return _result(claim, "rejected", "policy_denied", observed_state=state)
        if str(fresh.get("monitor") or "").lower() != "true":
            return _result(claim, "rejected", "policy_denied", observed_state=state)
        local_id = self.docker.local_resources.get(claim.resource_key)
        if local_id is None:
            return _result(claim, "rejected", "resource_missing", observed_state=state)

        if claim.operation == "read_logs":
            if str(fresh.get("logs") or "").lower() != "true":
                return _result(claim, "rejected", "policy_denied", observed_state=state)
            try:
                output = self.docker._run(  # fixed local-only argv; never claim-derived
                    ["container", "logs", "--tail", "200", "--timestamps", local_id],
                    timeout=8,
                    limit=MAX_LOG_BYTES,
                    include_stderr=True,
                )
            except DockerCommandError as exc:
                code = "timed_out" if exc.code == "timed_out" else "docker_unavailable"
                return _result(claim, "failed", code, observed_state=state)
            if output.timed_out:
                return _result(claim, "failed", "timed_out", observed_state=state)
            excerpt, text_truncated = _redact_logs(output.stdout)
            if output.returncode != 0 and not output.truncated:
                return _result(claim, "failed", "command_failed", observed_state=state)
            return _result(
                claim,
                "succeeded",
                "ok",
                observed_state=state,
                log_excerpt=excerpt,
                truncated=output.truncated or text_truncated,
            )

        if str(fresh.get("actions") or "").lower() != "restart":
            return _result(claim, "rejected", "policy_denied", observed_state=state)
        if state != "running":
            return _result(claim, "rejected", "invalid_state", observed_state=state)
        try:
            output = self.docker._run(  # fixed local-only argv; never claim-derived
                ["container", "restart", "--timeout", "10", local_id],
                timeout=20,
                limit=16 * 1024,
            )
        except DockerCommandError as exc:
            code = "timed_out" if exc.code == "timed_out" else "docker_unavailable"
            return _result(claim, "failed", code, observed_state=state)
        if output.timed_out:
            return _result(claim, "failed", "timed_out", observed_state=state)
        if output.returncode != 0 or output.truncated:
            return _result(claim, "failed", "command_failed", observed_state=state)
        observed = self.docker.revalidate(claim.resource_key)
        observed_state = str((observed or {}).get("state") or "unknown").lower()
        if observed_state not in _STATES:
            observed_state = "unknown"
        return _result(claim, "succeeded", "ok", observed_state=observed_state)


__all__ = ["ActionExecutor", "MAX_LOG_BYTES", "MAX_LOG_LINES", "uncertain_result"]
