import threading
import time
import sys
import os
import psutil
from __init__ import __version__
from global_logger import GlobalLogger
from config_manager import ConfigManager
from event_handler import EventHandler
from webserver import WebServer

class Main:

    def __init__(self):
        self.logger = GlobalLogger().get_logger("Main")
        self.logger.info(f"Starting Kasugai version {__version__}...")
        self.config = ConfigManager()
        self.event_handler = EventHandler()

        webserver_thread = threading.Thread(target=self.start_webserver, daemon=True)
        webserver_thread.start()

        server_thread = threading.Thread(target=self.start_server, daemon=True)
        server_thread.start()

        self.run()
    
    def start_webserver(self):
        self.webserver = WebServer()
        self.webserver.run()

    def start_server(self):
        self.event_handler.register_event([os.getpid(), "ChatServer"])
    
    def run(self):
        """Main loop to monitor events, process statuses, and handle shutdown signals."""
        try:
            while "Shutdown" not in self.event_handler.events:
                self.process_events()
                #self.monitor_process()
                time.sleep(5)
        except KeyboardInterrupt:
            self.terminate_processes()
            self.logger.info("Program terminated")
            sys.exit(0)

    def process_events(self):
        for event in list(self.event_handler.events):
            if event == "WebServer":
                if not self.is_pid_running(self.event_handler.events['WebServer']):
                    self.logger.warning(f"Process with PID {self.event_handler.events['WebServer']} has stopped running.")
                    self.logger.info(f"Restarting process PID {self.event_handler.events['WebServer']}")
                    self.start_webserver()
            elif event == "ChatServer":
                if not self.is_pid_running(self.event_handler.events['ChatServer']):
                    self.logger.warning(f"Process with PID {self.event_handler.events['ChatServer']} has stopped running.")
                    self.logger.info(f"Restarting process PID {self.event_handler.events['ChatServer']}")
                    self.start_server()
            elif event == "Shutdown":
                self.logger.info("Shutdown signal detected. Shutting down application...")
                self.event_handler.events.clear()
                self.terminate_processes()
                sys.exit(0)

    @staticmethod
    def is_pid_running(pid):
        """Check if a process with the given PID is still running."""
        try:
            p = psutil.Process(pid)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def terminate_processes(self):
        """Terminate all processes."""
        for pid in self.event_handler.events.values():
            try:
                p = psutil.Process(pid)
                p.terminate()
                p.wait(timeout=5)
                self.logger.info(f"Terminated process with PID {pid}.")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self.logger.warning(f"Process with PID {pid} does not exist or access denied.")
            except psutil.TimeoutExpired:
                self.logger.error(f"Timeout expired when trying to terminate process with PID {pid}.")
                p.kill()

if __name__ == "__main__":
    Main()