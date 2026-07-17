"""Fail-closed execution of locally declared launcher tasks."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from . import SCHEMA_VERSION
from .catalog import task_map, utc_now
from .client import ClaimedRun
from .config import ConfigError, LauncherPolicy, LocalTask


MAX_OUTPUT_BYTES = 64 * 1024
_ANSI = re.compile(r"\x1b(?:[@-_]|\[[0-?]*[ -/]*[@-~])")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:password|passwd|token|api[_-]?key|secret)\s*[:=]\s*)[^\s,;]+"),
)
_ENV_ALLOWLIST = {
    "APPDATA",
    "COMSPEC",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
}


def _result(
    claim: ClaimedRun,
    status: str,
    code: str,
    summary: str,
    *,
    output: str = "",
    truncated: bool = False,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "claim_token": claim.claim_token,
        "completed_at": utc_now(),
        "status": status,
        "code": code,
        "summary": summary[:240],
        "output": output,
        "truncated": bool(truncated),
    }


def uncertain_result(claim: ClaimedRun) -> dict:
    """Journal this before execution so a crash can never repeat a task."""
    return _result(
        claim,
        "failed",
        "execution_failed",
        "The task outcome is unknown after an agent interruption.",
    )


def _scrub_output(value: bytes) -> str:
    decoded = value.decode("utf-8", errors="replace")
    decoded = _ANSI.sub("", decoded.replace("\x00", ""))
    decoded = "".join(
        character
        for character in decoded
        if character in "\n\r\t" or 32 <= ord(character) < 127 or ord(character) >= 160
    )
    for pattern in _SECRET_PATTERNS:
        decoded = pattern.sub(r"\1<redacted>", decoded)
    encoded = decoded.encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        encoded = encoded[:MAX_OUTPUT_BYTES]
        while encoded and encoded[-1] & 0xC0 == 0x80:
            encoded = encoded[:-1]
        decoded = encoded.decode("utf-8", errors="ignore")
    return decoded


def _safe_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    source = source if source is not None else os.environ
    return {
        key: value
        for key, value in source.items()
        if key.upper() in _ENV_ALLOWLIST and isinstance(value, str) and "\x00" not in value
    }


def _validated_task(task: LocalTask) -> tuple[str, str | None]:
    executable = Path(task.executable)
    if not executable.is_absolute() or executable.is_symlink():
        raise FileNotFoundError
    resolved_executable = executable.resolve(strict=True)
    if not resolved_executable.is_file():
        raise FileNotFoundError
    cwd = None
    if task.cwd is not None:
        directory = Path(task.cwd)
        if not directory.is_absolute() or directory.is_symlink():
            raise FileNotFoundError
        resolved_directory = directory.resolve(strict=True)
        if not resolved_directory.is_dir():
            raise FileNotFoundError
        cwd = os.fspath(resolved_directory)
    return os.fspath(resolved_executable), cwd


class TaskExecutor:
    def __init__(
        self,
        config_loader: Callable[[], LauncherPolicy],
        task_key_secret: str,
        *,
        popen: Callable = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.config_loader = config_loader
        self.task_key_secret = task_key_secret
        self.popen = popen
        self.monotonic = monotonic

    @staticmethod
    def _stop(process) -> None:
        try:
            process.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def execute(self, claim: ClaimedRun) -> dict:
        try:
            policy = self.config_loader()
        except (ConfigError, OSError, ValueError):
            return _result(claim, "rejected", "policy_denied", "Local launcher policy is unavailable.")
        if not policy.enabled:
            return _result(claim, "rejected", "policy_denied", "Local launcher execution is disabled.")
        task = task_map(policy, self.task_key_secret).get(claim.task_key)
        if task is None:
            return _result(claim, "rejected", "task_missing", "The approved local task no longer exists.")
        try:
            executable, cwd = _validated_task(task)
        except (OSError, RuntimeError):
            return _result(claim, "rejected", "task_missing", "The approved local task is unavailable.")

        argv = [executable, *task.arguments]
        creationflags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                subprocess, "CREATE_NO_WINDOW", 0
            )
        try:
            process = self.popen(
                argv,
                cwd=cwd,
                env=_safe_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                close_fds=True,
                bufsize=0,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except (OSError, ValueError):
            return _result(claim, "failed", "execution_failed", "The approved task could not be started.")

        output = bytearray()
        overflow = threading.Event()

        def collect_output() -> None:
            stream = process.stdout
            if stream is None:
                return
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    remaining = MAX_OUTPUT_BYTES - len(output)
                    if remaining > 0:
                        output.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
                        break
            except OSError:
                pass

        reader = threading.Thread(target=collect_output, name="launcher-output", daemon=True)
        reader.start()
        deadline = self.monotonic() + task.timeout_seconds
        timed_out = False
        while process.poll() is None:
            if overflow.is_set():
                self._stop(process)
                break
            if self.monotonic() >= deadline:
                timed_out = True
                self._stop(process)
                break
            time.sleep(0.02)
        reader.join(timeout=2)
        if reader.is_alive():
            self._stop(process)
            overflow.set()
        sanitized = _scrub_output(bytes(output))
        if overflow.is_set():
            return _result(
                claim,
                "failed",
                "output_limit",
                "The task exceeded the 64 KiB output limit and was stopped.",
                output=sanitized,
                truncated=True,
            )
        if timed_out:
            return _result(
                claim,
                "failed",
                "timed_out",
                "The task exceeded its local timeout and was stopped.",
                output=sanitized,
                truncated=False,
            )
        return_code = process.poll()
        if return_code == 0:
            return _result(claim, "succeeded", "ok", "The approved task completed.", output=sanitized)
        return _result(
            claim,
            "failed",
            "exit_nonzero",
            "The approved task returned a non-zero exit code.",
            output=sanitized,
        )


__all__ = ["MAX_OUTPUT_BYTES", "TaskExecutor", "uncertain_result"]
