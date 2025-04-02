# Main Documentation

## Summary
The `Main` class initializes and manages the lifecycle of a web server and a chat server in separate threads. It monitors these processes, restarts them if they stop unexpectedly, and handles shutdown signals.

___
## Example Usage
```python
if __name__ == "__main__":
    main_instance = Main()
```

___
## Code Analysis
### Main functionalities
- Initializes logging, configuration, and event handling.
- Starts the web server and chat server in separate threads.
- Monitors the running status of these servers and restarts them if they stop.
- Handles shutdown signals and terminates processes gracefully.
### Methods
- `__init__`: Sets up logging, configuration, and starts server threads.
- `start_webserver`: Initializes and runs the web server.
- `start_server`: Registers the chat server event.
- `run`: Main loop for monitoring events and handling shutdown.
- `process_events`: Checks server statuses and restarts them if necessary.
- `is_pid_running`: Checks if a process with a given PID is running.
- `terminate_processes`: Terminates all registered processes.
### Fields
- `logger`: Logger instance for logging messages.
- `config`: Configuration handler instance.
- `event_handler`: Event handler instance for managing process events.

