import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.project_manager import ProjectStore


class FakeConfig:
    def __init__(self, database_path):
        self.values = {
            ("Database", "projectdbpath"): str(database_path),
            ("Database", "encryption_key"): Fernet.generate_key().decode("ascii"),
        }

    def get(self, section, option, fallback=None):
        return self.values.get((section, option), fallback)

    def set(self, section, option, value):
        self.values[(section, option)] = value


def project_values(code="AI-SESSION"):
    return {
        "name": "Private AI workspace",
        "code": code,
        "description": "Project context",
        "status": "active",
        "priority": "high",
        "health": "on_track",
        "manager": "Project manager",
        "sponsor": "Project sponsor",
        "start_date": "2026-07-01",
        "target_date": "2026-09-30",
        "budget": 1000,
        "progress": 10,
    }


class ProjectAISessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "projects.db"
        self.config = FakeConfig(self.database_path)
        self.store = ProjectStore(self.config)
        self.owner = "owner-id"
        self.project = self.store.create_project(self.owner, project_values())

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_editor(self, actor_key="editor-id", email="editor@example.com"):
        invitation = self.store.create_share(
            self.owner,
            "owner@example.com",
            self.project["id"],
            email,
            "editor",
        )
        self.store.accept_invitation(invitation["token"], actor_key, email)
        return actor_key

    def test_session_and_message_secrets_are_encrypted_and_not_returned(self):
        session = self.store.create_ai_session(
            self.owner,
            self.project["id"],
            "Acquisition risk review",
            backend="local",
            model="gpt-oss-20b",
        )
        uuid.UUID(session["id"])
        self.assertEqual(session["title"], "Acquisition risk review")
        self.assertEqual(session["message_count"], 0)
        self.assertNotIn("actor_key", session)

        saved = self.store.append_ai_turn(
            self.owner,
            self.project["id"],
            session["id"],
            "Summarize the confidential acquisition risk.",
            "The principal risk is the approval date.",
            model_context="The principal risk is the approval date. Proposed action: risk-7.",
            model="gpt-oss-20b",
            request_id="request-one",
        )
        self.assertEqual([item["role"] for item in saved["messages"]], ["user", "assistant"])
        self.assertEqual(saved["session"]["message_count"], 2)
        for message in saved["messages"]:
            self.assertNotIn("actor_key", message)
            self.assertNotIn("project_id", message)
            self.assertNotIn("model_context", message)
            self.assertNotIn("request_id", message)

        with closing(sqlite3.connect(self.database_path)) as connection:
            raw_title = connection.execute(
                "SELECT title FROM project_ai_sessions WHERE id = ?", (session["id"],)
            ).fetchone()[0]
            raw_messages = connection.execute(
                """SELECT content, model_context FROM project_ai_messages
                   WHERE session_id = ? ORDER BY id""",
                (session["id"],),
            ).fetchall()
        self.assertTrue(raw_title.startswith("gAAAA"))
        self.assertNotIn("Acquisition", raw_title)
        self.assertEqual(len(raw_messages), 2)
        self.assertTrue(all(content.startswith("gAAAA") for content, _ in raw_messages))
        self.assertTrue(all(context.startswith("gAAAA") for _, context in raw_messages))
        self.assertNotIn("confidential acquisition", str(raw_messages))
        self.assertNotIn("Proposed action", str(raw_messages))

    def test_sessions_are_private_to_the_actor_even_from_the_project_owner(self):
        editor = self.add_editor()
        owner_session = self.store.create_ai_session(
            self.owner, self.project["id"], "Owner chat"
        )
        editor_session = self.store.create_ai_session(
            editor, self.project["id"], "Editor chat"
        )

        self.assertEqual(
            [item["id"] for item in self.store.list_ai_sessions(self.owner, self.project["id"])],
            [owner_session["id"]],
        )
        self.assertEqual(
            [item["id"] for item in self.store.list_ai_sessions(editor, self.project["id"])],
            [editor_session["id"]],
        )
        with self.assertRaisesRegex(KeyError, "AI session not found"):
            self.store.get_ai_session(self.owner, self.project["id"], editor_session["id"])
        with self.assertRaisesRegex(KeyError, "AI session not found"):
            self.store.get_ai_session(editor, self.project["id"], owner_session["id"])
        with self.assertRaisesRegex(KeyError, "AI session not found"):
            self.store.delete_ai_session(self.owner, self.project["id"], editor_session["id"])

    def test_project_access_and_project_id_are_revalidated_for_every_session(self):
        session = self.store.create_ai_session(self.owner, self.project["id"], "First project")
        second_project = self.store.create_project(self.owner, project_values("AI-OTHER"))

        with self.assertRaisesRegex(KeyError, "AI session not found"):
            self.store.get_ai_session(self.owner, second_project["id"], session["id"])
        with self.assertRaisesRegex(KeyError, "Project not found"):
            self.store.list_ai_sessions("outsider-id", self.project["id"])

        viewer_email = "viewer@example.com"
        invitation = self.store.create_share(
            self.owner,
            "owner@example.com",
            self.project["id"],
            viewer_email,
            "viewer",
        )
        self.store.accept_invitation(invitation["token"], "viewer-id", viewer_email)
        self.assertEqual(self.store.list_ai_sessions("viewer-id", self.project["id"]), [])
        with self.assertRaisesRegex(PermissionError, "Editor access"):
            self.store.create_ai_session("viewer-id", self.project["id"], "Not allowed")

        editor = self.add_editor("revoked-editor", "revoked@example.com")
        editor_session = self.store.create_ai_session(
            editor, self.project["id"], "Unavailable after revocation"
        )
        share = next(
            item for item in self.store.workspace(self.owner, self.project["id"])["shares"]
            if item["invited_email"] == "revoked@example.com"
        )
        self.store.delete_share(self.owner, share["id"])
        with self.assertRaisesRegex(KeyError, "Project not found"):
            self.store.get_ai_session(editor, self.project["id"], editor_session["id"])

    def test_model_history_is_server_owned_bounded_and_uses_private_context(self):
        session = self.store.create_ai_session(
            self.owner,
            self.project["id"],
            "Long chat",
            model="gpt-oss-20b",
        )
        for index in range(7):
            self.store.append_ai_turn(
                self.owner,
                self.project["id"],
                session["id"],
                f"user-{index}",
                f"visible-assistant-{index}",
                model_context=f"trusted-context-{index}",
                request_id=f"history-{index}",
            )

        history = self.store.ai_session_model_history(
            self.owner, self.project["id"], session["id"]
        )
        self.assertEqual(len(history), 12)
        self.assertEqual(history[0], {"role": "user", "content": "user-1"})
        self.assertEqual(
            history[-1], {"role": "assistant", "content": "trusted-context-6"}
        )
        self.assertFalse(any("visible-assistant" in item["content"] for item in history))
        with self.assertRaisesRegex(ValueError, "between 1 and 12"):
            self.store.ai_session_model_history(
                self.owner, self.project["id"], session["id"], limit=13
            )

        page = self.store.get_ai_session(
            self.owner, self.project["id"], session["id"], message_limit=3
        )
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_before_id"], page["messages"][0]["id"])
        self.assertEqual(
            [item["content"] for item in page["messages"]],
            ["visible-assistant-5", "user-6", "visible-assistant-6"],
        )
        older = self.store.get_ai_session(
            self.owner,
            self.project["id"],
            session["id"],
            message_limit=3,
            before_id=page["next_before_id"],
        )
        self.assertEqual(
            [item["content"] for item in older["messages"]],
            ["user-4", "visible-assistant-4", "user-5"],
        )

    def test_successful_turn_is_atomic_and_failed_inference_cannot_leave_user_message(self):
        session = self.store.create_ai_session(self.owner, self.project["id"], "Atomic chat")

        with self.assertRaisesRegex(ValueError, "assistant_content is required"):
            self.store.append_ai_turn(
                self.owner, self.project["id"], session["id"], "orphan", ""
            )
        self.assertEqual(
            self.store.get_ai_session(self.owner, self.project["id"], session["id"])[
                "messages"
            ],
            [],
        )

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_assistant_message
                BEFORE INSERT ON project_ai_messages
                WHEN NEW.role = 'assistant'
                BEGIN
                    SELECT RAISE(ABORT, 'simulated assistant insert failure');
                END;
                """
            )
            connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_ai_turn(
                self.owner,
                self.project["id"],
                session["id"],
                "must roll back",
                "assistant reply",
            )
        with closing(sqlite3.connect(self.database_path)) as connection:
            message_count = connection.execute(
                "SELECT COUNT(*) FROM project_ai_messages WHERE session_id = ?",
                (session["id"],),
            ).fetchone()[0]
        self.assertEqual(message_count, 0)

    def test_request_retry_is_idempotent_and_model_is_pinned(self):
        requested_session_id = str(uuid.uuid4())
        session = self.store.create_ai_session(
            self.owner,
            self.project["id"],
            "Retry chat",
            model="gpt-oss-20b",
            session_id=requested_session_id,
        )
        self.assertEqual(session["id"], requested_session_id)
        self.assertFalse(self.store.ai_session_has_request(
            self.owner, self.project["id"], session["id"], "same-request"
        ))
        first = self.store.append_ai_turn(
            self.owner,
            self.project["id"],
            session["id"],
            "hello",
            "hi",
            model="gpt-oss-20b",
            request_id="same-request",
        )
        retry = self.store.append_ai_turn(
            self.owner,
            self.project["id"],
            session["id"],
            "hello",
            "hi",
            model="gpt-oss-20b",
            request_id="same-request",
        )
        self.assertTrue(self.store.ai_session_has_request(
            self.owner, self.project["id"], session["id"], "same-request"
        ))
        self.assertEqual(first["turn_id"], retry["turn_id"])
        self.assertEqual(
            [item["id"] for item in first["messages"]],
            [item["id"] for item in retry["messages"]],
        )
        self.assertEqual(
            self.store.get_ai_session(self.owner, self.project["id"], session["id"])[
                "session"
            ]["message_count"],
            2,
        )
        with self.assertRaisesRegex(ValueError, "another AI turn"):
            self.store.append_ai_turn(
                self.owner,
                self.project["id"],
                session["id"],
                "changed",
                "hi",
                request_id="same-request",
            )
        with self.assertRaisesRegex(ValueError, "pinned to a different model"):
            self.store.append_ai_turn(
                self.owner,
                self.project["id"],
                session["id"],
                "new prompt",
                "new response",
                model="different-model",
            )

    def test_caps_and_project_delete_cascade_are_enforced(self):
        with patch("src.project_manager.AI_SESSION_LIMIT_PER_PROJECT", 2):
            self.store.ensure_ai_session_capacity(self.owner, self.project["id"])
            first = self.store.create_ai_session(self.owner, self.project["id"], "One")
            self.store.create_ai_session(self.owner, self.project["id"], "Two")
            with self.assertRaisesRegex(ValueError, "at most 2"):
                self.store.ensure_ai_session_capacity(self.owner, self.project["id"])
            with self.assertRaisesRegex(ValueError, "at most 2"):
                self.store.create_ai_session(self.owner, self.project["id"], "Three")

        with patch("src.project_manager.AI_SESSION_MESSAGE_LIMIT", 2):
            self.store.append_ai_turn(
                self.owner,
                self.project["id"],
                first["id"],
                "first",
                "reply",
            )
            with self.assertRaisesRegex(ValueError, "at most 2"):
                self.store.ensure_ai_session_capacity(
                    self.owner, self.project["id"], first["id"]
                )
            with self.assertRaisesRegex(ValueError, "at most 2"):
                self.store.append_ai_turn(
                    self.owner,
                    self.project["id"],
                    first["id"],
                    "second",
                    "reply",
                )

        self.store.delete_project(self.owner, self.project["id"])
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM project_ai_sessions").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM project_ai_messages").fetchone()[0],
                0,
            )

    def test_schema_initialization_is_idempotent(self):
        session = self.store.create_ai_session(self.owner, self.project["id"], "Durable")
        second_store = ProjectStore(self.config)
        loaded = second_store.get_ai_session(
            self.owner, self.project["id"], session["id"]
        )
        self.assertEqual(loaded["session"]["title"], "Durable")


if __name__ == "__main__":
    unittest.main()
