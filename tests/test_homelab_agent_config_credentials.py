import json
import tempfile
import unittest
from pathlib import Path

from homelab_agent.actions import uncertain_result
from homelab_agent.client import ClaimedAction
from homelab_agent.config import ConfigError, HomelabConfig, load_config
from homelab_agent.credentials import AgentCredentials, CredentialStore, new_resource_key_secret


AGENT_ID = "homelab_agent_123456"


class FakeProtector:
    name = "test-protector"

    def protect(self, plaintext):
        return bytes(value ^ 0x6D for value in plaintext)

    def unprotect(self, ciphertext):
        return bytes(value ^ 0x6D for value in ciphertext)


class ConfigTests(unittest.TestCase):
    def test_missing_policy_is_fully_disabled_but_protocol_inventory_capability_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory) / "missing.json")
        self.assertEqual(config, HomelabConfig())
        self.assertEqual(config.capabilities, ["inventory", "read_logs", "restart"])

    def test_policy_accepts_only_explicit_local_grants_and_strict_health_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "inventory_enabled": True,
                        "grants": {"read_logs": True, "restart": False},
                        "health_checks": [
                            {
                                "name": "Home Assistant",
                                "url": "https://home.example.test/health",
                                "timeout_seconds": 2,
                                "expected_statuses": [200, 204],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertTrue(config.inventory_enabled)
        self.assertTrue(config.allow_logs)
        self.assertFalse(config.allow_restart)
        self.assertEqual(config.capabilities, ["inventory", "read_logs", "restart"])
        self.assertEqual(config.health_checks[0].expected_statuses, (200, 204))

    def test_policy_rejects_dashboard_style_dynamic_or_secret_urls(self):
        invalid_checks = [
            {"name": "file", "url": "file:///etc/passwd"},
            {"name": "secret", "url": "https://user:pass@example.test/"},
            {"name": "query", "url": "https://example.test/?token=secret"},
        ]
        for check in invalid_checks:
            with self.subTest(check=check), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "policy.json"
                path.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "inventory_enabled": False,
                            "grants": {},
                            "health_checks": [check],
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(ConfigError):
                    load_config(path)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "credentials.json"
        self.store = CredentialStore(self.path, protector=FakeProtector())
        self.credentials = AgentCredentials(
            server_url="https://dashboard.example.test",
            agent_id=AGENT_ID,
            token="homelab-secret-token-123456789",
            snapshot_interval_seconds=15,
            action_poll_interval_seconds=5,
            resource_key_secret=new_resource_key_secret(),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_homelab_token_secret_and_sequence_are_protected_and_separate(self):
        self.store.save(self.credentials)
        raw = self.path.read_bytes()
        self.assertNotIn(self.credentials.token.encode(), raw)
        self.assertNotIn(self.credentials.resource_key_secret.encode(), raw)
        self.assertNotIn(self.credentials.token, repr(self.credentials))
        first, sequence = self.store.reserve_sequence()
        recreated = CredentialStore(self.path, protector=FakeProtector())
        second, next_sequence = recreated.reserve_sequence()
        self.assertEqual((sequence, next_sequence), (1, 2))
        self.assertEqual((first.sequence, second.sequence), (1, 2))

    def test_action_fallback_and_exact_result_are_persisted_for_idempotent_retry(self):
        self.store.save(self.credentials)
        claim = ClaimedAction(
            "action_123456789012",
            "claim-token-value-123456789",
            "restart",
            "ctr_12345678901234567890",
            "2030-01-01T00:00:00Z",
        )
        fallback = uncertain_result(claim)
        self.store.save_pending_result(claim.action_id, fallback)
        recreated = CredentialStore(self.path, protector=FakeProtector())
        self.assertEqual(recreated.load().pending_result["payload"], fallback)
        recreated.clear_pending_result(claim.action_id)
        self.assertIsNone(recreated.load().pending_result)


if __name__ == "__main__":
    unittest.main()
