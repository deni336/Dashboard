import configparser
import tempfile
import unittest
from pathlib import Path

from src.config_handler import ConfigHandler


class ConfigHandlerMigrationTests(unittest.TestCase):
    def test_legacy_default_ai_model_is_upgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("[AI]\nmodel = gpt-5.5\n", encoding="utf-8")

            config = ConfigHandler(str(path))

            self.assertEqual(config.get("AI", "model"), "gpt-5.6-sol")

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
