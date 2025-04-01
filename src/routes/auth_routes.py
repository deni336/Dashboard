# routes/auth_routes.py
from flask import Blueprint, redirect, session, url_for
from global_logger import GlobalLogger

auth_bp = Blueprint('auth_bp', __name__)
logger = GlobalLogger.get_logger("AuthRoutes")

def init_auth_routes(app, oauth, connect_callback):
    google = oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        access_token_url='https://oauth2.googleapis.com/token',
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://www.googleapis.com/oauth2/v1/userinfo',
        jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
        client_kwargs={'scope': 'openid email profile'},
    )

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
