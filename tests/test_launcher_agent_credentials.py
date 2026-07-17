import tempfile
import unittest
from pathlib import Path

from launcher_agent.client import ClaimedRun
from launcher_agent.actions import uncertain_result
from launcher_agent.credentials import AgentCredentials, CredentialError, CredentialStore


class ReverseProtector:
    name = "test-reverse"

    def protect(self, plaintext):
        return plaintext[::-1]

    def unprotect(self, ciphertext):
        return ciphertext[::-1]


def credentials():
    return AgentCredentials(
        server_url="https://dashboard.example",
        agent_id="agent_1234567890123456",
        token="token_1234567890123456",
        catalog_interval_seconds=30,
        poll_interval_seconds=5,
        task_key_secret="s" * 43,
    )


class CredentialTests(unittest.TestCase):
    def test_round_trip_sequence_and_result_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            store = CredentialStore(path, ReverseProtector())
            store.save(credentials())
            self.assertNotIn("token_1234567890123456", path.read_text("ascii"))
            current, sequence = store.reserve_sequence()
            self.assertEqual(sequence, 1)
            claim = ClaimedRun(
                "run_12345678901234567",
                "claim_1234567890123456",
                "tsk_12345678901234567890",
                "2030-01-01T00:00:00Z",
            )
            pending = uncertain_result(claim)
            store.save_pending_result(claim.run_id, pending)
            final = dict(pending, status="succeeded", code="ok", summary="done")
            store.save_pending_result(claim.run_id, final)
            self.assertEqual(store.load().pending_result["payload"], final)
            with self.assertRaises(CredentialError):
                store.save_pending_result("other_1234567890123456", pending)
            store.clear_pending_result(claim.run_id)
            self.assertIsNone(store.load().pending_result)
            self.assertEqual(current.task_key_secret, "s" * 43)


if __name__ == "__main__":
    unittest.main()
