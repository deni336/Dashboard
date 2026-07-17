import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.knowledge_vault import (
    LANGUAGES,
    MAX_LIST_ITEMS,
    CapacityError,
    ConflictError,
    KnowledgeVault,
    NotFoundError,
    StorageError,
    ValidationError,
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


def item_payload(**overrides):
    value = {
        "kind": "note",
        "title": "Private architecture",
        "content": "The launch code is glass-wombat-923.",
        "language": "markdown",
        "tags": ["Private", "Architecture"],
        "pinned": False,
    }
    value.update(overrides)
    return value


class KnowledgeVaultTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.vault = KnowledgeVault(self.store, clock=lambda: self.clock[0])

    def tearDown(self):
        self.directory.cleanup()

    def test_sensitive_payload_is_encrypted_and_bound_to_owner_and_item(self):
        created = self.vault.create(
            "owner-a",
            item_payload(
                kind="snippet",
                title="Unique plaintext title 8f02",
                content="Write-Host 'unique secret body 2c91'",
                language="powershell",
                tags=["Unique Secret Tag 4a77"],
            ),
        )
        connection = sqlite3.connect(self.store.db_path)
        try:
            dump = "\n".join(connection.iterdump())
            columns = [row[1] for row in connection.execute("PRAGMA table_info(knowledge_items)")]
            encrypted = connection.execute(
                "SELECT payload_encrypted FROM knowledge_items WHERE owner_key = 'owner-a'"
            ).fetchone()[0]
        finally:
            connection.close()
        for plaintext in (
            "Unique plaintext title 8f02",
            "unique secret body 2c91",
            "Unique Secret Tag 4a77",
            "powershell",
        ):
            self.assertNotIn(plaintext, dump)
        self.assertEqual(
            columns,
            [
                "owner_key",
                "item_id",
                "kind",
                "pinned",
                "version",
                "payload_encrypted",
                "created_at",
                "updated_at",
            ],
        )
        decrypted = self.store.fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
        self.assertIn('"schema_version":1', decrypted)
        self.assertIn('"binding":', decrypted)
        self.assertEqual(self.vault.get("owner-a", created["id"])["content"], created["content"])

        other = self.vault.create("owner-a", item_payload(title="Second item"))
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute(
                """UPDATE knowledge_items SET payload_encrypted = ?
                   WHERE owner_key = 'owner-a' AND item_id = ?""",
                (encrypted, other["id"]),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(StorageError):
            self.vault.get("owner-a", other["id"])

    def test_owner_isolation_returns_not_found(self):
        created = self.vault.create("owner-a", item_payload())
        self.assertEqual(self.vault.list("owner-b")["items"], [])
        operations = (
            lambda: self.vault.get("owner-b", created["id"]),
            lambda: self.vault.update(
                "owner-b", created["id"], {"version": 1, "title": "stolen"}
            ),
            lambda: self.vault.delete("owner-b", created["id"], 1),
            lambda: self.vault.duplicate("owner-b", created["id"]),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(NotFoundError):
                operation()

    def test_filters_counts_tags_languages_and_summary_contract(self):
        self.vault.create(
            "owner-a",
            item_payload(
                title="Python deployment",
                content="Use a virtual environment.",
                tags=["  Ｐython   Tools ", "Ops"],
                pinned=True,
            ),
        )
        self.clock[0] += 1
        snippet = self.vault.create(
            "owner-a",
            item_payload(
                kind="snippet",
                title="Database query",
                content="SELECT private_column FROM records;",
                language="sql",
                tags=["Ops", "Database"],
            ),
        )
        result = self.vault.list("owner-a")
        self.assertEqual(result["counts"], {"total": 2, "notes": 1, "snippets": 1, "pinned": 1})
        self.assertEqual(result["languages"], list(LANGUAGES))
        self.assertEqual(
            result["tags"],
            [
                {"name": "Database", "count": 1},
                {"name": "Ops", "count": 2},
                {"name": "Python Tools", "count": 1},
            ],
        )
        summary_keys = {
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
        }
        self.assertTrue(all(set(item) == summary_keys for item in result["items"]))
        self.assertNotIn("content", result["items"][0])
        self.assertEqual(
            [item["id"] for item in self.vault.list("owner-a", kind="snippet")["items"]],
            [snippet["id"]],
        )
        self.assertEqual(len(self.vault.list("owner-a", q="PRIVATE_COLUMN")["items"]), 1)
        self.assertEqual(len(self.vault.list("owner-a", tag="ｐｙｔｈｏｎ tools")["items"]), 1)
        self.assertEqual(len(self.vault.list("owner-a", pinned=True)["items"]), 1)

    def test_optimistic_update_delete_and_duplicate(self):
        created = self.vault.create("owner-a", item_payload())
        self.clock[0] += 10
        with patch.object(
            self.vault,
            "get",
            side_effect=AssertionError("post-commit reread must not occur"),
        ):
            updated = self.vault.update(
                "owner-a",
                created["id"],
                {"version": 1, "title": "Updated title", "pinned": True},
            )
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["title"], "Updated title")
        self.assertTrue(updated["pinned"])
        with self.assertRaises(ConflictError) as context:
            self.vault.update(
                "owner-a", created["id"], {"version": 1, "title": "Stale title"}
            )
        self.assertEqual(context.exception.current_version, 2)
        with self.assertRaises(ConflictError):
            self.vault.delete("owner-a", created["id"], 1)

        duplicate = self.vault.duplicate("owner-a", created["id"])
        self.assertNotEqual(duplicate["id"], created["id"])
        self.assertEqual(duplicate["version"], 1)
        for field in ("kind", "title", "content", "language", "tags", "pinned"):
            self.assertEqual(duplicate[field], updated[field])
        self.vault.delete("owner-a", created["id"], 2)
        with self.assertRaises(NotFoundError):
            self.vault.get("owner-a", created["id"])

    def test_validation_and_utf8_content_limit(self):
        self.vault.create("owner-a", item_payload(content="é" * (64 * 1024 // 2)))
        invalid_payloads = (
            item_payload(content="é" * (64 * 1024 // 2 + 1)),
            item_payload(title="x" * 161),
            item_payload(tags=["x" * 33]),
            item_payload(tags=["Python", "ｐｙｔｈｏｎ"]),
            item_payload(language="python"),
            item_payload(kind="snippet", language="ruby"),
            {key: value for key, value in item_payload().items() if key != "tags"},
            {**item_payload(), "unknown": True},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=list(payload)), self.assertRaises(ValidationError):
                self.vault.create("owner-a", payload)
        created = self.vault.create("owner-a", item_payload(title="Patch target"))
        invalid_patches = (
            {},
            {"title": "missing version"},
            {"version": True, "title": "bad"},
            {"version": 1},
            {"version": 1, "unknown": "bad"},
        )
        for payload in invalid_patches:
            with self.subTest(patch=payload), self.assertRaises(ValidationError):
                self.vault.update("owner-a", created["id"], payload)

    def test_capacity_is_owner_scoped_and_list_is_capped(self):
        with patch("src.knowledge_vault.MAX_ITEMS_PER_OWNER", 2):
            self.vault.create("owner-a", item_payload(title="One"))
            self.vault.create("owner-a", item_payload(title="Two"))
            with self.assertRaises(CapacityError):
                self.vault.create("owner-a", item_payload(title="Three"))
            self.vault.create("owner-b", item_payload(title="Other owner"))

        # Exercise the real public cap without changing the production value.
        for index in range(MAX_LIST_ITEMS + 1 - 2):
            self.vault.create("owner-a", item_payload(title=f"Bulk item {index}"))
        result = self.vault.list("owner-a")
        self.assertEqual(result["counts"]["total"], MAX_LIST_ITEMS + 1)
        self.assertEqual(len(result["items"]), MAX_LIST_ITEMS)

    def test_corrupt_ciphertext_fails_generically(self):
        created = self.vault.create("owner-a", item_payload())
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute(
                "UPDATE knowledge_items SET payload_encrypted = 'corrupt' WHERE item_id = ?",
                (created["id"],),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(StorageError) as context:
            self.vault.list("owner-a")
        self.assertNotIn("Private architecture", str(context.exception))
        self.assertNotIn("glass-wombat", str(context.exception))


if __name__ == "__main__":
    unittest.main()
