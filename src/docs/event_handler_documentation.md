# EventHandler Documentation

## Summary
The `EventHandler` class manages process events by allowing registration, removal, and querying of events. It uses a logger to record actions performed on the events.

___
## Example Usage
```python
from src.event_handler import EventHandler

# Initialize an EventHandler instance
event_handler = EventHandler()

# Register an event
event_handler.register_event('Process1', 1234)

# Check if an event exists
if event_handler.has_event('Process1'):
    print("Event exists")

# Get the PID of an event
pid = event_handler.get_pid('Process1')
print(f"PID: {pid}")

# List all events
events = event_handler.list_events()
print(events)

# Remove an event
event_handler.remove_event('Process1')

# Clear all events
event_handler.clear_events()
```

___
## Code Analysis
### Main functionalities
The main functionalities of the `EventHandler` class include registering events with a name and PID, removing events, checking for the existence of an event, retrieving the PID of an event, listing all events, and clearing all registered events.
### Methods
- `__init__`: Initializes the `EventHandler` with an optional logger.
- `register_event`: Registers an event with a name and PID.
- `remove_event`: Removes an event by name.
- `get_pid`: Retrieves the PID of a registered event by name.
- `list_events`: Returns a copy of all registered events.
- `clear_events`: Clears all registered events.
- `has_event`: Checks if an event exists by name.
### Fields
- `logger`: A logger instance used for logging actions.
- `_events`: A dictionary storing event names as keys and their corresponding PIDs as values.

