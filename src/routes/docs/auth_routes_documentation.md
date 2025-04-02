# Auth Routes Documentation

## Summary
This function initializes authentication routes for a Flask application using OAuth2 with Google as the provider. It sets up routes for login, authorization, and logout, handling user authentication and session management.

___
## Example Usage
```python
from flask import Flask
from authlib.integrations.flask_client import OAuth
from src.routes.auth_routes import init_auth_routes

app = Flask(__name__)
oauth = OAuth(app)

def on_user_connected():
    print("User connected")

init_auth_routes(app, oauth, on_user_connected)
```

___
## Code Analysis
### Inputs
- `app`: A Flask application instance.
- `oauth`: An OAuth client instance from the `authlib` library.
- `connect_callback`: A callback function to be executed after a successful login.
### Flow
1. Registers Google as an OAuth provider with necessary credentials and endpoints.
2. Defines a `/login` route that redirects users to Google's OAuth authorization page.
3. Defines an `/authorize` route that handles the OAuth callback, retrieves user information, stores it in the session, and calls the `connect_callback`.
4. Defines a `/logout` route that clears the user session and redirects to the application's index page.
### Outputs
- The function does not return any value. It sets up routes within the Flask application for handling authentication.

