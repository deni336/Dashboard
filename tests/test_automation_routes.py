import os
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes.automation_routes import automation_bp, init_automation_routes


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


def rule_payload():
    return {
        "name": "Morning reminder",
        "enabled": True,
        "trigger": {"type": "daily", "time": "09:00"},
        "action": {
            "type": "notify",
            "title": "Good morning",
            "body": "Review the dashboard.",
            "severity": "info",
        },
        "cooldown_minutes": 10,
    }


class AutomationRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        init_automation_routes(
            dashboard_store=store,
            clock=lambda: self.clock[0],
            timezone=UTC,
        )
        self.app.register_blueprint(automation_bp)
        self.client = self.app.test_client()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_AUTOMATION_ENABLED": "true",
                "KASUGAI_AUTOMATION_ALLOWED_USERS": "",
            },
        )
        self.environment.start()
        self.sign_in()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def sign_in(self, *, owner="owner-a", csrf="csrf-token"):
        with self.client.session_transaction() as session:
            session["profile"] = {"id": owner, "email": f"{owner}@example.test"}
            session["csrf_token"] = csrf

    @property
    def headers(self):
        return {"X-Kasugai-CSRF": "csrf-token"}

    def create(self):
        return self.client.post("/api/automations", json=rule_payload(), headers=self.headers)

    def test_contract_create_list_patch_run_and_delete(self):
        created_response = self.create()
        self.assertEqual(created_response.status_code, 201)
        created = created_response.get_json()
        self.assertEqual(
            set(created),
            {
                "id",
                "name",
                "enabled",
                "trigger",
                "action",
                "cooldown_minutes",
                "last_run_at",
                "next_run_at",
                "created_at",
                "updated_at",
            },
        )

        listed = self.client.get("/api/automations")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(set(listed.get_json()), {"rules", "runs"})
        catalog = self.client.get("/api/automations/catalog").get_json()
        self.assertEqual(set(catalog), {"metrics", "launcher_tasks"})
        self.assertEqual(len(catalog["metrics"]), 6)

        patched = self.client.patch(
            f"/api/automations/{created['id']}",
            json={"name": "Updated reminder", "enabled": False},
            headers=self.headers,
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.get_json()["name"], "Updated reminder")

        run = self.client.post(
            f"/api/automations/{created['id']}/run", json={}, headers=self.headers
        )
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.get_json()["status"], "succeeded")

        deleted = self.client.delete(
            f"/api/automations/{created['id']}", headers=self.headers
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/api/automations").get_json()["rules"], [])

    def test_auth_csrf_allowlist_and_kill_switch(self):
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get("/api/automations").status_code, 401)
        self.sign_in()
        self.assertEqual(self.client.post("/api/automations", json=rule_payload()).status_code, 403)
        with patch.dict(os.environ, {"KASUGAI_AUTOMATION_ALLOWED_USERS": "owner-b"}):
            self.assertEqual(self.client.get("/api/automations").status_code, 403)
        with patch.dict(os.environ, {"KASUGAI_AUTOMATION_ENABLED": "false"}):
            self.assertEqual(self.client.get("/api/automations").status_code, 404)

    def test_routes_reject_unknown_fields_and_non_json_run(self):
        malicious = rule_payload()
        malicious["command"] = "shutdown.exe"
        response = self.client.post("/api/automations", json=malicious, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        created = self.create().get_json()
        response = self.client.patch(
            f"/api/automations/{created['id']}",
            json={"url": "https://example.test"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/api/automations/{created['id']}/run",
            data="",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/api/automations/{created['id']}/run",
            json={"argv": ["cmd.exe"]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_owner_cannot_mutate_another_users_rule(self):
        rule_id = self.create().get_json()["id"]
        self.sign_in(owner="owner-b")
        response = self.client.patch(
            f"/api/automations/{rule_id}", json={"enabled": False}, headers=self.headers
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.delete(f"/api/automations/{rule_id}", headers=self.headers)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
