import json
import urllib.parse
from src.config_handler import ConfigHandler

class ButtonManager:
    """
    Manages the user-defined quick-launch buttons shown in the left-hand
    button container, persisted as JSON in Application.buttons.
    """
    def __init__(self):
        self.config = ConfigHandler()

    def get_buttons(self):
        raw = self.config.get('Application', 'buttons')
        if not raw:
            return []
        try:
            buttons = json.loads(raw)
            if isinstance(buttons, list):
                normalized = []
                for button in buttons:
                    if not isinstance(button, dict):
                        continue
                    try:
                        name = self._normalize_name(button.get('name'))
                        link = self._normalize_link(button.get('link'))
                    except ValueError:
                        # Older file-path launchers cannot safely execute from a
                        # container. They are replaced by the paired launcher
                        # runner and are deliberately omitted here.
                        continue
                    normalized.append({'name': name, 'link': link})
                return normalized
        except ValueError:
            pass
        # Fall back to the legacy "name:link,name:link" string format
        buttons = []
        for item in raw.split(','):
            if ':' in item:
                name, link = item.split(':', 1)
                try:
                    buttons.append({
                        'name': self._normalize_name(name),
                        'link': self._normalize_link(link),
                    })
                except ValueError:
                    continue
        return buttons

    @staticmethod
    def _normalize_name(value):
        if not isinstance(value, str):
            raise ValueError("Shortcut name is required")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Shortcut name contains unsupported characters")
        value = ' '.join(value.strip().split())
        if not value or len(value) > 80:
            raise ValueError("Shortcut name must contain 1 to 80 characters")
        return value

    @staticmethod
    def _normalize_link(value):
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise ValueError("Shortcut URL is invalid")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Shortcut URL is invalid")
        try:
            parsed = urllib.parse.urlsplit(value.strip())
            parsed.port
        except ValueError as exc:
            raise ValueError("Shortcut URL is invalid") from exc
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Shortcuts must use a credential-free HTTPS URL")
        return urllib.parse.urlunsplit(parsed)

    def _save(self, buttons):
        self.config.set('Application', 'buttons', json.dumps(buttons))

    def add_button(self, name, link):
        name = self._normalize_name(name)
        link = self._normalize_link(link)

        buttons = self.get_buttons()
        if any(b['name'] == name for b in buttons):
            raise ValueError(f"A button named '{name}' already exists")

        buttons.append({'name': name, 'link': link})
        self._save(buttons)
        return buttons

    def remove_button(self, name):
        buttons = self.get_buttons()
        remaining = [b for b in buttons if b['name'] != name]
        if len(remaining) == len(buttons):
            raise KeyError(f"No button named '{name}' found")

        self._save(remaining)
        return remaining

    def get_link(self, name):
        for button in self.get_buttons():
            if button['name'] == name:
                return button['link']
        return None
