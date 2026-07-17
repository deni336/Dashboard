import copy
import math
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.homelab_monitor import (
    AuthenticationError,
    ConflictError,
    HomelabMonitor,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    RateLimitError,
    ReplayError,
    ValidationError,
    validate_snapshot,
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


def snapshot(now, sequence=1, *, resource_key="resource_key_1234567890"):
    return {
        "schema_version": 1,
        "sequence": sequence,
        "captured_at": iso_timestamp(now),
        "policy": {
            "revision": "policy_revision_123456",
            "inventory_scope": "labeled",
            "logs_enabled": True,
            "allowed_actions": ["restart"],
            "image_updates_enabled": False,
        },
        "engine": {
            "available": True,
            "key": "engine_key_1234567890",
            "kind": "docker",
            "server_version": "28.5.1",
            "operating_system": "Docker Desktop",
            "os_type": "linux",
            "architecture": "x86_64",
            "cpu_count": 12,
            "memory_bytes": 34359738368,
            "container_counts": {"total": 1, "running": 1, "paused": 0, "stopped": 0},
            "image_count": 3,
            "volume_count": 2,
            "network_count": 4,
            "checked_at": iso_timestamp(now),
            "error_code": None,
        },
        "storage": [
            {
                "kind": "images",
                "total_count": 3,
                "active_count": 1,
                "size_bytes": 100000,
                "reclaimable_bytes": 1000,
            }
        ],
        "containers": [
            {
                "key": resource_key,
                "name": "immich-server",
                "image": "ghcr.io/immich/immich:v1",
                "compose_project": "immich",
                "compose_service": "server",
                "state": "running",
                "health": "healthy",
                "created_at": iso_timestamp(now - 3600),
                "cpu_percent": 3.1,
                "memory_usage_bytes": 700000,
                "memory_limit_bytes": 4000000,
                "memory_percent": 17.5,
                "network_rx_bytes": 10000,
                "network_tx_bytes": 8000,
                "block_read_bytes": 4000,
                "block_write_bytes": 2000,
                "pids": 38,
                "ports": [{"container_port": 2283, "host_port": 2283, "protocol": "tcp"}],
                "image_update": {"status": "unknown", "checked_at": None},
                "grants": {"logs": True, "actions": ["restart"]},
            }
        ],
        "health_checks": [
            {
                "key": "health_key_12345678901",
                "name": "Home Assistant",
                "kind": "http",
                "status": "up",
                "checked_at": iso_timestamp(now),
                "latency_ms": 24.2,
                "http_status": 200,
                "tls_expires_in_days": None,
                "consecutive_failures": 0,
                "error_code": None,
            }
        ],
        "truncated": {"containers": False, "storage": False, "health_checks": False},
    }


def pair_payload(pairing, **overrides):
    payload = {
        "pairing_id": pairing["pairing_id"],
        "code": pairing["code"],
        "display_name": "Home server",
        "agent_version": "1.0.0",
        "platform": "Windows 11",
        "capabilities": ["inventory", "read_logs", "restart"],
    }
    payload.update(overrides)
    return payload


def result_payload(now, claim_token, **overrides):
    payload = {
        "schema_version": 1,
        "claim_token": claim_token,
        "completed_at": iso_timestamp(now),
        "status": "succeeded",
        "code": "ok",
        "observed_state": "running",
        "log_excerpt": None,
        "truncated": False,
    }
    payload.update(overrides)
    return payload


class HomelabMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_HOMELAB_ACTIONS_ENABLED": "true",
                "KASUGAI_HOMELAB_MIN_INGEST_SECONDS": "0",
                "KASUGAI_HOMELAB_MIN_CLAIM_SECONDS": "0",
                "KASUGAI_HOMELAB_MIN_ACTION_SECONDS": "0",
            },
        )
        self.environment.start()
        store = PersonalDashboardStore(TemporaryConfig(self.temporary_directory.name))
        self.monitor = HomelabMonitor(store, clock=lambda: self.clock[0])

    def tearDown(self):
        self.environment.stop()
        self.temporary_directory.cleanup()

    def pair(self, owner="owner-a"):
        pairing = self.monitor.create_pairing(owner)
        return self.monitor.pair_agent(pair_payload(pairing))

    def ingest(self, credentials, sequence=1, **kwargs):
        return self.monitor.ingest_snapshot(
            credentials["agent_id"],
            credentials["token"],
            snapshot(self.clock[0], sequence, **kwargs),
        )

    def test_pairing_is_one_use_and_secrets_are_hmac_only(self):
        pairing = self.monitor.create_pairing("owner-a")
        credentials = self.monitor.pair_agent(pair_payload(pairing))
        with self.assertRaises(AuthenticationError):
            self.monitor.pair_agent(pair_payload(pairing))

        connection = sqlite3.connect(self.monitor.db_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn(pairing["code"], dump)
        self.assertNotIn(credentials["token"], dump)

    def test_inventory_is_encrypted_replay_protected_owner_scoped_and_bucketed(self):
        credentials = self.pair()
        self.ingest(credentials)
        with self.assertRaises(ReplayError):
            self.ingest(credentials)
        with self.assertRaises(AuthenticationError):
            self.monitor.ingest_snapshot(credentials["agent_id"], "wrong", {"bad": True})

        listed = self.monitor.list_agents("owner-a")["agents"]
        self.assertEqual(listed[0]["latest_summary"]["containers_running"], 1)
        self.assertEqual(self.monitor.list_agents("owner-b"), {"agents": []})
        with self.assertRaises(NotFoundError):
            self.monitor.latest("owner-b", credentials["agent_id"])
        latest = self.monitor.latest("owner-a", credentials["agent_id"])
        self.assertEqual(latest["snapshot"]["stacks"][0]["name"], "immich")
        self.assertEqual(len(self.monitor.history("owner-a", credentials["agent_id"])["points"]), 1)

        connection = sqlite3.connect(self.monitor.db_path)
        try:
            row = connection.execute(
                "SELECT latest_payload_encrypted FROM homelab_agents WHERE agent_id = ?",
                (credentials["agent_id"],),
            ).fetchone()[0]
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("immich-server", row)
        self.assertNotIn("ghcr.io/immich", dump)

    def test_restart_requires_one_use_preview_then_is_claimed_once(self):
        credentials = self.pair()
        self.ingest(credentials)
        request = {"operation": "restart", "resource_key": "resource_key_1234567890"}

        preview = self.monitor.queue_action("owner-a", credentials["agent_id"], request)
        self.assertFalse(preview["queued"])
        self.assertEqual(self.monitor.list_actions("owner-a", credentials["agent_id"]), {"actions": []})
        confirmation = preview["preview"]["confirmation_token"]
        queued = self.monitor.queue_action(
            "owner-a", credentials["agent_id"], {**request, "confirmation_token": confirmation}
        )
        self.assertTrue(queued["queued"])
        with self.assertRaises(AuthenticationError):
            self.monitor.queue_action(
                "owner-a", credentials["agent_id"], {**request, "confirmation_token": confirmation}
            )

        claimed = self.monitor.claim_action(
            credentials["agent_id"], credentials["token"], {"schema_version": 1}
        )
        self.assertEqual(claimed["operation"], "restart")
        self.assertEqual(claimed["resource_key"], request["resource_key"])
        self.assertIsNone(
            self.monitor.claim_action(
                credentials["agent_id"], credentials["token"], {"schema_version": 1}
            )
        )

    def test_result_is_encrypted_and_identical_retry_is_idempotent(self):
        credentials = self.pair()
        self.ingest(credentials)
        queued = self.monitor.queue_action(
            "owner-a",
            credentials["agent_id"],
            {"operation": "read_logs", "resource_key": "resource_key_1234567890"},
        )
        claimed = self.monitor.claim_action(
            credentials["agent_id"], credentials["token"], {"schema_version": 1}
        )
        payload = result_payload(
            self.clock[0],
            claimed["claim_token"],
            log_excerpt="safe application output",
        )
        accepted = self.monitor.submit_result(
            credentials["agent_id"], credentials["token"], claimed["action_id"], payload
        )
        repeated = self.monitor.submit_result(
            credentials["agent_id"], credentials["token"], claimed["action_id"], payload
        )
        self.assertFalse(accepted["idempotent"])
        self.assertTrue(repeated["idempotent"])
        different = copy.deepcopy(payload)
        different["log_excerpt"] = "different"
        with self.assertRaises(ReplayError):
            self.monitor.submit_result(
                credentials["agent_id"], credentials["token"], claimed["action_id"], different
            )
        detail = self.monitor.get_action(
            "owner-a", credentials["agent_id"], queued["action"]["id"]
        )
        self.assertEqual(detail["result"]["log_excerpt"], "safe application output")
        connection = sqlite3.connect(self.monitor.db_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("safe application output", dump)
        self.assertNotIn(claimed["claim_token"], dump)

    def test_owner_grants_freshness_kill_switch_and_revocation_are_enforced(self):
        credentials = self.pair()
        self.ingest(credentials)
        request = {"operation": "read_logs", "resource_key": "resource_key_1234567890"}
        with self.assertRaises(NotFoundError):
            self.monitor.queue_action("owner-b", credentials["agent_id"], request)

        with patch.dict(os.environ, {"KASUGAI_HOMELAB_ACTIONS_ENABLED": "false"}):
            with self.assertRaises(PermissionDeniedError):
                self.monitor.queue_action("owner-a", credentials["agent_id"], request)

        self.clock[0] += 46
        with self.assertRaises(ConflictError):
            self.monitor.queue_action("owner-a", credentials["agent_id"], request)
        self.monitor.revoke("owner-a", credentials["agent_id"])
        with self.assertRaises(AuthenticationError):
            self.monitor.claim_action(
                credentials["agent_id"], credentials["token"], {"schema_version": 1}
            )

    def test_stale_claim_becomes_unknown_and_is_never_requeued(self):
        credentials = self.pair()
        self.ingest(credentials)
        self.monitor.queue_action(
            "owner-a", credentials["agent_id"],
            {"operation": "read_logs", "resource_key": "resource_key_1234567890"},
        )
        claim = self.monitor.claim_action(
            credentials["agent_id"], credentials["token"], {"schema_version": 1}
        )
        self.clock[0] += 61
        self.assertIsNone(
            self.monitor.claim_action(
                credentials["agent_id"], credentials["token"], {"schema_version": 1}
            )
        )
        detail = self.monitor.get_action("owner-a", credentials["agent_id"], claim["action_id"])
        self.assertEqual(detail["state"], "unknown")

    def test_server_kill_switch_cancels_queued_work_before_delivery(self):
        credentials = self.pair()
        self.ingest(credentials)
        queued = self.monitor.queue_action(
            "owner-a", credentials["agent_id"],
            {"operation": "read_logs", "resource_key": "resource_key_1234567890"},
        )
        with patch.dict(os.environ, {"KASUGAI_HOMELAB_ACTIONS_ENABLED": "false"}):
            self.assertIsNone(
                self.monitor.claim_action(
                    credentials["agent_id"], credentials["token"], {"schema_version": 1}
                )
            )
        detail = self.monitor.get_action(
            "owner-a", credentials["agent_id"], queued["action"]["id"]
        )
        self.assertEqual(detail["state"], "cancelled")

    def test_concurrent_claims_deliver_an_action_only_once(self):
        credentials = self.pair()
        self.ingest(credentials)
        self.monitor.queue_action(
            "owner-a", credentials["agent_id"],
            {"operation": "read_logs", "resource_key": "resource_key_1234567890"},
        )

        def claim():
            return self.monitor.claim_action(
                credentials["agent_id"], credentials["token"], {"schema_version": 1}
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: claim(), range(2)))

        self.assertEqual(sum(result is not None for result in results), 1)


class HomelabSnapshotValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0

    def assert_invalid(self, mutate, error=ValidationError):
        payload = snapshot(self.now)
        mutate(payload)
        with self.assertRaises(error):
            validate_snapshot(payload, now_epoch=self.now)

    def test_rejects_unknown_fields_nonfinite_values_excess_arrays_and_controls(self):
        self.assert_invalid(lambda payload: payload.__setitem__("mounts", []))
        self.assert_invalid(lambda payload: payload["containers"][0].__setitem__("cpu_percent", math.nan))
        self.assert_invalid(lambda payload: payload.__setitem__("containers", payload["containers"] * 101))
        self.assert_invalid(lambda payload: payload["containers"][0].__setitem__("name", "bad\nname"))
        self.assert_invalid(lambda payload: payload["containers"][0].__setitem__("command", "sh"))

    def test_rejects_bad_versions_timestamps_keys_and_oversized_payloads(self):
        self.assert_invalid(lambda payload: payload.__setitem__("schema_version", 2))
        self.assert_invalid(
            lambda payload: payload.__setitem__("captured_at", iso_timestamp(self.now - 86401))
        )
        self.assert_invalid(lambda payload: payload["containers"][0].__setitem__("key", "raw"))
        self.assert_invalid(
            lambda payload: payload["containers"][0].__setitem__("image", "x" * (256 * 1024)),
            PayloadTooLargeError,
        )

    def test_unavailable_engine_requires_fixed_error_and_no_docker_resources(self):
        payload = snapshot(self.now)
        payload["engine"].update(
            {
                "available": False,
                "key": None,
                "server_version": "",
                "operating_system": "",
                "os_type": "",
                "architecture": "",
                "error_code": "daemon_unavailable",
                "container_counts": {"total": 0, "running": 0, "paused": 0, "stopped": 0},
            }
        )
        payload["storage"] = []
        payload["containers"] = []
        normalized = validate_snapshot(payload, now_epoch=self.now)
        self.assertFalse(normalized["engine"]["available"])


if __name__ == "__main__":
    unittest.main()
