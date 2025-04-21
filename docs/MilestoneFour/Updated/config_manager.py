import configparser
import os

default_user = os.getlogin()
file = fr"C:/Users/{default_user}/Kasugai/config.ini"

class ConfigManager:
    def __init__(self, config_file=file):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        if not os.path.exists(self.config_file):
            self.set_config({
                'Database': {
                    'uri': 'mongodb://localhost:27017',
                    'db_name': 'KasugaiDB',
                    'collection': 'ChatHistory'
                }
            })
        self.config.read(self.config_file)

    def get(self, section, option, fallback=None):
        try:
            value = self.config.get(section, option, fallback=fallback)
            return value.strip(',').strip() if isinstance(value, str) else value
        except configparser.NoOptionError:
            return fallback

    def set(self, section, option, value):
        if section not in self.config:
            self.config.add_section(section)
        self.config.set(section, option, value)
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)

    def set_config(self, config_data):
        for section, options in config_data.items():
            if section not in self.config:
                self.config.add_section(section)
            for option, value in options.items():
                self.config.set(section, option, value)
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)
