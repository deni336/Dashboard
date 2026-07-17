import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes.personal_hub_routes import (
    MAX_WRITE_BODY_BYTES,
    init_personal_hub_routes,
    personal_hub_bp,
)


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


def payload(**overrides):
    value = {
        "kind": "reminder",
        "title": "Route reminder",
        "note": "Private route note",
        "due_at": "2027-02-01T13:30:00Z",
        "completed": False,
    }
    value.update(overrides)
    return value


class PersonalHubRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_PERSONAL_HUB_ENABLED": "true",
                "KASUGAI_PERSONAL_HUB_ALLOWED_USERS": "",
            },
        )
        self.environment.start()
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(personal_hub_bp)
        self.hub = init_personal_hub_routes(
            dashboard_store=self.store,
            clock=lambda: 1_800_000_000.0,
        )
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def login(self, owner="owner-a", email="owner@example.test", *, csrf="csrf-token"):
        with self.client.session_transaction() as session:
            session.clear()
            if owner or email:
                session["profile"] = {"id": owner, "email": email}
            session["csrf_token"] = csrf

    @property
    def csrf(self):
        return {"X-Kasugai-CSRF": "csrf-token"}

    def create(self, **overrides):
        response = self.client.post(
            "/api/personal-hub/items", json=payload(**overrides), headers=self.csrf
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_lifecycle_exact_contract_and_security_headers(self):
        created = self.create()
        full_keys = {
            "id",
            "kind",
            "title",
            "note",
            "due_at",
            "completed",
            "version",
            "created_at",
            "updated_at",
        }
        self.assertEqual(set(created), full_keys)

        response = self.client.get("/api/personal-hub")
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(set(result), {"generated_at", "counts", "items"})
        self.assertEqual(set(result["items"][0]), full_keys - {"note"})
        self.assertEqual(
            result["counts"],
            {
                "total": 1,
                "reminders": 1,
                "countdowns": 0,
                "habits": 0,
                "bookmarks": 0,
            },
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        detail = self.client.get(f"/api/personal-hub/items/{created['id']}")
        self.assertEqual(set(detail.get_json()), full_keys)

        updated = self.client.patch(
            f"/api/personal-hub/items/{created['id']}",
            json={"version": 1, "completed": True},
            headers=self.csrf,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["version"], 2)
        response = self.client.delete(
            f"/api/personal-hub/items/{created['id']}",
            json={"version": 2},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.client.get(f"/api/personal-hub/items/{created['id']}").status_code,
            404,
        )

    def test_auth_csrf_allowlist_kill_switch_and_owner_isolation(self):
        created = self.create()
        self.login(owner="", email="")
        self.assertEqual(self.client.get("/api/personal-hub").status_code, 401)
        self.login()
        with patch.dict(
            os.environ,
            {"KASUGAI_PERSONAL_HUB_ALLOWED_USERS": "other@example.test"},
        ):
            self.assertEqual(self.client.get("/api/personal-hub").status_code, 403)
        with patch.dict(
            os.environ,
            {"KASUGAI_PERSONAL_HUB_ALLOWED_USERS": "OWNER@EXAMPLE.TEST"},
        ):
            self.assertEqual(self.client.get("/api/personal-hub").status_code, 200)
        self.assertEqual(
            self.client.post("/api/personal-hub/items", json=payload()).status_code,
            403,
        )
        with patch.dict(os.environ, {"KASUGAI_PERSONAL_HUB_ENABLED": "false"}):
            self.assertEqual(self.client.get("/api/personal-hub").status_code, 404)

        self.login("owner-b", "b@example.test")
        self.assertEqual(
            self.client.get(f"/api/personal-hub/items/{created['id']}").status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/personal-hub").get_json()["items"], [])

    def test_conflict_checkin_and_strict_request_boundaries(self):
        created = self.create()
        stale = self.client.patch(
            f"/api/personal-hub/items/{created['id']}",
            json={"version": 99, "title": "Do not disclose me"},
            headers=self.csrf,
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["current_version"], 1)
        self.assertNotIn("title", stale.get_json())
        self.assertEqual(self.client.get("/api/personal-hub?kind=habit").status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/personal-hub/items/{created['id']}?x=1").status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/personal-hub/items",
                data=b"{}",
                content_type="application/json",
                headers={**self.csrf, "Content-Encoding": "gzip"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/personal-hub/items",
                data="not json",
                content_type="text/plain",
                headers=self.csrf,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/personal-hub/items",
                data=b"x" * (MAX_WRITE_BODY_BYTES + 1),
                content_type="application/json",
                headers=self.csrf,
            ).status_code,
            413,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/personal-hub/items/{created['id']}",
                json={"version": 1, "extra": True},
                headers=self.csrf,
            ).status_code,
            400,
        )

        habit_response = self.client.post(
            "/api/personal-hub/items",
            json={
                "kind": "habit",
                "title": "Daily test",
                "note": "",
                "cadence": "daily",
                "checkins": [],
            },
            headers=self.csrf,
        )
        habit_item = habit_response.get_json()
        response = self.client.post(
            f"/api/personal-hub/items/{habit_item['id']}/check-in",
            json={"version": 1, "date": "2027-01-15"},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["checkins"], ["2027-01-15"])
        self.assertEqual(
            self.client.post(
                f"/api/personal-hub/items/{habit_item['id']}/check-in",
                json={"version": 2, "date": "2027-02-01"},
                headers=self.csrf,
            ).status_code,
            400,
        )

    def test_corrupt_storage_is_generic_and_bookmark_is_passive(self):
        created = self.create()
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute(
                "UPDATE personal_hub_items SET payload_encrypted = 'corrupt' WHERE item_id = ?",
                (created["id"],),
            )
            connection.commit()
        finally:
            connection.close()
        response = self.client.get("/api/personal-hub")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "Personal Hub data is unavailable"})

        source = (Path(__file__).parents[1] / "src" / "personal_hub.py").read_text(
            encoding="utf-8"
        )
        route_source = (
            Path(__file__).parents[1] / "src" / "routes" / "personal_hub_routes.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("urlopen(", "requests.", "webbrowser.", "subprocess."):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, route_source)


if __name__ == "__main__":
    unittest.main()
