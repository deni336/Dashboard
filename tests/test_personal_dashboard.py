import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.personal_dashboard import (
    DeveloperCockpit,
    PersonalDashboardStore,
    _parse_status,
    _run_git,
    _safe_remote,
    repository_root_allowed,
)


class TemporaryConfig:
    def __init__(self, directory):
        self.config_file = str(Path(directory) / "config.ini")
        self.values = {
            ("Database", "dashboarddbpath"): "personal_dashboard.db",
            ("Database", "encryption_key"): Fernet.generate_key().decode("ascii"),
        }

    def get(self, section, option, fallback=None):
        return self.values.get((section, option), fallback)

    def set(self, section, option, value):
        self.values[(section, option)] = str(value)


class PersonalDashboardStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.config = TemporaryConfig(self.root)
        self.store = PersonalDashboardStore(self.config)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_roots_connectors_and_preferences_are_isolated_by_owner(self):
        repository_root = self.root / "repositories"
        repository_root.mkdir()
        added = self.store.add_root("owner-a", str(repository_root), "My repos")
        self.store.save_connector(
            "owner-a",
            "github",
            "github-secret-token-value",
            {"login": "owner-a"},
        )
        self.store.set_repository_favorite("owner-a", "a" * 32, True)

        self.assertEqual(self.store.roots("owner-a")[0]["id"], added["id"])
        self.assertEqual(self.store.roots("owner-b"), [])
        self.assertEqual(self.store.connector_secret("owner-b", "github"), "")
        self.assertFalse(self.store.connector_status("owner-b", "github")["configured"])
        self.assertEqual(self.store.repository_preferences("owner-b"), {})

        with self.assertRaises(KeyError):
            self.store.remove_root("owner-b", added["id"])
        self.assertEqual(len(self.store.roots("owner-a")), 1)

    def test_repository_paths_and_connector_secrets_are_encrypted_at_rest(self):
        repository_root = self.root / "sensitive-workspace-name"
        repository_root.mkdir()
        secret = "github_pat_sensitive-test-token"
        self.store.add_root("owner-a", str(repository_root), "Work")
        self.store.save_connector("owner-a", "github", secret)

        connection = sqlite3.connect(self.store.db_path)
        try:
            encrypted_path = connection.execute(
                "SELECT path FROM developer_roots WHERE owner_key = ?", ("owner-a",)
            ).fetchone()[0]
            encrypted_secret = connection.execute(
                "SELECT secret FROM dashboard_connectors WHERE owner_key = ?",
                ("owner-a",),
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertNotEqual(encrypted_path, str(repository_root))
        self.assertNotIn(str(repository_root), encrypted_path)
        self.assertNotEqual(encrypted_secret, secret)
        self.assertNotIn(secret, encrypted_secret)
        self.assertEqual(self.store.connector_secret("owner-a", "github"), secret)


class DeveloperCockpitBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_repository_allowlist_rejects_prefix_and_parent_traversal(self):
        allowed = self.root / "allowed"
        inside = allowed / "team"
        sibling = self.root / "allowed-escape"
        inside.mkdir(parents=True)
        sibling.mkdir()

        with patch.dict(
            os.environ,
            {
                "KASUGAI_REPOSITORY_ALLOWED_ROOTS": str(allowed),
                "KASUGAI_REPOSITORY_ROOTS": "",
            },
        ):
            self.assertTrue(repository_root_allowed(str(inside)))
            self.assertFalse(repository_root_allowed(str(sibling)))
            traversal = allowed / ".." / sibling.name
            self.assertFalse(repository_root_allowed(str(traversal)))

    def test_discovery_rejects_gitfiles_whose_metadata_escapes_the_scan_root(self):
        scan_root = self.root / "scan"
        scan_root.mkdir()

        ordinary = scan_root / "ordinary"
        (ordinary / ".git").mkdir(parents=True)

        inside_metadata = scan_root / "metadata" / "inside"
        inside_metadata.mkdir(parents=True)
        safe_worktree = scan_root / "safe-worktree"
        safe_worktree.mkdir()
        (safe_worktree / ".git").write_text(
            f"gitdir: {inside_metadata}\n", encoding="utf-8"
        )

        outside_metadata = self.root / "outside-metadata"
        outside_metadata.mkdir()
        escaped_worktree = scan_root / "escaped-worktree"
        escaped_worktree.mkdir()
        (escaped_worktree / ".git").write_text(
            f"gitdir: {outside_metadata}\n", encoding="utf-8"
        )

        malformed = scan_root / "malformed-worktree"
        malformed.mkdir()
        (malformed / ".git").write_text("not a gitdir", encoding="utf-8")

        discovered = {
            Path(path) for path in DeveloperCockpit._discover(str(scan_root), max_depth=3)
        }

        self.assertIn(ordinary.resolve(), discovered)
        self.assertIn(safe_worktree.resolve(), discovered)
        self.assertNotIn(escaped_worktree.resolve(), discovered)
        self.assertNotIn(malformed.resolve(), discovered)


class GitInspectionTests(unittest.TestCase):
    def test_status_parser_counts_sync_and_worktree_state(self):
        status = _parse_status(
            "\n".join(
                (
                    "## main...origin/main [ahead 2, behind 1]",
                    "M  staged.py",
                    " M modified.py",
                    "?? untracked.py",
                    "UU conflicted.py",
                )
            )
        )

        self.assertEqual(status["branch"], "main")
        self.assertEqual(status["upstream"], "origin/main")
        self.assertEqual(status["ahead"], 2)
        self.assertEqual(status["behind"], 1)
        self.assertEqual(status["staged"], 2)
        self.assertEqual(status["modified"], 2)
        self.assertEqual(status["untracked"], 1)
        self.assertEqual(status["conflicted"], 1)
        self.assertTrue(status["dirty"])

    def test_remote_parser_removes_credentials_queries_and_local_paths(self):
        remote = _safe_remote(
            "https://build-user:secret@GitHub.com/example/project.git?token=leak#fragment"
        )

        self.assertEqual(remote["github_slug"], "example/project")
        self.assertEqual(remote["remote_url"], "https://github.com/example/project.git")
        self.assertEqual(remote["web_url"], "https://github.com/example/project")
        self.assertNotIn("secret", str(remote))
        self.assertEqual(
            _safe_remote(str(Path("C:/private/local-repo.git"))),
            {"remote_url": "", "web_url": "", "github_slug": ""},
        )
        self.assertEqual(
            _safe_remote("https://git.internal.example/secret/team.git"),
            {"remote_url": "", "web_url": "", "github_slug": ""},
        )

    @patch("src.personal_dashboard.subprocess.run")
    def test_git_runner_has_a_fixed_command_surface_and_scrubbed_environment(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout="## main\n", stderr="")
        with patch.dict(
            os.environ,
            {"GIT_DIR": "attacker-controlled", "GIT_CONFIG_COUNT": "99"},
        ):
            output = _run_git(
                str(Path("C:/repositories/project")),
                "status",
                "--porcelain=v1",
                "--branch",
            )

        self.assertEqual(output, "## main")
        command = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertIn("--no-pager", command)
        self.assertIn("core.fsmonitor=false", command)
        self.assertIn(f"core.hooksPath={os.devnull}", command)
        self.assertIs(options["stdin"], subprocess.DEVNULL)
        self.assertNotIn("GIT_DIR", options["env"])
        self.assertNotIn("GIT_CONFIG_COUNT", options["env"])
        self.assertEqual(options["env"]["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(options["env"]["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(options["env"]["GIT_TERMINAL_PROMPT"], "0")

        run.reset_mock()
        with self.assertRaises(ValueError):
            _run_git(str(Path("C:/repositories/project")), "fetch", "origin")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
