from flask import Blueprint, redirect, session, url_for
from src.global_logger import GlobalLogger
from src.auth_manager import AuthManager

auth_bp = Blueprint('auth_bp', __name__)
logger = GlobalLogger.get_logger("AuthRoutes")


def init_auth_routes(app, config_handler, connect_callback):
    """
    Initialize authentication routes using AuthManager.
    """
    # Setup OAuth client via AuthManager
    auth_manager = AuthManager(app, config_handler)
    google = auth_manager.get_google_client()

    @auth_bp.route('/login')
    def login():
        redirect_uri = url_for('auth_bp.authorize', _external=True)
        return google.authorize_redirect(redirect_uri)

    @auth_bp.route('/authorize')
    def authorize():
        token = google.authorize_access_token()
        resp = google.get('userinfo')
        user_info = resp.json()
        session['profile'] = user_info
        connect_callback()
        return redirect(url_for('ui_bp.index'))

    @auth_bp.route('/logout', methods=['GET', 'POST'])
    def logout():
        session.pop('profile', None)
        return redirect(url_for('ui_bp.index'))
