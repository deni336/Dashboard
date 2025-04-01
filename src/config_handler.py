import configparser
import os
import getpass

DEFAULT_CONFIG = {
    'Application': {
        'buttons': ''
    },
    'WebServer': {
        'port': '8000',
        'address': 'localhost'
    },
    'Logging': {
        'path': 'kasugai/logs/',
        'loglevel': 'INFO'
    },
    'FileTransfer': {
        'avail': ''
    }
}

def get_default_config_path():
    user = getpass.getuser()
    return fr"C:/Users/{user}/Kasugai/config.ini"

class ConfigHandler:
    def __init__(self, config_file=None):
        self.config_file = config_file or get_default_config_path()
        self.config = configparser.ConfigParser()

        if not os.path.exists(self.config_file):
            self._write_default_config()
        else:
            self.config.read(self.config_file)
            self._ensure_all_defaults_exist()

    def _write_default_config(self):
        self.config.read_dict(DEFAULT_CONFIG)
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w') as f:
            self.config.write(f)
        print(f"Created default config at {self.config_file}")

    def _ensure_all_defaults_exist(self):
        updated = False
        for section, options in DEFAULT_CONFIG.items():
            if not self.config.has_section(section):
                self.config.add_section(section)
                updated = True
            for key, val in options.items():
                if not self.config.has_option(section, key):
                    self.config.set(section, key, val)
                    updated = True
        if updated:
            with open(self.config_file, 'w') as f:
                self.config.write(f)
            print("Config updated with missing defaults.")

    def get(self, section, option, fallback=None):
        try:
            return self.config.get(section, option, fallback=fallback).strip(',').strip()
        except configparser.NoOptionError:
            return fallback

    def getint(self, section, option, fallback=None):
        try:
            return self.config.getint(section, option, fallback=fallback)
        except (ValueError, configparser.NoOptionError):
            return fallback

    def getfloat(self, section, option, fallback=None):
        try:
            return self.config.getfloat(section, option, fallback=fallback)
        except (ValueError, configparser.NoOptionError):
            return fallback

    def set(self, section, option, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, str(value))
        with open(self.config_file, 'w') as f:
            self.config.write(f)

    def set_float(self, section, option, value):
        if not isinstance(value, float):
            raise ValueError("Value must be a float.")
        self.set(section, option, str(value))

    def set_config(self, config_data):
        for section, options in config_data.items():
            if not self.config.has_section(section):
                self.config.add_section(section)
            for option, value in options.items():
                self.config.set(section, option, str(value))
        with open(self.config_file, 'w') as f:
            self.config.write(f)
