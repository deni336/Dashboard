"""Privacy-conscious workstation metric collection.

The collector intentionally does not enumerate processes, users, files, network
addresses, Wi-Fi networks, or listening ports.  GPU probing uses one fixed
``nvidia-smi`` command and never executes input received from the dashboard.
"""

from __future__ import annotations

import csv
import math
import os
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable

import psutil

from . import SNAPSHOT_SCHEMA_VERSION


NVIDIA_SMI_ARGV = (
    "nvidia-smi",
    "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
    "--format=csv,noheader,nounits",
)
_MAX_NVIDIA_OUTPUT = 32 * 1024
_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]?$")


def _number(
    value: Any,
    *,
    integer: bool = False,
    minimum: float | None = 0,
    maximum: float | None = None,
) -> int | float | None:
    if isinstance(value, bool):
        return None
    if integer and isinstance(value, int):
        if minimum is not None and value < minimum:
            return None
        if maximum is not None and value > maximum:
            return None
        return value
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    result = int(parsed) if integer else round(parsed, 2)
    if integer and parsed != result:
        return None
    return result


def _bounded_text(value: Any, limit: int) -> str:
    text = "".join(
        character for character in str(value or "") if ord(character) >= 32 and ord(character) != 127
    ).strip()
    return text[:limit]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _disk_name(mountpoint: str, position: int) -> str:
    if _DRIVE_ROOT.fullmatch(mountpoint):
        return mountpoint[:2].upper()
    return "System" if position == 0 else f"Disk {position + 1}"


def _collect_disks() -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        partitions = psutil.disk_partitions(all=False)
    except (OSError, RuntimeError):
        partitions = []

    # On restricted systems disk_partitions can be empty.  A root/system-drive
    # fallback still provides useful aggregate capacity without exposing paths.
    if not partitions:
        fallback = f"{os.environ.get('SystemDrive', 'C:')}\\" if os.name == "nt" else os.path.abspath(os.sep)
        partitions = [type("Partition", (), {"device": fallback, "mountpoint": fallback, "fstype": ""})()]

    for partition in partitions[:32]:
        mountpoint = str(getattr(partition, "mountpoint", ""))
        if not mountpoint or mountpoint in seen:
            continue
        # The Windows agent reports fixed drive roots only.  On other platforms
        # (primarily tests/development), report the filesystem root and nothing
        # from user-specific mount paths.
        if os.name == "nt" and not _DRIVE_ROOT.fullmatch(mountpoint):
            continue
        if os.name != "nt" and mountpoint != os.path.abspath(os.sep):
            continue
        try:
            usage = psutil.disk_usage(mountpoint)
        except (OSError, PermissionError, ValueError):
            continue
        seen.add(mountpoint)
        position = len(disks)
        disk = {
            "name": _disk_name(mountpoint, position),
            "filesystem": _bounded_text(getattr(partition, "fstype", ""), 24),
            "total_bytes": _number(usage.total, integer=True, maximum=2**63 - 1),
            "used_bytes": _number(usage.used, integer=True, maximum=2**63 - 1),
            "free_bytes": _number(usage.free, integer=True, maximum=2**63 - 1),
            "percent": _number(usage.percent, maximum=100),
        }
        if disk["total_bytes"] is not None:
            for key in ("used_bytes", "free_bytes"):
                if disk[key] is not None and disk[key] > disk["total_bytes"]:
                    disk[key] = None
        disks.append(disk)
    return disks


def collect_nvidia_gpus(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    """Return bounded NVIDIA telemetry, or an empty list when unavailable."""

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = runner(
            list(NVIDIA_SMI_ARGV),
            shell=False,
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=creationflags,
        )
    except (FileNotFoundError, PermissionError, OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    output = (result.stdout or "")[:_MAX_NVIDIA_OUTPUT]
    gpus: list[dict[str, Any]] = []
    try:
        rows = csv.reader(output.splitlines())
        for row in rows:
            if len(row) != 7 or len(gpus) >= 8:
                continue
            memory_used_mib = _number(row[3].strip(), maximum=(2**63 - 1) / 1024 / 1024)
            memory_total_mib = _number(row[4].strip(), maximum=(2**63 - 1) / 1024 / 1024)
            memory_used_bytes = (
                int(memory_used_mib * 1024 * 1024) if memory_used_mib is not None else None
            )
            memory_total_bytes = (
                int(memory_total_mib * 1024 * 1024) if memory_total_mib is not None else None
            )
            if (
                memory_used_bytes is not None
                and memory_total_bytes is not None
                and memory_used_bytes > memory_total_bytes
            ):
                memory_used_bytes = None
            gpu_index = _number(row[0].strip(), integer=True, maximum=31)
            gpu_name = _bounded_text(row[1], 160)
            if gpu_index is None or not gpu_name:
                continue
            gpus.append(
                {
                    "index": gpu_index,
                    "name": gpu_name,
                    "utilization_percent": _number(row[2].strip(), maximum=100),
                    "memory_used_bytes": memory_used_bytes,
                    "memory_total_bytes": memory_total_bytes,
                    "temperature_c": _number(row[5].strip(), minimum=-50, maximum=250),
                    "power_w": _number(row[6].strip(), maximum=10_000),
                }
            )
    except (csv.Error, TypeError):
        return []
    return gpus


def collect_snapshot(sequence: int, *, include_nvidia: bool = True) -> dict[str, Any]:
    """Collect one telemetry snapshot with a stable, privacy-safe schema."""

    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise ValueError("sequence must be a positive integer")

    try:
        cpu_percent = psutil.cpu_percent(interval=0.15)
    except (OSError, RuntimeError):
        cpu_percent = None
    try:
        frequency = psutil.cpu_freq()
    except (OSError, RuntimeError):
        frequency = None
    try:
        memory = psutil.virtual_memory()
    except (OSError, RuntimeError):
        memory = None
    try:
        disk_io = psutil.disk_io_counters(perdisk=False)
    except (OSError, RuntimeError):
        disk_io = None
    try:
        network = psutil.net_io_counters(pernic=False)
    except (OSError, RuntimeError):
        network = None
    try:
        battery = psutil.sensors_battery()
    except (AttributeError, OSError, RuntimeError):
        battery = None
    try:
        uptime_seconds = _number(
            int(datetime.now(timezone.utc).timestamp() - psutil.boot_time()),
            integer=True,
            maximum=100 * 366 * 24 * 60 * 60,
        )
    except (OSError, RuntimeError, ValueError):
        uptime_seconds = None

    system = {
        "uptime_seconds": uptime_seconds,
    }
    cpu = {
        "percent": _number(cpu_percent, maximum=100),
        "logical_count": _number(psutil.cpu_count(logical=True), integer=True, minimum=1, maximum=4096),
        "physical_count": _number(psutil.cpu_count(logical=False), integer=True, minimum=1, maximum=1024),
        "frequency_mhz": _number(getattr(frequency, "current", None), maximum=100_000),
    }
    memory_payload = {
        "total_bytes": _number(getattr(memory, "total", None), integer=True, maximum=2**63 - 1),
        "available_bytes": _number(
            getattr(memory, "available", None), integer=True, maximum=2**63 - 1
        ),
        "used_bytes": _number(getattr(memory, "used", None), integer=True, maximum=2**63 - 1),
        "percent": _number(getattr(memory, "percent", None), maximum=100),
    }
    if memory_payload["total_bytes"] is not None:
        for key in ("available_bytes", "used_bytes"):
            if memory_payload[key] is not None and memory_payload[key] > memory_payload["total_bytes"]:
                memory_payload[key] = None
    disk_io_payload = {
        "read_bytes_total": _number(
            getattr(disk_io, "read_bytes", None), integer=True, maximum=2**63 - 1
        ),
        "write_bytes_total": _number(
            getattr(disk_io, "write_bytes", None), integer=True, maximum=2**63 - 1
        ),
        "read_bps": None,
        "write_bps": None,
    }
    network_payload = {
        "received_bytes_total": _number(
            getattr(network, "bytes_recv", None), integer=True, maximum=2**63 - 1
        ),
        "sent_bytes_total": _number(
            getattr(network, "bytes_sent", None), integer=True, maximum=2**63 - 1
        ),
        "received_bps": None,
        "sent_bps": None,
    }
    battery_payload = None
    if battery is not None:
        seconds_left = getattr(battery, "secsleft", None)
        unknown_values = {getattr(psutil, "POWER_TIME_UNKNOWN", -1), getattr(psutil, "POWER_TIME_UNLIMITED", -2)}
        battery_payload = {
            "percent": _number(getattr(battery, "percent", None), maximum=100),
            "plugged": bool(getattr(battery, "power_plugged", False)),
            "seconds_left": (
                None
                if seconds_left in unknown_values
                else _number(seconds_left, integer=True, maximum=366 * 24 * 60 * 60)
            ),
        }

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "sequence": sequence,
        "captured_at": _utc_now(),
        "system": system,
        "cpu": cpu,
        "memory": memory_payload,
        "disks": _collect_disks(),
        "disk_io": disk_io_payload,
        "network": network_payload,
        "battery": battery_payload,
        "gpus": collect_nvidia_gpus() if include_nvidia else [],
    }


def platform_description() -> str:
    """Return a bounded platform label suitable for the pairing request."""

    parts = (platform.system(), platform.release(), platform.version(), platform.machine())
    return _bounded_text(" ".join(part for part in parts if part), 160)


def agent_capabilities() -> list[str]:
    return ["system", "cpu", "memory", "disks", "disk_io", "network", "battery", "nvidia_gpu"]


def _counter_rate(current: Any, previous: Any, elapsed: float) -> float | None:
    if current is None or previous is None or elapsed <= 0 or current < previous:
        return None
    rate = round((current - previous) / elapsed, 2)
    return rate if rate <= 1_000_000_000_000_000 else None


class WorkstationCollector:
    """Stateful collector that derives transfer rates from monotonic counters."""

    def __init__(self, *, include_nvidia: bool = True, monotonic: Callable[[], float] = time.monotonic):
        self.include_nvidia = include_nvidia
        self.monotonic = monotonic
        self._previous: tuple[float, dict[str, Any]] | None = None

    def collect(self, sequence: int) -> dict[str, Any]:
        snapshot = collect_snapshot(sequence, include_nvidia=self.include_nvidia)
        captured = self.monotonic()
        if self._previous is not None:
            previous_time, previous = self._previous
            elapsed = captured - previous_time
            snapshot["disk_io"]["read_bps"] = _counter_rate(
                snapshot["disk_io"]["read_bytes_total"],
                previous["disk_io"]["read_bytes_total"],
                elapsed,
            )
            snapshot["disk_io"]["write_bps"] = _counter_rate(
                snapshot["disk_io"]["write_bytes_total"],
                previous["disk_io"]["write_bytes_total"],
                elapsed,
            )
            snapshot["network"]["received_bps"] = _counter_rate(
                snapshot["network"]["received_bytes_total"],
                previous["network"]["received_bytes_total"],
                elapsed,
            )
            snapshot["network"]["sent_bps"] = _counter_rate(
                snapshot["network"]["sent_bytes_total"],
                previous["network"]["sent_bytes_total"],
                elapsed,
            )
        self._previous = (captured, snapshot)
        return snapshot
