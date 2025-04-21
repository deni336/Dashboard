import threading
import time
import sys
import os
import psutil
from __init__ import __version__
from global_logger import GlobalLogger
from config_manager import ConfigManager
from event_handler import EventHandler
from factory import ServerFactory

class Main:
    def __init__(self):
        self.logger = GlobalLogger().get_logger("Main")
        self.logger.info(f"Starting Kasugai version {__version__}...")
        self.config = ConfigManager()
        self.event_handler = EventHandler()

        self.webserver_thread = threading.Thread(target=self.launch_component, args=("WebServer",), daemon=True)
        self.chatserver_thread = threading.Thread(target=self.launch_component, args=("ChatServer",), daemon=True)

        self.webserver_thread.start()
        self.chatserver_thread.start()
        self.run()

    def launch_component(self, component_type):
        server = ServerFactory.create_server(component_type)
        if component_type == "WebServer":
            self.webserver = server
            self.webserver.run()
        elif component_type == "ChatServer":
            self.event_handler.register_event([os.getpid(), "ChatServer"])

    def run(self):
        try:
            while "Shutdown" not in self.event_handler.events:
                self.process_events()
                time.sleep(5)
        except KeyboardInterrupt:
            self.terminate_processes()
            self.logger.info("Program terminated")
            sys.exit(0)

    def process_events(self):
        for event in list(self.event_handler.events):
            pid = self.event_handler.events[event]
            if not self.is_pid_running(pid):
                self.logger.warning(f"Process {event} with PID {pid} has stopped. Restarting...")
                self.launch_component(event)

    @staticmethod
    def is_pid_running(pid):
        try:
            p = psutil.Process(pid)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def terminate_processes(self):
        for pid in self.event_handler.events.values():
            try:
                p = psutil.Process(pid)
                p.terminate()
                p.wait(timeout=5)
                self.logger.info(f"Terminated PID {pid}")
            except Exception:
                self.logger.warning(f"Could not terminate PID {pid}")

if __name__ == "__main__":
    Main()
