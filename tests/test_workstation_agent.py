import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workstation_agent.client import (
    MAX_JSON_BYTES,
    AgentClientError,
    AgentProtocolError,
    AgentSecurityError,
    WorkstationClient,
    normalize_server_url,
)
from workstation_agent.collector import (
    NVIDIA_SMI_ARGV,
    WorkstationCollector,
    collect_nvidia_gpus,
    collect_snapshot,
)
from workstation_agent.credentials import (
    AgentCredentials,
    CredentialError,
    CredentialStore,
    WindowsDPAPIProtector,
)


AGENT_ID = "agent_12345678901"
PAIRING_ID = "pairing_1234567890"


class FakeProtector:
    name = "test-protector"

    def protect(self, plaintext):
        return bytes(value ^ 0xA5 for value in plaintext)

    def unprotect(self, ciphertext):
        return bytes(value ^ 0xA5 for value in ciphertext)


class FakeResponse:
    def __init__(self, payload=b"{}", status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def getcode(self):
        return self.status

    def read(self, amount=-1):
        return self.payload if amount < 0 else self.payload[:amount]

    def close(self):
        self.closed = True


class QueueOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class CollectorTests(unittest.TestCase):
    def test_snapshot_has_bounded_privacy_safe_schema(self):
        snapshot = collect_snapshot(7, include_nvidia=False)

        self.assertEqual(
            set(snapshot),
            {
                "schema_version",
                "sequence",
                "captured_at",
                "system",
                "cpu",
                "memory",
                "disks",
                "disk_io",
                "network",
                "battery",
                "gpus",
            },
        )
        self.assertEqual(snapshot["sequence"], 7)
        self.assertEqual(snapshot["gpus"], [])
        self.assertEqual(set(snapshot["system"]), {"uptime_seconds"})
        self.assertEqual(
            set(snapshot["cpu"]),
            {"percent", "physical_count", "logical_count", "frequency_mhz"},
        )
        self.assertEqual(
            set(snapshot["disk_io"]),
            {"read_bytes_total", "write_bytes_total", "read_bps", "write_bps"},
        )
        self.assertEqual(
            set(snapshot["network"]),
            {"received_bytes_total", "sent_bytes_total", "received_bps", "sent_bps"},
        )
        encoded = json.dumps(snapshot, allow_nan=False).encode("utf-8")
        self.assertLess(len(encoded), MAX_JSON_BYTES)
        serialized_keys = set(snapshot["system"]) | set(snapshot["network"])
        self.assertFalse({"username", "processes", "ip_address", "mac_address"} & serialized_keys)
        for disk in snapshot["disks"]:
            self.assertEqual(
                set(disk),
                {"name", "filesystem", "total_bytes", "used_bytes", "free_bytes", "percent"},
            )
            self.assertNotIn("mountpoint", disk)
            self.assertNotIn("device", disk)

        # Keep the standalone collector and strict dashboard validator locked to
        # the same version-one wire contract.
        from src.workstation_monitor import validate_snapshot

        self.assertEqual(validate_snapshot(snapshot)["sequence"], 7)

    def test_sequence_must_be_positive(self):
        with self.assertRaises(ValueError):
            collect_snapshot(0, include_nvidia=False)

    def test_nvidia_uses_only_the_fixed_non_shell_command(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(
                returncode=0,
                stdout="0, NVIDIA RTX Test, 42, 1024, 8192, 61, 82.5\n",
            )

        gpus = collect_nvidia_gpus(runner)

        self.assertEqual(calls[0][0], list(NVIDIA_SMI_ARGV))
        self.assertIs(calls[0][1]["shell"], False)
        self.assertLessEqual(calls[0][1]["timeout"], 4)
        self.assertEqual(gpus[0]["name"], "NVIDIA RTX Test")
        self.assertEqual(gpus[0]["utilization_percent"], 42.0)
        self.assertEqual(gpus[0]["memory_used_bytes"], 1024 * 1024 * 1024)
        self.assertEqual(gpus[0]["power_w"], 82.5)

    def test_nvidia_failure_is_best_effort(self):
        def missing(*args, **kwargs):
            raise FileNotFoundError

        self.assertEqual(collect_nvidia_gpus(missing), [])

    def test_stateful_collector_derives_rates_without_revealing_interfaces(self):
        first = collect_snapshot(1, include_nvidia=False)
        second = collect_snapshot(2, include_nvidia=False)
        first["disk_io"].update(read_bytes_total=100, write_bytes_total=200)
        first["network"].update(received_bytes_total=300, sent_bytes_total=400)
        second["disk_io"].update(read_bytes_total=300, write_bytes_total=500)
        second["network"].update(received_bytes_total=700, sent_bytes_total=1000)
        ticks = iter((10.0, 12.0))
        collector = WorkstationCollector(include_nvidia=False, monotonic=lambda: next(ticks))
        with patch("workstation_agent.collector.collect_snapshot", side_effect=(first, second)):
            self.assertIsNone(collector.collect(1)["network"]["received_bps"])
            rated = collector.collect(2)
        self.assertEqual(rated["disk_io"]["read_bps"], 100.0)
        self.assertEqual(rated["disk_io"]["write_bps"], 150.0)
        self.assertEqual(rated["network"]["received_bps"], 200.0)
        self.assertEqual(rated["network"]["sent_bps"], 300.0)


class ClientSecurityTests(unittest.TestCase):
    def test_requires_https_except_literal_loopback(self):
        self.assertEqual(normalize_server_url("http://localhost:5000/"), "http://localhost:5000")
        self.assertEqual(normalize_server_url("http://127.0.0.1:5000"), "http://127.0.0.1:5000")
        self.assertEqual(normalize_server_url("http://[::1]:5000"), "http://[::1]:5000")
        self.assertEqual(normalize_server_url("https://dashboard.example.test/"), "https://dashboard.example.test")
        for value in (
            "http://dashboard.example.test",
            "http://192.168.1.4:5000",
            "ftp://dashboard.example.test",
            "https://user:password@dashboard.example.test",
            "https://dashboard.example.test?token=secret",
            "https://dashboard.example.test/#section",
        ):
            with self.subTest(value=value), self.assertRaises(AgentSecurityError):
                normalize_server_url(value)

    def test_pair_uses_exact_contract_and_never_authorization(self):
        response = FakeResponse(
            json.dumps(
                {"agent_id": AGENT_ID, "token": "t" * 32, "interval_seconds": 30}
            ).encode()
        )
        opener = QueueOpener([response])
        client = WorkstationClient("https://dashboard.example.test", opener=opener, max_retries=0)

        result = client.pair(
            pairing_id=PAIRING_ID,
            code="123456789012345678901234",
            display_name="Build workstation",
            platform="Windows 11 x86_64",
            capabilities=["cpu", "memory"],
        )

        request = opener.requests[0][0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://dashboard.example.test/api/workstation-agent/v1/pair")
        self.assertEqual(
            set(body),
            {"pairing_id", "code", "display_name", "agent_version", "platform", "capabilities"},
        )
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(result.agent_id, AGENT_ID)
        self.assertNotIn("t" * 32, repr(result))

    def test_push_uses_bearer_and_exact_agent_path(self):
        opener = QueueOpener([FakeResponse(b'{"accepted":true}')])
        client = WorkstationClient("https://dashboard.example.test", opener=opener, max_retries=0)
        snapshot = {"schema_version": 1, "sequence": 1}

        client.push_snapshot(AGENT_ID, "z" * 32, snapshot)

        request = opener.requests[0][0]
        self.assertEqual(
            request.full_url,
            f"https://dashboard.example.test/api/workstation-agent/v1/agents/{AGENT_ID}/snapshots",
        )
        self.assertEqual(request.get_header("Authorization"), f"Bearer {'z' * 32}")
        self.assertEqual(json.loads(request.data), snapshot)

    def test_redirect_status_is_rejected(self):
        opener = QueueOpener([FakeResponse(b"", status=302, headers={"Location": "https://other.test"})])
        client = WorkstationClient("https://dashboard.example.test", opener=opener, max_retries=3)
        with self.assertRaises(AgentSecurityError):
            client.push_snapshot(AGENT_ID, "z" * 32, {"schema_version": 1})
        self.assertEqual(len(opener.requests), 1)

    def test_oversized_response_is_rejected_and_closed(self):
        response = FakeResponse(b"x" * (MAX_JSON_BYTES + 1))
        opener = QueueOpener([response])
        client = WorkstationClient("https://dashboard.example.test", opener=opener, max_retries=0)
        with self.assertRaises(AgentProtocolError):
            client.push_snapshot(AGENT_ID, "z" * 32, {"schema_version": 1})
        self.assertTrue(response.closed)

    def test_retries_are_bounded_for_network_errors(self):
        sleeps = []
        opener = QueueOpener(
            [urllib.error.URLError("offline"), urllib.error.URLError("offline"), FakeResponse()]
        )
        client = WorkstationClient(
            "https://dashboard.example.test", opener=opener, max_retries=2, sleeper=sleeps.append
        )
        client.push_snapshot(AGENT_ID, "z" * 32, {"schema_version": 1})
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(len(sleeps), 2)

    def test_does_not_retry_authentication_failure(self):
        error = urllib.error.HTTPError("https://dashboard.example.test", 401, "no", {}, io.BytesIO())
        opener = QueueOpener([error])
        client = WorkstationClient("https://dashboard.example.test", opener=opener, max_retries=3)
        with self.assertRaises(AgentClientError):
            client.push_snapshot(AGENT_ID, "z" * 32, {"schema_version": 1})
        self.assertEqual(len(opener.requests), 1)

    def test_rejects_header_unsafe_tokens_before_network_access(self):
        opener = QueueOpener([])
        client = WorkstationClient("https://dashboard.example.test", opener=opener)
        with self.assertRaises(AgentProtocolError):
            client.push_snapshot(AGENT_ID, "safe-token-value-1234\r\nX-Evil: yes", {})
        self.assertEqual(opener.requests, [])


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "credentials.json"
        self.store = CredentialStore(self.path, protector=FakeProtector())
        self.credentials = AgentCredentials(
            server_url="https://dashboard.example.test",
            agent_id=AGENT_ID,
            token="secret-agent-token-value-12345",
            interval_seconds=30,
            sequence=0,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_credentials_are_protected_and_token_repr_is_redacted(self):
        self.store.save(self.credentials)
        raw = self.path.read_bytes()

        self.assertNotIn(self.credentials.token.encode(), raw)
        self.assertNotIn(self.credentials.token, repr(self.credentials))
        self.assertEqual(self.store.load(), self.credentials)

    def test_sequence_is_persisted_before_use_and_never_reused(self):
        self.store.save(self.credentials)
        first_credentials, first = self.store.reserve_sequence()
        recreated_store = CredentialStore(self.path, protector=FakeProtector())
        second_credentials, second = recreated_store.reserve_sequence()

        self.assertEqual(first, 1)
        self.assertEqual(first_credentials.sequence, 1)
        self.assertEqual(second, 2)
        self.assertEqual(second_credentials.sequence, 2)
        self.assertEqual(recreated_store.load().sequence, 2)

    def test_corrupt_and_oversized_records_fail_closed(self):
        self.path.write_text("not-json", encoding="ascii")
        with self.assertRaises(CredentialError):
            self.store.load()
        self.path.write_bytes(b"x" * (64 * 1024 + 1))
        with self.assertRaises(CredentialError):
            self.store.load()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is only available on Windows")
    def test_windows_dpapi_round_trip_is_current_user_protected(self):
        protector = WindowsDPAPIProtector()
        plaintext = b"kasugai-current-user-dpapi-test"
        ciphertext = protector.protect(plaintext)
        self.assertNotEqual(ciphertext, plaintext)
        self.assertEqual(protector.unprotect(ciphertext), plaintext)


if __name__ == "__main__":
    unittest.main()
