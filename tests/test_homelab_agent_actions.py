import unittest

from homelab_agent.actions import ActionExecutor
from homelab_agent.client import ClaimedAction
from homelab_agent.collector import CommandOutput
from homelab_agent.config import HomelabConfig
from src.homelab_monitor import validate_result


LOCAL_ID = "b" * 64
RESOURCE_KEY = "ctr_12345678901234567890"


class FakeDocker:
    def __init__(self, labels=None, state="running", output=None):
        self.labels = labels or {"monitor": "true", "logs": "true", "actions": "restart"}
        self.state = state
        self.output = output or CommandOutput(0, "container-name\n")
        self.local_resources = {}
        self.calls = []

    def collect(self, config):
        self.local_resources = {RESOURCE_KEY: LOCAL_ID}
        return {"available": True, "error_code": None}, [], [], False

    def revalidate(self, resource_key):
        self.calls.append(("revalidate", resource_key))
        if resource_key not in self.local_resources:
            return None
        return {"id": LOCAL_ID, "state": self.state, **self.labels}

    def _run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return self.output


def claim(operation):
    return ClaimedAction(
        "action_123456789012",
        "claim-token-value-123456789",
        operation,
        RESOURCE_KEY,
        "2030-01-01T00:00:00Z",
    )


class ActionTests(unittest.TestCase):
    def test_logs_require_global_and_fresh_container_labels_then_use_fixed_argv(self):
        docker = FakeDocker(output=CommandOutput(0, "password=hunter2\nAuthorization: Bearer abc\n"))
        result = ActionExecutor(
            docker,
            lambda: HomelabConfig(inventory_enabled=True, allow_logs=True),
        ).execute(claim("read_logs"))
        self.assertEqual(result["status"], "succeeded")
        self.assertNotIn("hunter2", result["log_excerpt"])
        self.assertNotIn("Bearer abc", result["log_excerpt"])
        validate_result(result, "read_logs")
        argv, kwargs = docker.calls[-1]
        self.assertEqual(
            argv,
            ["container", "logs", "--tail", "200", "--timestamps", LOCAL_ID],
        )
        self.assertTrue(kwargs["include_stderr"])
        self.assertNotIn(RESOURCE_KEY, argv)

    def test_restart_requires_all_grants_and_running_state_then_uses_fixed_argv(self):
        docker = FakeDocker()
        result = ActionExecutor(
            docker,
            lambda: HomelabConfig(inventory_enabled=True, allow_restart=True),
        ).execute(claim("restart"))
        self.assertEqual(result["status"], "succeeded")
        validate_result(result, "restart")
        argv, kwargs = docker.calls[-2]
        self.assertEqual(
            argv,
            ["container", "restart", "--timeout", "10", LOCAL_ID],
        )
        self.assertEqual(kwargs["timeout"], 20)
        self.assertNotIn(RESOURCE_KEY, argv)

    def test_global_denial_never_touches_docker(self):
        docker = FakeDocker()
        result = ActionExecutor(
            docker,
            lambda: HomelabConfig(inventory_enabled=True, allow_restart=False),
        ).execute(claim("restart"))
        self.assertEqual((result["status"], result["code"]), ("rejected", "policy_denied"))
        self.assertEqual(docker.calls, [])

    def test_removed_label_and_changed_state_fail_before_operation(self):
        for docker, expected in (
            (FakeDocker(labels={"monitor": "true", "logs": "false", "actions": ""}), "policy_denied"),
            (FakeDocker(state="exited"), "invalid_state"),
        ):
            operation = "read_logs" if expected == "policy_denied" else "restart"
            config = HomelabConfig(
                inventory_enabled=True,
                allow_logs=operation == "read_logs",
                allow_restart=operation == "restart",
            )
            with self.subTest(expected=expected):
                result = ActionExecutor(docker, lambda config=config: config).execute(claim(operation))
                self.assertEqual(result["code"], expected)
                self.assertFalse(any(isinstance(call[0], list) for call in docker.calls))

    def test_global_grant_is_reloaded_after_fresh_inspect_before_command(self):
        docker = FakeDocker()
        policies = iter(
            (
                HomelabConfig(inventory_enabled=True, allow_restart=True),
                HomelabConfig(inventory_enabled=True, allow_restart=False),
            )
        )
        result = ActionExecutor(docker, lambda: next(policies)).execute(claim("restart"))
        self.assertEqual((result["status"], result["code"]), ("rejected", "policy_denied"))
        self.assertFalse(any(isinstance(call[0], list) for call in docker.calls))


if __name__ == "__main__":
    unittest.main()
