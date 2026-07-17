import json
import io
import os
import tempfile
import unittest
from pathlib import Path

from homelab_agent.collector import (
    BoundedCommandRunner,
    CommandOutput,
    HomelabCollector,
    PS_FORMAT,
    opaque_resource_key,
    parse_ports,
)
from homelab_agent.config import HealthCheck, HomelabConfig
from homelab_agent.credentials import new_resource_key_secret
from src.homelab_monitor import validate_snapshot


CONTAINER_ID = "a" * 64


class DockerFixtureRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        joined = " ".join(argv[3:])
        if "context inspect" in joined:
            return CommandOutput(0, json.dumps("npipe:////./pipe/docker_engine"))
        if " version " in f" {joined} ":
            return CommandOutput(
                0,
                json.dumps(
                    {"Version": "28.1.0", "Os": "linux", "Arch": "amd64", "ID": "engine-local"}
                ),
            )
        if " info " in f" {joined} ":
            return CommandOutput(
                0,
                json.dumps(
                    {
                        "ID": "engine-local",
                        "ServerVersion": "28.1.0",
                        "OperatingSystem": "Docker Desktop",
                        "OSType": "linux",
                        "Architecture": "x86_64",
                        "NCPU": 12,
                        "MemTotal": 16 * 1024**3,
                        "Containers": 1,
                        "ContainersRunning": 1,
                        "ContainersPaused": 0,
                        "ContainersStopped": 0,
                        "Images": 12,
                    }
                ),
            )
        if "container ls" in joined:
            return CommandOutput(
                0,
                json.dumps(
                    {
                        "id": CONTAINER_ID,
                        "name": "home-assistant",
                        "image": "ghcr.io/home/assistant:stable",
                        "state": "running",
                        "status": "Up 2 hours",
                        "health": "healthy",
                        "created": "2026-07-16 20:00:00 +0000 UTC",
                        "ports": "0.0.0.0:8123->8123/tcp, [::]:8123->8123/tcp",
                        "compose_project": "home",
                        "compose_service": "assistant",
                        "monitor": "true",
                        "logs": "true",
                        "actions": "restart",
                    }
                )
                + "\n",
            )
        if "container stats" in joined:
            return CommandOutput(
                0,
                json.dumps(
                    {
                        "Container": CONTAINER_ID,
                        "Name": "home-assistant",
                        "CPUPerc": "3.5%",
                        "MemUsage": "512MiB / 4GiB",
                        "MemPerc": "12.5%",
                        "NetIO": "1.2MB / 800kB",
                        "BlockIO": "2MB / 3MB",
                        "PIDs": "42",
                    }
                )
                + "\n",
            )
        if "compose ls" in joined:
            return CommandOutput(0, "[]")
        if "system df" in joined:
            return CommandOutput(
                0,
                json.dumps(
                    {
                        "Type": "Images",
                        "TotalCount": "12",
                        "Active": "1",
                        "Size": "8.5GB",
                        "Reclaimable": "1.2GB (14%)",
                    }
                )
                + "\n",
            )
        if "volume ls" in joined:
            return CommandOutput(0, "volume-one\nvolume-two\n")
        if "network ls" in joined:
            return CommandOutput(0, "bridge\nhost\nnone\n")
        raise AssertionError(f"unexpected Docker argv: {argv}")


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.docker = Path(self.temp.name) / ("docker.exe" if os.name == "nt" else "docker")
        self.docker.touch()
        self.secret = new_resource_key_secret()

    def tearDown(self):
        self.temp.cleanup()

    def test_inventory_uses_only_fixed_bounded_cli_and_emits_server_valid_schema(self):
        runner = DockerFixtureRunner()
        collector = HomelabCollector(
            self.secret, docker_executable=self.docker, runner=runner
        )
        snapshot = collector.collect(
            7,
            HomelabConfig(inventory_enabled=True, allow_logs=True, allow_restart=True),
        )
        normalized = validate_snapshot(snapshot)
        container = normalized["containers"][0]
        self.assertEqual(container["key"], opaque_resource_key(self.secret, "container", CONTAINER_ID))
        self.assertNotIn(CONTAINER_ID, json.dumps(snapshot))
        self.assertTrue(container["grants"]["logs"])
        self.assertEqual(container["grants"]["actions"], ["restart"])
        self.assertEqual(snapshot["engine"]["volume_count"], 2)
        self.assertEqual(snapshot["engine"]["network_count"], 3)
        self.assertEqual(snapshot["storage"][0]["size_bytes"], 8_500_000_000)

        command_tails = [call[0][3:] for call in runner.calls]
        self.assertIn(
            ["container", "ls", "--all", "--no-trunc", "--format", PS_FORMAT],
            command_tails,
        )
        self.assertIn(
            [
                "container",
                "stats",
                "--all",
                "--no-stream",
                "--no-trunc",
                "--format",
                "{{json .}}",
            ],
            command_tails,
        )
        self.assertIn(["compose", "ls", "--all", "--format", "json"], command_tails)
        for argv, kwargs in runner.calls:
            self.assertEqual(argv[0], str(self.docker.resolve()))
            self.assertEqual(argv[1:3], ["--context", "default"])
            self.assertIn("timeout", kwargs)
            self.assertIn("max_output", kwargs)

    def test_disabled_inventory_does_not_execute_docker(self):
        runner = DockerFixtureRunner()
        snapshot = HomelabCollector(
            self.secret, docker_executable=self.docker, runner=runner
        ).collect(1, HomelabConfig())
        self.assertEqual(runner.calls, [])
        self.assertFalse(snapshot["engine"]["available"])
        self.assertEqual(snapshot["engine"]["error_code"], "permission_denied")
        validate_snapshot(snapshot)

    def test_container_visibility_and_grants_require_both_global_policy_and_labels(self):
        runner = DockerFixtureRunner()
        collector = HomelabCollector(
            self.secret, docker_executable=self.docker, runner=runner
        )
        snapshot = collector.collect(1, HomelabConfig(inventory_enabled=True))
        self.assertEqual(snapshot["containers"][0]["grants"], {"logs": False, "actions": []})

    def test_ports_strip_all_binding_addresses(self):
        ports = parse_ports("127.0.0.1:8080->80/tcp, [fe80::1]:5353->53/udp, 443/tcp")
        self.assertEqual(
            ports,
            [
                {"container_port": 80, "host_port": 8080, "protocol": "tcp"},
                {"container_port": 53, "host_port": 5353, "protocol": "udp"},
                {"container_port": 443, "host_port": None, "protocol": "tcp"},
            ],
        )
        self.assertNotIn("127.0.0.1", json.dumps(ports))

    def test_remote_docker_context_is_rejected_before_inventory(self):
        class RemoteContextRunner(DockerFixtureRunner):
            def __call__(self, argv, **kwargs):
                self.calls.append((argv, kwargs))
                return CommandOutput(0, json.dumps("tcp://10.0.0.12:2376"))

        runner = RemoteContextRunner()
        snapshot = HomelabCollector(
            self.secret, docker_executable=self.docker, runner=runner
        ).collect(1, HomelabConfig(inventory_enabled=True))
        self.assertEqual(snapshot["engine"]["error_code"], "context_not_local")
        self.assertEqual(len(runner.calls), 1)
        validate_snapshot(snapshot)

    def test_bounded_runner_never_uses_shell_and_kills_output_overflow(self):
        class FakeProcess:
            def __init__(self):
                self.stdout = io.BytesIO(b"sensitive" * 1024)
                self.killed = False

            def wait(self, timeout):
                return -9 if self.killed else 0

            def kill(self):
                self.killed = True

        captured = {}
        process = FakeProcess()

        def factory(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return process

        runner = BoundedCommandRunner(factory)
        result = runner([str(self.docker.resolve()), "version"], timeout=1, max_output=32)
        self.assertFalse(captured["kwargs"]["shell"])
        self.assertIsNotNone(captured["kwargs"]["stdin"])
        self.assertEqual(result.stdout, "sensitivesensitivesensitivesensitiv"[:32])
        self.assertTrue(result.truncated)
        self.assertTrue(process.killed)


class HealthResponse:
    status = 204
    headers = {"Content-Length": "0"}

    def read(self, amount=-1):
        return b""

    def close(self):
        pass


class HealthOpener:
    def __init__(self):
        self.urls = []

    def open(self, request, timeout):
        self.urls.append((request.full_url, timeout))
        return HealthResponse()


class HealthTests(unittest.TestCase):
    def test_health_target_is_local_config_only_and_url_never_enters_snapshot(self):
        opener = HealthOpener()
        secret = new_resource_key_secret()
        collector = HomelabCollector(secret, health_opener=opener)
        config = HomelabConfig(
            health_checks=(
                HealthCheck("Router", "http://router.lan/health", 1, (204,)),
            )
        )
        snapshot = collector.collect(1, config)
        self.assertEqual(opener.urls, [("http://router.lan/health", 1)])
        self.assertEqual(snapshot["health_checks"][0]["status"], "up")
        self.assertNotIn("router.lan", json.dumps(snapshot))
        validate_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
