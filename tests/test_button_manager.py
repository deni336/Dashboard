import unittest

from src.button_manager import ButtonManager


class ButtonManagerValidationTests(unittest.TestCase):
    def test_shortcuts_are_https_bookmarks_not_host_executables(self):
        self.assertEqual(
            ButtonManager._normalize_link("https://example.com/tools?q=1"),
            "https://example.com/tools?q=1",
        )
        for value in (
            "http://example.com",
            "https://user:secret@example.com",
            r"C:\Windows\System32\notepad.exe",
            "file:///tmp/tool",
            "javascript:alert(1)",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ButtonManager._normalize_link(value)

    def test_shortcut_names_are_bounded_and_control_free(self):
        self.assertEqual(ButtonManager._normalize_name("  Dev   portal "), "Dev portal")
        with self.assertRaises(ValueError):
            ButtonManager._normalize_name("bad\nname")


if __name__ == "__main__":
    unittest.main()
