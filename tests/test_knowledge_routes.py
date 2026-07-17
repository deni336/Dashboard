import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes.knowledge_routes import (
    MAX_WRITE_BODY_BYTES,
    init_knowledge_routes,
    knowledge_bp,
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
        "kind": "note",
        "title": "Route note",
        "content": "Private route content",
        "language": "markdown",
        "tags": ["Routes"],
        "pinned": False,
    }
    value.update(overrides)
    return value


class KnowledgeRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_KNOWLEDGE_ENABLED": "true",
                "KASUGAI_KNOWLEDGE_ALLOWED_USERS": "",
            },
        )
        self.environment.start()
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(knowledge_bp)
        self.vault = init_knowledge_routes(
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
            session["profile"] = {"id": owner, "email": email}
            session["csrf_token"] = csrf

    @property
    def csrf(self):
        return {"X-Kasugai-CSRF": "csrf-token"}

    def create(self, **overrides):
        response = self.client.post(
            "/api/knowledge", json=payload(**overrides), headers=self.csrf
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_lifecycle_exact_contract_and_security_headers(self):
        created = self.create()
        full_keys = {
            "id",
            "kind",
            "title",
            "preview",
            "language",
            "tags",
            "pinned",
            "version",
            "created_at",
            "updated_at",
            "content",
        }
        self.assertEqual(set(created), full_keys)

        response = self.client.get("/api/knowledge")
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(set(result), {"items", "counts", "tags", "languages"})
        self.assertNotIn("content", result["items"][0])
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(
            set(self.client.get(f"/api/knowledge/{created['id']}").get_json()), full_keys
        )

        response = self.client.patch(
            f"/api/knowledge/{created['id']}",
            json={"version": 1, "title": "Changed", "pinned": True},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["version"], 2)
        duplicate = self.client.post(
            f"/api/knowledge/{created['id']}/duplicate", json={}, headers=self.csrf
        )
        self.assertEqual(duplicate.status_code, 201)
        self.assertNotEqual(duplicate.get_json()["id"], created["id"])
        response = self.client.delete(
            f"/api/knowledge/{created['id']}", json={"version": 2}, headers=self.csrf
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(f"/api/knowledge/{created['id']}").status_code, 404)

    def test_auth_csrf_allowlist_and_kill_switch(self):
        self.login(owner="", email="")
        self.assertEqual(self.client.get("/api/knowledge").status_code, 401)
        self.login()
        with patch.dict(os.environ, {"KASUGAI_KNOWLEDGE_ALLOWED_USERS": "other@example.test"}):
            self.assertEqual(self.client.get("/api/knowledge").status_code, 403)
        with patch.dict(os.environ, {"KASUGAI_KNOWLEDGE_ALLOWED_USERS": "OWNER@EXAMPLE.TEST"}):
            self.assertEqual(self.client.get("/api/knowledge").status_code, 200)
        self.assertEqual(self.client.post("/api/knowledge", json=payload()).status_code, 403)
        with patch.dict(os.environ, {"KASUGAI_KNOWLEDGE_ENABLED": "false"}):
            self.assertEqual(self.client.get("/api/knowledge").status_code, 404)

    def test_filters_and_strict_query_validation(self):
        self.create(title="Pinned Python", content="virtualenv", tags=["Python"], pinned=True)
        self.create(
            kind="snippet",
            title="SQL query",
            content="SELECT 1",
            language="sql",
            tags=["Database"],
        )
        response = self.client.get(
            "/api/knowledge?kind=note&q=VIRTUALENV&tag=python&pinned=true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["title"] for item in response.get_json()["items"]], ["Pinned Python"])
        invalid_urls = (
            "/api/knowledge?unknown=x",
            "/api/knowledge?kind=note&kind=snippet",
            "/api/knowledge?kind=other",
            "/api/knowledge?pinned=1",
            "/api/knowledge?q=" + "x" * 121,
            "/api/knowledge?tag=" + "x" * 33,
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 400)
        item_id = self.client.get("/api/knowledge").get_json()["items"][0]["id"]
        self.assertEqual(self.client.get(f"/api/knowledge/{item_id}?q=x").status_code, 400)

    def test_owner_conflict_body_hardening_and_corrupt_storage(self):
        created = self.create()
        stale = self.client.patch(
            f"/api/knowledge/{created['id']}",
            json={"version": 99, "title": "Do not disclose me"},
            headers=self.csrf,
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["current_version"], 1)
        self.assertNotIn("content", stale.get_json())
        self.assertNotIn("title", stale.get_json())

        self.login("owner-b", "b@example.test")
        self.assertEqual(self.client.get(f"/api/knowledge/{created['id']}").status_code, 404)
        self.assertEqual(
            self.client.patch(
                f"/api/knowledge/{created['id']}",
                json={"version": 1, "title": "x"},
                headers=self.csrf,
            ).status_code,
            404,
        )
        self.login()

        self.assertEqual(
            self.client.post(
                "/api/knowledge",
                data=b"{}",
                content_type="application/json",
                headers={**self.csrf, "Content-Encoding": "gzip"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/knowledge", data="not json", content_type="text/plain", headers=self.csrf
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/knowledge",
                data=b"x" * (MAX_WRITE_BODY_BYTES + 1),
                content_type="application/json",
                headers=self.csrf,
            ).status_code,
            413,
        )
        self.assertEqual(
            self.client.post(
                f"/api/knowledge/{created['id']}/duplicate",
                json={"unexpected": True},
                headers=self.csrf,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/knowledge/{created['id']}", json={}, headers=self.csrf
            ).status_code,
            400,
        )

        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute(
                "UPDATE knowledge_items SET payload_encrypted = 'corrupt' WHERE item_id = ?",
                (created["id"],),
            )
            connection.commit()
        finally:
            connection.close()
        response = self.client.get("/api/knowledge")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "Knowledge data is unavailable"})


if __name__ == "__main__":
    unittest.main()
