"""Small, hardened HTTPS client for the workstation agent protocol."""

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

from . import AGENT_VERSION


MAX_JSON_BYTES = 64 * 1024
PAIR_PATH = "/api/workstation-agent/v1/pair"
_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


class AgentClientError(RuntimeError):
    """Base error that is safe to display without leaking credentials."""


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
        raise AgentSecurityError("dashboard URL must not contain credentials, a query, or a fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise AgentSecurityError("dashboard URL has an invalid port") from exc
    if parsed.scheme == "http":
        host = parsed.hostname.rstrip(".").lower()
        is_loopback = host == "localhost"
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise AgentSecurityError("unencrypted HTTP is only allowed for a loopback dashboard")
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


@dataclass(frozen=True)
class PairingResult:
    agent_id: str
    token: str = field(repr=False)
    interval_seconds: int


class WorkstationClient:
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
            parsed_timeout = float(timeout)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AgentProtocolError("request timeout is invalid") from exc
        if not math.isfinite(parsed_timeout):
            raise AgentProtocolError("request timeout is invalid")
        self.timeout = min(max(parsed_timeout, 1.0), 30.0)
        self.max_retries = min(max(int(max_retries), 0), 5)
        if opener is not None:
            self.opener = opener
        elif self.server_url.startswith("http://"):
            # Never send loopback HTTP through a proxy inherited from the user
            # environment. HTTPS retains normal proxy support and certificate
            # verification for managed networks.
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
        if not display_name or len(display_name) > 80:
            raise AgentProtocolError("display name is invalid")
        if not isinstance(platform, str) or not platform.strip() or len(platform) > 160:
            raise AgentProtocolError("platform description is invalid")
        if (
            not isinstance(capabilities, list)
            or len(capabilities) > 32
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
        agent_id = response.get("agent_id")
        token = response.get("token")
        interval = response.get("interval_seconds")
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise AgentProtocolError("pairing response has an invalid agent ID")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise AgentProtocolError("pairing response has an invalid token")
        if not isinstance(interval, int) or isinstance(interval, bool) or not 5 <= interval <= 3600:
            raise AgentProtocolError("pairing response has an invalid interval")
        return PairingResult(agent_id=agent_id, token=token, interval_seconds=interval)

    def push_snapshot(self, agent_id: str, token: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise AgentProtocolError("agent ID is invalid")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise AgentProtocolError("agent token is invalid")
        if not isinstance(snapshot, dict):
            raise AgentProtocolError("snapshot must be an object")
        path = f"/api/workstation-agent/v1/agents/{urllib.parse.quote(agent_id, safe='')}/snapshots"
        return self._request_json("POST", path, snapshot, token=token)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None,
    ) -> dict[str, Any]:
        try:
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AgentProtocolError("request contains invalid JSON values") from exc
        if len(body) > MAX_JSON_BYTES:
            raise AgentProtocolError("request exceeds the 64 KiB limit")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"Kasugai-Workstation-Agent/{AGENT_VERSION}",
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
                    length = response.headers.get("Content-Length") if response.headers else None
                    if length is not None:
                        try:
                            if int(length) > MAX_JSON_BYTES:
                                raise AgentProtocolError("dashboard response exceeds the 64 KiB limit")
                        except ValueError as exc:
                            raise AgentProtocolError("dashboard sent an invalid Content-Length") from exc
                    raw = response.read(MAX_JSON_BYTES + 1)
                    if len(raw) > MAX_JSON_BYTES:
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
                # Do not include urllib's reason in the error: proxy/server errors
                # can contain URLs and other environment details.
                error = AgentClientError("dashboard connection failed")
                transient = True
            if not transient or attempt >= self.max_retries:
                raise error
            delay = min(0.5 * (2**attempt), 4.0) + random.uniform(0.0, 0.1)
            self.sleeper(delay)

        raise AgentClientError("dashboard request failed")
