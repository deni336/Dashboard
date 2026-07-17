import copy
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.launcher_runner import (
    AuthenticationError,
    ConflictError,
    LauncherRunner,
    NotFoundError,
    PermissionDeniedError,
    ReplayError,
    ValidationError,
    validate_catalog,
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


def pair_payload(pairing, **overrides):
    payload = {
        "pairing_id": pairing["pairing_id"],
        "code": pairing["code"],
        "display_name": "Desk runner",
        "platform": "Windows 11",
        "agent_version": "1.0.0",
        "capabilities": ["run_tasks"],
    }
    payload.update(overrides)
    return payload


def catalog(now, sequence=1, *, confirmation=True):
    return {
        "schema_version": 1,
        "sequence": sequence,
        "captured_at": iso_timestamp(now),
        "tasks": [
            {
                "key": "local_task_key_1234567890",
                "title": "Run focused tests",
                "description": "Runs the locally approved focused test suite.",
                "category": "Development",
                "icon": "test-tube-2",
                "requires_confirmation": confirmation,
            }
        ],
    }


def result(now, claim_token, **overrides):
    value = {
        "schema_version": 1,
        "claim_token": claim_token,
        "completed_at": iso_timestamp(now),
        "status": "succeeded",
        "code": "ok",
        "summary": "Focused tests passed.",
        "output": "12 passed",
        "truncated": False,
    }
    value.update(overrides)
    return value


class LauncherRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_LAUNCHER_RUNS_ENABLED": "true",
                "KASUGAI_LAUNCHER_MIN_CATALOG_SECONDS": "0",
                "KASUGAI_LAUNCHER_MIN_CLAIM_SECONDS": "0",
                "KASUGAI_LAUNCHER_MIN_RUN_SECONDS": "0",
            },
        )
        self.environment.start()
        store = PersonalDashboardStore(TemporaryConfig(self.temporary_directory.name))
        self.runner = LauncherRunner(store, clock=lambda: self.clock[0])

    def tearDown(self):
        self.environment.stop()
        self.temporary_directory.cleanup()

    def pair(self, owner="owner-a"):
        pairing = self.runner.create_pairing(owner)
        return self.runner.pair_agent(pair_payload(pairing))

    def publish(self, credentials, sequence=1, **kwargs):
        return self.runner.ingest_catalog(
            credentials["agent_id"],
            credentials["token"],
            catalog(self.clock[0], sequence, **kwargs),
        )

    def task(self, owner="owner-a"):
        return self.runner.catalog(owner)["tasks"][0]

    def test_pairing_is_one_use_and_secrets_are_hmac_only(self):
        pairing = self.runner.create_pairing("owner-a")
        credentials = self.runner.pair_agent(pair_payload(pairing))
        with self.assertRaises(AuthenticationError):
            self.runner.pair_agent(pair_payload(pairing))
        connection = sqlite3.connect(self.runner.db_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn(pairing["code"], dump)
        self.assertNotIn(credentials["token"], dump)

    def test_catalog_is_encrypted_replay_protected_and_owner_scoped(self):
        credentials = self.pair()
        self.publish(credentials)
        with self.assertRaises(ReplayError):
            self.publish(credentials)
        self.assertEqual(self.runner.catalog("owner-b")["tasks"], [])
        task = self.task()
        self.assertNotEqual(task["id"], "local_task_key_1234567890")
        self.assertTrue(task["available"])
        connection = sqlite3.connect(self.runner.db_path)
        try:
            encrypted = connection.execute(
                "SELECT catalog_encrypted FROM launcher_agents WHERE agent_id = ?",
                (credentials["agent_id"],),
            ).fetchone()[0]
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("Run focused tests", encrypted)
        self.assertNotIn("local_task_key_1234567890", dump)

    def test_catalog_rejects_execution_fields_and_malformed_metadata(self):
        base = catalog(self.clock[0])
        for field, value in (
            ("argv", ["cmd.exe", "/c", "whoami"]),
            ("executable", "C:\\Windows\\System32\\cmd.exe"),
            ("working_directory", "C:\\"),
            ("environment", {"TOKEN": "secret"}),
        ):
            malicious = copy.deepcopy(base)
            malicious["tasks"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate_catalog(malicious, now_epoch=self.clock[0])

    def test_confirmation_is_one_use_then_claim_contains_only_opaque_key(self):
        credentials = self.pair()
        self.publish(credentials)
        task = self.task()
        preview = self.runner.queue_run("owner-a", task["id"], {})
        self.assertFalse(preview["queued"])
        token = preview["preview"]["confirmation_token"]
        queued = self.runner.queue_run(
            "owner-a", task["id"], {"confirmation_token": token}
        )
        self.assertTrue(queued["queued"])
        with self.assertRaises((AuthenticationError, ConflictError)):
            self.runner.queue_run(
                "owner-a", task["id"], {"confirmation_token": token}
            )
        claim = self.runner.claim_run(
            credentials["agent_id"], credentials["token"], {"schema_version": 1}
        )
        self.assertEqual(
            set(claim),
            {"schema_version", "run_id", "claim_token", "task_key", "expires_at"},
        )
        self.assertNotIn("argv", str(claim).lower())

    def test_claim_is_delivered_only_once_under_concurrency(self):
        credentials = self.pair()
        self.publish(credentials, confirmation=False)
        self.runner.queue_run("owner-a", self.task()["id"], {})

        def claim_once(_index):
            return self.runner.claim_run(
                credentials["agent_id"], credentials["token"], {"schema_version": 1}
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(claim_once, range(2)))
        self.assertEqual(sum(item is not None for item in claims), 1)

    def test_result_is_encrypted_and_identical_retry_is_idempotent(self):
        credentials = self.pair()
        self.publish(credentials, confirmation=False)
        self.runner.queue_run("owner-a", self.task()["id"], {})
        claim = self.runner.claim_run(
            credentials["agent_id"], credentials["token"], {"schema_version": 1}
        )
        payload = result(self.clock[0], claim["claim_token"])
        accepted = self.runner.submit_result(
            credentials["agent_id"], credentials["token"], claim["run_id"], payload
        )
        self.assertFalse(accepted["idempotent"])
        retried = self.runner.submit_result(
            credentials["agent_id"], credentials["token"], claim["run_id"], payload
        )
        self.assertTrue(retried["idempotent"])
        run = self.runner.get_run("owner-a", claim["run_id"])
        self.assertEqual(run["result"]["output"], "12 passed")
        connection = sqlite3.connect(self.runner.db_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("12 passed", dump)

    def test_owner_freshness_revocation_and_kill_switch_are_enforced(self):
        credentials = self.pair()
        self.publish(credentials, confirmation=False)
        task = self.task()
        with self.assertRaises(NotFoundError):
            self.runner.queue_run("owner-b", task["id"], {})
        self.clock[0] += 91
        with self.assertRaises(ConflictError):
            self.runner.queue_run("owner-a", task["id"], {})
        self.clock[0] -= 91
        with patch.dict(os.environ, {"KASUGAI_LAUNCHER_RUNS_ENABLED": "false"}):
            with self.assertRaises(PermissionDeniedError):
                self.runner.queue_run("owner-a", task["id"], {})
        self.runner.revoke("owner-a", credentials["agent_id"])
        with self.assertRaises(AuthenticationError):
            self.runner.claim_run(
                credentials["agent_id"], credentials["token"], {"schema_version": 1}
            )


if __name__ == "__main__":
    unittest.main()
