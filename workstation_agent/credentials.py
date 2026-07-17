"""Current-user DPAPI credential storage for the Windows agent."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import tempfile
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .client import normalize_server_url


MAX_CREDENTIAL_FILE_BYTES = 64 * 1024
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


class CredentialError(RuntimeError):
    pass


class Protector(Protocol):
    name: str

    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDPAPIProtector:
    """DPAPI protection scoped to the interactive Windows user."""

    name = "windows-dpapi-current-user"
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialError("Windows DPAPI is required for credential storage")
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
    def _input_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(value, len(value))
        blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def protect(self, plaintext: bytes) -> bytes:
        input_blob, input_buffer = self._input_blob(plaintext)
        output_blob = _DataBlob()
        description = "Kasugai workstation agent credentials"
        success = self._crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            description,
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        del input_buffer
        if not success:
            raise CredentialError("Windows could not protect the agent credentials")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(output_blob.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        input_blob, input_buffer = self._input_blob(ciphertext)
        output_blob = _DataBlob()
        success = self._crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        del input_buffer
        if not success:
            raise CredentialError("Windows could not decrypt the agent credentials for this user")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(output_blob.pbData)


@dataclass(frozen=True)
class AgentCredentials:
    server_url: str
    agent_id: str
    token: str
    interval_seconds: int
    sequence: int = 0

    def __repr__(self) -> str:
        return (
            "AgentCredentials("
            f"server_url={self.server_url!r}, agent_id={self.agent_id!r}, "
            "token=<redacted>, "
            f"interval_seconds={self.interval_seconds!r}, sequence={self.sequence!r})"
        )


def default_credential_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise CredentialError("LOCALAPPDATA is not available for current-user credential storage")
    return Path(local_app_data) / "Kasugai" / "workstation-agent" / "data" / "credentials.json"


class CredentialStore:
    def __init__(self, path: Path | str | None = None, protector: Protector | None = None):
        self.path = Path(path) if path is not None else default_credential_path()
        self.protector = protector or WindowsDPAPIProtector()
        self._lock = threading.Lock()

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, credentials: AgentCredentials) -> None:
        self._validate(credentials)
        payload = json.dumps(
            {
                "version": 1,
                "server_url": normalize_server_url(credentials.server_url),
                "agent_id": credentials.agent_id,
                "token": credentials.token,
                "interval_seconds": credentials.interval_seconds,
                "sequence": credentials.sequence,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        protected = self.protector.protect(payload)
        envelope = json.dumps(
            {
                "version": 1,
                "protection": self.protector.name,
                "ciphertext": base64.b64encode(protected).decode("ascii"),
            },
            separators=(",", ":"),
        ).encode("ascii")
        if len(envelope) > MAX_CREDENTIAL_FILE_BYTES:
            raise CredentialError("protected credential record is unexpectedly large")

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
            raise CredentialError("agent credentials could not be saved") from exc

    def load(self) -> AgentCredentials:
        try:
            size = self.path.stat().st_size
            if size <= 0 or size > MAX_CREDENTIAL_FILE_BYTES:
                raise CredentialError("agent credential record has an invalid size")
            with self.path.open("rb") as credential_file:
                raw_envelope = credential_file.read(MAX_CREDENTIAL_FILE_BYTES + 1)
            if len(raw_envelope) > MAX_CREDENTIAL_FILE_BYTES:
                raise CredentialError("agent credential record has an invalid size")
            envelope = json.loads(raw_envelope.decode("ascii"))
            if (
                not isinstance(envelope, dict)
                or envelope.get("version") != 1
                or envelope.get("protection") != self.protector.name
            ):
                raise CredentialError("agent credential record has an unsupported format")
            ciphertext = base64.b64decode(envelope.get("ciphertext", ""), validate=True)
            payload = json.loads(self.protector.unprotect(ciphertext).decode("utf-8"))
            credentials = AgentCredentials(
                server_url=payload["server_url"],
                agent_id=payload["agent_id"],
                token=payload["token"],
                interval_seconds=payload["interval_seconds"],
                sequence=payload["sequence"],
            )
            self._validate(credentials)
            return credentials
        except CredentialError:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialError("agent credential record is corrupt or unavailable") from exc

    def reserve_sequence(self) -> tuple[AgentCredentials, int]:
        """Atomically persist and return the next sequence number.

        Reserving before collection/push means retries and crashes may create gaps,
        but a sequence number is never reused after a restart.
        """

        with self._lock:
            current = self.load()
            if current.sequence >= 2**63 - 1:
                raise CredentialError("agent sequence is exhausted")
            next_sequence = current.sequence + 1
            updated = AgentCredentials(
                server_url=current.server_url,
                agent_id=current.agent_id,
                token=current.token,
                interval_seconds=current.interval_seconds,
                sequence=next_sequence,
            )
            self.save(updated)
            return updated, next_sequence

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialError("agent credentials could not be removed") from exc

    @staticmethod
    def _validate(credentials: AgentCredentials) -> None:
        if not isinstance(credentials, AgentCredentials):
            raise CredentialError("agent credentials are invalid")
        normalize_server_url(credentials.server_url)
        if not isinstance(credentials.agent_id, str) or not _IDENTIFIER_PATTERN.fullmatch(
            credentials.agent_id
        ):
            raise CredentialError("agent ID is invalid")
        if not isinstance(credentials.token, str) or not _TOKEN_PATTERN.fullmatch(credentials.token):
            raise CredentialError("agent token is invalid")
        if (
            not isinstance(credentials.interval_seconds, int)
            or isinstance(credentials.interval_seconds, bool)
            or not 5 <= credentials.interval_seconds <= 3600
        ):
            raise CredentialError("agent interval is invalid")
        if (
            not isinstance(credentials.sequence, int)
            or isinstance(credentials.sequence, bool)
            or not 0 <= credentials.sequence < 2**63
        ):
            raise CredentialError("agent sequence is invalid")
