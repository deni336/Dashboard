import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.local_ai_toolbox import (
    MAX_ASSISTANT_BYTES,
    MAX_MESSAGES,
    MAX_PROMPT_HISTORY_BYTES,
    MAX_PROMPT_HISTORY_MESSAGES,
    MAX_USER_BYTES,
    CapacityError,
    ConflictError,
    EndpointError,
    LocalAIToolbox,
    NotFoundError,
    OpenAICompatibleCompletionClient,
    StorageError,
    ValidationError,
    _NoRedirectHandler,
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


class FakeCompletion:
    def __init__(self, response=None, callback=None):
        self.response = response or {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Plain local response"},
                }
            ]
        }
        self.callback = callback
        self.calls = []

    def complete(self, *, messages, model):
        self.calls.append({"messages": messages, "model": model})
        if self.callback:
            self.callback()
        return self.response


class LocalAIToolboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_AI_PROVIDER": "ollama",
                "KASUGAI_AI_BASE_URL": "http://ollama.internal:11434/v1",
                "KASUGAI_AI_MODEL": "qwen-local:latest",
                "KASUGAI_AI_API_KEY": "deployment-secret-key",
                "KASUGAI_AI_API_KEY_FILE": "",
            },
        )
        self.environment.start()
        self.clock = [1_800_000_000.0]
        self.store = PersonalDashboardStore(TemporaryConfig(self.directory.name))
        self.completion = FakeCompletion()
        self.toolbox = LocalAIToolbox(
            self.store,
            completion_client=self.completion,
            clock=lambda: self.clock[0],
        )

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def create(self, owner="owner-a", **overrides):
        value = {"title": "Private debugging chat", "mode": "review"}
        value.update(overrides)
        return self.toolbox.create(owner, value)

    def test_encryption_binding_and_hostile_output_remains_plain_data(self):
        hostile = '<script>alert("x")</script>\n```shell\nrm -rf /\n```\n{"actions":[{"type":"shell"}]}'
        self.completion.response = {
            "choices": [{"finish_reason": "stop", "message": {"content": hostile}}]
        }
        created = self.create()
        detail = self.toolbox.message(
            "owner-a",
            created["id"],
            {"version": 1, "message": "Unique user secret needle-771"},
        )
        self.assertEqual(detail["messages"][-1], {"role": "assistant", "content": hostile})
        self.assertEqual(detail["version"], 2)

        connection = sqlite3.connect(self.store.db_path)
        try:
            dump = "\n".join(connection.iterdump())
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(ai_toolbox_sessions)")
            ]
            encrypted = connection.execute(
                "SELECT payload_encrypted FROM ai_toolbox_sessions WHERE session_id = ?",
                (created["id"],),
            ).fetchone()[0]
        finally:
            connection.close()
        for plaintext in (
            "Private debugging chat",
            "review",
            "Unique user secret needle-771",
            "<script>",
            '"actions"',
        ):
            self.assertNotIn(plaintext, dump)
        self.assertEqual(
            columns,
            [
                "owner_key",
                "session_id",
                "version",
                "payload_encrypted",
                "created_at",
                "updated_at",
            ],
        )
        decrypted = self.store.fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
        self.assertIn('"schema_version":1', decrypted)
        self.assertIn('"binding":', decrypted)

        second = self.create(title="Second session")
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute(
                "UPDATE ai_toolbox_sessions SET payload_encrypted = ? WHERE session_id = ?",
                (encrypted, second["id"]),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(StorageError):
            self.toolbox.get("owner-a", second["id"])

    def test_owner_isolation_and_version_precheck_avoid_model_calls(self):
        created = self.create()
        self.assertEqual(self.toolbox.list("owner-b")["sessions"], [])
        with self.assertRaises(NotFoundError):
            self.toolbox.get("owner-b", created["id"])
        with self.assertRaises(NotFoundError):
            self.toolbox.message(
                "owner-b", created["id"], {"version": 1, "message": "steal"}
            )
        with self.assertRaises(NotFoundError):
            self.toolbox.delete("owner-b", created["id"], 1)
        with self.assertRaises(ConflictError) as context:
            self.toolbox.message(
                "owner-a", created["id"], {"version": 2, "message": "stale"}
            )
        self.assertEqual(context.exception.current_version, 1)
        self.assertEqual(self.completion.calls, [])

    def test_model_call_is_outside_transaction_and_commit_rechecks_version(self):
        created = self.create()

        def concurrent_update():
            connection = sqlite3.connect(self.store.db_path, timeout=1)
            try:
                connection.execute(
                    "UPDATE ai_toolbox_sessions SET version = 2 WHERE session_id = ?",
                    (created["id"],),
                )
                connection.commit()
            finally:
                connection.close()

        self.completion.callback = concurrent_update
        with self.assertRaises(ConflictError) as context:
            self.toolbox.message(
                "owner-a", created["id"], {"version": 1, "message": "race me"}
            )
        self.assertEqual(context.exception.current_version, 2)
        connection = sqlite3.connect(self.store.db_path)
        try:
            encrypted = connection.execute(
                "SELECT payload_encrypted FROM ai_toolbox_sessions WHERE session_id = ?",
                (created["id"],),
            ).fetchone()[0]
        finally:
            connection.close()
        payload = json.loads(self.store.fernet.decrypt(encrypted.encode("ascii")))
        self.assertEqual(payload["messages"], [])

    def test_success_response_is_read_in_transaction_and_transport_rejects_redirects(self):
        created = self.create()
        with patch.object(
            self.toolbox,
            "get",
            side_effect=AssertionError("post-commit reread must not occur"),
        ):
            detail = self.toolbox.message(
                "owner-a", created["id"], {"version": 1, "message": "hello"}
            )
        self.assertEqual(detail["version"], 2)

        client = OpenAICompatibleCompletionClient(
            "https://ollama.example/v1", "secret", 30
        )
        redirect_handler = next(
            handler
            for handler in client.opener.handlers
            if isinstance(handler, _NoRedirectHandler)
        )
        self.assertIsNone(
            redirect_handler.redirect_request(
                None,
                None,
                302,
                "Found",
                {},
                "https://credential-receiver.example/chat/completions",
            )
        )

    def test_outbound_history_is_role_safe_and_independently_bounded(self):
        created = self.create(mode="assistant")
        messages = []
        for index in range(MAX_MESSAGES):
            role = "user" if index % 2 == 0 else "assistant"
            maximum = MAX_USER_BYTES if role == "user" else MAX_ASSISTANT_BYTES
            marker = f"history-{index:02d}-"
            messages.append(
                {"role": role, "content": marker + "é" * ((maximum - len(marker)) // 2)}
            )
        connection = sqlite3.connect(self.store.db_path)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT * FROM ai_toolbox_sessions WHERE session_id = ?", (created["id"],)
            ).fetchone()
            value = self.toolbox._decrypt("owner-a", row)  # noqa: SLF001
            value["messages"] = messages
            encrypted = self.toolbox._encrypt("owner-a", created["id"], value)  # noqa: SLF001
            connection.execute(
                "UPDATE ai_toolbox_sessions SET payload_encrypted = ? WHERE session_id = ?",
                (encrypted, created["id"]),
            )
            connection.commit()
        finally:
            connection.close()

        detail = self.toolbox.message(
            "owner-a", created["id"], {"version": 1, "message": "new bounded question"}
        )
        request_messages = self.completion.calls[-1]["messages"]
        self.assertEqual([message["role"] for message in request_messages], ["system", "user"])
        self.assertNotIn("tools", self.completion.calls[-1])
        untrusted = request_messages[1]["content"]
        self.assertIn("history-23-", untrusted)
        self.assertNotIn("history-00-", untrusted)
        self.assertLessEqual(
            len(untrusted.encode("utf-8")),
            MAX_PROMPT_HISTORY_BYTES + len("new bounded question".encode("utf-8")) + 512,
        )
        self.assertEqual(len(detail["messages"]), MAX_MESSAGES)
        self.assertEqual(detail["messages"][-2]["content"], "new bounded question")
        # The helper itself never considers more than the newest fixed window.
        prompt = self.toolbox._prompt_messages(  # noqa: SLF001
            "assistant", messages, "x"
        )[1]["content"]
        present = sum(f"history-{index:02d}-" in prompt for index in range(MAX_MESSAGES))
        self.assertLessEqual(present, MAX_PROMPT_HISTORY_MESSAGES)

    def test_provider_configuration_and_endpoint_errors_never_leak_secrets(self):
        created = self.create()
        with patch.dict(os.environ, {"KASUGAI_AI_PROVIDER": "openai"}):
            status = self.toolbox.status()
            self.assertEqual(
                status,
                {"configured": False, "provider": "ollama", "model": "qwen-local:latest"},
            )
            with self.assertRaises(EndpointError) as context:
                self.toolbox.message(
                    "owner-a", created["id"], {"version": 1, "message": "hello"}
                )
            self.assertNotIn("openai", str(context.exception).lower())
            self.assertEqual(self.completion.calls, [])

        with patch.dict(os.environ, {"KASUGAI_AI_TIMEOUT_SECONDS": "1"}):
            self.assertFalse(self.toolbox.status()["configured"])
            with self.assertRaises(EndpointError):
                self.toolbox.message(
                    "owner-a", created["id"], {"version": 1, "message": "hello"}
                )
            self.assertEqual(self.completion.calls, [])

        class LeakingClient:
            def complete(self, **_kwargs):
                raise RuntimeError(
                    "deployment-secret-key at http://ollama.internal:11434/v1"
                )

        toolbox = LocalAIToolbox(
            self.store,
            completion_client=LeakingClient(),
            clock=lambda: self.clock[0],
        )
        with self.assertRaises(EndpointError) as context:
            toolbox.message(
                "owner-a", created["id"], {"version": 1, "message": "hello"}
            )
        self.assertNotIn("deployment-secret-key", str(context.exception))
        self.assertNotIn("ollama.internal", str(context.exception))

    def test_validation_output_limit_capacity_and_delete_conflict(self):
        invalid_creates = (
            {},
            {"title": "x", "mode": "shell"},
            {"title": "x" * 101, "mode": "assistant"},
            {"title": "x", "mode": "assistant", "endpoint": "http://evil"},
        )
        for value in invalid_creates:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.toolbox.create("owner-a", value)
        created = self.create()
        for value in (
            {"version": 1, "message": ""},
            {"version": True, "message": "x"},
            {"version": 1, "message": "é" * (MAX_USER_BYTES // 2 + 1)},
            {"version": 1, "message": "x", "model": "evil"},
        ):
            with self.subTest(value=list(value)), self.assertRaises(ValidationError):
                self.toolbox.message("owner-a", created["id"], value)

        self.completion.response = "x" * (MAX_ASSISTANT_BYTES + 1)
        with self.assertRaises(EndpointError):
            self.toolbox.message(
                "owner-a", created["id"], {"version": 1, "message": "hello"}
            )
        self.assertEqual(self.toolbox.get("owner-a", created["id"])["messages"], [])

        with patch("src.local_ai_toolbox.MAX_SESSIONS_PER_OWNER", 2):
            self.create(owner="capacity-owner", title="One")
            self.create(owner="capacity-owner", title="Two")
            with self.assertRaises(CapacityError):
                self.create(owner="capacity-owner", title="Three")
        with self.assertRaises(ConflictError):
            self.toolbox.delete("owner-a", created["id"], 2)
        self.toolbox.delete("owner-a", created["id"], 1)
        with self.assertRaises(NotFoundError):
            self.toolbox.get("owner-a", created["id"])


if __name__ == "__main__":
    unittest.main()
