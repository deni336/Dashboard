import os
import re
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask

from src.personal_dashboard import PersonalDashboardStore
from src.routes import inbox_routes as routes_module
from src.routes.inbox_routes import inbox_bp, init_inbox_routes


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


class FakeDeveloperCockpit:
    def __init__(self):
        self.owners = []
        self.fail = False

    def github_notifications(self, owner_key):
        self.owners.append(owner_key)
        if self.fail:
            raise RuntimeError("connector secret must not escape")
        return {"configured": False, "notifications": []}


class InboxRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_inbox = routes_module.inbox
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_INBOX_ENABLED": "true",
                "KASUGAI_INBOX_ALLOWED_USERS": "",
            },
        )
        self.environment.start()
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.developer = FakeDeveloperCockpit()
        self.now = 1_800_000_000.0
        init_inbox_routes(
            dashboard_store=self.store,
            developer_cockpit=self.developer,
            clock=lambda: self.now,
        )
        self._event("owner-a", "developer", "event", "Owner A activity")
        self._event(
            "owner-a", "automation", "rule_failure", "Owner A rule failed", "error"
        )
        self._event("owner-b", "system", "event", "Owner B activity")

        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="inbox-route-tests")
        self.app.register_blueprint(inbox_bp)
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        routes_module.inbox = self.previous_inbox
        self.environment.stop()
        self.directory.cleanup()

    def _event(self, owner, source, kind, title, severity="info"):
        timestamp = datetime.fromtimestamp(self.now, UTC).isoformat()
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO dashboard_events
                   (owner_key, source, kind, severity, title, body, resource_url,
                    occurred_at, created_at)
                   VALUES (?, ?, ?, ?, ?, 'Safe event body', '', ?, ?)""",
                (owner, source, kind, severity, title, timestamp, timestamp),
            )

    def login(self, owner="owner-a", csrf="known-csrf"):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["profile"] = {
                "id": owner,
                "email": f"{owner}@example.test",
            }
            browser_session["csrf_token"] = csrf

    @property
    def headers(self):
        return {"X-Kasugai-CSRF": "known-csrf"}

    def items(self, query=""):
        response = self.client.get(f"/api/inbox{query}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["items"]

    def test_get_contract_filters_query_validation_and_security_headers(self):
        response = self.client.get("/api/inbox")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            set(payload),
            {
                "items",
                "counts",
                "sources",
                "refreshed_at",
                "connector_errors",
            },
        )
        self.assertEqual(set(payload["counts"]), {"unread", "total", "pinned"})
        self.assertEqual(payload["counts"], {"unread": 2, "total": 2, "pinned": 0})
        self.assertEqual(
            [source["id"] for source in payload["sources"]],
            [
                "github",
                "developer",
                "workstation",
                "homelab",
                "launcher",
                "automation",
                "system",
            ],
        )
        self.assertTrue(
            all(set(source) == {"id", "label", "count"} for source in payload["sources"])
        )
        self.assertEqual(payload["connector_errors"], [])
        self.assertEqual(len(payload["items"]), 2)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{32}", item["id"]) for item in payload["items"]))
        self.assertTrue(
            all(
                set(item)
                == {
                    "id",
                    "source",
                    "kind",
                    "severity",
                    "title",
                    "body",
                    "url",
                    "occurred_at",
                    "state",
                    "pinned",
                    "snoozed_until",
                    "live",
                }
                for item in payload["items"]
            )
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

        developer = self.client.get("/api/inbox?source=developer&state=unread")
        self.assertEqual([item["source"] for item in developer.get_json()["items"]], ["developer"])
        self.assertEqual(self.client.get("/api/inbox?limit=1").status_code, 400)
        self.assertEqual(
            self.client.get("/api/inbox?state=active&state=all").status_code, 400
        )
        self.assertEqual(self.client.get("/api/inbox?source=github&source=system").status_code, 400)
        self.assertEqual(self.client.get("/api/inbox?state=pending").status_code, 400)
        self.assertEqual(self.client.get("/api/inbox?source=email").status_code, 400)

    def test_auth_owner_isolation_csrf_allowlist_and_kill_switch(self):
        owner_a_id = self.items()[0]["id"]
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.client.get("/api/inbox").status_code, 401)

        self.login()
        self.assertEqual(
            self.client.patch(f"/api/inbox/{owner_a_id}", json={"state": "read"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/inbox/{owner_a_id}",
                json={"state": "read"},
                headers={"X-Kasugai-CSRF": "wrong"},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.post("/api/inbox/mark-all-read", json={}).status_code, 403)

        with patch.dict(os.environ, {"KASUGAI_INBOX_ALLOWED_USERS": "owner-b"}):
            self.assertEqual(self.client.get("/api/inbox").status_code, 403)
        with patch.dict(
            os.environ, {"KASUGAI_INBOX_ALLOWED_USERS": "owner-a@example.test"}
        ):
            self.assertEqual(self.client.get("/api/inbox").status_code, 200)
        with patch.dict(os.environ, {"KASUGAI_INBOX_ENABLED": "false"}):
            self.assertEqual(self.client.get("/api/inbox").status_code, 404)

        self.login("owner-b")
        owner_b_items = self.items()
        self.assertEqual([item["title"] for item in owner_b_items], ["Owner B activity"])
        self.assertEqual(
            self.client.patch(
                f"/api/inbox/{owner_a_id}",
                json={"state": "read"},
                headers=self.headers,
            ).status_code,
            404,
        )

    def test_patch_snooze_pin_and_source_scoped_mark_all_read(self):
        by_source = {item["source"]: item for item in self.items()}
        developer_id = by_source["developer"]["id"]
        automation_id = by_source["automation"]["id"]

        patched = self.client.patch(
            f"/api/inbox/{developer_id}",
            json={"state": "read", "pinned": True},
            headers=self.headers,
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(
            patched.get_json(),
            {
                "id": developer_id,
                "state": "read",
                "pinned": True,
                "snoozed_until": None,
            },
        )

        future = datetime.fromtimestamp(self.now + 3600, UTC).isoformat().replace(
            "+00:00", "Z"
        )
        snoozed = self.client.patch(
            f"/api/inbox/{automation_id}",
            json={"snoozed_until": future},
            headers=self.headers,
        )
        self.assertEqual(snoozed.status_code, 200)
        self.assertEqual(snoozed.get_json()["state"], "snoozed")
        self.assertEqual(
            [item["id"] for item in self.items("?state=snoozed")], [automation_id]
        )

        marked = self.client.post(
            "/api/inbox/mark-all-read",
            json={"source": "automation"},
            headers=self.headers,
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.get_json(), {"updated": 1})
        cleared = self.client.patch(
            f"/api/inbox/{automation_id}",
            json={"snoozed_until": None},
            headers=self.headers,
        )
        self.assertEqual(cleared.get_json()["state"], "read")
        self.assertEqual(len(self.items("?state=read")), 2)

    def test_mutation_body_validation_compression_and_limits(self):
        item_id = self.items()[0]["id"]
        endpoint = f"/api/inbox/{item_id}"
        self.assertEqual(
            self.client.patch(endpoint, json={}, headers=self.headers).status_code, 400
        )
        self.assertEqual(
            self.client.patch(
                endpoint, json={"command": "shutdown"}, headers=self.headers
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                endpoint,
                json={"state": "read"},
                headers={**self.headers, "Content-Encoding": "gzip"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(endpoint, data="state=read", headers=self.headers).status_code,
            400,
        )
        oversized_patch = self.client.patch(
            endpoint,
            data=b"{" + b" " * 5000 + b"}",
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(oversized_patch.status_code, 413)

        self.assertEqual(
            self.client.post(
                "/api/inbox/mark-all-read",
                json={"unexpected": True},
                headers=self.headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/inbox/mark-all-read",
                json={"source": None},
                headers=self.headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/inbox/mark-all-read",
                data="source=system",
                headers=self.headers,
            ).status_code,
            400,
        )
        oversized_mark = self.client.post(
            "/api/inbox/mark-all-read",
            data=b"{" + b" " * 1500 + b"}",
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(oversized_mark.status_code, 413)

    def test_connector_failure_remains_http_200_and_is_sanitized(self):
        self.developer.fail = True
        response = self.client.get("/api/inbox")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["connector_errors"],
            [
                {
                    "source": "github",
                    "message": "GitHub notifications are temporarily unavailable.",
                }
            ],
        )
        self.assertNotIn("connector secret", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
