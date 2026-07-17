import configparser
import tempfile
import unittest
from pathlib import Path

from src.config_handler import ConfigHandler


class ConfigHandlerMigrationTests(unittest.TestCase):
    def test_background_resource_folder_is_stable_relative_to_the_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            config = ConfigHandler(str(path))

            self.assertEqual(config.get("Application", "resourcefolder"), "backgrounds/")

    def test_legacy_background_moves_to_dedicated_storage_without_copying_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.ini"
            path.write_text(
                "[Application]\nresourcefolder = resources/\n",
                encoding="utf-8",
            )
            legacy_folder = root / "resources"
            legacy_folder.mkdir()
            background = b"legacy-background"
            (legacy_folder / "bg.jpg").write_bytes(background)
            (legacy_folder / "bg.png").write_bytes(b"ordinary-download")
            (legacy_folder / "background-deadbeefdeadbeef.png").write_bytes(
                b"ordinary-download-with-managed-looking-name"
            )

            config = ConfigHandler(str(path))

            destination = root / "backgrounds"
            self.assertEqual(config.get("Application", "resourcefolder"), "backgrounds/")
            self.assertEqual((destination / "bg.jpg").read_bytes(), background)
            self.assertFalse((destination / "bg.png").exists())
            self.assertFalse((destination / "background-deadbeefdeadbeef.png").exists())
            self.assertEqual((legacy_folder / "bg.png").read_bytes(), b"ordinary-download")

    def test_docker_keeps_backgrounds_below_but_separate_from_file_downloads(self):
        entrypoint = (
            Path(__file__).resolve().parents[1] / "docker" / "docker-entrypoint.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "resourcefolder = /app/kasugai/resources/backgrounds/",
            entrypoint,
        )
        self.assertIn("uploadfolder = /app/kasugai/resources/", entrypoint)

    def test_personal_dashboard_database_is_persisted_with_container_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigHandler(str(Path(directory) / "config.ini"))
            self.assertEqual(
                config.get("Database", "dashboarddbpath"),
                "personal_dashboard.db",
            )

        entrypoint = (
            Path(__file__).resolve().parents[1] / "docker" / "docker-entrypoint.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("dashboarddbpath = personal_dashboard.db", entrypoint)

    def test_active_native_format_background_is_preserved_during_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.ini"
            path.write_text(
                "[Application]\nresourcefolder = resources/\n",
                encoding="utf-8",
            )
            source = root / "resources"
            source.mkdir()
            active_name = "background-0123456789abcdef.webp"
            active_bytes = b"verified-webp-placeholder"
            (source / active_name).write_bytes(active_bytes)
            (source / ".background-active").write_text(active_name, encoding="ascii")
            (source / "background-fedcba9876543210.png").write_bytes(
                b"unreferenced-download"
            )

            config = ConfigHandler(str(path))

            destination = root / "backgrounds"
            self.assertEqual(config.get("Application", "resourcefolder"), "backgrounds/")
            self.assertEqual((destination / active_name).read_bytes(), active_bytes)
            self.assertEqual(
                (destination / ".background-active").read_text(encoding="ascii"),
                active_name,
            )
            self.assertFalse(
                (destination / "background-fedcba9876543210.png").exists()
            )

    def test_missing_legacy_resource_option_still_migrates_the_background(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.ini"
            path.write_text("[Application]\nbuttons =\n", encoding="utf-8")
            source = root / "resources"
            source.mkdir()
            background = b"legacy-background-without-config-option"
            (source / "bg.jpg").write_bytes(background)

            config = ConfigHandler(str(path))

            self.assertEqual(config.get("Application", "resourcefolder"), "backgrounds/")
            self.assertEqual((root / "backgrounds" / "bg.jpg").read_bytes(), background)
            self.assertEqual((source / "bg.jpg").read_bytes(), background)

    def test_legacy_default_ai_model_is_upgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("[AI]\nmodel = gpt-5.5\n", encoding="utf-8")

            config = ConfigHandler(str(path))

            self.assertEqual(config.get("AI", "model"), "gpt-oss:20b")

    def test_previous_cloud_default_is_migrated_to_local_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("[AI]\nmodel = gpt-5.6-sol\n", encoding="utf-8")

            config = ConfigHandler(str(path))

            self.assertEqual(config.get("AI", "provider"), "ollama")
            self.assertEqual(config.get("AI", "baseurl"), "http://127.0.0.1:11434/v1")
            self.assertEqual(config.get("AI", "model"), "gpt-oss:20b")

    def test_custom_ai_model_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            parser = configparser.ConfigParser()
            parser["AI"] = {"model": "custom-model-deployment"}
            with path.open("w", encoding="utf-8") as config_file:
                parser.write(config_file)

            config = ConfigHandler(str(path))

            self.assertEqual(config.get("AI", "model"), "custom-model-deployment")


if __name__ == "__main__":
    unittest.main()
