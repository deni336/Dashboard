import os
import unittest
from unittest.mock import patch

from src.security_center import SecurityCenter


class Store:
    fernet = object()
    lookup_key = b"configured-encryption-key"


class Workstations:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.owners = []

    def list_workstations(self, owner_key):
        self.owners.append(owner_key)
        if self.error:
            raise self.error
        return self.payload


class Agents:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.owners = []

    def list_agents(self, owner_key):
        self.owners.append(owner_key)
        if self.error:
            raise self.error
        return self.payload


def workstation_payload():
    return {
        "workstations": [
            {
                "id": "private-workstation-id",
                "display_name": "Private workstation name",
                "status": "online",
                "latest_summary": {
                    "cpu_percent": 95,
                    "memory_percent": 60,
                    "gpu_percent": 91,
                    "disk_percent": 30,
                    "network_received_bps": 125.5,
                    "network_sent_bps": 50,
                    "raw_ip": "192.0.2.5",
                },
            },
            {
                "status": "stale",
                "latest_summary": {
                    "cpu_percent": 20,
                    "memory_percent": 92,
                    "gpu_percent": None,
                    "disk_percent": 96,
                    "network_received_bps": 74.5,
                    "network_sent_bps": 25,
                },
            },
            {"status": "offline", "latest_summary": None},
        ]
    }


def homelab_payload():
    return {
        "agents": [
            {
                "id": "private-homelab-id",
                "display_name": "Private homelab",
                "status": "online",
                "latest_summary": {
                    "engine_available": True,
                    "containers_total": 8,
                    "containers_running": 6,
                    "containers_unhealthy": 1,
                    "health_checks_down": 2,
                    "updates_available": 3,
                    "ports": [22, 443],
                },
            },
            {
                "status": "offline",
                "latest_summary": {
                    "engine_available": False,
                    "containers_total": 0,
                    "containers_running": 0,
                    "containers_unhealthy": 0,
                    "health_checks_down": 0,
                    "updates_available": 0,
                },
            },
        ]
    }


def launcher_payload():
    return {
        "agents": [
            {"id": "private-launcher-id", "display_name": "Private runner", "status": "online"},
            {"status": "stale"},
        ]
    }


class SecurityCenterTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_HOMELAB_ACTIONS_ENABLED": "false",
                "KASUGAI_LAUNCHER_RUNS_ENABLED": "false",
                "KASUGAI_AUTOMATION_TASKS_ENABLED": "false",
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def make_center(self, *, workstations=None, homelab=None, launcher=None, store=None):
        return SecurityCenter(
            store or Store(),
            workstation_monitor=workstations or Workstations(workstation_payload()),
            homelab_monitor=homelab or Agents(homelab_payload()),
            launcher_runner=launcher or Agents(launcher_payload()),
            clock=lambda: 1_800_000_000.0,
        )

    def test_overview_contract_aggregates_only_safe_counts_and_checks(self):
        workstations = Workstations(workstation_payload())
        homelab = Agents(homelab_payload())
        launcher = Agents(launcher_payload())
        overview = self.make_center(
            workstations=workstations, homelab=homelab, launcher=launcher
        ).overview("owner-a", secure_cookie=True, trust_proxy=False)

        self.assertEqual(
            set(overview), {"generated_at", "score", "grade", "checks", "sources"}
        )
        self.assertEqual(
            set(overview["sources"]), {"workstation", "homelab", "launcher"}
        )
        workstation = overview["sources"]["workstation"]
        self.assertEqual(
            workstation["agents"], {"total": 3, "online": 1, "stale": 1, "offline": 1}
        )
        self.assertEqual(workstation["network"], {"received_bps": 200, "sent_bps": 75})
        self.assertEqual(
            workstation["resource_warnings"], {"cpu": 1, "memory": 1, "gpu": 1, "disk": 1}
        )
        self.assertEqual(overview["sources"]["homelab"]["containers"]["total"], 8)
        self.assertEqual(overview["sources"]["homelab"]["health_checks_down"], 2)
        self.assertEqual(
            overview["sources"]["launcher"]["agents"],
            {"total": 2, "online": 1, "stale": 1, "offline": 0},
        )
        self.assertEqual(workstations.owners, ["owner-a"])
        self.assertEqual(homelab.owners, ["owner-a"])
        self.assertEqual(launcher.owners, ["owner-a"])

        self.assertEqual(
            [item["id"] for item in overview["checks"]],
            [
                "secure_cookie",
                "trust_proxy",
                "encryption",
                "homelab_actions",
                "launcher_runs",
                "automation_tasks",
                "workstation_posture",
                "homelab_posture",
                "launcher_posture",
            ],
        )
        for item in overview["checks"]:
            self.assertEqual(
                set(item), {"id", "status", "title", "detail", "recommendation"}
            )
            self.assertIn(item["status"], {"good", "warning", "critical"})

        serialized = repr(overview)
        for forbidden in (
            "Private workstation name",
            "Private homelab",
            "Private runner",
            "192.0.2.5",
            "private-workstation-id",
            "private-homelab-id",
            "private-launcher-id",
            "443",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_all_good_inputs_score_one_hundred_and_grade_a(self):
        center = self.make_center(
            workstations=Workstations(
                {
                    "workstations": [
                        {
                            "status": "online",
                            "latest_summary": {
                                "cpu_percent": 10,
                                "memory_percent": 20,
                                "gpu_percent": 30,
                                "disk_percent": 40,
                                "network_received_bps": 1,
                                "network_sent_bps": 2,
                            },
                        }
                    ]
                }
            ),
            homelab=Agents(
                {
                    "agents": [
                        {
                            "status": "online",
                            "latest_summary": {
                                "engine_available": True,
                                "containers_total": 1,
                                "containers_running": 1,
                                "containers_unhealthy": 0,
                                "health_checks_down": 0,
                                "updates_available": 0,
                            },
                        }
                    ]
                }
            ),
            launcher=Agents({"agents": [{"status": "online"}]}),
        )
        overview = center.overview("owner-a", secure_cookie=True, trust_proxy=False)
        self.assertEqual((overview["score"], overview["grade"]), (100, "A"))

    def test_configuration_booleans_change_checks_without_revealing_values(self):
        class UnencryptedStore:
            fernet = None
            lookup_key = None

        with patch.dict(
            os.environ,
            {
                "KASUGAI_HOMELAB_ACTIONS_ENABLED": "true",
                "KASUGAI_LAUNCHER_RUNS_ENABLED": "true",
                "KASUGAI_AUTOMATION_TASKS_ENABLED": "true",
            },
        ):
            overview = self.make_center(store=UnencryptedStore()).overview(
                "owner-a", secure_cookie=False, trust_proxy=True
            )
        checks = {item["id"]: item for item in overview["checks"]}
        self.assertEqual(checks["secure_cookie"]["status"], "critical")
        self.assertEqual(checks["encryption"]["status"], "critical")
        self.assertEqual(checks["trust_proxy"]["status"], "warning")
        self.assertEqual(checks["homelab_actions"]["status"], "warning")
        self.assertEqual(checks["launcher_runs"]["status"], "warning")
        self.assertEqual(checks["automation_tasks"]["status"], "warning")
        self.assertNotIn("KASUGAI_", repr(overview))

    def test_each_source_failure_is_isolated_and_exception_text_is_hidden(self):
        center = self.make_center(
            workstations=Workstations(error=RuntimeError("secret workstation failure")),
            homelab=Agents(error=RuntimeError("secret homelab failure")),
            launcher=Agents({"agents": [{"status": "online"}]}),
        )
        overview = center.overview("owner-a", secure_cookie=True, trust_proxy=False)
        self.assertEqual(overview["sources"]["workstation"]["status"], "unavailable")
        self.assertEqual(overview["sources"]["homelab"]["status"], "unavailable")
        self.assertEqual(overview["sources"]["launcher"]["status"], "available")
        self.assertNotIn("secret", repr(overview))


if __name__ == "__main__":
    unittest.main()
