import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes.ai_toolbox_routes import (
    MAX_MESSAGE_BODY_BYTES,
    ai_toolbox_bp,
    init_ai_toolbox_routes,
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


class FakeCompletion:
    def __init__(self):
        self.calls = []
        self.error = None
        self.output = "Local plain-text answer"

    def complete(self, *, messages, model):
        self.calls.append({"messages": messages, "model": model})
        if self.error:
            raise self.error
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": self.output}}
            ]
        }


class AIToolboxRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_AI_TOOLBOX_ENABLED": "true",
                "KASUGAI_AI_TOOLBOX_ALLOWED_USERS": "",
                "KASUGAI_AI_PROVIDER": "ollama",
                "KASUGAI_AI_BASE_URL": "http://private-ollama:11434/v1",
                "KASUGAI_AI_MODEL": "local-test-model",
                "KASUGAI_AI_API_KEY": "private-api-key",
                "KASUGAI_AI_API_KEY_FILE": "",
            },
        )
        self.environment.start()
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.completion = FakeCompletion()
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(ai_toolbox_bp)
        self.toolbox = init_ai_toolbox_routes(
            dashboard_store=self.store,
            completion_client=self.completion,
            clock=lambda: 1_800_000_000.0,
        )
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def login(self, owner="owner-a", email="owner@example.test", csrf="csrf-token"):
        with self.client.session_transaction() as session:
            session.clear()
            session["profile"] = {"id": owner, "email": email}
            session["csrf_token"] = csrf

    @property
    def csrf(self):
        return {"X-Kasugai-CSRF": "csrf-token"}

    def create(self, **overrides):
        body = {"title": "Route AI chat", "mode": "assistant"}
        body.update(overrides)
        response = self.client.post(
            "/api/ai-toolbox/sessions", json=body, headers=self.csrf
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_lifecycle_response_shapes_and_security_headers(self):
        response = self.client.get("/api/ai-toolbox")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["status"],
            {"configured": True, "provider": "ollama", "model": "local-test-model"},
        )
        self.assertEqual(
            response.get_json()["modes"],
            ["assistant", "explain", "review", "refactor", "tests", "docs", "regex", "sql"],
        )
        self.assertEqual(response.get_json()["sessions"], [])
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

        created = self.create(mode="review")
        self.assertEqual(
            set(created),
            {"id", "title", "mode", "version", "messages", "created_at", "updated_at"},
        )
        listing = self.client.get("/api/ai-toolbox").get_json()
        self.assertEqual(
            set(listing["sessions"][0]),
            {
                "id",
                "title",
                "mode",
                "version",
                "message_count",
                "created_at",
                "updated_at",
            },
        )
        self.assertNotIn("messages", listing["sessions"][0])
        self.assertEqual(
            self.client.get(f"/api/ai-toolbox/sessions/{created['id']}").get_json(),
            created,
        )

        response = self.client.post(
            f"/api/ai-toolbox/sessions/{created['id']}/messages",
            json={"version": 1, "message": "Review this untrusted text"},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 200)
        detail = response.get_json()
        self.assertEqual(detail["version"], 2)
        self.assertEqual(
            [message["role"] for message in detail["messages"]], ["user", "assistant"]
        )
        self.assertEqual([message["role"] for message in self.completion.calls[0]["messages"]], ["system", "user"])
        response = self.client.delete(
            f"/api/ai-toolbox/sessions/{created['id']}",
            json={"version": 2},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 204)

    def test_auth_csrf_allowlist_kill_switch_and_owner_isolation(self):
        created = self.create()
        self.login(owner="", email="")
        self.assertEqual(self.client.get("/api/ai-toolbox").status_code, 401)
        self.login()
        with patch.dict(os.environ, {"KASUGAI_AI_TOOLBOX_ALLOWED_USERS": "other@test"}):
            self.assertEqual(self.client.get("/api/ai-toolbox").status_code, 403)
        with patch.dict(
            os.environ, {"KASUGAI_AI_TOOLBOX_ALLOWED_USERS": "OWNER@EXAMPLE.TEST"}
        ):
            self.assertEqual(self.client.get("/api/ai-toolbox").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/ai-toolbox/sessions", json={"title": "x", "mode": "assistant"}
            ).status_code,
            403,
        )
        with patch.dict(os.environ, {"KASUGAI_AI_TOOLBOX_ENABLED": "false"}):
            self.assertEqual(self.client.get("/api/ai-toolbox").status_code, 404)

        self.login("owner-b", "b@example.test")
        self.assertEqual(
            self.client.get(f"/api/ai-toolbox/sessions/{created['id']}").status_code,
            404,
        )
        response = self.client.post(
            f"/api/ai-toolbox/sessions/{created['id']}/messages",
            json={"version": 1, "message": "steal"},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.completion.calls, [])

    def test_provider_disabled_endpoint_failures_and_conflicts_are_sanitized(self):
        created = self.create()
        with patch.dict(os.environ, {"KASUGAI_AI_PROVIDER": "openai"}):
            status = self.client.get("/api/ai-toolbox").get_json()["status"]
            self.assertFalse(status["configured"])
            response = self.client.post(
                f"/api/ai-toolbox/sessions/{created['id']}/messages",
                json={"version": 1, "message": "hello"},
                headers=self.csrf,
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json(), {"error": "Local AI is unavailable"})

        self.completion.error = RuntimeError(
            "private-api-key at http://private-ollama:11434/v1"
        )
        response = self.client.post(
            f"/api/ai-toolbox/sessions/{created['id']}/messages",
            json={"version": 1, "message": "hello"},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 503)
        body = response.get_data(as_text=True)
        self.assertNotIn("private-api-key", body)
        self.assertNotIn("private-ollama", body)
        self.completion.error = None

        response = self.client.post(
            f"/api/ai-toolbox/sessions/{created['id']}/messages",
            json={"version": 9, "message": "stale"},
            headers=self.csrf,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["current_version"], 1)
        self.assertNotIn("messages", response.get_json())

    def test_strict_query_json_compression_fields_and_body_limits(self):
        created = self.create()
        self.assertEqual(self.client.get("/api/ai-toolbox?q=x").status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/ai-toolbox/sessions/{created['id']}?x=1").status_code,
            400,
        )
        invalid_creates = (
            {},
            {"title": "x", "mode": "shell"},
            {"title": "x", "mode": "assistant", "base_url": "http://evil"},
        )
        for body in invalid_creates:
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.post(
                        "/api/ai-toolbox/sessions", json=body, headers=self.csrf
                    ).status_code,
                    400,
                )
        self.assertEqual(
            self.client.post(
                f"/api/ai-toolbox/sessions/{created['id']}/messages",
                data=b"{}",
                content_type="application/json",
                headers={**self.csrf, "Content-Encoding": "gzip"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/ai-toolbox/sessions/{created['id']}/messages",
                data="plain",
                content_type="text/plain",
                headers=self.csrf,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/ai-toolbox/sessions/{created['id']}/messages",
                data=b"x" * (MAX_MESSAGE_BODY_BYTES + 1),
                content_type="application/json",
                headers=self.csrf,
            ).status_code,
            413,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/ai-toolbox/sessions/{created['id']}", json={}, headers=self.csrf
            ).status_code,
            400,
        )


if __name__ == "__main__":
    unittest.main()
