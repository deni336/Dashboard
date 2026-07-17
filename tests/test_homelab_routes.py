import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes import homelab_routes as routes_module
from src.routes.homelab_routes import homelab_bp, init_homelab_routes

from tests.test_homelab_monitor import pair_payload, result_payload, snapshot


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


class HomelabRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_monitor = routes_module.monitor
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_HOMELAB_ENABLED": "true",
                "KASUGAI_HOMELAB_ALLOWED_USERS": "",
                "KASUGAI_HOMELAB_ACTIONS_ENABLED": "true",
                "KASUGAI_HOMELAB_MIN_INGEST_SECONDS": "0",
                "KASUGAI_HOMELAB_MIN_CLAIM_SECONDS": "0",
                "KASUGAI_HOMELAB_MIN_ACTION_SECONDS": "0",
            },
        )
        self.environment.start()
        store = PersonalDashboardStore(TemporaryConfig(self.temporary_directory.name))
        init_homelab_routes(dashboard_store=store)
        self.now = 1_800_000_000.0
        routes_module.monitor.clock = lambda: self.now

        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="homelab-route-tests")
        self.app.register_blueprint(homelab_bp)
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        routes_module.monitor = self.previous_monitor
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
        pairing = self.browser_post("/api/homelab/pairings")
        self.assertEqual(pairing.status_code, 201)
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        paired = self.client.post(
            "/api/homelab-agent/v1/pair", json=pair_payload(pairing.get_json())
        )
        self.assertEqual(paired.status_code, 201)
        self.login()
        return paired.get_json()

    def agent_post(self, path, credentials, payload, *, token=None, raw=None):
        headers = {"Authorization": f"Bearer {token or credentials['token']}"}
        if raw is not None:
            return self.client.post(path, data=raw, content_type="application/json", headers=headers)
        return self.client.post(path, json=payload, headers=headers)

    def ingest(self, credentials, sequence=1):
        return self.agent_post(
            f"/api/homelab-agent/v1/agents/{credentials['agent_id']}/snapshots",
            credentials,
            snapshot(self.now, sequence),
        )

    def test_browser_access_requires_session_csrf_and_json(self):
        self.assertEqual(self.client.post("/api/homelab/pairings", json={}).status_code, 403)
        self.assertEqual(self.browser_post("/api/homelab/pairings", csrf="wrong").status_code, 403)
        form = self.client.post(
            "/api/homelab/pairings",
            data={},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(form.status_code, 400)
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.client.get("/api/homelab/agents").status_code, 401)

    def test_agent_pair_snapshot_claim_and_result_need_only_separate_bearer(self):
        credentials = self.pair()
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        no_token = self.client.post(
            f"/api/homelab-agent/v1/agents/{credentials['agent_id']}/snapshots",
            json=snapshot(self.now),
        )
        bad_token = self.agent_post(
            f"/api/homelab-agent/v1/agents/{credentials['agent_id']}/snapshots",
            credentials,
            snapshot(self.now),
            token="workstation-token-cannot-authenticate",
        )
        accepted = self.ingest(credentials)
        replay = self.ingest(credentials)
        self.assertEqual(no_token.status_code, 401)
        self.assertEqual(bad_token.status_code, 401)
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(replay.status_code, 409)

    def test_browser_list_latest_history_are_owner_scoped_and_no_store(self):
        credentials = self.pair()
        self.ingest(credentials)
        listed = self.client.get("/api/homelab/agents")
        latest = self.client.get(f"/api/homelab/agents/{credentials['agent_id']}/latest")
        history = self.client.get(f"/api/homelab/agents/{credentials['agent_id']}/history?hours=1")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["agents"][0]["latest_summary"]["containers_total"], 1)
        self.assertEqual(latest.get_json()["snapshot"]["stacks"][0]["name"], "immich")
        self.assertEqual(len(history.get_json()["points"]), 1)
        self.assertEqual(listed.headers["Cache-Control"], "no-store, max-age=0")
        self.login("owner-b")
        self.assertEqual(self.client.get("/api/homelab/agents").get_json(), {"agents": []})
        self.assertEqual(
            self.client.get(f"/api/homelab/agents/{credentials['agent_id']}/latest").status_code,
            404,
        )

    def test_restart_preview_confirmation_queue_claim_and_result_contract(self):
        credentials = self.pair()
        self.ingest(credentials)
        action_url = f"/api/homelab/agents/{credentials['agent_id']}/actions"
        request = {"operation": "restart", "resource_key": "resource_key_1234567890"}
        preview = self.browser_post(action_url, request)
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.get_json()["queued"])
        confirmation = preview.get_json()["preview"]["confirmation_token"]
        queued = self.browser_post(action_url, {**request, "confirmation_token": confirmation})
        self.assertEqual(queued.status_code, 202)
        action_id = queued.get_json()["action"]["id"]

        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        claim = self.agent_post(
            f"/api/homelab-agent/v1/agents/{credentials['agent_id']}/actions/claim",
            credentials,
            {"schema_version": 1},
        )
        self.assertEqual(claim.status_code, 200)
        self.assertEqual(claim.get_json()["action_id"], action_id)
        result = result_payload(self.now, claim.get_json()["claim_token"])
        result_url = (
            f"/api/homelab-agent/v1/agents/{credentials['agent_id']}/actions/{action_id}/result"
        )
        accepted = self.agent_post(result_url, credentials, result)
        repeated = self.agent_post(result_url, credentials, result)
        self.assertEqual(accepted.status_code, 202)
        self.assertFalse(accepted.get_json()["idempotent"])
        self.assertTrue(repeated.get_json()["idempotent"])

    def test_read_logs_queues_without_confirmation_and_unknown_operations_fail(self):
        credentials = self.pair()
        self.ingest(credentials)
        url = f"/api/homelab/agents/{credentials['agent_id']}/actions"
        accepted = self.browser_post(
            url, {"operation": "read_logs", "resource_key": "resource_key_1234567890"}
        )
        rejected = self.browser_post(
            url, {"operation": "exec", "resource_key": "resource_key_1234567890"}
        )
        parameters = self.browser_post(
            url,
            {
                "operation": "read_logs",
                "resource_key": "resource_key_1234567890",
                "parameters": {"command": "sh"},
            },
        )
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(parameters.status_code, 400)

    def test_compression_and_body_limits_are_rejected(self):
        credentials = self.pair()
        path = f"/api/homelab-agent/v1/agents/{credentials['agent_id']}/snapshots"
        compressed = self.client.post(
            path,
            data=b"{}",
            content_type="application/json",
            headers={"Authorization": f"Bearer {credentials['token']}", "Content-Encoding": "gzip"},
        )
        oversized = self.agent_post(path, credentials, None, raw=b"{" + b" " * (256 * 1024))
        self.assertEqual(compressed.status_code, 400)
        self.assertEqual(oversized.status_code, 413)

    def test_rename_revoke_and_revoked_agent_token(self):
        credentials = self.pair()
        rename = self.client.patch(
            f"/api/homelab/agents/{credentials['agent_id']}",
            json={"display_name": "NAS"},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(rename.status_code, 200)
        revoked = self.client.delete(
            f"/api/homelab/agents/{credentials['agent_id']}",
            json={"delete_history": True},
            headers={"X-Kasugai-CSRF": "known-csrf"},
        )
        self.assertEqual(revoked.status_code, 204)
        self.assertEqual(self.client.get("/api/homelab/agents").get_json(), {"agents": []})
        self.assertEqual(self.ingest(credentials).status_code, 401)


if __name__ == "__main__":
    unittest.main()
