import os
import subprocess
import json
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, ttk
import ctypes, sys

# Check if the script is running with administrator privileges
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# Re-launch the script as administrator if not already elevated
if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, '"' + os.path.abspath(__file__) + '"', None, 1)
    sys.exit(0)

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
            return f"Error: {e}"

    def show_history(self):
        return "\n".join([
            f"Timestamp: {entry['timestamp']}\n{entry['settings']}\n{'-' * 40}"
            for entry in self.history
        ])

class NetworkSettingsApp:
    def __init__(self, root):
        self.tool = NetworkSettingsTool()
        self.root = root
        self.root.title("Network Settings Adjustment Tool")

        # UI Elements
        self.output_text = scrolledtext.ScrolledText(root, width=80, height=20, wrap=tk.WORD)
        self.output_text.grid(column=0, row=0, columnspan=4, padx=10, pady=10)

        self.show_button = tk.Button(root, text="Show Current Settings", command=self.show_current_settings)
        self.show_button.grid(column=0, row=1, padx=5, pady=5)

        self.save_button = tk.Button(root, text="Save Current Settings", command=self.save_current_settings)
        self.save_button.grid(column=1, row=1, padx=5, pady=5)

        self.history_button = tk.Button(root, text="Show History", command=self.show_history)
        self.history_button.grid(column=2, row=1, padx=5, pady=5)

        self.change_ip_button = tk.Button(root, text="Change IP Settings", command=self.change_ip_settings)
        self.change_ip_button.grid(column=0, row=2, padx=5, pady=5)

        self.change_dns_button = tk.Button(root, text="Change DNS Settings", command=self.change_dns_settings)
        self.change_dns_button.grid(column=1, row=2, padx=5, pady=5)

        # Dropdown for selecting network interface
        self.interface_label = tk.Label(root, text="Select Network Interface:")
        self.interface_label.grid(column=0, row=3, padx=5, pady=5)

        self.interface_combobox = ttk.Combobox(root, values=self.tool.get_network_interfaces())
        self.interface_combobox.grid(column=1, row=3, padx=5, pady=5)

    def show_current_settings(self):
        settings = self.tool.get_current_settings()
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.INSERT, settings)

    def save_current_settings(self):
        self.tool.save_current_settings()
        messagebox.showinfo("Info", "Current settings saved successfully.")

    def show_history(self):
        history = self.tool.show_history()
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.INSERT, history)

    def change_ip_settings(self):
        interface = self.interface_combobox.get()
        if not interface:
            messagebox.showwarning("Warning", "Please select a network interface.")
            return
        ip_address = self.get_user_input("Enter new IP address")
        subnet_mask = self.get_user_input("Enter new Subnet Mask")
        gateway = self.get_user_input("Enter new Gateway")
        if ip_address and subnet_mask and gateway:
            result = self.tool.change_ip_settings(interface, ip_address, subnet_mask, gateway)
            messagebox.showinfo("Info", result)

    def change_dns_settings(self):
        interface = self.interface_combobox.get()
        if not interface:
            messagebox.showwarning("Warning", "Please select a network interface.")
            return
        dns_address = self.get_user_input("Enter new DNS address")
        if dns_address:
            result = self.tool.change_dns_settings(interface, dns_address)
            messagebox.showinfo("Info", result)

    def get_user_input(self, prompt):
        return simpledialog.askstring("Input", prompt, parent=self.root)

if __name__ == "__main__":
    root = tk.Tk()
    app = NetworkSettingsApp(root)
    root.mainloop()