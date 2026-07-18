import atexit

from src.webserver import WebServer

server = WebServer()
server.automation_scheduler.start()
atexit.register(server.stop)
app = server.app
