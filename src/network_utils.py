import os
import subprocess
import json
from datetime import datetime
from global_logger import GlobalLogger

logger = GlobalLogger.get_logger("NetworkSettings")

class NetworkSettingsTool:
    def __init__(self, history_file='network_settings_history.json'):
        self.history_file = history_file
        self.load_history()

    def load_history(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as file:
                self.history = json.load(file)
        else:
            self.history = []

    def save_history(self):
        with open(self.history_file, 'w') as file:
            json.dump(self.history, file, indent=4)

    def get_current_settings(self):
        result = subprocess.run(['ipconfig', '/all'], capture_output=True, text=True)
        return result.stdout

    def get_network_interfaces(self):
        result = subprocess.run(['netsh', 'interface', 'show', 'interface'], capture_output=True, text=True)
        interfaces = []
        for line in result.stdout.splitlines():
            if 'Dedicated' in line or 'Loopback' in line or 'Wi-Fi' in line or 'Ethernet' in line:
                parts = line.split()
                if len(parts) > 3:
                    interfaces.append(parts[-1])
        return interfaces

    def save_current_settings(self):
        current_settings = self.get_current_settings()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.history.append({
            'timestamp': timestamp,
            'settings': current_settings
        })
        self.save_history()

    def change_ip_settings(self, interface, ip_address, subnet_mask, gateway):
        try:
            subprocess.run([
                'netsh', 'interface', 'ip', 'set', 'address',
                f'name={interface}',
                f'static', ip_address, subnet_mask, gateway
            ], check=True)
            self.save_current_settings()
            return f"Successfully changed IP settings for {interface}"
        except subprocess.CalledProcessError as e:
            logger.error(f"IP setting error: {e}")
            return f"Error: {e}"

    def change_dns_settings(self, interface, dns_address):
        try:
            subprocess.run([
                'netsh', 'interface', 'ip', 'set', 'dns',
                f'name={interface}',
                'static', dns_address
            ], check=True)
            self.save_current_settings()
            return f"Successfully changed DNS settings for {interface}"
        except subprocess.CalledProcessError as e:
            logger.error(f"DNS setting error: {e}")
            return f"Error: {e}"

    def show_history(self):
        return "\n".join([
            f"Timestamp: {entry['timestamp']}\n{entry['settings']}\n{'-' * 40}"
            for entry in self.history
        ])
