import os
import webbrowser
import platform
import threading
import secrets
from flask import Flask, session
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix
from src.config_handler import ConfigHandler
from src.global_logger import GlobalLogger
from src.event_handler import EventHandler
from src.chat_manager import ChatManager

# Import modular routes
from src.routes.auth_routes import auth_bp, init_auth_routes
from src.routes.chat_routes import chat_bp, init_chat_routes
from src.routes.file_routes import file_bp
from src.routes.button_routes import button_bp, init_button_routes
from src.routes.settings_routes import settings_bp, init_settings_routes
from src.routes.screenshare_routes import screenshare_bp
from src.routes.ui_routes import ui_bp, init_ui_routes
from src.routes.project_routes import project_bp, init_project_routes


def get_or_create_session_secret(config):
    session_secret = config.get("WebServer", "sessionsecret", fallback="")
    if not session_secret:
        session_secret = secrets.token_urlsafe(32)
        config.set("WebServer", "sessionsecret", session_secret)
    return session_secret


class WebServer:
    def __init__(self):
        self.logger = GlobalLogger.get_logger("WebServer")
        self.config = ConfigHandler()
        self.event_handler = EventHandler()
        self.app = Flask(__name__, template_folder='../sites/templates', static_folder='../sites/static')
        trust_proxy = os.getenv("KASUGAI_TRUST_PROXY", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if trust_proxy:
            # Trust exactly one reverse proxy hop. Never enable this when clients can
            # connect to Waitress directly, since forwarded headers are client-controlled.
            self.app.wsgi_app = ProxyFix(
                self.app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1,
            )
        secure_cookie = os.getenv("KASUGAI_SESSION_COOKIE_SECURE", "").strip().lower()
        self.app.config.update(
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_SECURE=(
                trust_proxy if not secure_cookie else secure_cookie in {"1", "true", "yes", "on"}
            ),
        )
        self.app.config['UPLOAD_FOLDER'] = self.config.get("FileTransfer", "uploadfolder")
        self.app.secret_key = get_or_create_session_secret(self.config)

        self.rooms = {}

        # Initialize modular routes
        init_auth_routes(self.app, self.config, self.server_connect)
        init_button_routes(self.config)
        init_settings_routes(self.config)
        init_ui_routes(self.config, self.config.get("Application", "resourcefolder"))
        init_project_routes(self.config)

        self.setup_routes()

    def setup_routes(self):
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(chat_bp)
        self.app.register_blueprint(file_bp)
        self.app.register_blueprint(button_bp)
        self.app.register_blueprint(settings_bp)
        self.app.register_blueprint(screenshare_bp)
        self.app.register_blueprint(ui_bp)
        self.app.register_blueprint(project_bp)

    def server_connect(self):
        self.logger.info('Connecting to server...')
        self.chat_manager = ChatManager(self.app, session['profile']['name'])
        session['kasugai_user_id'] = self.chat_manager.user.id.uuid if self.chat_manager.user else None
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
