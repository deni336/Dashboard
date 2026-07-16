import configparser
import getpass
import os
import re
import secrets
import shutil
import sys

DEFAULT_CONFIG = {
    'Application': {
        'buttons': '',
        'resourcefolder': 'backgrounds/'
    },
    'AI': {
        'provider': 'ollama',
        'baseurl': 'http://127.0.0.1:11434/v1',
        'model': 'gpt-oss:20b'
    },
    'Licensing': {
        'apiurl': 'http://127.0.0.1:8080',
        'issuer': 'http://127.0.0.1:8080',
        'productcode': 'KASUGAI',
        'activationlabel': 'Kasugai Dashboard',
        'deviceprivatekey': '',
        'activationid': '',
        'activationlease': ''
    },
    'WebServer': {
        'port': '8000',
        'address': 'localhost',
        'kasaddress': 'localhost',
        'kasport': '8008',
        'mediaport': '50052',
        'publicurl': '',
        'sessionsecret': ''
    },
    'Logging': {
        'path': 'kasugai/logs/',
        'loglevel': 'INFO'
    },
    'FileTransfer': {
        'uploadfolder': 'kasugai/resources/',
        'address': 'localhost',
        'port': '50051'
    },
    'Database': {
        'dbpath': 'chat_history.db',
        'projectdbpath': 'project_manager.db',
        'encryption_key': ''
    }
}

LEGACY_CONFIG_VALUE_MIGRATIONS = {
    ('Application', 'resourcefolder'): {
        'resources': 'backgrounds/',
        'resources/': 'backgrounds/',
        'resources\\': 'backgrounds/',
    },
    ('AI', 'model'): {
        'gpt-5.5': 'gpt-oss:20b',
        'gpt-5.6-sol': 'gpt-oss:20b',
    },
}

BACKGROUND_ACTIVE_MARKER = '.background-active'
BACKGROUND_MANAGED_FILE = re.compile(
    r'^background-[0-9a-f]{16}\.(?:jpg|png|webp)$'
)


def _config_relative_path(config_file, configured_folder):
    expanded_folder = os.path.expanduser(configured_folder)
    if os.path.isabs(expanded_folder):
        return os.path.abspath(expanded_folder)
    config_directory = os.path.dirname(
        os.path.abspath(os.path.expanduser(config_file))
    )
    return os.path.abspath(os.path.join(config_directory, expanded_folder))


def migrate_background_resources(config_file, source_folder, destination_folder):
    """Copy only known Kasugai background assets into dedicated storage."""
    source = _config_relative_path(config_file, source_folder)
    destination = _config_relative_path(config_file, destination_folder)
    if os.path.normcase(source) == os.path.normcase(destination):
        os.makedirs(destination, exist_ok=True)
        return

    os.makedirs(destination, exist_ok=True)
    if not os.path.isdir(source):
        return

    names_to_copy = []
    legacy_jpg = os.path.join(source, 'bg.jpg')
    if os.path.isfile(legacy_jpg) and not os.path.islink(legacy_jpg):
        names_to_copy.append('bg.jpg')

    source_marker = os.path.join(source, BACKGROUND_ACTIVE_MARKER)
    try:
        if os.path.islink(source_marker):
            raise OSError('The background marker cannot be a symbolic link')
        with open(source_marker, encoding='ascii') as marker_file:
            active_filename = marker_file.read(128).strip()
    except (OSError, UnicodeError):
        active_filename = ''
    active_source = os.path.join(source, active_filename)
    if (
        BACKGROUND_MANAGED_FILE.fullmatch(active_filename)
        and os.path.isfile(active_source)
        and not os.path.islink(active_source)
    ):
        names_to_copy.extend((active_filename, BACKGROUND_ACTIVE_MARKER))

    for filename in names_to_copy:
        source_path = os.path.join(source, filename)
        destination_path = os.path.join(destination, filename)
        if os.path.exists(destination_path):
            continue
        temporary_path = os.path.join(
            destination,
            f'.background-migration-{secrets.token_hex(8)}.tmp',
        )
        try:
            shutil.copy2(source_path, temporary_path)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, destination_path)
        finally:
            if os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass


def get_default_config_path():
    configured = os.getenv("KASUGAI_CONFIG_FILE", "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    user = getpass.getuser()
    base_dir = os.path.join(os.path.expanduser("~"), "Kasugai")
    config_file = os.path.join(base_dir, "config.ini")
    return config_file


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
                    value_to_set = val
                    if (section, key) == ('Application', 'resourcefolder'):
                        try:
                            migrate_background_resources(
                                self.config_file,
                                'resources/',
                                val,
                            )
                        except OSError as exc:
                            print(
                                f'WARNING: Could not migrate background storage: {exc}',
                                file=sys.stderr,
                            )
                            # Keep the old effective location so a migration
                            # failure cannot make an existing background vanish.
                            value_to_set = 'resources/'
                    self.config.set(section, key, value_to_set)
                    updated = True
                else:
                    migrations = LEGACY_CONFIG_VALUE_MIGRATIONS.get((section, key), {})
                    current = self.config.get(section, key).strip()
                    if current in migrations:
                        migrated_value = migrations[current]
                        if (section, key) == ('Application', 'resourcefolder'):
                            try:
                                migrate_background_resources(
                                    self.config_file,
                                    current,
                                    migrated_value,
                                )
                            except OSError as exc:
                                print(
                                    f'WARNING: Could not migrate background storage: {exc}',
                                    file=sys.stderr,
                                )
                                continue
                        self.config.set(section, key, migrated_value)
                        updated = True
        if updated:
            with open(self.config_file, 'w') as f:
                self.config.write(f)
            print("Config updated with missing defaults.")

    def get(self, section, option, fallback=None):
        try:
            value = self.config.get(section, option, fallback=fallback)
            if isinstance(value, str):
                return value.strip(',').strip()
            return value
        except (configparser.NoOptionError, configparser.NoSectionError):
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
