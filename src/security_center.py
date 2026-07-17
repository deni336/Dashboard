"""Read-only security posture assembled from existing public monitor summaries."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime


AGENT_STATUSES = ("online", "stale", "offline")
RESOURCE_WARNING_PERCENT = 90.0
CHECK_PENALTIES = {"good": 0, "warning": 7, "critical": 20}


def _environment_enabled(name, default=False):
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _iso_timestamp(value):
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=UTC)
    else:
        current = datetime.fromtimestamp(float(value), UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _nonnegative_number(value):
    if isinstance(value, bool):
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if math.isfinite(result) and result >= 0 else 0.0


def _clean_total(value):
    result = _nonnegative_number(value)
    return int(result) if result.is_integer() else round(result, 3)


def _agent_counts(values):
    counts = {"total": len(values), "online": 0, "stale": 0, "offline": 0}
    for item in values:
        if not isinstance(item, dict) or item.get("status") not in AGENT_STATUSES:
            raise ValueError("Monitor returned an invalid agent summary")
        counts[item["status"]] += 1
    return counts


def _check(identifier, status, title, detail, recommendation):
    if status not in CHECK_PENALTIES:
        raise ValueError("Unsupported security check status")
    return {
        "id": identifier,
        "status": status,
        "title": title,
        "detail": detail,
        "recommendation": recommendation,
    }


class SecurityCenter:
    """Aggregate safe counts without scanning or reaching beyond existing services."""

    def __init__(
        self,
        dashboard_store,
        *,
        workstation_monitor=None,
        homelab_monitor=None,
        launcher_runner=None,
        clock=None,
    ):
        self.store = dashboard_store
        self.workstation_monitor = workstation_monitor
        self.homelab_monitor = homelab_monitor
        self.launcher_runner = launcher_runner
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())

    @staticmethod
    def _unavailable_workstation():
        return {
            "status": "unavailable",
            "agents": {"total": 0, "online": 0, "stale": 0, "offline": 0},
            "network": {"received_bps": 0, "sent_bps": 0},
            "resource_warnings": {"cpu": 0, "memory": 0, "gpu": 0, "disk": 0},
        }

    @staticmethod
    def _unavailable_homelab():
        return {
            "status": "unavailable",
            "agents": {"total": 0, "online": 0, "stale": 0, "offline": 0},
            "engines_unavailable": 0,
            "containers": {"total": 0, "running": 0, "unhealthy": 0},
            "health_checks_down": 0,
            "updates_available": 0,
        }

    @staticmethod
    def _unavailable_launcher():
        return {
            "status": "unavailable",
            "agents": {"total": 0, "online": 0, "stale": 0, "offline": 0},
        }

    def _workstation_summary(self, owner_key):
        if self.workstation_monitor is None:
            raise RuntimeError("Workstation monitor is unavailable")
        payload = self.workstation_monitor.list_workstations(owner_key)
        values = payload.get("workstations") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise ValueError("Workstation monitor returned an invalid response")
        network_received = 0.0
        network_sent = 0.0
        warnings = {"cpu": 0, "memory": 0, "gpu": 0, "disk": 0}
        fields = {
            "cpu": "cpu_percent",
            "memory": "memory_percent",
            "gpu": "gpu_percent",
            "disk": "disk_percent",
        }
        for item in values:
            summary = item.get("latest_summary")
            if summary is None:
                continue
            if not isinstance(summary, dict):
                raise ValueError("Workstation monitor returned an invalid summary")
            network_received += _nonnegative_number(summary.get("network_received_bps"))
            network_sent += _nonnegative_number(summary.get("network_sent_bps"))
            for warning_id, field in fields.items():
                raw_value = summary.get(field)
                if raw_value is not None and _nonnegative_number(raw_value) >= RESOURCE_WARNING_PERCENT:
                    warnings[warning_id] += 1
        return {
            "status": "available",
            "agents": _agent_counts(values),
            "network": {
                "received_bps": _clean_total(network_received),
                "sent_bps": _clean_total(network_sent),
            },
            "resource_warnings": warnings,
        }

    def _homelab_summary(self, owner_key):
        if self.homelab_monitor is None:
            raise RuntimeError("Homelab monitor is unavailable")
        payload = self.homelab_monitor.list_agents(owner_key)
        values = payload.get("agents") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise ValueError("Homelab monitor returned an invalid response")
        engines_unavailable = 0
        containers = {"total": 0, "running": 0, "unhealthy": 0}
        health_checks_down = 0
        updates_available = 0
        for item in values:
            summary = item.get("latest_summary")
            if summary is None:
                continue
            if not isinstance(summary, dict):
                raise ValueError("Homelab monitor returned an invalid summary")
            engines_unavailable += int(not bool(summary.get("engine_available")))
            containers["total"] += int(_nonnegative_number(summary.get("containers_total")))
            containers["running"] += int(_nonnegative_number(summary.get("containers_running")))
            containers["unhealthy"] += int(
                _nonnegative_number(summary.get("containers_unhealthy"))
            )
            health_checks_down += int(_nonnegative_number(summary.get("health_checks_down")))
            updates_available += int(_nonnegative_number(summary.get("updates_available")))
        return {
            "status": "available",
            "agents": _agent_counts(values),
            "engines_unavailable": engines_unavailable,
            "containers": containers,
            "health_checks_down": health_checks_down,
            "updates_available": updates_available,
        }

    def _launcher_summary(self, owner_key):
        if self.launcher_runner is None:
            raise RuntimeError("Launcher runner is unavailable")
        payload = self.launcher_runner.list_agents(owner_key)
        values = payload.get("agents") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise ValueError("Launcher runner returned an invalid response")
        return {"status": "available", "agents": _agent_counts(values)}

    @staticmethod
    def _configuration_checks(*, secure_cookie, trust_proxy, encryption_configured):
        return [
            _check(
                "secure_cookie",
                "good" if secure_cookie else "critical",
                "Secure session cookie",
                "Session cookies are restricted to encrypted transport."
                if secure_cookie
                else "Session cookies are not restricted to encrypted transport.",
                "Keep secure cookies enabled whenever the dashboard is served over HTTPS.",
            ),
            _check(
                "trust_proxy",
                "warning" if trust_proxy else "good",
                "Reverse proxy trust",
                "One forwarded-header proxy hop is trusted."
                if trust_proxy
                else "Forwarded client headers are not trusted.",
                "When proxy trust is enabled, prevent clients from reaching the dashboard directly.",
            ),
            _check(
                "encryption",
                "good" if encryption_configured else "critical",
                "Encrypted dashboard storage",
                "Authenticated encryption is available for protected dashboard data."
                if encryption_configured
                else "Authenticated encryption is unavailable for protected dashboard data.",
                "Configure and preserve the dashboard encryption key before storing protected data.",
            ),
            _check(
                "homelab_actions",
                "warning"
                if _environment_enabled("KASUGAI_HOMELAB_ACTIONS_ENABLED")
                else "good",
                "Remote homelab actions",
                "Remote Docker actions are enabled."
                if _environment_enabled("KASUGAI_HOMELAB_ACTIONS_ENABLED")
                else "Remote Docker actions are disabled by the server kill switch.",
                "Enable remote Docker actions only with matching local and per-container grants.",
            ),
            _check(
                "launcher_runs",
                "warning"
                if _environment_enabled("KASUGAI_LAUNCHER_RUNS_ENABLED")
                else "good",
                "Remote launcher runs",
                "Delivery of locally approved launcher tasks is enabled."
                if _environment_enabled("KASUGAI_LAUNCHER_RUNS_ENABLED")
                else "Launcher task delivery is disabled by the server kill switch.",
                "Keep task delivery disabled unless a locally allowlisted runner is required.",
            ),
            _check(
                "automation_tasks",
                "warning"
                if _environment_enabled("KASUGAI_AUTOMATION_TASKS_ENABLED")
                else "good",
                "Automated task delivery",
                "Automations may queue eligible launcher tasks."
                if _environment_enabled("KASUGAI_AUTOMATION_TASKS_ENABLED")
                else "Automatic launcher task delivery is disabled.",
                "Enable automatic tasks only for non-confirming tasks with narrow local policies.",
            ),
        ]

    @staticmethod
    def _source_checks(workstation, homelab, launcher):
        checks = []
        if workstation["status"] != "available":
            workstation_status = "warning"
            workstation_detail = "Workstation posture summaries are temporarily unavailable."
        else:
            warning_total = sum(workstation["resource_warnings"].values())
            affected = (
                workstation["agents"]["stale"]
                + workstation["agents"]["offline"]
                + warning_total
            )
            workstation_status = "warning" if affected else "good"
            workstation_detail = (
                f"{warning_total} resource warnings and "
                f"{workstation['agents']['stale'] + workstation['agents']['offline']} inactive agents."
                if affected
                else "No high resource readings or inactive workstation agents were reported."
            )
        checks.append(
            _check(
                "workstation_posture",
                workstation_status,
                "Workstation posture",
                workstation_detail,
                "Review sustained resource pressure and agents that are stale or offline.",
            )
        )

        if homelab["status"] != "available":
            homelab_status = "warning"
            homelab_detail = "Homelab posture summaries are temporarily unavailable."
        elif homelab["containers"]["unhealthy"] or homelab["health_checks_down"]:
            homelab_status = "critical"
            homelab_detail = (
                f"{homelab['containers']['unhealthy']} unhealthy containers and "
                f"{homelab['health_checks_down']} failed health checks were reported."
            )
        else:
            affected = (
                homelab["engines_unavailable"]
                + homelab["agents"]["stale"]
                + homelab["agents"]["offline"]
                + homelab["updates_available"]
            )
            homelab_status = "warning" if affected else "good"
            homelab_detail = (
                "Homelab attention is recommended for unavailable engines, inactive agents, or updates."
                if affected
                else "No unhealthy containers, failed checks, unavailable engines, or pending updates were reported."
            )
        checks.append(
            _check(
                "homelab_posture",
                homelab_status,
                "Homelab posture",
                homelab_detail,
                "Review failed checks and unhealthy services before enabling remote actions.",
            )
        )

        if launcher["status"] != "available":
            launcher_status = "warning"
            launcher_detail = "Launcher runner summaries are temporarily unavailable."
        else:
            inactive = launcher["agents"]["stale"] + launcher["agents"]["offline"]
            launcher_status = "warning" if inactive else "good"
            launcher_detail = (
                f"{inactive} launcher runners are stale or offline."
                if inactive
                else "All reported launcher runners are online."
            )
        checks.append(
            _check(
                "launcher_posture",
                launcher_status,
                "Launcher runner posture",
                launcher_detail,
                "Revoke unused runners and investigate runners that remain inactive.",
            )
        )
        return checks

    @staticmethod
    def _grade(checks):
        score = max(0, 100 - sum(CHECK_PENALTIES[item["status"]] for item in checks))
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"
        return score, grade

    def overview(self, owner_key, *, secure_cookie, trust_proxy):
        try:
            workstation = self._workstation_summary(owner_key)
        except Exception:
            workstation = self._unavailable_workstation()
        try:
            homelab = self._homelab_summary(owner_key)
        except Exception:
            homelab = self._unavailable_homelab()
        try:
            launcher = self._launcher_summary(owner_key)
        except Exception:
            launcher = self._unavailable_launcher()

        encryption_configured = bool(
            getattr(self.store, "fernet", None) is not None
            and getattr(self.store, "lookup_key", None)
        )
        checks = self._configuration_checks(
            secure_cookie=bool(secure_cookie),
            trust_proxy=bool(trust_proxy),
            encryption_configured=encryption_configured,
        )
        checks.extend(self._source_checks(workstation, homelab, launcher))
        score, grade = self._grade(checks)
        return {
            "generated_at": _iso_timestamp(self.clock()),
            "score": score,
            "grade": grade,
            "checks": checks,
            "sources": {
                "workstation": workstation,
                "homelab": homelab,
                "launcher": launcher,
            },
        }


__all__ = ["SecurityCenter"]
