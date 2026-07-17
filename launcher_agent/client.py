"""Bounded HTTPS client for the outbound launcher-agent protocol."""

from __future__ import annotations

import ipaddress
import json
import math
import random
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from . import AGENT_VERSION, SCHEMA_VERSION


MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
PAIR_PATH = "/api/launcher-agent/v1/pair"
_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_TASK_KEY = re.compile(r"^tsk_[A-Za-z0-9_-]{16,64}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_TRANSIENT = {408, 425, 429, 500, 502, 503, 504}


class AgentClientError(RuntimeError):
    """An agent error deliberately safe to log."""


class AgentSecurityError(AgentClientError):
    pass


class AgentProtocolError(AgentClientError):
    pass


class AgentHTTPError(AgentClientError):
    def __init__(self, status: int):
        super().__init__(f"dashboard returned HTTP {status}")
        self.status = status


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise AgentSecurityError("dashboard redirects are not allowed")


def normalize_server_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise AgentSecurityError("dashboard URL is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise AgentSecurityError("dashboard URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value.strip())
    except ValueError as exc:
        raise AgentSecurityError("dashboard URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AgentSecurityError("dashboard URL must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AgentSecurityError("dashboard URL must not include credentials, a query, or a fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise AgentSecurityError("dashboard URL has an invalid port") from exc
    if parsed.scheme == "http":
        host = parsed.hostname.rstrip(".").lower()
        loopback = host == "localhost"
        if not loopback:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
        if not loopback:
            raise AgentSecurityError("unencrypted HTTP is only allowed for a loopback dashboard")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class PairingResult:
    agent_id: str
    token: str = field(repr=False)
    catalog_interval_seconds: int
    poll_interval_seconds: int


@dataclass(frozen=True)
class ClaimedRun:
    run_id: str
    claim_token: str = field(repr=False)
    task_key: str
    expires_at: str


class LauncherClient:
    def __init__(
        self,
        server_url: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.server_url = normalize_server_url(server_url)
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AgentProtocolError("request timeout is invalid") from exc
        if not math.isfinite(timeout_value):
            raise AgentProtocolError("request timeout is invalid")
        self.timeout = min(max(timeout_value, 1.0), 30.0)
        self.max_retries = min(max(int(max_retries), 0), 5)
        if opener is not None:
            self.opener = opener
        elif self.server_url.startswith("http://"):
            self.opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirectHandler()
            )
        else:
            self.opener = urllib.request.build_opener(_NoRedirectHandler())
        self.sleeper = sleeper

    def pair(
        self,
        *,
        pairing_id: str,
        code: str,
        display_name: str,
        platform: str,
        capabilities: list[str],
    ) -> PairingResult:
        if not isinstance(pairing_id, str) or not _ID.fullmatch(pairing_id):
            raise AgentProtocolError("pairing ID is invalid")
        if not isinstance(code, str) or not 20 <= len(code) <= 128:
            raise AgentProtocolError("pairing code is invalid")
        display_name = str(display_name or "").strip()
        platform = str(platform or "").strip()
        if not display_name or len(display_name) > 80 or any(ord(c) < 32 for c in display_name):
            raise AgentProtocolError("display name is invalid")
        if not platform or len(platform) > 160 or any(ord(c) < 32 for c in platform):
            raise AgentProtocolError("platform description is invalid")
        if (
            not isinstance(capabilities, list)
            or len(capabilities) > 16
            or any(not isinstance(item, str) or not _CAPABILITY.fullmatch(item) for item in capabilities)
        ):
            raise AgentProtocolError("capabilities are invalid")
        response = self._request_json(
            "POST",
            PAIR_PATH,
            {
                "pairing_id": pairing_id,
                "code": code,
                "display_name": display_name,
                "agent_version": AGENT_VERSION,
                "platform": platform,
                "capabilities": capabilities,
            },
            token=None,
            retry_transient=False,
        )
        expected = {"agent_id", "token", "catalog_interval_seconds", "poll_interval_seconds"}
        if not isinstance(response, dict) or set(response) != expected:
            raise AgentProtocolError("pairing response has an unsupported schema")
        agent_id, token = response["agent_id"], response["token"]
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise AgentProtocolError("pairing response has an invalid agent ID")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise AgentProtocolError("pairing response has an invalid token")
        intervals = (response["catalog_interval_seconds"], response["poll_interval_seconds"])
        if any(
            not isinstance(value, int) or isinstance(value, bool) or not 2 <= value <= 3600
            for value in intervals
        ):
            raise AgentProtocolError("pairing response has an invalid interval")
        return PairingResult(agent_id, token, intervals[0], intervals[1])

    def push_catalog(self, agent_id: str, token: str, catalog: dict[str, Any]) -> dict[str, Any]:
        path = self._agent_path(agent_id, "/catalog")
        result = self._request_json(
            "POST", path, catalog, token=token, retry_transient=False
        )
        return result or {}

    def claim_run(self, agent_id: str, token: str) -> ClaimedRun | None:
        path = self._agent_path(agent_id, "/runs/claim")
        response = self._request_json(
            "POST",
            path,
            {"schema_version": SCHEMA_VERSION},
            token=token,
            retry_transient=False,
        )
        if response is None:
            return None
        if set(response) != {"schema_version", "run_id", "claim_token", "task_key", "expires_at"}:
            raise AgentProtocolError("run claim has an unsupported schema")
        if response.get("schema_version") != SCHEMA_VERSION:
            raise AgentProtocolError("run claim has an unsupported schema")
        run_id = response.get("run_id")
        claim_token = response.get("claim_token")
        task_key = response.get("task_key")
        expires_at = response.get("expires_at")
        if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
            raise AgentProtocolError("run claim has an invalid run ID")
        if not isinstance(claim_token, str) or not _TOKEN.fullmatch(claim_token):
            raise AgentProtocolError("run claim has an invalid claim token")
        if not isinstance(task_key, str) or not _TASK_KEY.fullmatch(task_key):
            raise AgentProtocolError("run claim has an invalid task key")
        if not isinstance(expires_at, str) or not 20 <= len(expires_at) <= 40:
            raise AgentProtocolError("run claim has an invalid expiry")
        return ClaimedRun(run_id, claim_token, task_key, expires_at)

    def push_result(
        self, agent_id: str, token: str, run_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
            raise AgentProtocolError("run ID is invalid")
        path = self._agent_path(
            agent_id, f"/runs/{urllib.parse.quote(run_id, safe='')}/result"
        )
        response = self._request_json("POST", path, payload, token=token, retry_transient=True)
        return response or {}

    @staticmethod
    def _validate_token(token: str) -> None:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise AgentProtocolError("agent token is invalid")

    def _agent_path(self, agent_id: str, suffix: str) -> str:
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise AgentProtocolError("agent ID is invalid")
        return f"/api/launcher-agent/v1/agents/{urllib.parse.quote(agent_id, safe='')}{suffix}"

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None,
        retry_transient: bool,
    ) -> dict[str, Any] | None:
        if token is not None:
            self._validate_token(token)
        if not isinstance(payload, dict):
            raise AgentProtocolError("request body must be an object")
        try:
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AgentProtocolError("request contains invalid JSON") from exc
        if len(body) > MAX_REQUEST_BYTES:
            raise AgentProtocolError("request exceeds the 256 KiB limit")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"Kasugai-Launcher-Agent/{AGENT_VERSION}",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"{self.server_url}{path}", data=body, headers=headers, method=method
        )
        attempts = self.max_retries + 1 if retry_transient else 1
        for attempt in range(attempts):
            try:
                response = self.opener.open(request, timeout=self.timeout)
                try:
                    status_value = getattr(response, "status", None)
                    status = int(status_value if status_value is not None else response.getcode())
                    if 300 <= status < 400:
                        raise AgentSecurityError("dashboard redirects are not allowed")
                    if not 200 <= status < 300:
                        raise AgentHTTPError(status)
                    if status == 204:
                        return None
                    length = response.headers.get("Content-Length") if response.headers else None
                    if length is not None:
                        try:
                            if int(length) > MAX_RESPONSE_BYTES:
                                raise AgentProtocolError("dashboard response exceeds the 64 KiB limit")
                        except ValueError as exc:
                            raise AgentProtocolError("dashboard sent an invalid Content-Length") from exc
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise AgentProtocolError("dashboard response exceeds the 64 KiB limit")
                finally:
                    response.close()
                if not raw:
                    return {}
                try:
                    decoded = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise AgentProtocolError("dashboard response is not valid JSON") from exc
                if not isinstance(decoded, dict):
                    raise AgentProtocolError("dashboard response must be an object")
                return decoded
            except AgentSecurityError:
                raise
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                exc.close()
                error: AgentClientError = AgentHTTPError(status)
                transient = status in _TRANSIENT
            except AgentHTTPError as exc:
                error = exc
                transient = exc.status in _TRANSIENT
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError):
                error = AgentClientError("dashboard connection failed")
                transient = True
            if not retry_transient or not transient or attempt + 1 >= attempts:
                raise error
            self.sleeper(min(0.5 * (2**attempt), 4.0) + random.uniform(0.0, 0.1))
        raise AgentClientError("dashboard request failed")


__all__ = [
    "AgentClientError",
    "AgentProtocolError",
    "AgentSecurityError",
    "ClaimedRun",
    "LauncherClient",
    "PairingResult",
    "normalize_server_url",
]
