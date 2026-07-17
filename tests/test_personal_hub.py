import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.personal_dashboard import PersonalDashboardStore
from src.personal_hub import (
    MAX_CHECKINS,
    CapacityError,
    ConflictError,
    NotFoundError,
    PersonalHub,
    StorageError,
    ValidationError,
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


def reminder(**overrides):
    value = {
        "kind": "reminder",
        "title": "Rotate the private signing key",
        "note": "Only after the release is complete.",
        "due_at": "2027-02-01T13:30:00Z",
        "completed": False,
    }
    value.update(overrides)
    return value


def habit(**overrides):
    value = {
        "kind": "habit",
        "title": "Review error budgets",
        "note": "Check the private service dashboard.",
        "cadence": "weekdays",
        "checkins": [],
    }
    value.update(overrides)
    return value


class PersonalHubTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        self.identities = iter(f"{index:032x}" for index in range(1, 1000))
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.hub = PersonalHub(
            self.store,
            clock=lambda: self.clock[0],
            id_factory=lambda: next(self.identities),
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_all_kinds_list_and_detail_contract(self):
        created = [
            self.hub.create("owner-a", reminder()),
            self.hub.create(
                "owner-a",
                {
                    "kind": "countdown",
                    "title": "Launch window",
                    "note": "Private launch note",
                    "target_at": "2027-03-02T10:15:00-05:00",
                },
            ),
            self.hub.create("owner-a", habit()),
            self.hub.create(
                "owner-a",
                {
                    "kind": "bookmark",
                    "title": "Internal docs",
                    "note": "Private bookmark note",
                    "url": "https://docs.example.test/runbook?q=private#deploy",
                },
            ),
        ]
        result = self.hub.list("owner-a")
        self.assertEqual(
            result["counts"],
            {
                "total": 4,
                "reminders": 1,
                "countdowns": 1,
                "habits": 1,
                "bookmarks": 1,
            },
        )
        self.assertEqual(result["generated_at"], "2027-01-15T08:00:00Z")
        self.assertTrue(all("kind" in item and "note" not in item for item in result["items"]))
        self.assertEqual(
            self.hub.get("owner-a", created[1]["id"])["target_at"],
            "2027-03-02T15:15:00Z",
        )
        self.assertEqual(created[2]["checkins"], [])
        self.assertEqual(created[3]["url"], "https://docs.example.test/runbook?q=private#deploy")

    def test_all_user_state_is_encrypted_and_ciphertext_is_bound(self):
        first = self.hub.create(
            "owner-a",
            reminder(
                title="Unmistakable title 84c9",
                note="Unmistakable note c527",
                due_at="2027-02-07T04:05:06Z",
            ),
        )
        second = self.hub.create("owner-a", reminder(title="Second reminder"))
        same_id_other_owner = PersonalHub(
            self.store,
            clock=lambda: self.clock[0],
            id_factory=lambda: first["id"],
        ).create("owner-b", reminder(title="Other owner"))
        connection = sqlite3.connect(self.store.db_path)
        try:
            dump = "\n".join(connection.iterdump())
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(personal_hub_items)")
            ]
            encrypted = connection.execute(
                """SELECT payload_encrypted FROM personal_hub_items
                   WHERE owner_key = ? AND item_id = ?""",
                ("owner-a", first["id"]),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(
            columns,
            [
                "owner_key",
                "item_id",
                "kind",
                "version",
                "payload_encrypted",
                "created_at",
                "updated_at",
            ],
        )
        for secret in (
            "Unmistakable title 84c9",
            "Unmistakable note c527",
            "2027-02-07T04:05:06Z",
        ):
            self.assertNotIn(secret, dump)
        decrypted = self.store.fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
        self.assertIn('"schema_version":1', decrypted)
        self.assertIn('"binding":', decrypted)

        for owner, item_id in (
            ("owner-a", second["id"]),
            ("owner-b", same_id_other_owner["id"]),
        ):
            connection = sqlite3.connect(self.store.db_path)
            try:
                connection.execute(
                    """UPDATE personal_hub_items SET payload_encrypted = ?
                       WHERE owner_key = ? AND item_id = ?""",
                    (encrypted, owner, item_id),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(StorageError):
                self.hub.get(owner, item_id)

    def test_url_and_strict_create_validation(self):
        valid = self.hub.create(
            "owner-a",
            {
                "kind": "bookmark",
                "title": "IPv6 docs",
                "note": "",
                "url": "https://[2001:db8::1]:8443/docs",
            },
        )
        self.assertEqual(valid["kind"], "bookmark")
        invalid_urls = (
            "http://example.test",
            "https://user:secret@example.test/path",
            "https://user@example.test/path",
            "https:///missing-host",
            "https://example.test\\@evil.test",
            "https://example.test:99999/",
            "https://example.test/\nheader",
            "https://example.test/" + "x" * 2048,
        )
        for url in invalid_urls:
            with self.subTest(url=url[:60]), self.assertRaises(ValidationError):
                self.hub.create(
                    "owner-a",
                    {"kind": "bookmark", "title": "Bad", "note": "", "url": url},
                )

        invalid_payloads = (
            reminder(completed=True),
            habit(checkins=["2027-01-15"]),
            reminder(title="bad\ncontrol"),
            reminder(note="bad\tcontrol"),
            {key: value for key, value in reminder().items() if key != "note"},
            {**reminder(), "unknown": True},
            {
                "kind": "countdown",
                "title": "No timezone",
                "note": "",
                "target_at": "2027-01-16T12:00:00",
            },
        )
        for payload in invalid_payloads:
            with self.subTest(payload=list(payload)), self.assertRaises(ValidationError):
                self.hub.create("owner-a", payload)

    def test_optimistic_mutations_owner_isolation_and_immutable_kind(self):
        created = self.hub.create("owner-a", reminder())
        updated = self.hub.update(
            "owner-a",
            created["id"],
            {"version": 1, "title": "Updated", "completed": True},
        )
        self.assertEqual(updated["version"], 2)
        self.assertTrue(updated["completed"])
        with self.assertRaises(ConflictError) as context:
            self.hub.update(
                "owner-a", created["id"], {"version": 1, "title": "Stale"}
            )
        self.assertEqual(context.exception.current_version, 2)
        with self.assertRaises(ConflictError):
            self.hub.delete("owner-a", created["id"], 1)
        with self.assertRaises(ValidationError):
            self.hub.update(
                "owner-a", created["id"], {"version": 2, "kind": "bookmark"}
            )
        with self.assertRaises(ValidationError):
            self.hub.update(
                "owner-a", created["id"], {"version": 2, "target_at": "2027-02-01T00:00:00Z"}
            )

        self.assertEqual(self.hub.list("owner-b")["items"], [])
        for operation in (
            lambda: self.hub.get("owner-b", created["id"]),
            lambda: self.hub.update(
                "owner-b", created["id"], {"version": 2, "title": "stolen"}
            ),
            lambda: self.hub.delete("owner-b", created["id"], 2),
        ):
            with self.subTest(operation=operation), self.assertRaises(NotFoundError):
                operation()
        self.hub.delete("owner-a", created["id"], 2)
        with self.assertRaises(NotFoundError):
            self.hub.get("owner-a", created["id"])

    def test_capacity_is_owner_scoped(self):
        with patch("src.personal_hub.MAX_ITEMS_PER_OWNER", 2):
            self.hub.create("owner-a", reminder(title="One"))
            self.hub.create("owner-a", reminder(title="Two"))
            with self.assertRaises(CapacityError):
                self.hub.create("owner-a", reminder(title="Three"))
            self.hub.create("owner-b", reminder(title="Other owner"))

    def test_checkin_window_toggle_conflict_kind_and_retention(self):
        created = self.hub.create("owner-a", habit())
        today = datetime.fromtimestamp(self.clock[0], UTC).date()
        version = 1
        for offset in (-14, 14):
            value = (today + timedelta(days=offset)).isoformat()
            result = self.hub.toggle_checkin(
                "owner-a", created["id"], {"version": version, "date": value}
            )
            version += 1
            self.assertIn(value, result["checkins"])
        with self.assertRaises(ValidationError):
            self.hub.toggle_checkin(
                "owner-a",
                created["id"],
                {"version": version, "date": (today + timedelta(days=15)).isoformat()},
            )
        with self.assertRaises(ConflictError):
            self.hub.toggle_checkin(
                "owner-a", created["id"], {"version": 1, "date": today.isoformat()}
            )

        toggled = self.hub.toggle_checkin(
            "owner-a",
            created["id"],
            {"version": version, "date": (today - timedelta(days=14)).isoformat()},
        )
        version += 1
        self.assertNotIn((today - timedelta(days=14)).isoformat(), toggled["checkins"])
        non_habit = self.hub.create("owner-a", reminder(title="Not a habit"))
        with self.assertRaises(ValidationError):
            self.hub.toggle_checkin(
                "owner-a", non_habit["id"], {"version": 1, "date": today.isoformat()}
            )

        # Move the injected clock forward one day per write. Old dates remain valid
        # stored state, while each new date is inside the bounded write window.
        for index in range(MAX_CHECKINS + 1):
            current = datetime(2028, 1, 1, tzinfo=UTC) + timedelta(days=index)
            self.clock[0] = current.timestamp()
            latest = self.hub.toggle_checkin(
                "owner-a",
                created["id"],
                {"version": version, "date": current.date().isoformat()},
            )
            version += 1
        self.assertEqual(len(latest["checkins"]), MAX_CHECKINS)
        self.assertNotIn("2028-01-01", latest["checkins"])

    def test_corrupt_ciphertext_fails_without_disclosing_content(self):
        created = self.hub.create("owner-a", reminder())
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute(
                "UPDATE personal_hub_items SET payload_encrypted = 'corrupt' WHERE item_id = ?",
                (created["id"],),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(StorageError) as context:
            self.hub.list("owner-a")
        self.assertNotIn("signing key", str(context.exception))


if __name__ == "__main__":
    unittest.main()
