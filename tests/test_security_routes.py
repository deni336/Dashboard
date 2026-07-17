import os
import unittest
from unittest.mock import patch

from flask import Flask

from src.routes import security_routes as routes_module
from src.routes.security_routes import init_security_routes, security_bp
from tests.test_security_center import Agents, Store, Workstations


class SecurityRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_center = routes_module.security_center
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_SECURITY_ENABLED": "true",
                "KASUGAI_SECURITY_ALLOWED_USERS": "",
                "KASUGAI_TRUST_PROXY": "false",
                "KASUGAI_HOMELAB_ACTIONS_ENABLED": "false",
                "KASUGAI_LAUNCHER_RUNS_ENABLED": "false",
                "KASUGAI_AUTOMATION_TASKS_ENABLED": "false",
            },
        )
        self.environment.start()
        self.workstations = Workstations({"workstations": [{"status": "online", "latest_summary": None}]})
        self.homelab = Agents({"agents": [{"status": "online", "latest_summary": None}]})
        self.launcher = Agents({"agents": [{"status": "online"}]})
        initialized = init_security_routes(
            dashboard_store=Store(),
            workstation_monitor=self.workstations,
            homelab_monitor=self.homelab,
            launcher_runner=self.launcher,
            clock=lambda: 1_800_000_000.0,
        )
        self.assertIs(initialized, routes_module.security_center)
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="security-route-tests",
            SESSION_COOKIE_SECURE=True,
        )
        self.app.register_blueprint(security_bp)
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        routes_module.security_center = self.previous_center
        self.environment.stop()

    def login(self, owner="owner-a", email=None):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["profile"] = {
                "id": owner,
                "email": email or f"{owner}@example.test",
            }

    def test_overview_is_owner_scoped_get_only_and_has_strict_shape_headers(self):
        response = self.client.get("/api/security/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.get_json()), {"generated_at", "score", "grade", "checks", "sources"}
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.workstations.owners, ["owner-a"])
        self.assertEqual(self.homelab.owners, ["owner-a"])
        self.assertEqual(self.launcher.owners, ["owner-a"])
        self.assertEqual(self.client.post("/api/security/overview", json={}).status_code, 405)

    def test_authentication_allowlist_feature_flag_and_zero_query_contract(self):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.client.get("/api/security/overview").status_code, 401)

        self.login("owner-a")
        with patch.dict(os.environ, {"KASUGAI_SECURITY_ALLOWED_USERS": "owner-b"}):
            self.assertEqual(self.client.get("/api/security/overview").status_code, 403)
        with patch.dict(
            os.environ,
            {"KASUGAI_SECURITY_ALLOWED_USERS": "OWNER-A@example.test"},
        ):
            self.assertEqual(self.client.get("/api/security/overview").status_code, 200)
        with patch.dict(os.environ, {"KASUGAI_SECURITY_ENABLED": "false"}):
            self.assertEqual(self.client.get("/api/security/overview").status_code, 404)

        self.assertEqual(self.client.get("/api/security/overview?unexpected=1").status_code, 400)
        self.assertEqual(self.client.get("/api/security/overview?unexpected=").status_code, 400)

    def test_route_passes_only_safe_runtime_booleans(self):
        with patch.dict(
            os.environ,
            {
                "KASUGAI_TRUST_PROXY": "true",
                "KASUGAI_HOMELAB_ACTIONS_ENABLED": "true",
            },
        ):
            payload = self.client.get("/api/security/overview").get_json()
        checks = {item["id"]: item for item in payload["checks"]}
        self.assertEqual(checks["secure_cookie"]["status"], "good")
        self.assertEqual(checks["trust_proxy"]["status"], "warning")
        self.assertEqual(checks["homelab_actions"]["status"], "warning")
        self.assertNotIn("KASUGAI_", repr(payload))


if __name__ == "__main__":
    unittest.main()
