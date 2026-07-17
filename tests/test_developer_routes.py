import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.routes import developer_routes as routes_module
from src.routes.developer_routes import developer_bp, init_developer_routes


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


def all_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)
    elif isinstance(value, str):
        yield value


class DeveloperRouteSecurityTests(unittest.TestCase):
    def setUp(self):
        self.previous_store = routes_module.store
        self.previous_cockpit = routes_module.cockpit
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_REPOSITORY_ALLOWED_ROOTS": str(self.allowed),
                "KASUGAI_REPOSITORY_ROOTS": "",
                "KASUGAI_DEVELOPER_ALLOWED_USERS": "",
            },
        )
        self.environment.start()
        init_developer_routes(TemporaryConfig(self.root))

        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="developer-route-tests")
        self.app.register_blueprint(developer_bp)
        self.client = self.app.test_client()
        self.login("Owner-A")

    def tearDown(self):
        routes_module.store = self.previous_store
        routes_module.cockpit = self.previous_cockpit
        self.environment.stop()
        self.temporary_directory.cleanup()

    def login(self, owner="Owner-A", csrf="known-csrf-token"):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["profile"] = {
                "id": owner,
                "email": f"{owner.lower()}@example.test",
            }
            browser_session["csrf_token"] = csrf

    def post_root(self, path, label="Workspace", csrf="known-csrf-token"):
        return self.client.post(
            "/api/developer/roots",
            json={"path": str(path), "label": label},
            headers={"X-Kasugai-CSRF": csrf},
        )

    def assert_payload_does_not_contain(self, payload, sensitive_value):
        for value in all_strings(payload):
            self.assertNotIn(str(sensitive_value), value)

    def test_mutations_require_json_and_a_session_bound_csrf_token(self):
        repository_root = self.allowed / "workspace"
        repository_root.mkdir()

        missing = self.client.post(
            "/api/developer/roots",
            json={"path": str(repository_root)},
        )
        wrong = self.post_root(repository_root, csrf="wrong-token")
        form_encoded = self.client.post(
            "/api/developer/roots",
            data={"path": str(repository_root)},
            headers={"X-Kasugai-CSRF": "known-csrf-token"},
        )
        non_object = self.client.post(
            "/api/developer/roots",
            json=[str(repository_root)],
            headers={"X-Kasugai-CSRF": "known-csrf-token"},
        )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(form_encoded.status_code, 415)
        self.assertEqual(non_object.status_code, 400)
        self.assertEqual(self.client.get("/api/developer/roots").get_json(), [])

        accepted = self.post_root(repository_root)
        self.assertEqual(accepted.status_code, 201)

    def test_root_and_overview_payloads_redact_absolute_server_paths(self):
        repository_root = self.allowed / "private" / "workspace"
        repository_root.mkdir(parents=True)
        # An invalid Git directory makes Git produce an error containing a host
        # path; the public response must still use only the generic error.
        (repository_root / ".git").mkdir()

        created = self.post_root(repository_root, label="Private workspace")
        self.assertEqual(created.status_code, 201)
        created_payload = created.get_json()
        self.assertNotIn("path", created_payload)
        self.assert_payload_does_not_contain(created_payload, repository_root)

        listed = self.client.get("/api/developer/roots").get_json()
        self.assertNotIn("path", listed[0])
        self.assert_payload_does_not_contain(listed, repository_root)

        overview_response = self.client.get("/api/developer/overview")
        self.assertEqual(overview_response.status_code, 200)
        overview = overview_response.get_json()
        self.assertNotIn("path", overview["roots"][0])
        self.assert_payload_does_not_contain(overview, repository_root)
        self.assertEqual(
            overview["repositories"][0]["error"],
            "Git could not inspect this repository",
        )

    def test_connector_settings_never_echo_the_encrypted_secret(self):
        token = "github_pat_this-must-never-be-returned"
        with patch.object(
            routes_module.cockpit,
            "_github_request",
            return_value={
                "login": "owner-a",
                "avatar_url": "https://avatars.githubusercontent.com/u/1",
                "html_url": "https://github.com/owner-a",
            },
        ):
            configured = self.client.put(
                "/api/developer/github/settings",
                json={"token": token},
                headers={"X-Kasugai-CSRF": "known-csrf-token"},
            )

        self.assertEqual(configured.status_code, 200)
        self.assert_payload_does_not_contain(configured.get_json(), token)

        response = self.client.get("/api/developer/github/settings")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["metadata"]["login"], "owner-a")
        self.assert_payload_does_not_contain(payload, token)
        self.assertNotIn(token, json.dumps(payload))

    def test_roots_cannot_be_read_or_deleted_by_another_owner(self):
        repository_root = self.allowed / "isolated"
        repository_root.mkdir()
        root_id = self.post_root(repository_root).get_json()["id"]

        self.login("Owner-B")
        self.assertEqual(self.client.get("/api/developer/roots").get_json(), [])
        denied_delete = self.client.delete(
            f"/api/developer/roots/{root_id}",
            json={},
            headers={"X-Kasugai-CSRF": "known-csrf-token"},
        )
        self.assertEqual(denied_delete.status_code, 404)

        self.login("Owner-A")
        self.assertEqual(len(self.client.get("/api/developer/roots").get_json()), 1)

    def test_allowlist_rejects_a_sibling_reached_with_parent_traversal(self):
        sibling = self.root / "allowed-escape"
        sibling.mkdir()
        traversed = self.allowed / ".." / sibling.name

        response = self.post_root(traversed)

        self.assertEqual(response.status_code, 400)
        self.assertIn("outside", response.get_json()["error"])
        self.assertEqual(self.client.get("/api/developer/roots").get_json(), [])

    def test_anonymous_requests_are_rejected(self):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()

        response = self.client.get("/api/developer/overview")

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
