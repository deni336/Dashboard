"""Hardened HTTPS client for the outbound homelab-agent protocol."""

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
from datetime import datetime
from typing import Any, Callable

from . import ACTION_SCHEMA_VERSION, AGENT_VERSION


MAX_JSON_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
PAIR_PATH = "/api/homelab-agent/v1/pair"
_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_RESOURCE_KEY = re.compile(r"^ctr_[A-Za-z0-9_-]{20,64}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}
_OPERATIONS = {"read_logs", "restart"}


class AgentClientError(RuntimeError):
    """Base exception whose message contains no token, URL, or payload."""


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
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise AgentSecurityError("dashboard URL is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AgentSecurityError("dashboard URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value.strip())
    except ValueError as exc:
        raise AgentSecurityError("dashboard URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AgentSecurityError("dashboard URL must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AgentSecurityError("dashboard URL must not contain credentials, a query, or a fragment")
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
    snapshot_interval_seconds: int
    action_poll_interval_seconds: int


@dataclass(frozen=True)
class ClaimedAction:
    action_id: str
    claim_token: str = field(repr=False)
    operation: str
    resource_key: str
    expires_at: str


class HomelabClient:
    def __init__(
        self,
        server_url: str,
        *,
        timeout: float = 10,
        max_retries: int = 3,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.server_url = normalize_server_url(server_url)
        try:
            parsed_timeout = float(timeout)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AgentProtocolError("request timeout is invalid") from exc
        if not math.isfinite(parsed_timeout):
            raise AgentProtocolError("request timeout is invalid")
        self.timeout = min(max(parsed_timeout, 1), 30)
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
        if not display_name or len(display_name) > 80 or any(ord(char) < 32 for char in display_name):
            raise AgentProtocolError("display name is invalid")
        if not isinstance(platform, str) or not platform.strip() or len(platform) > 160:
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
        )
        if response is None:
            raise AgentProtocolError("pairing response is empty")
        agent_id = response.get("agent_id")
        token = response.get("token")
        snapshot_interval = response.get("interval_seconds")
        action_interval = response.get("action_poll_interval_seconds")
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise AgentProtocolError("pairing response has an invalid agent ID")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise AgentProtocolError("pairing response has an invalid token")
        for value, label in ((snapshot_interval, "snapshot"), (action_interval, "action poll")):
            if not isinstance(value, int) or isinstance(value, bool) or not 5 <= value <= 3600:
                raise AgentProtocolError(f"pairing response has an invalid {label} interval")
        return PairingResult(agent_id, token, snapshot_interval, action_interval)

    def push_snapshot(self, agent_id: str, token: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        path = self._agent_path(agent_id, "/snapshots")
        response = self._request_json("POST", path, snapshot, token=token)
        return response or {}

    def claim_action(self, agent_id: str, token: str) -> ClaimedAction | None:
        path = self._agent_path(agent_id, "/actions/claim")
        response = self._request_json(
            "POST", path, {"schema_version": ACTION_SCHEMA_VERSION}, token=token
        )
        if response is None:
            return None
        if set(response) != {
            "schema_version",
            "action_id",
            "claim_token",
            "operation",
            "resource_key",
            "expires_at",
        } or response.get("schema_version") != ACTION_SCHEMA_VERSION:
            raise AgentProtocolError("dashboard action claim has an unsupported schema")
        action_id = response.get("action_id")
        claim_token = response.get("claim_token")
        operation = response.get("operation")
        resource_key = response.get("resource_key")
        expires_at = response.get("expires_at")
        if not isinstance(action_id, str) or not _ID.fullmatch(action_id):
            raise AgentProtocolError("dashboard action ID is invalid")
        if not isinstance(claim_token, str) or not _TOKEN.fullmatch(claim_token):
            raise AgentProtocolError("dashboard action claim token is invalid")
        if operation not in _OPERATIONS:
            raise AgentProtocolError("dashboard action operation is not allowed")
        if not isinstance(resource_key, str) or not _RESOURCE_KEY.fullmatch(resource_key):
            raise AgentProtocolError("dashboard action resource key is invalid")
        if not isinstance(expires_at, str) or not 20 <= len(expires_at) <= 40:
            raise AgentProtocolError("dashboard action expiry is invalid")
        try:
            parsed_expiry = datetime.fromisoformat(
                expires_at[:-1] + "+00:00" if expires_at.endswith("Z") else expires_at
            )
        except ValueError as exc:
            raise AgentProtocolError("dashboard action expiry is invalid") from exc
        if parsed_expiry.tzinfo is None:
            raise AgentProtocolError("dashboard action expiry is invalid")
        return ClaimedAction(action_id, claim_token, operation, resource_key, expires_at)

    def push_action_result(
        self, agent_id: str, token: str, action_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(action_id, str) or not _ID.fullmatch(action_id):
            raise AgentProtocolError("action ID is invalid")
        path = self._agent_path(
            agent_id, f"/actions/{urllib.parse.quote(action_id, safe='')}/result"
        )
        response = self._request_json("POST", path, result, token=token)
        return response or {}

    @staticmethod
    def _validate_token(token: str) -> None:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise AgentProtocolError("agent token is invalid")

    def _agent_path(self, agent_id: str, suffix: str) -> str:
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise AgentProtocolError("agent ID is invalid")
        return (
            "/api/homelab-agent/v1/agents/"
            f"{urllib.parse.quote(agent_id, safe='')}{suffix}"
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None,
    ) -> dict[str, Any] | None:
        if token is not None:
            self._validate_token(token)
        if not isinstance(payload, dict):
            raise AgentProtocolError("request payload must be an object")
        try:
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AgentProtocolError("request contains invalid JSON values") from exc
        if len(body) > MAX_JSON_BYTES:
            raise AgentProtocolError("request exceeds the 256 KiB limit")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"Kasugai-Homelab-Agent/{AGENT_VERSION}",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"{self.server_url}{path}", data=body, headers=headers, method=method
        )

        for attempt in range(self.max_retries + 1):
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
                    raise AgentProtocolError("dashboard response must be a JSON object")
                return decoded
            except AgentSecurityError:
                raise
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                exc.close()
                error: AgentClientError = AgentHTTPError(status)
                transient = status in _TRANSIENT_STATUS
            except AgentHTTPError as exc:
                error = exc
                transient = exc.status in _TRANSIENT_STATUS
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError):
                error = AgentClientError("dashboard connection failed")
                transient = True
            if not transient or attempt >= self.max_retries:
                raise error
            self.sleeper(min(0.5 * (2**attempt), 4) + random.uniform(0, 0.1))
        raise AgentClientError("dashboard request failed")


__all__ = [
    "AgentClientError",
    "AgentProtocolError",
    "AgentSecurityError",
    "ClaimedAction",
    "HomelabClient",
    "MAX_JSON_BYTES",
    "PairingResult",
    "normalize_server_url",
]
