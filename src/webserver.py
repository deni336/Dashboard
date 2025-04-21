import os
import webbrowser
import platform
import threading
import secrets
from flask import Flask, session
from waitress import serve
from src.config_handler import ConfigHandler
from src.global_logger import GlobalLogger
from src.event_handler import EventHandler
from src.chat_manager import ChatManager
from src.auth_manager import AuthManager

# Import modular routes
from src.routes.auth_routes import auth_bp, init_auth_routes
from src.routes.chat_routes import chat_bp, init_chat_routes
from src.routes.file_routes import file_bp
from src.routes.button_routes import button_bp, init_button_routes
from src.routes.ui_routes import ui_bp, init_ui_routes

class WebServer:
    def __init__(self):
        self.logger = GlobalLogger.get_logger("WebServer")
        self.config = ConfigHandler()
        self.event_handler = EventHandler()
        self.app = Flask(__name__, template_folder='../sites/templates', static_folder='../sites/static')
        self.app.config['UPLOAD_FOLDER'] = self.config.get("FileTransfer", "uploadfolder")
        self.app.secret_key = secrets.token_hex(16)

        # Initialize OAuth via AuthManager
        self.auth_manager = AuthManager(self.app, self.config)

        self.rooms = {}

        # Initialize modular routes
        init_auth_routes(self.app, self.config, self.server_connect)
        init_button_routes(self.config)
        init_ui_routes(self.config, self.config.get("FileTransfer", "uploadfolder"))

        self.setup_routes()

    def setup_routes(self):
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(chat_bp)
        self.app.register_blueprint(file_bp)
        self.app.register_blueprint(button_bp)
        self.app.register_blueprint(ui_bp)

    def server_connect(self):
        self.logger.info('Connecting to server...')
        self.chat_manager = ChatManager(self.app, session['profile']['name'])
        init_chat_routes(self.chat_manager, self.rooms)

    def open_browser(self):
        port = self.config.getint('WebServer', 'port')
        url = f"http://{self.config.get('WebServer', 'address')}:{port}"
        webbrowser.get('windows-default').open(url)

    def run(self):
        self.event_handler.register_event("WebServer", os.getpid())
        port = self.config.get('WebServer', 'port')
        self.logger.info(f'Starting WebServer using Waitress on port: {port}')
        if platform.system() == "Windows":
            self.open_browser()
        serve(self.app, host=self.config.get('WebServer', 'address'), port=port)

    def shutdown_server(self):
        pass

    def stop(self):
        self.is_running = False
        print("ChatManager stopped.")