"""Independent current-user credentials and crash-safe result journal."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import tempfile
import threading
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from .client import normalize_server_url


MAX_CREDENTIAL_BYTES = 256 * 1024
MAX_RESULT_OUTPUT_BYTES = 64 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_SECRET = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_STATUS = {"succeeded", "failed", "rejected"}
_CODES = {
    "ok",
    "exit_nonzero",
    "policy_denied",
    "task_missing",
    "timed_out",
    "output_limit",
    "execution_failed",
}


class CredentialError(RuntimeError):
    """A credential failure safe to display without sensitive values."""


class Protector(Protocol):
    name: str

    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDPAPIProtector:
    name = "windows-dpapi-current-user"
    _UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialError("Windows DPAPI is required for launcher credentials")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    @staticmethod
    def _blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(value, len(value))
        return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer

    def protect(self, plaintext: bytes) -> bytes:
        source, source_buffer = self._blob(plaintext)
        output = _DataBlob()
        success = self._crypt32.CryptProtectData(
            ctypes.byref(source),
            "Kasugai launcher agent credentials and pending result",
            None,
            None,
            None,
            self._UI_FORBIDDEN,
            ctypes.byref(output),
        )
        del source_buffer
        if not success:
            raise CredentialError("Windows could not protect launcher credentials")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        source, source_buffer = self._blob(ciphertext)
        output = _DataBlob()
        success = self._crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, self._UI_FORBIDDEN, ctypes.byref(output)
        )
        del source_buffer
        if not success:
            raise CredentialError("Windows could not decrypt launcher credentials for this user")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)


@dataclass(frozen=True)
class AgentCredentials:
    server_url: str
    agent_id: str
    token: str
    catalog_interval_seconds: int
    poll_interval_seconds: int
    task_key_secret: str
    sequence: int = 0
    pending_result: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return (
            "AgentCredentials("
            f"server_url={self.server_url!r}, agent_id={self.agent_id!r}, token=<redacted>, "
            f"catalog_interval_seconds={self.catalog_interval_seconds!r}, "
            f"poll_interval_seconds={self.poll_interval_seconds!r}, task_key_secret=<redacted>, "
            f"sequence={self.sequence!r}, pending_result={'yes' if self.pending_result else 'no'})"
        )


def new_task_key_secret() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")


def default_credential_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise CredentialError("LOCALAPPDATA is unavailable for launcher credentials")
    return Path(local_app_data) / "Kasugai" / "launcher-agent" / "data" / "credentials.json"


def _valid_result(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"run_id", "payload"}:
        return False
    if not isinstance(value.get("run_id"), str) or not _ID.fullmatch(value["run_id"]):
        return False
    payload = value.get("payload")
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "claim_token",
        "completed_at",
        "status",
        "code",
        "summary",
        "output",
        "truncated",
    }:
        return False
    if payload.get("schema_version") != 1 or isinstance(payload.get("schema_version"), bool):
        return False
    if not isinstance(payload.get("claim_token"), str) or not _TOKEN.fullmatch(payload["claim_token"]):
        return False
    if payload.get("status") not in _STATUS or payload.get("code") not in _CODES:
        return False
    completed = payload.get("completed_at")
    summary = payload.get("summary")
    output = payload.get("output")
    if not isinstance(completed, str) or not 20 <= len(completed) <= 40:
        return False
    if not isinstance(summary, str) or len(summary) > 240:
        return False
    if output is not None and (
        not isinstance(output, str)
        or len(output.encode("utf-8")) > MAX_RESULT_OUTPUT_BYTES
    ):
        return False
    return isinstance(payload.get("truncated"), bool)


class CredentialStore:
    def __init__(self, path: Path | str | None = None, protector: Protector | None = None):
        self.path = Path(path) if path is not None else default_credential_path()
        self.protector = protector or WindowsDPAPIProtector()
        self._lock = threading.RLock()

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, credentials: AgentCredentials) -> None:
        self._validate(credentials)
        plaintext = json.dumps(
            {
                "version": 1,
                "server_url": normalize_server_url(credentials.server_url),
                "agent_id": credentials.agent_id,
                "token": credentials.token,
                "catalog_interval_seconds": credentials.catalog_interval_seconds,
                "poll_interval_seconds": credentials.poll_interval_seconds,
                "task_key_secret": credentials.task_key_secret,
                "sequence": credentials.sequence,
                "pending_result": credentials.pending_result,
            },
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        protected = self.protector.protect(plaintext)
        envelope = json.dumps(
            {
                "version": 1,
                "protection": self.protector.name,
                "ciphertext": base64.b64encode(protected).decode("ascii"),
            },
            separators=(",", ":"),
        ).encode("ascii")
        if len(envelope) > MAX_CREDENTIAL_BYTES:
            raise CredentialError("protected launcher credential record is unexpectedly large")
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="credentials-",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as handle:
                handle.write(envelope)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, self.path)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise CredentialError("launcher credentials could not be saved") from exc

    def load(self) -> AgentCredentials:
        try:
            size = self.path.stat().st_size
            if size <= 0 or size > MAX_CREDENTIAL_BYTES:
                raise CredentialError("launcher credential record has an invalid size")
            raw = self.path.read_bytes()
            if len(raw) > MAX_CREDENTIAL_BYTES:
                raise CredentialError("launcher credential record has an invalid size")
            envelope = json.loads(raw.decode("ascii"))
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"version", "protection", "ciphertext"}
                or envelope.get("version") != 1
                or envelope.get("protection") != self.protector.name
            ):
                raise CredentialError("launcher credential record has an unsupported format")
            ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
            payload = json.loads(self.protector.unprotect(ciphertext).decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                "version",
                "server_url",
                "agent_id",
                "token",
                "catalog_interval_seconds",
                "poll_interval_seconds",
                "task_key_secret",
                "sequence",
                "pending_result",
            } or payload.get("version") != 1:
                raise CredentialError("launcher credential record has an unsupported format")
            credentials = AgentCredentials(
                server_url=payload["server_url"],
                agent_id=payload["agent_id"],
                token=payload["token"],
                catalog_interval_seconds=payload["catalog_interval_seconds"],
                poll_interval_seconds=payload["poll_interval_seconds"],
                task_key_secret=payload["task_key_secret"],
                sequence=payload["sequence"],
                pending_result=payload["pending_result"],
            )
            self._validate(credentials)
            return credentials
        except CredentialError:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialError("launcher credential record is corrupt or unavailable") from exc

    def reserve_sequence(self) -> tuple[AgentCredentials, int]:
        with self._lock:
            current = self.load()
            if current.sequence >= 2**63 - 1:
                raise CredentialError("launcher catalog sequence is exhausted")
            updated = replace(current, sequence=current.sequence + 1)
            self.save(updated)
            return updated, updated.sequence

    def save_pending_result(self, run_id: str, payload: dict[str, Any]) -> AgentCredentials:
        with self._lock:
            current = self.load()
            pending = {"run_id": run_id, "payload": payload}
            if not _valid_result(pending):
                raise CredentialError("launcher result journal is invalid")
            if (
                current.pending_result is not None
                and current.pending_result.get("run_id") != run_id
            ):
                raise CredentialError("a different launcher result is already pending")
            updated = replace(current, pending_result=pending)
            self.save(updated)
            return updated

    def clear_pending_result(self, run_id: str) -> AgentCredentials:
        with self._lock:
            current = self.load()
            if current.pending_result is not None and current.pending_result.get("run_id") != run_id:
                raise CredentialError("launcher result journal does not match the completed run")
            updated = replace(current, pending_result=None)
            self.save(updated)
            return updated

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialError("launcher credentials could not be removed") from exc

    @staticmethod
    def _validate(credentials: AgentCredentials) -> None:
        if not isinstance(credentials, AgentCredentials):
            raise CredentialError("launcher credentials are invalid")
        normalize_server_url(credentials.server_url)
        if not isinstance(credentials.agent_id, str) or not _ID.fullmatch(credentials.agent_id):
            raise CredentialError("launcher agent ID is invalid")
        if not isinstance(credentials.token, str) or not _TOKEN.fullmatch(credentials.token):
            raise CredentialError("launcher agent token is invalid")
        for value, label in (
            (credentials.catalog_interval_seconds, "catalog interval"),
            (credentials.poll_interval_seconds, "poll interval"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 2 <= value <= 3600:
                raise CredentialError(f"launcher {label} is invalid")
        if not isinstance(credentials.task_key_secret, str) or not _SECRET.fullmatch(
            credentials.task_key_secret
        ):
            raise CredentialError("launcher task-key secret is invalid")
        if (
            not isinstance(credentials.sequence, int)
            or isinstance(credentials.sequence, bool)
            or not 0 <= credentials.sequence < 2**63
        ):
            raise CredentialError("launcher catalog sequence is invalid")
        if not _valid_result(credentials.pending_result):
            raise CredentialError("launcher result journal is invalid")


__all__ = [
    "AgentCredentials",
    "CredentialError",
    "CredentialStore",
    "WindowsDPAPIProtector",
    "default_credential_path",
    "new_task_key_secret",
]
