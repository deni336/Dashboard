from global_logger import GlobalLogger
from config_manager import ConfigManager

class EventHandler:
    events = {}

    def __init__(self):
        self.logger = GlobalLogger.get_logger('EventHandler')

    def register_event(self, event):
        self.events[event[1]] = event[0] # event[1] is the event name, event[0] is the PID
        self.logger.info(f"Event received: PID={event[0]}, {event[1]}")

    def remove_event(self, event):
        # Ensure the event exists before removing
        if event[1] in self.events:
            del self.events[event[1]]  # Remove the event by its name (event[1])
            self.logger.info(f"Event removed: PID={event[0]}, {event[1]}")
        else:
            self.logger.warning(f"Event not found: {event[1]}")