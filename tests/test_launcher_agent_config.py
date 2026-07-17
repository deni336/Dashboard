import os
import tempfile
import unittest
from pathlib import Path

from launcher_agent.catalog import build_catalog, task_key
from launcher_agent.config import ConfigError, parse_config


def policy_payload(executable, **changes):
    task = {
        "id": "open-editor",
        "title": "Open editor",
        "description": "Open the approved editor",
        "category": "application",
        "icon": "code-2",
        "requires_confirmation": False,
        "executable": str(executable),
        "args": ["--safe"],
        "cwd": None,
        "timeout_seconds": 10,
    }
    task.update(changes.pop("task", {}))
    payload = {"schema_version": 1, "enabled": True, "tasks": [task]}
    payload.update(changes)
    return payload


class LauncherConfigTests(unittest.TestCase):
    def test_catalog_uses_opaque_key_and_never_transmits_execution_details(self):
        executable = Path(os.path.abspath(__file__))
        policy = parse_config(policy_payload(executable))
        secret = "a" * 43
        catalog = build_catalog(policy, secret, 7)
        self.assertEqual(catalog["sequence"], 7)
        self.assertEqual(catalog["tasks"][0]["key"], task_key(secret, "open-editor"))
        serialized = repr(catalog)
        self.assertNotIn(str(executable), serialized)
        for forbidden in ("executable", "args", "cwd", "timeout_seconds", "open-editor"):
            self.assertNotIn(forbidden, catalog["tasks"][0])

    def test_disabled_policy_publishes_no_tasks(self):
        payload = policy_payload(Path(os.path.abspath(__file__)), enabled=False)
        catalog = build_catalog(parse_config(payload), "b" * 43, 1)
        self.assertEqual(catalog["tasks"], [])

    def test_config_is_strict_and_rejects_relative_executable_and_unknown_fields(self):
        with self.assertRaises(ConfigError):
            parse_config(policy_payload("python.exe"))
        payload = policy_payload(Path(os.path.abspath(__file__)))
        payload["remote_parameters"] = []
        with self.assertRaises(ConfigError):
            parse_config(payload)
        payload = policy_payload(Path(os.path.abspath(__file__)), task={"args": ["ok\x00bad"]})
        with self.assertRaises(ConfigError):
            parse_config(payload)


if __name__ == "__main__":
    unittest.main()
