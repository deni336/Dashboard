import json
import unittest

from homelab_agent.client import AgentProtocolError, HomelabClient


AGENT_ID = "homelab_agent_123456"
PAIRING_ID = "pairing_1234567890"


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
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


class HomelabClientTests(unittest.TestCase):
    def test_pair_uses_separate_homelab_contract(self):
        opener = QueueOpener(
            [
                FakeResponse(
                    json.dumps(
                        {
                            "agent_id": AGENT_ID,
                            "token": "h" * 32,
                            "interval_seconds": 15,
                            "action_poll_interval_seconds": 5,
                        }
                    ).encode()
                )
            ]
        )
        client = HomelabClient("https://dashboard.example.test", opener=opener, max_retries=0)
        result = client.pair(
            pairing_id=PAIRING_ID,
            code="12345678901234567890",
            display_name="Home rack",
            platform="Windows Docker Desktop",
            capabilities=["inventory", "read_logs"],
        )
        request = opener.requests[0][0]
        self.assertEqual(
            request.full_url, "https://dashboard.example.test/api/homelab-agent/v1/pair"
        )
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(result.snapshot_interval_seconds, 15)
        self.assertNotIn("h" * 32, repr(result))

    def test_claim_is_post_poll_and_accepts_only_fixed_operation_and_opaque_key(self):
        claim = {
            "schema_version": 1,
            "action_id": "action_123456789012",
            "claim_token": "claim-token-value-123456789",
            "operation": "read_logs",
            "resource_key": "ctr_12345678901234567890",
            "expires_at": "2030-01-01T00:00:00Z",
        }
        opener = QueueOpener([FakeResponse(json.dumps(claim).encode())])
        client = HomelabClient("https://dashboard.example.test", opener=opener, max_retries=0)
        result = client.claim_action(AGENT_ID, "h" * 32)
        request = opener.requests[0][0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.full_url,
            f"https://dashboard.example.test/api/homelab-agent/v1/agents/{AGENT_ID}/actions/claim",
        )
        self.assertEqual(json.loads(request.data), {"schema_version": 1})
        self.assertEqual(result.operation, "read_logs")
        self.assertNotIn(result.claim_token, repr(result))

    def test_empty_204_claim_means_no_work(self):
        opener = QueueOpener([FakeResponse(b"", status=204)])
        client = HomelabClient("https://dashboard.example.test", opener=opener, max_retries=0)
        self.assertIsNone(client.claim_action(AGENT_ID, "h" * 32))
        self.assertTrue(opener.requests[0][0])

    def test_claim_rejects_commands_parameters_ids_and_urls(self):
        for mutation in (
            {"operation": "exec"},
            {"parameters": {"argv": ["whoami"]}},
            {"resource_key": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
        ):
            claim = {
                "schema_version": 1,
                "action_id": "action_123456789012",
                "claim_token": "claim-token-value-123456789",
                "operation": "restart",
                "resource_key": "ctr_12345678901234567890",
                "expires_at": "2030-01-01T00:00:00Z",
            }
            claim.update(mutation)
            opener = QueueOpener([FakeResponse(json.dumps(claim).encode())])
            with self.subTest(mutation=mutation), self.assertRaises(AgentProtocolError):
                HomelabClient(
                    "https://dashboard.example.test", opener=opener, max_retries=0
                ).claim_action(AGENT_ID, "h" * 32)


if __name__ == "__main__":
    unittest.main()
