from flask import session, redirect, url_for
from authlib.integrations.flask_client import OAuth
import os

class AuthManager:
    def __init__(self, app=None):
        self.oauth = None
        self.google = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.oauth = OAuth(app)
        self.google = self.oauth.register(
            name='google',
            client_id=os.getenv('GOOGLE_CLIENT_ID') or app.config.get("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv('GOOGLE_CLIENT_SECRET') or app.config.get("GOOGLE_CLIENT_SECRET"),
            access_token_url='https://oauth2.googleapis.com/token',
            authorize_url='https://accounts.google.com/o/oauth2/auth',
            api_base_url='https://www.googleapis.com/oauth2/v1/',
            userinfo_endpoint='https://www.googleapis.com/oauth2/v1/userinfo',
            client_kwargs={'scope': 'openid email profile'}
        )

    def login_user(self):
        redirect_uri = url_for('authorize', _external=True)
        return self.google.authorize_redirect(redirect_uri)

    def logout_user(self):
        session.pop('profile', None)

    def is_authenticated(self):
        return 'profile' in session

    def fetch_user_profile(self):
        token = self.google.authorize_access_token()
        resp = self.google.get('userinfo')
        session['profile'] = resp.json()
        return session['profile']
