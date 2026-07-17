import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.automation_engine import (
    AutomationEngine,
    NotFoundError,
    ValidationError,
    validate_action,
    validate_trigger,
)
from src.personal_dashboard import PersonalDashboardStore


class TemporaryConfig:
    def __init__(self, directory):
        self.config_file = str(Path(directory) / "config.ini")
        self.values = {
            ("Database", "dashboarddbpath"): "personal_dashboard.db",
            ("Database", "encryption_key"): Fernet.generate_key().decode("ascii"),
        }

    def get(self, section, option, fallback=None):
        return self.values.get((section, option), fallback)

    def set(self, section, option, value):
        self.values[(section, option)] = str(value)


class FakeLauncher:
    def __init__(self):
        self.queued = []

    def catalog(self, owner_key):
        return {
            "tasks": [
                {
                    "id": "a" * 32,
                    "title": "Safe tests",
                    "agent_name": "Desk runner",
                    "requires_confirmation": False,
                },
                {
                    "id": "b" * 32,
                    "title": "Dangerous cleanup",
                    "agent_name": "Desk runner",
                    "requires_confirmation": True,
                },
            ]
        }

    def queue_run(self, owner_key, task_id, payload):
        self.queued.append((owner_key, task_id, payload))
        return {"queued": True, "run": {"id": "launcher-run"}}


def notify_rule(**overrides):
    value = {
        "name": "CPU warning",
        "enabled": True,
        "trigger": {"type": "interval", "minutes": 1},
        "action": {
            "type": "notify",
            "title": "Workstation needs attention",
            "body": "CPU stayed high.",
            "severity": "warning",
        },
        "cooldown_minutes": 0,
    }
    value.update(overrides)
    return value


class AutomationEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.launcher = FakeLauncher()
        self.engine = AutomationEngine(
            self.store,
            launcher_runner=self.launcher,
            clock=lambda: self.clock[0],
            timezone=UTC,
        )
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_AUTOMATION_ENABLED": "true",
                "KASUGAI_AUTOMATION_TASKS_ENABLED": "true",
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_rules_are_encrypted_and_owner_scoped(self):
        created = self.engine.create_rule("owner-a", notify_rule())
        self.assertEqual(created["name"], "CPU warning")
        self.assertEqual(self.engine.list("owner-b"), {"rules": [], "runs": []})
        with self.assertRaises(NotFoundError):
            self.engine.update_rule("owner-b", created["id"], {"enabled": False})
        with self.assertRaises(NotFoundError):
            self.engine.delete_rule("owner-b", created["id"])

        connection = sqlite3.connect(self.engine.db_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("CPU warning", dump)
        self.assertNotIn("CPU stayed high", dump)
        self.assertNotIn("Workstation needs attention", dump)

    def test_validation_has_no_arbitrary_execution_or_network_surface(self):
        for trigger in (
            {"type": "webhook", "url": "https://example.test"},
            {"type": "interval", "minutes": 0},
            {"type": "daily", "time": "25:00"},
            {"type": "event", "source": "shell", "severity": "error"},
            {
                "type": "metric",
                "metric": "sqlite.query",
                "operator": "gt",
                "threshold": 1,
            },
        ):
            with self.subTest(trigger=trigger), self.assertRaises(ValidationError):
                validate_trigger(trigger)

        for action in (
            {"type": "command", "argv": ["cmd.exe"]},
            {"type": "notify", "title": "x", "body": "", "severity": "root", "url": "/"},
            {"type": "launcher_task", "task_id": "--evil"},
        ):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                validate_action(action)

    def test_interval_claim_is_atomic_and_cooldown_suppresses_runs(self):
        self.engine.create_rule("owner-a", notify_rule(cooldown_minutes=5))
        self.clock[0] += 60
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: self.engine.evaluate_due(), range(2)))
        self.assertEqual(sum(item["triggered"] for item in results), 1)
        self.assertEqual(len(self.engine.list("owner-a")["runs"]), 1)

        self.clock[0] += 60
        self.assertEqual(self.engine.evaluate_due()["triggered"], 0)
        self.clock[0] += 240
        self.assertEqual(self.engine.evaluate_due()["triggered"], 1)
        self.assertEqual(len(self.engine.list("owner-a")["runs"]), 2)

    def test_event_rules_ignore_old_events_and_consume_new_event_once(self):
        timestamp = datetime.fromtimestamp(self.clock[0], UTC).isoformat()
        connection = sqlite3.connect(self.engine.db_path)
        try:
            connection.execute(
                """INSERT INTO dashboard_events
                   (owner_key, source, kind, severity, title, occurred_at, created_at)
                   VALUES ('owner-a','homelab','health','error','Old',?,?)""",
                (timestamp, timestamp),
            )
            connection.commit()
        finally:
            connection.close()
        self.engine.create_rule(
            "owner-a",
            notify_rule(trigger={"type": "event", "source": "homelab", "severity": "error"}),
        )
        self.assertEqual(self.engine.evaluate_due()["triggered"], 0)
        connection = sqlite3.connect(self.engine.db_path)
        try:
            connection.execute(
                """INSERT INTO dashboard_events
                   (owner_key, source, kind, severity, title, occurred_at, created_at)
                   VALUES ('owner-a','homelab','health','error','New',?,?)""",
                (timestamp, timestamp),
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.engine.evaluate_due()["triggered"], 1)
        self.assertEqual(self.engine.evaluate_due()["triggered"], 0)

    def _create_workstation_tables(self):
        connection = sqlite3.connect(self.engine.db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE workstation_agents (
                    agent_id TEXT PRIMARY KEY, owner_key TEXT, revoked_at REAL
                );
                CREATE TABLE workstation_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT, received_at REAL, payload_encrypted TEXT
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _workstation_snapshot(self, percent):
        payload = {
            "cpu": {"percent": percent},
            "memory": {"percent": 40},
            "disks": [{"percent": 50}],
        }
        connection = sqlite3.connect(self.engine.db_path)
        try:
            connection.execute(
                """INSERT OR IGNORE INTO workstation_agents(agent_id, owner_key, revoked_at)
                   VALUES ('agent-a','owner-a',NULL)"""
            )
            connection.execute(
                """INSERT INTO workstation_snapshots(agent_id, received_at, payload_encrypted)
                   VALUES ('agent-a',?,?)""",
                (self.clock[0], self.engine._encrypt(payload)),
            )
            connection.commit()
        finally:
            connection.close()

    def test_metric_trigger_reads_encrypted_latest_data_and_is_edge_triggered(self):
        self._create_workstation_tables()
        self.engine.create_rule(
            "owner-a",
            notify_rule(
                trigger={
                    "type": "metric",
                    "metric": "workstation.cpu_percent",
                    "operator": "gte",
                    "threshold": 80,
                }
            ),
        )
        self._workstation_snapshot(90)
        self.assertEqual(self.engine.evaluate_due()["triggered"], 1)
        self.assertEqual(self.engine.evaluate_due()["triggered"], 0)
        self.clock[0] += 1
        self._workstation_snapshot(50)
        self.assertEqual(self.engine.evaluate_due()["triggered"], 0)
        self.clock[0] += 1
        self._workstation_snapshot(95)
        self.assertEqual(self.engine.evaluate_due()["triggered"], 1)

    def test_catalog_and_launcher_action_exclude_confirming_tasks(self):
        catalog = self.engine.catalog("owner-a")
        self.assertEqual(catalog["launcher_tasks"], [
            {"id": "a" * 32, "title": "Safe tests", "agent_name": "Desk runner"}
        ])
        rule = self.engine.create_rule(
            "owner-a",
            notify_rule(action={"type": "launcher_task", "task_id": "a" * 32}),
        )
        run = self.engine.run_rule("owner-a", rule["id"])
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(self.launcher.queued, [("owner-a", "a" * 32, {})])
        with self.assertRaises(ValidationError):
            self.engine.create_rule(
                "owner-a",
                notify_rule(action={"type": "launcher_task", "task_id": "b" * 32}),
            )

    def test_launcher_kill_switch_fails_safely_and_records_an_event(self):
        rule = self.engine.create_rule(
            "owner-a",
            notify_rule(action={"type": "launcher_task", "task_id": "a" * 32}),
        )
        with patch.dict(os.environ, {"KASUGAI_AUTOMATION_TASKS_ENABLED": "false"}):
            run = self.engine.run_rule("owner-a", rule["id"])
        self.assertEqual(run["status"], "failed")
        self.assertNotIn("disabled", run["summary"].lower())
        connection = sqlite3.connect(self.engine.db_path)
        try:
            event = connection.execute(
                """SELECT source, kind, severity, resource_url FROM dashboard_events
                   WHERE owner_key = 'owner-a' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(event, ("automation", "rule_failure", "error", "#automationModule"))

    def test_daily_next_run_is_calculated_in_injected_timezone(self):
        self.clock[0] = datetime(2027, 1, 15, 8, 0, tzinfo=UTC).timestamp()
        rule = self.engine.create_rule(
            "owner-a", notify_rule(trigger={"type": "daily", "time": "09:30"})
        )
        self.assertEqual(rule["next_run_at"], "2027-01-15T09:30:00Z")


if __name__ == "__main__":
    unittest.main()
