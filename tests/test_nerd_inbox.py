import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet

from src.homelab_monitor import HomelabMonitor
from src.launcher_runner import LauncherRunner
from src.nerd_inbox import (
    MAX_PUBLIC_ITEMS,
    NerdInbox,
    NotFoundError,
    ValidationError,
    validate_public_url,
)
from src.personal_dashboard import PersonalDashboardStore


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


def iso_timestamp(epoch):
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


class FakeDeveloper:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.account_id = "github-account-42"

    def github_notifications(self, owner_key):
        self.calls.append(owner_key)
        if self.fail:
            raise RuntimeError("connector secret must not escape")
        return {
            "configured": True,
            "account": {"account_id": self.account_id, "login": "octocat"},
            "notifications": [
                {
                    "id": "private-thread-123",
                    "reason": "review_requested",
                    "unread": True,
                    "updated_at": "2027-01-15T08:00:00Z",
                    "repository": "octocat/private-repo",
                    "repository_url": "https://github.com/octocat/private-repo",
                    "title": "Please review this change",
                    "type": "PullRequest",
                },
                {
                    "id": "already-read",
                    "reason": "subscribed",
                    "unread": False,
                    "updated_at": "2027-01-15T07:00:00Z",
                    "repository": "octocat/ignored",
                    "repository_url": "https://github.com/octocat/ignored",
                    "title": "Ignored provider notification",
                    "type": "Issue",
                },
            ],
        }


class FakeWorkstations:
    def list_workstations(self, owner_key):
        if owner_key != "owner-a":
            return {"workstations": []}
        return {
            "workstations": [
                {
                    "id": "private-workstation-id",
                    "display_name": "Main Rig",
                    "status": "stale",
                    "paired_at": "2027-01-15T07:00:00Z",
                    "last_seen_at": "2027-01-15T07:59:00Z",
                },
                "malformed-item",
            ]
        }


class FakeHomelab:
    def __init__(self):
        self.fail_one = False

    def list_agents(self, owner_key):
        if owner_key != "owner-a":
            return {"agents": []}
        agents = [
            {
                "id": "private-homelab-id",
                "display_name": "Rack Agent",
                "status": "online",
                "paired_at": "2027-01-15T07:00:00Z",
                "last_seen_at": "2027-01-15T08:00:00Z",
            }
        ]
        if self.fail_one:
            agents.append(
                {
                    "id": "broken-agent-id",
                    "display_name": "Broken Agent",
                    "status": "offline",
                    "paired_at": "2027-01-15T06:00:00Z",
                    "last_seen_at": None,
                }
            )
        return {"agents": agents}

    def latest(self, owner_key, agent_id):
        if agent_id == "broken-agent-id":
            raise RuntimeError("one damaged encrypted row")
        return {
            "snapshot": {
                "captured_at": "2027-01-15T08:00:00Z",
                "containers": [
                    "malformed-container",
                    {
                        "key": "private-container-key",
                        "name": "Reverse proxy",
                        "image": "private.registry/proxy:latest",
                        "health": "unhealthy",
                        "image_update": {
                            "status": "available",
                            "checked_at": "2027-01-15T08:00:00Z",
                        },
                    },
                ],
                "health_checks": [
                    None,
                    {
                        "key": "private-check-key",
                        "name": "Source forge",
                        "status": "down",
                        "checked_at": "2027-01-15T08:00:00Z",
                    },
                ],
            }
        }


class FakeLauncher:
    def list_agents(self, owner_key):
        if owner_key != "owner-a":
            return {"agents": []}
        return {
            "agents": [
                {
                    "id": "private-launcher-id",
                    "display_name": "Task Runner",
                    "status": "offline",
                    "paired_at": "2027-01-15T07:00:00Z",
                    "last_seen_at": None,
                }
            ]
        }


class NerdInboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.developer = FakeDeveloper()
        self.workstations = FakeWorkstations()
        self.homelab = FakeHomelab()
        self.launcher = FakeLauncher()
        self.inbox = NerdInbox(
            self.store,
            developer_cockpit=self.developer,
            workstation_monitor=self.workstations,
            homelab_monitor=self.homelab,
            launcher_runner=self.launcher,
            clock=lambda: self.clock[0],
        )

    def tearDown(self):
        self.directory.cleanup()

    def event(
        self,
        source,
        kind="event",
        *,
        owner="owner-a",
        severity="info",
        title="Dashboard event",
        body="",
        url="https://attacker.invalid/relay-me",
        occurred_at="2027-01-15T08:00:00Z",
    ):
        connection = sqlite3.connect(self.store.db_path)
        try:
            cursor = connection.execute(
                """INSERT INTO dashboard_events
                       (owner_key, source, kind, severity, title, body,
                        resource_url, dedupe_key, occurred_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
                (
                    owner,
                    source,
                    kind,
                    severity,
                    title,
                    body,
                    url,
                    occurred_at,
                    occurred_at,
                ),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def state_count(self, owner=None):
        connection = sqlite3.connect(self.store.db_path)
        try:
            if owner is None:
                return connection.execute("SELECT COUNT(*) FROM inbox_states").fetchone()[0]
            return connection.execute(
                "SELECT COUNT(*) FROM inbox_states WHERE owner_key = ?", (owner,)
            ).fetchone()[0]
        finally:
            connection.close()

    def test_aggregation_contract_safe_destinations_and_body_bounds(self):
        raw_event_id = self.event(
            "developer", body="x" * 1500, url="#attackerControlledFragment"
        )
        self.event("launcher", "task_run")
        self.event("automation", "rule_failure", severity="error")
        self.event("homelab")
        self.event("github", url="https://github.com/evil/repository")
        self.event("unknown-source")

        result = self.inbox.get("owner-a", state="all")

        self.assertEqual(
            set(result),
            {"items", "counts", "sources", "refreshed_at", "connector_errors"},
        )
        self.assertEqual(result["connector_errors"], [])
        self.assertEqual(
            [source["id"] for source in result["sources"]],
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
        expected_keys = {
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
        self.assertTrue(result["items"])
        self.assertTrue(all(set(item) == expected_keys for item in result["items"]))
        self.assertTrue(all(len(item["id"]) == 32 for item in result["items"]))
        self.assertTrue(all(set(item["id"]) <= set("0123456789abcdef") for item in result["items"]))

        developer_event = next(
            item
            for item in result["items"]
            if item["source"] == "developer" and item["live"] is False
        )
        self.assertEqual(developer_event["url"], "#developerCockpit")
        self.assertEqual(len(developer_event["body"]), 1000)
        self.assertNotEqual(developer_event["id"], str(raw_event_id))
        self.assertEqual(
            next(item for item in result["items"] if item["source"] == "homelab" and not item["live"])["url"],
            "#homelabDashboard",
        )
        self.assertEqual(
            next(item for item in result["items"] if item["source"] == "github" and not item["live"])["url"],
            "",
        )
        self.assertEqual(
            next(item for item in result["items"] if item["source"] == "system")["url"],
            "",
        )
        self.assertIn("task_run", {item["kind"] for item in result["items"]})
        self.assertIn("rule_failure", {item["kind"] for item in result["items"]})
        self.assertIn("container_unhealthy", {item["kind"] for item in result["items"]})
        self.assertIn("health_check_down", {item["kind"] for item in result["items"]})
        self.assertIn("image_update", {item["kind"] for item in result["items"]})

        serialized = json.dumps(result)
        self.assertNotIn("private-thread-123", serialized)
        self.assertNotIn("private-workstation-id", serialized)
        self.assertNotIn("private-homelab-id", serialized)
        self.assertNotIn("private-container-key", serialized)
        self.assertNotIn("private-check-key", serialized)
        self.assertNotIn("private-launcher-id", serialized)

    def test_get_is_read_only_and_github_is_cached_per_owner(self):
        self.event("developer")
        self.assertEqual(self.state_count(), 0)
        first = self.inbox.get("owner-a", state="all")
        second = self.inbox.get("owner-a", state="all")
        self.assertEqual(self.state_count(), 0)
        self.assertEqual(self.developer.calls, ["owner-a"])
        self.assertEqual(first["items"], second["items"])

        self.inbox.get("owner-b", state="all")
        self.assertEqual(self.developer.calls, ["owner-a", "owner-b"])
        self.clock[0] += 46
        self.inbox.get("owner-a", state="all")
        self.assertEqual(self.developer.calls, ["owner-a", "owner-b", "owner-a"])

    def test_owner_isolation_and_account_identity_change_public_ids(self):
        owner_a = next(
            item for item in self.inbox.get("owner-a", state="all")["items"] if item["source"] == "github"
        )
        owner_b = next(
            item for item in self.inbox.get("owner-b", state="all")["items"] if item["source"] == "github"
        )
        self.assertNotEqual(owner_a["id"], owner_b["id"])
        with self.assertRaises(NotFoundError):
            self.inbox.patch_state("owner-b", owner_a["id"], {"state": "read"})

        self.developer.account_id = "replacement-account"
        self.clock[0] += 46
        replacement = next(
            item for item in self.inbox.get("owner-a", state="all")["items"] if item["source"] == "github"
        )
        self.assertNotEqual(owner_a["id"], replacement["id"])

    def test_local_state_pin_snooze_and_filters(self):
        self.event("developer")
        item = next(
            item
            for item in self.inbox.get("owner-a", state="active")["items"]
            if item["source"] == "developer"
        )
        updated = self.inbox.patch_state(
            "owner-a", item["id"], {"state": "read", "pinned": True}
        )
        self.assertEqual(updated["state"], "read")
        self.assertTrue(updated["pinned"])
        self.assertIn(item["id"], {entry["id"] for entry in self.inbox.get("owner-a", state="read")["items"]})

        future = iso_timestamp(self.clock[0] + 3600)
        updated = self.inbox.patch_state(
            "owner-a", item["id"], {"state": "unread", "snoozed_until": future}
        )
        self.assertEqual(updated["state"], "snoozed")
        self.assertNotIn(item["id"], {entry["id"] for entry in self.inbox.get("owner-a", state="active")["items"]})
        self.assertIn(item["id"], {entry["id"] for entry in self.inbox.get("owner-a", state="snoozed")["items"]})

        updated = self.inbox.patch_state(
            "owner-a", item["id"], {"state": "archived", "snoozed_until": None}
        )
        self.assertEqual(updated["state"], "archived")
        self.assertIn(item["id"], {entry["id"] for entry in self.inbox.get("owner-a", state="archived")["items"]})

    def test_mark_all_read_is_source_scoped_and_upserts_unseen_items(self):
        self.event("developer")
        self.event("automation")
        result = self.inbox.mark_all_read("owner-a", source="developer")
        self.assertEqual(result, {"updated": 1})
        self.assertEqual(self.state_count("owner-a"), 1)
        developer_items = self.inbox.get("owner-a", state="all", source="developer")["items"]
        automation_items = self.inbox.get("owner-a", state="all", source="automation")["items"]
        self.assertTrue(developer_items and all(item["state"] == "read" for item in developer_items))
        self.assertTrue(automation_items and all(item["state"] == "unread" for item in automation_items))

    def test_source_failure_and_per_agent_failure_are_isolated(self):
        self.event("automation", "rule_failure")
        self.developer.fail = True
        self.homelab.fail_one = True
        result = self.inbox.get("owner-a", state="all")
        self.assertIn("automation", {item["source"] for item in result["items"]})
        self.assertIn("homelab", {item["source"] for item in result["items"]})
        self.assertIn("workstation", {item["source"] for item in result["items"]})
        self.assertEqual(
            result["connector_errors"],
            [
                {
                    "source": "homelab",
                    "message": "Homelab status is temporarily unavailable.",
                },
                {
                    "source": "github",
                    "message": "GitHub notifications are temporarily unavailable.",
                },
            ],
        )

    def test_real_homelab_corrupt_payload_preserves_other_agents(self):
        monitor = HomelabMonitor(self.store, clock=lambda: self.clock[0])
        valid_snapshot = monitor._encrypt_payload(  # noqa: SLF001
            {
                "captured_at": iso_timestamp(self.clock[0]),
                "containers": [
                    {
                        "key": "good-resource-key",
                        "name": "Healthy source row",
                        "health": "unhealthy",
                        "image_update": {"status": "current", "checked_at": None},
                    }
                ],
                "health_checks": [],
            }
        )
        connection = sqlite3.connect(self.store.db_path)
        try:
            values = (
                "owner-a",
                "token-hash",
                "linux",
                "1.0.0",
                "[]",
                self.clock[0] - 100,
                self.clock[0] - 1000,
            )
            connection.execute(
                """INSERT INTO homelab_agents
                       (agent_id, owner_key, token_hash, display_name, platform,
                        agent_version, capabilities_json, paired_at, last_seen_at,
                        latest_payload_encrypted)
                   VALUES ('good-agent', ?, ? || '-good', 'Good agent', ?, ?, ?, ?, ?, ?)""",
                (*values, valid_snapshot),
            )
            connection.execute(
                """INSERT INTO homelab_agents
                       (agent_id, owner_key, token_hash, display_name, platform,
                        agent_version, capabilities_json, paired_at, last_seen_at,
                        latest_payload_encrypted)
                   VALUES ('bad-agent', ?, ? || '-bad', 'Bad agent', ?, ?, ?, ?, ?, 'corrupt')""",
                values,
            )
            connection.commit()
        finally:
            connection.close()
        inbox = NerdInbox(
            self.store,
            developer_cockpit=self.developer,
            homelab_monitor=monitor,
            clock=lambda: self.clock[0],
        )
        result = inbox.get("owner-a", state="all")
        homelab_items = [item for item in result["items"] if item["source"] == "homelab"]
        self.assertIn("container_unhealthy", {item["kind"] for item in homelab_items})
        self.assertIn("agent_offline", {item["kind"] for item in homelab_items})
        self.assertEqual(
            [error["source"] for error in result["connector_errors"]], ["homelab"]
        )

    def test_real_launcher_does_not_decrypt_catalog_for_health(self):
        runner = LauncherRunner(self.store, clock=lambda: self.clock[0])
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute(
                """INSERT INTO launcher_agents
                       (agent_id, owner_key, token_hash, display_name, platform,
                        agent_version, capabilities_json, paired_at, last_seen_at,
                        catalog_encrypted)
                   VALUES ('runner-agent', 'owner-a', 'runner-token', 'Runner',
                           'linux', '1.0.0', '[]', ?, NULL, 'corrupt')""",
                (self.clock[0] - 100,),
            )
            connection.commit()
        finally:
            connection.close()
        inbox = NerdInbox(
            self.store,
            developer_cockpit=self.developer,
            launcher_runner=runner,
            clock=lambda: self.clock[0],
        )
        result = inbox.get("owner-a", state="all")
        launcher_items = [item for item in result["items"] if item["source"] == "launcher"]
        self.assertEqual([item["kind"] for item in launcher_items], ["agent_offline"])
        self.assertNotIn("launcher", {error["source"] for error in result["connector_errors"]})

    def test_orphan_cleanup_is_old_and_owner_scoped(self):
        self.event("developer")
        current = next(
            item for item in self.inbox.get("owner-a", state="all")["items"] if item["source"] == "developer"
        )
        old = self.clock[0] - 91 * 24 * 60 * 60
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.executemany(
                """INSERT INTO inbox_states
                       (owner_key, item_id, state, pinned, snoozed_until,
                        created_at, updated_at, last_seen_at)
                   VALUES (?, ?, 'read', 0, NULL, ?, ?, ?)""",
                [
                    ("owner-a", "a" * 32, old, old, old),
                    ("owner-b", "b" * 32, old, old, old),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        self.inbox.patch_state("owner-a", current["id"], {"pinned": True})
        connection = sqlite3.connect(self.store.db_path)
        try:
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM inbox_states WHERE owner_key = 'owner-a' AND item_id = ?",
                    ("a" * 32,),
                ).fetchone()
            )
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM inbox_states WHERE owner_key = 'owner-b' AND item_id = ?",
                    ("b" * 32,),
                ).fetchone()
            )
        finally:
            connection.close()

    def test_filters_validation_url_policy_and_public_cap(self):
        for _index in range(MAX_PUBLIC_ITEMS + 25):
            self.event("system", title=f"event {_index}")
        self.assertEqual(len(self.inbox.get("owner-a", state="all")["items"]), MAX_PUBLIC_ITEMS)
        with self.assertRaises(ValidationError):
            self.inbox.get("owner-a", state="invalid")
        with self.assertRaises(ValidationError):
            self.inbox.get("owner-a", source="")
        with self.assertRaises(ValidationError):
            self.inbox.mark_all_read("owner-a", source="invalid")

        accepted = (
            "",
            "#homelabDashboard",
            "https://github.com/octocat/Hello-World",
        )
        rejected = (
            " #homelabDashboard",
            "https://user@github.com/octocat/repo",
            "https://github.com:443/octocat/repo",
            "https://github.com/octocat/repo?token=secret",
            "https://github.com/octocat/repo#fragment",
            "https://github.com/octocat/repo/extra",
            "https://github.com/octocat/%2Frepo",
            "https://github.com/octocat/..",
            "https://github.com/octo_cat/repo",
            "http://github.com/octocat/repo",
        )
        for value in accepted:
            with self.subTest(accepted=value):
                self.assertEqual(validate_public_url(value), value)
        for value in rejected:
            with self.subTest(rejected=value), self.assertRaises(ValidationError):
                validate_public_url(value)


if __name__ == "__main__":
    unittest.main()
