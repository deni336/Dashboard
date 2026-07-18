import unittest
from pathlib import Path


class ContainerIsolationTests(unittest.TestCase):
    def test_dashboard_compose_files_never_expose_host_control_planes(self):
        root = Path(__file__).resolve().parents[1]
        compose_files = sorted(root.glob("docker-compose*.yml"))
        self.assertTrue(compose_files)

        forbidden = (
            "/var/run/docker.sock",
            "docker_engine",
            "privileged: true",
            "pid: host",
            "network_mode: host",
            "/proc:",
        )
        for compose_file in compose_files:
            source = compose_file.read_text(encoding="utf-8").lower()
            with self.subTest(compose=compose_file.name):
                for value in forbidden:
                    self.assertNotIn(value, source)

    def test_primary_stack_is_read_only_and_drops_server_privileges(self):
        source = (
            Path(__file__).resolve().parents[1] / "docker-compose.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("read_only: true", source)
        self.assertIn("no-new-privileges:true", source)
        self.assertIn("cap_drop:", source)
        self.assertIn("- ALL", source)

    def test_production_wsgi_starts_and_registers_cleanup_for_background_services(self):
        source = (
            Path(__file__).resolve().parents[1] / "src" / "wsgi.py"
        ).read_text(encoding="utf-8")

        self.assertIn("server.automation_scheduler.start()", source)
        self.assertIn("atexit.register(server.stop)", source)


if __name__ == "__main__":
    unittest.main()
