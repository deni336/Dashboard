import io
import json
import unittest

from launcher_agent.client import AgentProtocolError, LauncherClient, normalize_server_url


class Response:
    def __init__(self, payload=None, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self.body = io.BytesIO(b"" if payload is None else json.dumps(payload).encode())

    def read(self, size=-1):
        return self.body.read(size)

    def close(self):
        pass


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return self.responses.pop(0)


class ClientTests(unittest.TestCase):
    def test_url_policy(self):
        self.assertEqual(normalize_server_url("https://example.com/"), "https://example.com")
        self.assertEqual(normalize_server_url("http://127.0.0.1:5000"), "http://127.0.0.1:5000")
        for value in ("http://example.com", "https://user:pass@example.com", "javascript:alert(1)"):
            with self.assertRaises(Exception):
                normalize_server_url(value)

    def test_pair_and_claim_have_strict_schemas(self):
        opener = Opener(
            [
                Response(
                    {
                        "agent_id": "agent_1234567890123456",
                        "token": "token_1234567890123456",
                        "catalog_interval_seconds": 30,
                        "poll_interval_seconds": 5,
                    }
                ),
                Response(
                    {
                        "schema_version": 1,
                        "run_id": "run_12345678901234567",
                        "claim_token": "claim_1234567890123456",
                        "task_key": "tsk_12345678901234567890",
                        "expires_at": "2030-01-01T00:00:00Z",
                    }
                ),
            ]
        )
        client = LauncherClient("https://example.com", opener=opener)
        paired = client.pair(
            pairing_id="pair_1234567890123456",
            code="c" * 24,
            display_name="Desktop",
            platform="Windows",
            capabilities=["run_tasks"],
        )
        run = client.claim_run(paired.agent_id, paired.token)
        self.assertEqual(run.task_key, "tsk_12345678901234567890")
        claim_request = json.loads(opener.requests[1].data)
        self.assertEqual(claim_request, {"schema_version": 1})

    def test_oversized_response_is_rejected(self):
        response = Response({"value": "x"})
        response.headers = {"Content-Length": str(1000000)}
        client = LauncherClient("https://example.com", opener=Opener([response]))
        with self.assertRaises(AgentProtocolError):
            client.claim_run("agent_1234567890123456", "token_1234567890123456")


if __name__ == "__main__":
    unittest.main()
