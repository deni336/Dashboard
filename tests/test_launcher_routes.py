import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes import launcher_routes as routes_module
from src.routes.launcher_routes import init_launcher_routes, launcher_bp

from tests.test_launcher_runner import catalog, pair_payload, result


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


class LauncherRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_runner = routes_module.runner
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_LAUNCHER_ENABLED": "true",
                "KASUGAI_LAUNCHER_ALLOWED_USERS": "",
                "KASUGAI_LAUNCHER_RUNS_ENABLED": "true",
                "KASUGAI_LAUNCHER_MIN_CATALOG_SECONDS": "0",
                "KASUGAI_LAUNCHER_MIN_CLAIM_SECONDS": "0",
                "KASUGAI_LAUNCHER_MIN_RUN_SECONDS": "0",
            },
        )
        self.environment.start()
        store = PersonalDashboardStore(TemporaryConfig(self.temporary_directory.name))
        init_launcher_routes(dashboard_store=store)
        self.now = 1_800_000_000.0
        routes_module.runner.clock = lambda: self.now
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="launcher-route-tests")
        self.app.register_blueprint(launcher_bp)
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        routes_module.runner = self.previous_runner
        self.environment.stop()
        self.temporary_directory.cleanup()

    def login(self, owner="owner-a", csrf="known-csrf"):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["profile"] = {"id": owner, "email": f"{owner}@example.test"}
            browser_session["csrf_token"] = csrf

    def browser_post(self, url, payload=None, csrf="known-csrf"):
        return self.client.post(
            url,
            json={} if payload is None else payload,
            headers={"X-Kasugai-CSRF": csrf},
        )

    def pair(self):
        pairing = self.browser_post("/api/launcher/pairings")
        self.assertEqual(pairing.status_code, 201)
        self.assertIn("python -m launcher_agent pair", pairing.get_json()["command"])
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        paired = self.client.post(
            "/api/launcher-agent/v1/pair", json=pair_payload(pairing.get_json())
        )
        self.assertEqual(paired.status_code, 201)
        self.login()
        return paired.get_json()

    def agent_post(self, path, credentials, payload, token=None):
        return self.client.post(
            path,
            json=payload,
            headers={"Authorization": f"Bearer {token or credentials['token']}"},
        )

    def publish(self, credentials, confirmation=True):
        return self.agent_post(
            f"/api/launcher-agent/v1/agents/{credentials['agent_id']}/catalog",
            credentials,
            catalog(self.now, confirmation=confirmation),
        )

    def test_browser_session_csrf_json_and_no_store(self):
        self.assertEqual(self.client.post("/api/launcher/pairings", json={}).status_code, 403)
        self.assertEqual(self.browser_post("/api/launcher/pairings", csrf="wrong").status_code, 403)
        form = self.client.post(
            "/api/launcher/pairings", data={}, headers={"X-Kasugai-CSRF": "known-csrf"}
        )
        self.assertEqual(form.status_code, 400)
        response = self.client.get("/api/launcher/catalog")
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.client.get("/api/launcher/catalog").status_code, 401)

    def test_separate_agent_bearer_catalog_and_replay_contract(self):
        credentials = self.pair()
        path = f"/api/launcher-agent/v1/agents/{credentials['agent_id']}/catalog"
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.client.post(path, json=catalog(self.now)).status_code, 401)
        self.assertEqual(
            self.agent_post(path, credentials, catalog(self.now), "workstation-token").status_code,
            401,
        )
        self.assertEqual(self.publish(credentials).status_code, 202)
        self.assertEqual(self.publish(credentials).status_code, 409)

    def test_catalog_owner_scope_confirmation_claim_and_result(self):
        credentials = self.pair()
        self.assertEqual(self.publish(credentials).status_code, 202)
        catalog_response = self.client.get("/api/launcher/catalog")
        self.assertEqual(catalog_response.status_code, 200)
        task = catalog_response.get_json()["tasks"][0]
        preview = self.browser_post(f"/api/launcher/tasks/{task['id']}/runs", {})
        self.assertEqual(preview.status_code, 200)
        confirmation = preview.get_json()["preview"]["confirmation_token"]
        queued = self.browser_post(
            f"/api/launcher/tasks/{task['id']}/runs",
            {"confirmation_token": confirmation},
        )
        self.assertEqual(queued.status_code, 202)
        run_id = queued.get_json()["run"]["id"]

        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        claim = self.agent_post(
            f"/api/launcher-agent/v1/agents/{credentials['agent_id']}/runs/claim",
            credentials,
            {"schema_version": 1},
        )
        self.assertEqual(claim.status_code, 200)
        accepted = self.agent_post(
            f"/api/launcher-agent/v1/agents/{credentials['agent_id']}/runs/{run_id}/result",
            credentials,
            result(self.now, claim.get_json()["claim_token"]),
        )
        self.assertEqual(accepted.status_code, 202)
        self.login()
        listed = self.client.get("/api/launcher/runs")
        self.assertEqual(listed.get_json()["runs"][0]["state"], "succeeded")
        detail = self.client.get(f"/api/launcher/runs/{run_id}")
        self.assertEqual(detail.get_json()["result"]["output"], "12 passed")
        self.login("owner-b")
        self.assertEqual(self.client.get("/api/launcher/catalog").get_json()["tasks"], [])
        self.assertEqual(self.client.get(f"/api/launcher/runs/{run_id}").status_code, 404)

    def test_unknown_fields_compression_and_oversized_bodies_fail(self):
        pairing = self.browser_post("/api/launcher/pairings", {"command": "whoami"})
        self.assertEqual(pairing.status_code, 400)
        compressed = self.client.post(
            "/api/launcher/pairings",
            json={},
            headers={"X-Kasugai-CSRF": "known-csrf", "Content-Encoding": "gzip"},
        )
        self.assertEqual(compressed.status_code, 400)
        oversized = self.client.post(
            "/api/launcher/pairings",
            data=b"{" + b" " * 2048 + b"}",
            content_type="application/json",
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(oversized.status_code, 413)

    def test_rename_and_revoke(self):
        credentials = self.pair()
        renamed = self.client.patch(
            f"/api/launcher/agents/{credentials['agent_id']}",
            json={"display_name": "Build box"},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(renamed.get_json()["display_name"], "Build box")
        revoked = self.client.delete(
            f"/api/launcher/agents/{credentials['agent_id']}",
            json={},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(revoked.status_code, 204)
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.publish(credentials).status_code, 401)

    def test_global_auth_exemptions_are_exact_agent_endpoints(self):
        source = (
            Path(__file__).resolve().parents[1] / "src" / "routes" / "auth_routes.py"
        ).read_text(encoding="utf-8")
        for endpoint in (
            "launcher_bp.pair_launcher_agent",
            "launcher_bp.ingest_launcher_catalog",
            "launcher_bp.claim_launcher_run",
            "launcher_bp.submit_launcher_result",
        ):
            self.assertIn(f"'{endpoint}'", source)
        self.assertNotIn("request.path.startswith('/api/launcher-agent", source)


if __name__ == "__main__":
    unittest.main()
