import math
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.personal_dashboard import PersonalDashboardStore
from src.workstation_monitor import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ReplayError,
    ValidationError,
    WorkstationMonitor,
    validate_snapshot,
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


def iso_timestamp(epoch):
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def snapshot(epoch, sequence=1):
    return {
        "schema_version": 1,
        "sequence": sequence,
        "captured_at": iso_timestamp(epoch),
        "system": {"uptime_seconds": 12345},
        "cpu": {
            "percent": 14.2,
            "physical_count": 6,
            "logical_count": 12,
            "frequency_mhz": 3875,
        },
        "memory": {
            "total_bytes": 64 * 1024**3,
            "available_bytes": 40 * 1024**3,
            "used_bytes": 24 * 1024**3,
            "percent": 37.5,
        },
        "disks": [
            {
                "name": "C:",
                "filesystem": "NTFS",
                "total_bytes": 1_000_000_000_000,
                "used_bytes": 500_000_000_000,
                "free_bytes": 500_000_000_000,
                "percent": 50.0,
            }
        ],
        "disk_io": {
            "read_bytes_total": 100,
            "write_bytes_total": 200,
            "read_bps": 10.0,
            "write_bps": 20.0,
        },
        "network": {
            "received_bytes_total": 300,
            "sent_bytes_total": 400,
            "received_bps": 30.0,
            "sent_bps": 40.0,
        },
        "battery": {"percent": 80.0, "plugged": True, "seconds_left": None},
        "gpus": [
            {
                "index": 0,
                "name": "NVIDIA GeForce RTX 3060 Laptop GPU",
                "utilization_percent": 17.0,
                "memory_used_bytes": 1024,
                "memory_total_bytes": 6 * 1024**3,
                "temperature_c": 53.0,
                "power_w": 21.51,
            }
        ],
    }


def pair_payload(pairing, **overrides):
    payload = {
        "pairing_id": pairing["pairing_id"],
        "code": pairing["code"],
        "display_name": "Development laptop",
        "agent_version": "1.0.0",
        "platform": "Windows 11 10.0.26100 x86_64",
        "capabilities": ["battery", "nvidia_gpu"],
    }
    payload.update(overrides)
    return payload


class WorkstationMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000.0]
        self.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_WORKSTATION_MIN_INGEST_SECONDS": "1",
                "KASUGAI_WORKSTATION_RETENTION_HOURS": "24",
                "KASUGAI_WORKSTATION_MAX_AGENTS": "8",
            },
        )
        self.environment.start()
        store = PersonalDashboardStore(TemporaryConfig(self.temporary_directory.name))
        self.monitor = WorkstationMonitor(store, clock=lambda: self.clock[0])

    def tearDown(self):
        self.environment.stop()
        self.temporary_directory.cleanup()

    def pair(self, owner="owner-a"):
        pairing = self.monitor.create_pairing(owner)
        return self.monitor.pair_agent(pair_payload(pairing))

    def test_pairing_is_one_use_expires_and_enforces_attempt_limit(self):
        pairing = self.monitor.create_pairing("owner-a")
        wrong = pair_payload(pairing, code="x" * len(pairing["code"]))
        for _ in range(5):
            with self.assertRaises(AuthenticationError):
                self.monitor.pair_agent(wrong)
        with self.assertRaises(AuthenticationError):
            self.monitor.pair_agent(pair_payload(pairing))

        pairing = self.monitor.create_pairing("owner-a")
        credentials = self.monitor.pair_agent(pair_payload(pairing))
        self.assertIn("agent_id", credentials)
        with self.assertRaises(AuthenticationError):
            self.monitor.pair_agent(pair_payload(pairing))

        expired = self.monitor.create_pairing("owner-a")
        self.clock[0] += 601
        with self.assertRaises(AuthenticationError):
            self.monitor.pair_agent(pair_payload(expired))

    def test_only_newest_unconsumed_pairing_remains_valid(self):
        old_pairing = self.monitor.create_pairing("owner-a")
        new_pairing = self.monitor.create_pairing("owner-a")

        with self.assertRaises(AuthenticationError):
            self.monitor.pair_agent(pair_payload(old_pairing))
        self.assertIn("token", self.monitor.pair_agent(pair_payload(new_pairing)))

    def test_pairing_codes_and_agent_tokens_are_never_stored_raw(self):
        pairing = self.monitor.create_pairing("owner-a")
        credentials = self.monitor.pair_agent(pair_payload(pairing))

        connection = sqlite3.connect(self.monitor.db_path)
        try:
            code_hash = connection.execute(
                "SELECT code_hash FROM workstation_pairings WHERE pairing_id = ?",
                (pairing["pairing_id"],),
            ).fetchone()[0]
            token_hash = connection.execute(
                "SELECT token_hash FROM workstation_agents WHERE agent_id = ?",
                (credentials["agent_id"],),
            ).fetchone()[0]
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()

        self.assertNotEqual(code_hash, pairing["code"])
        self.assertNotEqual(token_hash, credentials["token"])
        self.assertNotIn(pairing["code"], dump)
        self.assertNotIn(credentials["token"], dump)

    def test_ingest_rejects_bad_tokens_replays_rate_abuse_and_revoked_tokens(self):
        credentials = self.pair()
        first = snapshot(self.clock[0], 1)

        with self.assertRaises(AuthenticationError):
            self.monitor.ingest_snapshot(credentials["agent_id"], "wrong-token", first)
        invalid = {"not": "a snapshot"}
        with self.assertRaises(AuthenticationError):
            self.monitor.ingest_snapshot(credentials["agent_id"], "wrong-token", invalid)
        self.monitor.ingest_snapshot(credentials["agent_id"], credentials["token"], first)
        with self.assertRaises(ReplayError):
            self.monitor.ingest_snapshot(credentials["agent_id"], credentials["token"], first)
        with self.assertRaises(RateLimitError):
            self.monitor.ingest_snapshot(
                credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 2)
            )

        self.clock[0] += 1
        self.monitor.ingest_snapshot(
            credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 2)
        )
        self.monitor.revoke("owner-a", credentials["agent_id"], delete_history=False)
        self.clock[0] += 1
        with self.assertRaises(AuthenticationError):
            self.monitor.ingest_snapshot(
                credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 3)
            )

    def test_owner_queries_are_isolated_and_payload_is_encrypted(self):
        credentials = self.pair("owner-a")
        self.monitor.ingest_snapshot(
            credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 1)
        )

        listed = self.monitor.list_workstations("owner-a")["workstations"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["latest_summary"]["cpu_percent"], 14.2)
        self.assertEqual(self.monitor.list_workstations("owner-b"), {"workstations": []})
        with self.assertRaises(NotFoundError):
            self.monitor.latest("owner-b", credentials["agent_id"])
        with self.assertRaises(NotFoundError):
            self.monitor.rename("owner-b", credentials["agent_id"], "Stolen")
        with self.assertRaises(NotFoundError):
            self.monitor.revoke("owner-b", credentials["agent_id"])

        latest = self.monitor.latest("owner-a", credentials["agent_id"])
        self.assertEqual(latest["snapshot"]["sequence"], 1)
        self.assertIn("received_at", latest["snapshot"])
        connection = sqlite3.connect(self.monitor.db_path)
        try:
            encrypted = connection.execute(
                "SELECT payload_encrypted FROM workstation_snapshots"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertNotIn("NVIDIA GeForce", encrypted)
        self.assertNotIn('"cpu"', encrypted)

    def test_status_thresholds_history_bucketing_and_retention(self):
        credentials = self.pair()
        self.monitor.retention_hours = 1
        self.monitor.min_ingest_seconds = 0
        self.monitor.ingest_snapshot(
            credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 1)
        )
        self.assertEqual(self.monitor.list_workstations("owner-a")["workstations"][0]["status"], "online")

        self.clock[0] += 31
        self.assertEqual(self.monitor.list_workstations("owner-a")["workstations"][0]["status"], "stale")
        self.monitor.ingest_snapshot(
            credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 2)
        )
        self.clock[0] += 121
        self.assertEqual(self.monitor.list_workstations("owner-a")["workstations"][0]["status"], "offline")

        self.monitor.ingest_snapshot(
            credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 3)
        )
        history = self.monitor.history(
            "owner-a", credentials["agent_id"], minutes=1441, bucket_seconds=1
        )
        self.assertEqual(history["minutes"], 1440)
        self.assertGreaterEqual(history["bucket_seconds"], 173)
        self.assertLessEqual(len(history["points"]), 500)

        self.clock[0] += 3601
        self.monitor.ingest_snapshot(
            credentials["agent_id"], credentials["token"], snapshot(self.clock[0], 4)
        )
        connection = sqlite3.connect(self.monitor.db_path)
        try:
            sequences = [
                row[0]
                for row in connection.execute(
                    "SELECT sequence FROM workstation_snapshots ORDER BY sequence"
                )
            ]
        finally:
            connection.close()
        self.assertEqual(sequences, [4])


class SnapshotValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0

    def assert_invalid(self, mutate):
        payload = snapshot(self.now)
        mutate(payload)
        with self.assertRaises(ValidationError):
            validate_snapshot(payload, now_epoch=self.now)

    def test_rejects_non_finite_out_of_range_unknown_and_oversized_values(self):
        self.assert_invalid(lambda payload: payload["cpu"].__setitem__("percent", math.nan))
        self.assert_invalid(lambda payload: payload["network"].__setitem__("sent_bps", math.inf))
        self.assert_invalid(lambda payload: payload["memory"].__setitem__("percent", 101))
        self.assert_invalid(lambda payload: payload.__setitem__("processes", []))
        self.assert_invalid(lambda payload: payload.__setitem__("gpus", payload["gpus"] * 9))
        self.assert_invalid(
            lambda payload: payload["gpus"][0].__setitem__("name", "x" * (64 * 1024))
        )

    def test_rejects_unknown_versions_and_implausible_capture_times(self):
        self.assert_invalid(lambda payload: payload.__setitem__("schema_version", 2))
        self.assert_invalid(
            lambda payload: payload.__setitem__(
                "captured_at", payload["captured_at"].replace("T", " ")
            )
        )
        self.assert_invalid(
            lambda payload: payload.__setitem__("captured_at", iso_timestamp(self.now + 301))
        )
        self.assert_invalid(
            lambda payload: payload.__setitem__("captured_at", iso_timestamp(self.now - 86401))
        )

    def test_accepts_null_best_effort_sensor_values(self):
        payload = snapshot(self.now)
        payload["cpu"]["frequency_mhz"] = None
        payload["disk_io"]["read_bps"] = None
        payload["network"]["sent_bps"] = None
        payload["battery"] = None
        payload["gpus"] = []

        normalized = validate_snapshot(payload, now_epoch=self.now)

        self.assertIsNone(normalized["cpu"]["frequency_mhz"])
        self.assertIsNone(normalized["disk_io"]["read_bps"])
        self.assertEqual(normalized["gpus"], [])

    def test_rejects_non_string_field_names_and_unbounded_integers(self):
        self.assert_invalid(lambda payload: payload.__setitem__(1, "invalid"))
        self.assert_invalid(
            lambda payload: payload.__setitem__("sequence", 10**1000)
        )


if __name__ == "__main__":
    unittest.main()
