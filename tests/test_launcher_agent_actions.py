import io
import os
import tempfile
import unittest
from pathlib import Path

from launcher_agent.actions import MAX_OUTPUT_BYTES, TaskExecutor
from launcher_agent.catalog import task_key
from launcher_agent.client import ClaimedRun
from launcher_agent.config import parse_config


SECRET = "k" * 43


def make_policy(executable, *, enabled=True, task_id="task-one", timeout=5):
    return parse_config(
        {
            "schema_version": 1,
            "enabled": enabled,
            "tasks": [
                {
                    "id": task_id,
                    "title": "Safe task",
                    "description": "Locally approved",
                    "category": "script",
                    "icon": "play",
                    "requires_confirmation": True,
                    "executable": str(executable),
                    "args": ["literal;not-a-shell-command"],
                    "cwd": None,
                    "timeout_seconds": timeout,
                }
            ],
        }
    )


def claim(key=None):
    return ClaimedRun(
        "run_12345678901234567",
        "claim_1234567890123456",
        key or task_key(SECRET, "task-one"),
        "2030-01-01T00:00:00Z",
    )


class FakeProcess:
    def __init__(self, output=b"done", running=False):
        self.stdout = io.BytesIO(output)
        self.returncode = None if running else 0
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.executable = Path(os.path.abspath(__file__))

    def test_only_local_argv_is_used_with_no_shell_stdin_or_sensitive_environment(self):
        calls = []

        def popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return FakeProcess()

        result = TaskExecutor(lambda: make_policy(self.executable), SECRET, popen=popen).execute(claim())
        self.assertEqual(result["code"], "ok")
        argv, kwargs = calls[0]
        self.assertEqual(argv, [str(self.executable.resolve()), "literal;not-a-shell-command"])
        self.assertFalse(kwargs["shell"])
        self.assertIsNotNone(kwargs["stdin"])
        self.assertNotIn("claim_1234567890123456", repr(argv))
        self.assertNotIn("PATH", {key.upper() for key in kwargs["env"]})

    def test_disabled_or_changed_policy_rejects_before_process_creation(self):
        calls = []
        executor = TaskExecutor(
            lambda: make_policy(self.executable, enabled=False),
            SECRET,
            popen=lambda *args, **kwargs: calls.append(args),
        )
        self.assertEqual(executor.execute(claim())["code"], "policy_denied")
        missing = TaskExecutor(
            lambda: make_policy(self.executable, task_id="replacement"),
            SECRET,
            popen=lambda *args, **kwargs: calls.append(args),
        ).execute(claim())
        self.assertEqual(missing["code"], "task_missing")
        self.assertEqual(calls, [])

    def test_output_limit_kills_process_and_returns_bounded_result(self):
        process = FakeProcess(b"x" * (MAX_OUTPUT_BYTES + 1), running=True)
        result = TaskExecutor(
            lambda: make_policy(self.executable), SECRET, popen=lambda *a, **k: process
        ).execute(claim())
        self.assertTrue(process.killed)
        self.assertEqual(result["code"], "output_limit")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["output"].encode()), MAX_OUTPUT_BYTES)

    def test_timeout_kills_process(self):
        process = FakeProcess(b"", running=True)
        ticks = iter((0.0, 2.0, 2.0, 2.0))
        result = TaskExecutor(
            lambda: make_policy(self.executable, timeout=1),
            SECRET,
            popen=lambda *a, **k: process,
            monotonic=lambda: next(ticks),
        ).execute(claim())
        self.assertTrue(process.killed)
        self.assertEqual(result["code"], "timed_out")


if __name__ == "__main__":
    unittest.main()
