import configparser
import os

class ConfigManager:
    def __init__(self, config_file='src/config.ini'):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        try:
            if os.path.exists(self.config_file):
                self.config.read(self.config_file)
            else:
                # If the config file doesn't exist, create a default one
                self.config['Application'] = {
                    'buttons': ''
                }
                self.config['WebServer'] = {
                    'port': '8000',
                    'address': 'localhost',
                }
                self.config['Logging'] = {
                    'path': 'logs/',
                    'loglevel': 'INFO'
                }
                with open(self.config_file, 'w') as configfile:
                    self.config.write(configfile)
        except Exception as e:
            print(f"Error initializing ConfigManager: {e}")

    def get(self, section, option, fallback=None):
        """Retrieve a value from the config file with an optional fallback."""
        try:
            value = self.config.get(section, option, fallback=fallback)
            if isinstance(value, str):
                return value.strip(',').strip()
            return value
        except configparser.NoOptionError:
            return fallback

    def getint(self, section, option, fallback=None):
        """Retrieve an integer value from the config file."""
        value = self.get(section, option, fallback=fallback)
        try:
            return int(value) if value is not None else fallback
        except ValueError:
            return fallback

    def getfloat(self, section, option, fallback=None):
        """Retrieve a float value from the config file."""
        value = self.get(section, option, fallback=fallback)
        try:
            return float(value) if value is not None else fallback
        except ValueError:
            return fallback

    def set(self, section, option, value):
        """Set a value in the config file."""
        if section not in self.config:
            self.config.add_section(section)
        self.config.set(section, option, value)
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)
    
    def set_float(self, section, option, value):
        """Set a float value in the config file."""
        if not isinstance(value, float):
            raise ValueError(f"The value for {option} must be a float.")
        if section not in self.config:
            self.config.add_section(section)
        self.config.set(section, option, str(value))
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)

    def set_config(self, config_data):
        """Set multiple values in the config file."""
        for section, options in config_data.items():
            if section not in self.config:
                self.config.add_section(section)
            for option, value in options.items():
                self.config.set(section, option, value)
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)
