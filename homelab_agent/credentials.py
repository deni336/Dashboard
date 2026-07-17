"""Independent current-user DPAPI state for the Kasugai homelab agent."""

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


MAX_CREDENTIAL_FILE_BYTES = 256 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_SECRET = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_RESULT_STATUS = {"succeeded", "failed", "rejected"}


class CredentialError(RuntimeError):
    """A local state failure safe to display without secret material."""


class Protector(Protocol):
    name: str

    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDPAPIProtector:
    """DPAPI protection scoped to the Windows user running this agent."""

    name = "windows-dpapi-current-user"
    _UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialError("Windows DPAPI is required for homelab credential storage")
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
            "Kasugai homelab agent credentials and state",
            None,
            None,
            None,
            self._UI_FORBIDDEN,
            ctypes.byref(output),
        )
        del source_buffer
        if not success:
            raise CredentialError("Windows could not protect homelab agent credentials")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        source, source_buffer = self._blob(ciphertext)
        output = _DataBlob()
        success = self._crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            self._UI_FORBIDDEN,
            ctypes.byref(output),
        )
        del source_buffer
        if not success:
            raise CredentialError("Windows could not decrypt homelab credentials for this user")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)


@dataclass(frozen=True)
class AgentCredentials:
    server_url: str
    agent_id: str
    token: str
    snapshot_interval_seconds: int
    action_poll_interval_seconds: int
    resource_key_secret: str
    sequence: int = 0
    pending_result: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return (
            "AgentCredentials("
            f"server_url={self.server_url!r}, agent_id={self.agent_id!r}, token=<redacted>, "
            f"snapshot_interval_seconds={self.snapshot_interval_seconds!r}, "
            f"action_poll_interval_seconds={self.action_poll_interval_seconds!r}, "
            "resource_key_secret=<redacted>, "
            f"sequence={self.sequence!r}, pending_result={'yes' if self.pending_result else 'no'})"
        )


def default_credential_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise CredentialError("LOCALAPPDATA is not available for current-user credential storage")
    return Path(local_app_data) / "Kasugai" / "homelab-agent" / "data" / "credentials.json"


def new_resource_key_secret() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")


def _valid_pending_result(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"action_id", "payload"}:
        return False
    action_id = value.get("action_id")
    payload = value.get("payload")
    if not isinstance(action_id, str) or not _IDENTIFIER.fullmatch(action_id):
        return False
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "claim_token",
        "completed_at",
        "status",
        "code",
        "observed_state",
        "log_excerpt",
        "truncated",
    }:
        return False
    if payload.get("schema_version") != 1:
        return False
    if not isinstance(payload.get("claim_token"), str) or not _TOKEN.fullmatch(payload["claim_token"]):
        return False
    if payload.get("status") not in _RESULT_STATUS:
        return False
    for key, limit in (("completed_at", 40), ("code", 64)):
        field = payload.get(key)
        if not isinstance(field, str) or len(field) > limit:
            return False
    observed_state = payload.get("observed_state")
    if observed_state is not None and (
        not isinstance(observed_state, str) or len(observed_state) > 32
    ):
        return False
    log_excerpt = payload.get("log_excerpt")
    if log_excerpt is not None and (
        not isinstance(log_excerpt, str) or len(log_excerpt.encode("utf-8")) > 65536
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
        data = {
            "version": 1,
            "server_url": normalize_server_url(credentials.server_url),
            "agent_id": credentials.agent_id,
            "token": credentials.token,
            "snapshot_interval_seconds": credentials.snapshot_interval_seconds,
            "action_poll_interval_seconds": credentials.action_poll_interval_seconds,
            "resource_key_secret": credentials.resource_key_secret,
            "sequence": credentials.sequence,
            "pending_result": credentials.pending_result,
        }
        plaintext = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
        protected = self.protector.protect(plaintext)
        envelope = json.dumps(
            {
                "version": 1,
                "protection": self.protector.name,
                "ciphertext": base64.b64encode(protected).decode("ascii"),
            },
            separators=(",", ":"),
        ).encode("ascii")
        if len(envelope) > MAX_CREDENTIAL_FILE_BYTES:
            raise CredentialError("protected homelab credential record is unexpectedly large")

        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix="credentials-", suffix=".tmp", dir=self.path.parent, delete=False
            ) as temporary:
                temporary.write(envelope)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise CredentialError("homelab credentials could not be saved") from exc

    def load(self) -> AgentCredentials:
        try:
            size = self.path.stat().st_size
            if size <= 0 or size > MAX_CREDENTIAL_FILE_BYTES:
                raise CredentialError("homelab credential record has an invalid size")
            raw = self.path.read_bytes()
            if len(raw) > MAX_CREDENTIAL_FILE_BYTES:
                raise CredentialError("homelab credential record has an invalid size")
            envelope = json.loads(raw.decode("ascii"))
            if (
                not isinstance(envelope, dict)
                or envelope.get("version") != 1
                or envelope.get("protection") != self.protector.name
            ):
                raise CredentialError("homelab credential record has an unsupported format")
            encrypted = base64.b64decode(envelope.get("ciphertext", ""), validate=True)
            payload = json.loads(self.protector.unprotect(encrypted).decode("utf-8"))
            credentials = AgentCredentials(
                server_url=payload["server_url"],
                agent_id=payload["agent_id"],
                token=payload["token"],
                snapshot_interval_seconds=payload["snapshot_interval_seconds"],
                action_poll_interval_seconds=payload["action_poll_interval_seconds"],
                resource_key_secret=payload["resource_key_secret"],
                sequence=payload["sequence"],
                pending_result=payload.get("pending_result"),
            )
            self._validate(credentials)
            return credentials
        except CredentialError:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialError("homelab credential record is corrupt or unavailable") from exc

    def reserve_sequence(self) -> tuple[AgentCredentials, int]:
        """Persist a unique snapshot sequence before the snapshot is collected."""

        with self._lock:
            current = self.load()
            if current.sequence >= 2**63 - 1:
                raise CredentialError("homelab snapshot sequence is exhausted")
            updated = replace(current, sequence=current.sequence + 1)
            self.save(updated)
            return updated, updated.sequence

    def save_pending_result(self, action_id: str, payload: dict[str, Any]) -> AgentCredentials:
        """Persist an exact result before network delivery so retries are idempotent."""

        with self._lock:
            current = self.load()
            pending = {"action_id": action_id, "payload": payload}
            if not _valid_pending_result(pending):
                raise CredentialError("action result state is invalid")
            updated = replace(current, pending_result=pending)
            self.save(updated)
            return updated

    def clear_pending_result(self, action_id: str) -> AgentCredentials:
        with self._lock:
            current = self.load()
            pending = current.pending_result
            if pending is not None and pending.get("action_id") != action_id:
                raise CredentialError("pending action result changed unexpectedly")
            updated = replace(current, pending_result=None)
            self.save(updated)
            return updated

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialError("homelab credentials could not be removed") from exc

    @staticmethod
    def _validate(credentials: AgentCredentials) -> None:
        if not isinstance(credentials, AgentCredentials):
            raise CredentialError("homelab credentials are invalid")
        normalize_server_url(credentials.server_url)
        if not isinstance(credentials.agent_id, str) or not _IDENTIFIER.fullmatch(credentials.agent_id):
            raise CredentialError("homelab agent ID is invalid")
        if not isinstance(credentials.token, str) or not _TOKEN.fullmatch(credentials.token):
            raise CredentialError("homelab agent token is invalid")
        for value, name in (
            (credentials.snapshot_interval_seconds, "snapshot interval"),
            (credentials.action_poll_interval_seconds, "action poll interval"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 5 <= value <= 3600:
                raise CredentialError(f"homelab {name} is invalid")
        if not isinstance(credentials.resource_key_secret, str) or not _SECRET.fullmatch(
            credentials.resource_key_secret
        ):
            raise CredentialError("homelab resource key secret is invalid")
        if (
            not isinstance(credentials.sequence, int)
            or isinstance(credentials.sequence, bool)
            or not 0 <= credentials.sequence < 2**63
        ):
            raise CredentialError("homelab sequence is invalid")
        if not _valid_pending_result(credentials.pending_result):
            raise CredentialError("homelab pending action state is invalid")


__all__ = [
    "AgentCredentials",
    "CredentialError",
    "CredentialStore",
    "WindowsDPAPIProtector",
    "default_credential_path",
    "new_resource_key_secret",
]
