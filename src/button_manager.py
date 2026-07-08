import json
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
                return buttons
        except ValueError:
            pass
        # Fall back to the legacy "name:link,name:link" string format
        buttons = []
        for item in raw.split(','):
            if ':' in item:
                name, link = item.split(':', 1)
                buttons.append({'name': name.strip(), 'link': link.strip()})
        return buttons

    def _save(self, buttons):
        self.config.set('Application', 'buttons', json.dumps(buttons))

    def add_button(self, name, link):
        name = name.strip()
        link = link.strip()
        if not name or not link:
            raise ValueError("Button name and link/filepath are both required")

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
