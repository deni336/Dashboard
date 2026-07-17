"""Bounded Docker inventory and locally configured homelab health checks."""

from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import SNAPSHOT_SCHEMA_VERSION
from .config import HealthCheck, HomelabConfig


MAX_CONTAINERS = 100
MAX_STORAGE_ITEMS = 8
MAX_HEALTH_CHECKS = 32
MAX_DOCKER_OUTPUT = 256 * 1024
MAX_HEALTH_BODY = 16 * 1024
DOCKER_CONTEXT = "default"
_FULL_CONTAINER_ID = re.compile(r"^[a-f0-9]{64}$")
_SAFE_STATE = {"created", "restarting", "running", "removing", "paused", "exited", "dead"}
_SAFE_HEALTH = {"healthy", "unhealthy", "starting", "none", "unknown"}

PS_FORMAT = (
    '{"id":{{json .ID}},"name":{{json .Names}},"image":{{json .Image}},'
    '"state":{{json .State}},"status":{{json .Status}},'
    '"health":{{json .HealthStatus}},"created":{{json .CreatedAt}},'
    '"ports":{{json .Ports}},'
    '"compose_project":{{json (.Label "com.docker.compose.project")}},'
    '"compose_service":{{json (.Label "com.docker.compose.service")}},'
    '"monitor":{{json (.Label "io.kasugai.monitor")}},'
    '"logs":{{json (.Label "io.kasugai.logs")}},'
    '"actions":{{json (.Label "io.kasugai.actions")}}}'
)
INSPECT_LABELS_FORMAT = (
    '{"id":{{json .Id}},"state":{{json .State.Status}},'
    '"monitor":{{json (index .Config.Labels "io.kasugai.monitor")}},'
    '"logs":{{json (index .Config.Labels "io.kasugai.logs")}},'
    '"actions":{{json (index .Config.Labels "io.kasugai.actions")}}}'
)


class DockerCommandError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str
    timed_out: bool = False
    truncated: bool = False


class BoundedCommandRunner:
    """Run fixed argv while killing producers that exceed time or output limits."""

    def __init__(self, popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen):
        self._popen_factory = popen_factory

    def __call__(
        self,
        argv: list[str],
        *,
        timeout: float,
        max_output: int,
        include_stderr: bool = False,
    ) -> CommandOutput:
        if not argv or not os.path.isabs(argv[0]):
            raise DockerCommandError("not_installed")
        environment = os.environ.copy()
        for name in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_API_VERSION",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            environment.pop(name, None)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            process = self._popen_factory(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if include_stderr else subprocess.DEVNULL,
                env=environment,
                creationflags=creationflags,
            )
        except PermissionError as exc:
            raise DockerCommandError("permission_denied") from exc
        except (FileNotFoundError, OSError) as exc:
            raise DockerCommandError("not_installed") from exc

        chunks: list[bytes] = []
        size = 0
        overflow = threading.Event()

        def drain() -> None:
            nonlocal size
            stream = process.stdout
            if stream is None:
                return
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                room = max_output - size
                if room > 0:
                    chunks.append(chunk[:room])
                    size += min(len(chunk), room)
                if len(chunk) > room:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return

        thread = threading.Thread(target=drain, name="kasugai-docker-output", daemon=True)
        thread.start()
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                process.kill()
            except OSError:
                pass
            returncode = process.wait(timeout=2)
        finally:
            thread.join(timeout=2)
            if process.stdout is not None:
                process.stdout.close()
        return CommandOutput(
            returncode=returncode,
            stdout=b"".join(chunks).decode("utf-8", errors="replace"),
            timed_out=timed_out,
            truncated=overflow.is_set(),
        )


def resolve_docker_executable(value: str | Path | None = None) -> str | None:
    candidate = str(value) if value is not None else shutil.which("docker")
    if not candidate:
        return None
    resolved = os.path.abspath(candidate)
    if not os.path.isfile(resolved):
        return None
    return resolved


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(
        char for char in value.strip() if ord(char) >= 32 and ord(char) != 127
    )[:limit]


def _number(
    value: Any, *, integer: bool = False, minimum: float = 0, maximum: float | None = None
) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < minimum or (maximum is not None and parsed > maximum):
        return None
    if integer:
        converted = int(parsed)
        return converted if converted == parsed else None
    return round(parsed, 2)


def _decode_secret(secret: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
    except (ValueError, TypeError) as exc:
        raise ValueError("resource key secret is invalid") from exc


def opaque_resource_key(secret: str, kind: str, local_value: str) -> str:
    if kind not in {"engine", "container", "health"} or not local_value:
        raise ValueError("resource key input is invalid")
    digest = hmac.new(
        _decode_secret(secret),
        f"kasugai-{kind}-v1\0{local_value}".encode("utf-8"),
        hashlib.sha256,
    ).digest()[:24]
    prefix = {"engine": "eng", "container": "ctr", "health": "chk"}[kind]
    return f"{prefix}_{base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')}"


def _parse_json_object(output: CommandOutput) -> dict[str, Any]:
    if output.timed_out:
        raise DockerCommandError("timed_out")
    if output.truncated:
        raise DockerCommandError("output_too_large")
    if output.returncode != 0:
        raise DockerCommandError("daemon_unavailable")
    try:
        payload = json.loads(output.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DockerCommandError("protocol_error") from exc
    if not isinstance(payload, dict):
        raise DockerCommandError("protocol_error")
    return payload


def _parse_json_lines(output: CommandOutput) -> list[dict[str, Any]]:
    if output.timed_out:
        raise DockerCommandError("timed_out")
    if output.truncated:
        raise DockerCommandError("output_too_large")
    if output.returncode != 0:
        raise DockerCommandError("daemon_unavailable")
    rows: list[dict[str, Any]] = []
    try:
        for line in output.stdout.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    except json.JSONDecodeError as exc:
        raise DockerCommandError("protocol_error") from exc
    return rows


_SIZE_UNITS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}
_SIZE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?i?B)$", re.IGNORECASE)


def parse_size(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = _SIZE.fullmatch(value.strip())
    if not match:
        return None
    parsed = float(match.group(1)) * _SIZE_UNITS[match.group(2).lower()]
    return int(parsed) if 0 <= parsed <= 2**63 - 1 else None


def _pair_sizes(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, str) or " / " not in value:
        return None, None
    left, right = value.split(" / ", 1)
    return parse_size(left), parse_size(right)


def _percent(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    return _number(value.strip().removesuffix("%"), maximum=100000)


def _created_at(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidates = (value, value[:25])
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                )
        except ValueError:
            pass
        try:
            parsed = datetime.strptime(candidate, "%Y-%m-%d %H:%M:%S %z")
            return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            )
        except ValueError:
            pass
    return None


_PORT_MAPPING = re.compile(r"(?:(?:\[[^]]+\]|[^, ]+):)?(\d+)->(\d+)/(tcp|udp|sctp)$")
_CONTAINER_PORT = re.compile(r"^(\d+)/(tcp|udp|sctp)$")


def parse_ports(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        return []
    ports: list[dict[str, Any]] = []
    seen: set[tuple[int, int | None, str]] = set()
    for raw in value.split(",")[:64]:
        item = raw.strip()
        mapping = _PORT_MAPPING.search(item)
        if mapping:
            host = int(mapping.group(1))
            container = int(mapping.group(2))
            protocol = mapping.group(3)
        else:
            exposed = _CONTAINER_PORT.fullmatch(item)
            if not exposed:
                continue
            container = int(exposed.group(1))
            host = None
            protocol = exposed.group(2)
        if not 1 <= container <= 65535 or host is not None and not 1 <= host <= 65535:
            continue
        key = (container, host, protocol)
        if key in seen:
            continue
        seen.add(key)
        ports.append({"container_port": container, "host_port": host, "protocol": protocol})
    return ports[:32]


def _policy_revision(config: HomelabConfig) -> str:
    canonical = json.dumps(
        {
            "inventory_enabled": config.inventory_enabled,
            "allow_logs": config.allow_logs,
            "allow_restart": config.allow_restart,
            "checks": [
                [check.name, check.url, check.timeout_seconds, check.expected_statuses]
                for check in config.health_checks
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(canonical).digest()[:18]).rstrip(b"=").decode()


class DockerInventoryCollector:
    def __init__(
        self,
        resource_key_secret: str,
        *,
        docker_executable: str | Path | None = None,
        runner: Callable[..., CommandOutput] | None = None,
    ):
        self.resource_key_secret = resource_key_secret
        self.docker_executable = resolve_docker_executable(docker_executable)
        self.runner = runner or BoundedCommandRunner()
        self.local_resources: dict[str, str] = {}
        self.storage_truncated = False

    def _run(
        self,
        arguments: Iterable[str],
        *,
        timeout: float = 4,
        limit: int = MAX_DOCKER_OUTPUT,
        include_stderr: bool = False,
    ) -> CommandOutput:
        if self.docker_executable is None:
            raise DockerCommandError("not_installed")
        return self.runner(
            [self.docker_executable, "--context", DOCKER_CONTEXT, *arguments],
            timeout=timeout,
            max_output=limit,
            include_stderr=include_stderr,
        )

    def _validate_context(self) -> None:
        result = self._run(
            ["context", "inspect", DOCKER_CONTEXT, "--format", "{{json .Endpoints.docker.Host}}"],
            timeout=3,
            limit=4096,
        )
        if result.timed_out:
            raise DockerCommandError("timed_out")
        if result.returncode != 0 or result.truncated:
            raise DockerCommandError("context_unavailable")
        try:
            endpoint = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DockerCommandError("context_unavailable") from exc
        if not isinstance(endpoint, str) or not endpoint.startswith(("npipe://", "unix://")):
            raise DockerCommandError("context_not_local")

    def collect(self, config: HomelabConfig) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], bool]:
        self.local_resources = {}
        self.storage_truncated = False
        if not config.inventory_enabled:
            return self._unavailable_engine("permission_denied"), [], [], False
        try:
            self._validate_context()
            version = _parse_json_object(
                self._run(["version", "--format", "{{json .Server}}"], timeout=4)
            )
            info = _parse_json_object(
                self._run(["info", "--format", "{{json .}}"], timeout=4)
            )
            ps_rows = _parse_json_lines(
                self._run(
                    ["container", "ls", "--all", "--no-trunc", "--format", PS_FORMAT],
                    timeout=4,
                )
            )
            stats_rows = _parse_json_lines(
                self._run(
                    [
                        "container",
                        "stats",
                        "--all",
                        "--no-stream",
                        "--no-trunc",
                        "--format",
                        "{{json .}}",
                    ],
                    timeout=8,
                )
            )
            compose_output = self._run(
                ["compose", "ls", "--all", "--format", "json"], timeout=4, limit=64 * 1024
            )
            storage_rows = _parse_json_lines(
                self._run(["system", "df", "--format", "json"], timeout=5, limit=64 * 1024)
            )
            volume_output = self._run(
                ["volume", "ls", "--quiet"], timeout=4, limit=64 * 1024
            )
            network_output = self._run(
                ["network", "ls", "--quiet"], timeout=4, limit=64 * 1024
            )
        except DockerCommandError as exc:
            allowed_error = exc.code if exc.code in {
                "not_installed",
                "daemon_unavailable",
                "context_not_local",
                "timed_out",
                "permission_denied",
                "protocol_error",
            } else "protocol_error"
            return self._unavailable_engine(allowed_error), [], [], False

        stats_by_id: dict[str, dict[str, Any]] = {}
        stats_by_name: dict[str, dict[str, Any]] = {}
        for row in stats_rows:
            local_id = str(row.get("Container") or row.get("ID") or "").lower()
            if _FULL_CONTAINER_ID.fullmatch(local_id):
                stats_by_id[local_id] = row
            name = str(row.get("Name") or "")
            if name:
                stats_by_name[name] = row

        monitored = [row for row in ps_rows if str(row.get("monitor", "")).lower() == "true"]
        truncated = len(monitored) > MAX_CONTAINERS
        containers: list[dict[str, Any]] = []
        for row in monitored[:MAX_CONTAINERS]:
            local_id = str(row.get("id") or "").lower()
            if not _FULL_CONTAINER_ID.fullmatch(local_id):
                continue
            name = _bounded_text(row.get("name"), 128)
            image = _bounded_text(row.get("image"), 240)
            if not name or not image:
                continue
            key = opaque_resource_key(self.resource_key_secret, "container", local_id)
            self.local_resources[key] = local_id
            stats = stats_by_id.get(local_id) or stats_by_name.get(name) or {}
            memory_used, memory_limit = _pair_sizes(stats.get("MemUsage"))
            if memory_used is not None and memory_limit is not None and memory_used > memory_limit:
                memory_used = None
            network_rx, network_tx = _pair_sizes(stats.get("NetIO"))
            block_read, block_write = _pair_sizes(stats.get("BlockIO"))
            state = str(row.get("state") or "").lower()
            health = str(row.get("health") or "").lower() or "none"
            grants_actions = (
                ["restart"]
                if config.allow_restart and str(row.get("actions", "")).lower() == "restart"
                else []
            )
            containers.append(
                {
                    "key": key,
                    "name": name,
                    "image": image,
                    "compose_project": _bounded_text(row.get("compose_project"), 128) or None,
                    "compose_service": _bounded_text(row.get("compose_service"), 128) or None,
                    "state": state if state in _SAFE_STATE else "unknown",
                    "health": health if health in _SAFE_HEALTH else "unknown",
                    "created_at": _created_at(row.get("created")),
                    "cpu_percent": _percent(stats.get("CPUPerc")),
                    "memory_usage_bytes": memory_used,
                    "memory_limit_bytes": memory_limit,
                    "memory_percent": _percent(stats.get("MemPerc")),
                    "network_rx_bytes": network_rx,
                    "network_tx_bytes": network_tx,
                    "block_read_bytes": block_read,
                    "block_write_bytes": block_write,
                    "pids": _number(stats.get("PIDs"), integer=True, maximum=1_000_000),
                    "ports": parse_ports(row.get("ports")),
                    "image_update": {"status": "unknown", "checked_at": None},
                    "grants": {
                        "logs": config.allow_logs and str(row.get("logs", "")).lower() == "true",
                        "actions": grants_actions,
                    },
                }
            )

        # Compose inventory is intentionally queried to detect local stacks, but
        # only the per-container project/service fields are transmitted. Paths
        # and raw Compose documents never leave this process.
        del compose_output

        def line_count(output: CommandOutput) -> int:
            if output.returncode != 0 or output.timed_out or output.truncated:
                return 0
            return min(sum(1 for line in output.stdout.splitlines() if line.strip()), 1_000_000)

        storage_kind = {
            "images": "images",
            "containers": "containers",
            "local volumes": "volumes",
            "volumes": "volumes",
            "build cache": "build_cache",
        }
        storage: list[dict[str, Any]] = []
        self.storage_truncated = len(storage_rows) > MAX_STORAGE_ITEMS
        for row in storage_rows[:MAX_STORAGE_ITEMS]:
            kind = storage_kind.get(str(row.get("Type") or "").strip().casefold())
            if kind is None or any(item["kind"] == kind for item in storage):
                continue
            reclaimable = str(row.get("Reclaimable") or "").split(" ", 1)[0]
            storage.append(
                {
                    "kind": kind,
                    "total_count": _number(row.get("TotalCount"), integer=True, maximum=1_000_000) or 0,
                    "active_count": _number(row.get("Active"), integer=True, maximum=1_000_000) or 0,
                    "size_bytes": parse_size(row.get("Size")),
                    "reclaimable_bytes": parse_size(reclaimable),
                }
            )
            if storage[-1]["active_count"] > storage[-1]["total_count"]:
                storage[-1]["active_count"] = storage[-1]["total_count"]
            if (
                storage[-1]["size_bytes"] is not None
                and storage[-1]["reclaimable_bytes"] is not None
                and storage[-1]["reclaimable_bytes"] > storage[-1]["size_bytes"]
            ):
                storage[-1]["reclaimable_bytes"] = None
        checked_at = _utc_now()
        engine_local = str(info.get("ID") or version.get("ID") or "default-local-engine")
        def container_count(value: Any) -> int:
            parsed = _number(value, integer=True, maximum=10_000_000)
            return min(parsed, MAX_CONTAINERS) if isinstance(parsed, int) else 0

        counts = {
            "total": container_count(info.get("Containers")),
            "running": container_count(info.get("ContainersRunning")),
            "paused": container_count(info.get("ContainersPaused")),
            "stopped": container_count(info.get("ContainersStopped")),
        }
        active_sum = counts["running"] + counts["paused"] + counts["stopped"]
        if active_sum > counts["total"]:
            counts["stopped"] = max(0, counts["total"] - counts["running"] - counts["paused"])
            if counts["running"] + counts["paused"] > counts["total"]:
                counts["paused"] = max(0, counts["total"] - counts["running"])
            if counts["running"] > counts["total"]:
                counts["running"] = counts["total"]
        engine = {
            "available": True,
            "key": opaque_resource_key(self.resource_key_secret, "engine", engine_local),
            "kind": "docker",
            "server_version": _bounded_text(version.get("Version") or info.get("ServerVersion"), 64) or "unknown",
            "operating_system": _bounded_text(info.get("OperatingSystem"), 128) or "unknown",
            "os_type": _bounded_text(info.get("OSType") or version.get("Os"), 32) or "unknown",
            "architecture": _bounded_text(info.get("Architecture") or version.get("Arch"), 32) or "unknown",
            "cpu_count": _number(info.get("NCPU"), integer=True, maximum=4096),
            "memory_bytes": _number(info.get("MemTotal"), integer=True, maximum=2**63 - 1),
            "container_counts": counts,
            "image_count": _number(info.get("Images"), integer=True, maximum=1_000_000) or 0,
            "volume_count": line_count(volume_output),
            "network_count": line_count(network_output),
            "checked_at": checked_at,
            "error_code": None,
        }
        return engine, storage, containers, truncated

    @staticmethod
    def _unavailable_engine(error_code: str | None) -> dict[str, Any]:
        return {
            "available": False,
            "key": None,
            "kind": "docker",
            "server_version": "",
            "operating_system": "",
            "os_type": "",
            "architecture": "",
            "cpu_count": None,
            "memory_bytes": None,
            "container_counts": {"total": 0, "running": 0, "paused": 0, "stopped": 0},
            "image_count": 0,
            "volume_count": 0,
            "network_count": 0,
            "checked_at": _utc_now(),
            "error_code": error_code,
        }

    def revalidate(self, resource_key: str) -> dict[str, Any] | None:
        """Resolve an opaque key locally and freshly revalidate labels/state."""

        local_id = self.local_resources.get(resource_key)
        if not local_id or not _FULL_CONTAINER_ID.fullmatch(local_id):
            return None
        try:
            result = self._run(
                ["container", "inspect", "--format", INSPECT_LABELS_FORMAT, local_id],
                timeout=4,
                limit=16 * 1024,
            )
            payload = _parse_json_object(result)
        except DockerCommandError:
            return None
        observed_id = str(payload.get("id") or "").lower()
        if observed_id != local_id:
            return None
        if opaque_resource_key(self.resource_key_secret, "container", observed_id) != resource_key:
            return None
        return payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


class HealthCollector:
    def __init__(self, resource_key_secret: str, *, opener: Any | None = None):
        self.resource_key_secret = resource_key_secret
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self._failures: dict[str, int] = {}

    def _check(self, check: HealthCheck) -> dict[str, Any]:
        checked_at = _utc_now()
        key = opaque_resource_key(self.resource_key_secret, "health", f"{check.name}\0{check.url}")
        started = time.monotonic()
        http_status: int | None = None
        error_code: str | None = None
        try:
            request = urllib.request.Request(
                check.url,
                headers={"Accept": "*/*", "User-Agent": "Kasugai-Homelab-Health/1"},
                method="GET",
            )
            response = self.opener.open(request, timeout=check.timeout_seconds)
            try:
                http_status = int(
                    getattr(response, "status", None)
                    if getattr(response, "status", None) is not None
                    else response.getcode()
                )
                length = response.headers.get("Content-Length") if response.headers else None
                if length is not None and int(length) > MAX_HEALTH_BODY:
                    error_code = "protocol_error"
                else:
                    body = response.read(MAX_HEALTH_BODY + 1)
                    if len(body) > MAX_HEALTH_BODY:
                        error_code = "protocol_error"
            finally:
                response.close()
        except urllib.error.HTTPError as exc:
            http_status = int(exc.code)
            exc.close()
            # HTTPError is also the bounded response object for non-2xx status;
            # it may still be an explicitly expected health result.
            error_code = None
        except (TimeoutError, socket.timeout):
            error_code = "timeout"
        except ssl.SSLError:
            error_code = "tls_failed"
        except socket.gaierror:
            error_code = "dns_failed"
        except ConnectionRefusedError:
            error_code = "connection_refused"
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                error_code = "timeout"
            elif isinstance(reason, socket.gaierror):
                error_code = "dns_failed"
            elif isinstance(reason, ConnectionRefusedError):
                error_code = "connection_refused"
            elif isinstance(reason, ssl.SSLError):
                error_code = "tls_failed"
            else:
                error_code = "protocol_error"
        except (OSError, ValueError):
            error_code = "protocol_error"
        latency = _number((time.monotonic() - started) * 1000, maximum=600_000)
        if error_code is None and http_status not in check.expected_statuses:
            error_code = "unexpected_status"
        if error_code is None:
            self._failures[key] = 0
            status = "up"
        else:
            self._failures[key] = min(self._failures.get(key, 0) + 1, 2**31 - 1)
            status = "down"
        return {
            "key": key,
            "name": check.name,
            "kind": "http",
            "status": status,
            "checked_at": checked_at,
            "latency_ms": latency,
            "http_status": http_status,
            "tls_expires_in_days": None,
            "consecutive_failures": self._failures[key],
            "error_code": error_code,
        }

    def collect(self, checks: tuple[HealthCheck, ...]) -> tuple[list[dict[str, Any]], bool]:
        selected = checks[:MAX_HEALTH_CHECKS]
        truncated = len(checks) > MAX_HEALTH_CHECKS
        if not selected:
            return [], truncated
        results: list[dict[str, Any]] = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(selected)))
        futures = [executor.submit(self._check, check) for check in selected]
        done, unfinished = concurrent.futures.wait(futures, timeout=10)
        for future in done:
            try:
                results.append(future.result())
            except (OSError, RuntimeError, ValueError):
                # Individual checks normally convert failures to an enum. A
                # truly unexpected local failure is omitted, never serialized.
                pass
        for future in unfinished:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        results.sort(key=lambda item: item["key"])
        return results, truncated or bool(unfinished)


class HomelabCollector:
    def __init__(
        self,
        resource_key_secret: str,
        *,
        docker_executable: str | Path | None = None,
        runner: Callable[..., CommandOutput] | None = None,
        health_opener: Any | None = None,
    ):
        self.docker = DockerInventoryCollector(
            resource_key_secret, docker_executable=docker_executable, runner=runner
        )
        self.health = HealthCollector(resource_key_secret, opener=health_opener)

    def collect(self, sequence: int, config: HomelabConfig) -> dict[str, Any]:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ValueError("sequence must be a positive integer")
        captured_at = _utc_now()
        engine, storage, containers, containers_truncated = self.docker.collect(config)
        health_checks, health_truncated = self.health.collect(config.health_checks)
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "sequence": sequence,
            "captured_at": captured_at,
            "policy": {
                "revision": _policy_revision(config),
                "inventory_scope": "labeled",
                "logs_enabled": config.allow_logs,
                "allowed_actions": ["restart"] if config.allow_restart else [],
                "image_updates_enabled": False,
            },
            "engine": engine,
            "storage": storage,
            "containers": containers,
            "health_checks": health_checks,
            "truncated": {
                "containers": containers_truncated,
                "storage": self.docker.storage_truncated,
                "health_checks": health_truncated,
            },
        }


def platform_description() -> str:
    import platform

    return _bounded_text(
        f"{platform.system()} {platform.release()} {platform.machine()} Docker CLI", 160
    )


__all__ = [
    "BoundedCommandRunner",
    "CommandOutput",
    "DockerInventoryCollector",
    "HomelabCollector",
    "INSPECT_LABELS_FORMAT",
    "PS_FORMAT",
    "opaque_resource_key",
    "parse_ports",
    "parse_size",
    "platform_description",
    "resolve_docker_executable",
]
