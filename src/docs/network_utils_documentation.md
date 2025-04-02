# NetworkSettingsTool Documentation

## Summary
The `NetworkSettingsTool` class provides functionalities to manage and manipulate network settings on a system. It can retrieve current network settings, list network interfaces, change IP and DNS settings, and maintain a history of changes.

___
## Example Usage
```python
tool = NetworkSettingsTool()
interfaces = tool.get_network_interfaces()
print("Available interfaces:", interfaces)

# Change IP settings for a specific interface
result = tool.change_ip_settings('Ethernet', '192.168.1.10', '255.255.255.0', '192.168.1.1')
print(result)

# Change DNS settings for a specific interface
result = tool.change_dns_settings('Ethernet', '8.8.8.8')
print(result)

# Show history of network settings changes
print(tool.show_history())
```

___
## Code Analysis
### Main functionalities
- Load and save network settings history.
- Retrieve current network settings.
- List available network interfaces.
- Change IP and DNS settings for network interfaces.
- Log changes to network settings.
### Methods
- `__init__`: Initializes the tool and loads history from a file.
- `load_history`: Loads network settings history from a JSON file.
- `save_history`: Saves the current history to a JSON file.
- `get_current_settings`: Retrieves current network settings using `ipconfig`.
- `get_network_interfaces`: Lists available network interfaces using `netsh`.
- `save_current_settings`: Saves the current network settings with a timestamp.
- `change_ip_settings`: Changes the IP settings for a specified interface.
- `change_dns_settings`: Changes the DNS settings for a specified interface.
- `show_history`: Displays the history of network settings changes.
### Fields
- `history_file`: The file path for storing network settings history.
- `history`: A list storing the history of network settings changes.

