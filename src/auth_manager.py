from authlib.integrations.flask_client import OAuth

class AuthManager:
    """
    Manages OAuth setup for a Flask application, specifically configuring Google OAuth.
    """
    def __init__(self, app, config_handler):
        # Load OAuth credentials from configuration
        app.config['GOOGLE_CLIENT_ID'] = config_handler.get('Application', 'clientid')
        app.config['GOOGLE_CLIENT_SECRET'] = config_handler.get('Application', 'clientsecret')

        # Initialize OAuth integration
        self.oauth = OAuth(app)
        # Register Google OAuth client with full endpoint configuration
        self.google = self.oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            access_token_url='https://oauth2.googleapis.com/token',
            authorize_url='https://accounts.google.com/o/oauth2/auth',
            api_base_url='https://www.googleapis.com/oauth2/v1/',
            userinfo_endpoint='https://www.googleapis.com/oauth2/v1/userinfo',
            jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
            client_kwargs={'scope': 'openid email profile'}
        )

    def get_google_client(self):
        """
        Return the registered Google OAuth client for use in routes.
        """
        return self.google
