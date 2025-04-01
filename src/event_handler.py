from src.global_logger import GlobalLogger

class EventHandler:
    def __init__(self, logger=None):
        self.logger = logger or GlobalLogger.get_logger('EventHandler')
        self._events = {}

    def register_event(self, name, pid):
        """Register a process event by name and PID."""
        self._events[name] = pid
        self.logger.info(f"Event registered: {name} with PID={pid}")

    def remove_event(self, name):
        """Remove an event by name."""
        if name in self._events:
            del self._events[name]
            self.logger.info(f"Event removed: {name}")
        else:
            self.logger.warning(f"Tried to remove nonexistent event: {name}")

    def get_pid(self, name):
        return self._events.get(name)

    def list_events(self):
        return self._events.copy()

    def clear_events(self):
        self.logger.info("Clearing all registered events.")
        self._events.clear()

    def has_event(self, name):
        return name in self._events
