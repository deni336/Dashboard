import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes import workstation_routes as routes_module
from src.routes.workstation_routes import init_workstation_routes, workstation_bp

from tests.test_workstation_monitor import pair_payload, snapshot


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


class WorkstationRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_monitor = routes_module.monitor
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_WORKSTATION_ENABLED": "true",
                "KASUGAI_WORKSTATION_ALLOWED_USERS": "",
                "KASUGAI_WORKSTATION_MIN_INGEST_SECONDS": "0",
            },
        )
        self.environment.start()
        config = TemporaryConfig(self.temporary_directory.name)
        store = PersonalDashboardStore(config)
        init_workstation_routes(dashboard_store=store)
        self.now = 1_800_000_000.0
        routes_module.monitor.clock = lambda: self.now

        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="workstation-route-tests")
        self.app.register_blueprint(workstation_bp)
        self.client = self.app.test_client()
        self.login("owner-a")

    def tearDown(self):
        routes_module.monitor = self.previous_monitor
        self.environment.stop()
        self.temporary_directory.cleanup()

    def login(self, owner="owner-a", csrf="known-csrf"):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["profile"] = {
                "id": owner,
                "email": f"{owner}@example.test",
            }
            browser_session["csrf_token"] = csrf

    def browser_post(self, url, payload=None, csrf="known-csrf"):
        return self.client.post(
            url,
            json={} if payload is None else payload,
            headers={"X-Kasugai-CSRF": csrf},
        )

    def create_pairing(self):
        response = self.browser_post("/api/workstations/pairings")
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def pair(self):
        pairing = self.create_pairing()
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        response = self.client.post(
            "/api/workstation-agent/v1/pair", json=pair_payload(pairing)
        )
        self.assertEqual(response.status_code, 201)
        self.login("owner-a")
        return response.get_json()

    def ingest(self, credentials, payload, token=None):
        return self.client.post(
            f"/api/workstation-agent/v1/agents/{credentials['agent_id']}/snapshots",
            json=payload,
            headers={"Authorization": f"Bearer {token or credentials['token']}"},
        )

    def test_browser_mutations_require_session_csrf_and_json(self):
        missing_csrf = self.client.post("/api/workstations/pairings", json={})
        wrong_csrf = self.browser_post("/api/workstations/pairings", csrf="wrong")
        form_body = self.client.post(
            "/api/workstations/pairings",
            data={},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )

        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(wrong_csrf.status_code, 403)
        self.assertEqual(form_body.status_code, 400)

        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.client.get("/api/workstations").status_code, 401)

    def test_agent_pair_and_ingest_need_no_browser_session_but_require_bearer(self):
        credentials = self.pair()
        with self.client.session_transaction() as browser_session:
            browser_session.clear()

        no_token = self.client.post(
            f"/api/workstation-agent/v1/agents/{credentials['agent_id']}/snapshots",
            json=snapshot(self.now, 1),
        )
        bad_token = self.ingest(credentials, snapshot(self.now, 1), token="bad")
        accepted = self.ingest(credentials, snapshot(self.now, 1))
        replay = self.ingest(credentials, snapshot(self.now, 1))

        self.assertEqual(no_token.status_code, 401)
        self.assertEqual(bad_token.status_code, 401)
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(accepted.get_json()["sequence"], 1)

    def test_global_license_hook_exempts_only_the_two_agent_endpoint_names(self):
        auth_source = (
            Path(__file__).resolve().parents[1] / "src" / "routes" / "auth_routes.py"
        ).read_text(encoding="utf-8")

        self.assertIn("'workstation_bp.pair_workstation_agent'", auth_source)
        self.assertIn("'workstation_bp.ingest_workstation_snapshot'", auth_source)
        self.assertNotIn("request.path.startswith('/api/workstation-agent", auth_source)

    def test_browser_responses_are_owner_scoped_and_match_widget_shape(self):
        credentials = self.pair()
        self.ingest(credentials, snapshot(self.now, 1))

        listed = self.client.get("/api/workstations")
        latest = self.client.get(
            f"/api/workstations/{credentials['agent_id']}/latest"
        )
        history = self.client.get(
            f"/api/workstations/{credentials['agent_id']}/history?minutes=60&bucket_seconds=60"
        )

        self.assertEqual(listed.status_code, 200)
        workstation = listed.get_json()["workstations"][0]
        self.assertEqual(
            set(workstation),
            {
                "id",
                "display_name",
                "platform",
                "agent_version",
                "capabilities",
                "paired_at",
                "last_seen_at",
                "status",
                "latest_summary",
            },
        )
        self.assertEqual(latest.get_json()["snapshot"]["sequence"], 1)
        self.assertIn("points", history.get_json())
        self.assertEqual(listed.headers["Cache-Control"], "no-store, max-age=0")

        self.login("owner-b")
        self.assertEqual(
            self.client.get("/api/workstations").get_json(), {"workstations": []}
        )
        self.assertEqual(
            self.client.get(
                f"/api/workstations/{credentials['agent_id']}/latest"
            ).status_code,
            404,
        )

    def test_rename_revoke_and_revoked_token(self):
        credentials = self.pair()
        rename = self.client.patch(
            f"/api/workstations/{credentials['agent_id']}",
            json={"display_name": "Main workstation"},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(rename.status_code, 200)
        self.assertEqual(rename.get_json()["display_name"], "Main workstation")

        revoked = self.client.delete(
            f"/api/workstations/{credentials['agent_id']}",
            json={"delete_history": True},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(revoked.status_code, 204)
        self.assertEqual(self.client.get("/api/workstations").get_json(), {"workstations": []})
        self.assertEqual(self.ingest(credentials, snapshot(self.now, 1)).status_code, 401)

    def test_snapshot_size_and_numeric_validation_are_enforced(self):
        credentials = self.pair()
        oversize = self.client.post(
            f"/api/workstation-agent/v1/agents/{credentials['agent_id']}/snapshots",
            data=b"{" + b" " * (64 * 1024),
            content_type="application/json",
            headers={"Authorization": f"Bearer {credentials['token']}"},
        )
        invalid = snapshot(self.now, 1)
        invalid["cpu"]["percent"] = float("nan")
        non_finite = self.ingest(credentials, invalid)

        self.assertEqual(oversize.status_code, 413)
        self.assertEqual(non_finite.status_code, 400)
        self.assertIn("valid JSON", non_finite.get_json()["error"])

    def test_rate_limit_returns_retry_after(self):
        routes_module.monitor.min_ingest_seconds = 1
        credentials = self.pair()
        self.assertEqual(self.ingest(credentials, snapshot(self.now, 1)).status_code, 202)

        response = self.ingest(credentials, snapshot(self.now, 2))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "1")


if __name__ == "__main__":
    unittest.main()
