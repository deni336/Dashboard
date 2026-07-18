import re
import unittest
from pathlib import Path
from urllib.parse import unquote


MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class DocumentationLinkTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        root = Path(__file__).resolve().parents[1]
        documents = [root / "README.md", *sorted((root / "docs").glob("*.md"))]
        failures = []

        for document in documents:
            text = document.read_text(encoding="utf-8")
            for raw_target in MARKDOWN_LINK.findall(text):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                relative_path = unquote(target.split("#", 1)[0])
                resolved = (document.parent / relative_path).resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    failures.append(f"{document.relative_to(root)} escapes the repository: {target}")
                    continue
                if not resolved.exists():
                    failures.append(f"{document.relative_to(root)} -> {target}")

        self.assertEqual(failures, [], "Broken local documentation links:\n" + "\n".join(failures))

    def test_external_credential_contract_is_documented_and_forwarded(self):
        root = Path(__file__).resolve().parents[1]
        environment = (root / ".env.example").read_text(encoding="utf-8")
        credentials = (root / "docs" / "CREDENTIALS.md").read_text(encoding="utf-8")
        compose_sources = [
            (root / "docker-compose.yml").read_text(encoding="utf-8"),
            (root / "docker-compose.dashboard.yml").read_text(encoding="utf-8"),
        ]

        for name in (
            "DENILICENSE_ACTIVATION_LABEL",
            "KASUGAI_AI_API_KEY",
            "KASUGAI_AI_API_KEY_FILE",
            "OPENAI_API_KEY",
            "OPENAI_API_KEY_FILE",
            "GITHUB_TOKEN",
            "GITHUB_TOKEN_FILE",
            "KASUGAI_IMAP_PASSWORD",
            "KASUGAI_IMAP_PASSWORD_FILE",
        ):
            with self.subTest(setting=name):
                self.assertIn(name, environment)
                self.assertIn(name, credentials)
                for compose in compose_sources:
                    self.assertIn(name, compose)

        for heading in (
            "DeniLicense credentials and claim codes",
            "OpenAI and OpenAI-compatible API keys",
            "GitHub tokens",
            "Gmail app password for IMAP",
            "Companion-agent pairing codes",
            "Optional GHCR credential",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, credentials)


if __name__ == "__main__":
    unittest.main()
