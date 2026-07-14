# WebServer Documentation

## Summary
The `WebServer` class sets up the Flask application, DeniLicense-backed authentication routes, project/chat/file/screen-share routes, configuration, logging, and Waitress serving.

## Main Responsibilities
- Creates the Flask app with the repository templates and static files.
- Initializes route modules and registers their blueprints.
- Initializes the encrypted project store and project-management API.
- Connects a DeniLicense session to the Kasugai chat server only after its device-bound activation lease passes signature, issuer, product, installation-key, and time validation.
- Revalidates protected sessions and renews leases through a signed installation-key challenge before expiry.
- Starts Waitress on the configured address and port.

## Key Methods
- `__init__`: Initializes configuration, event handling, Flask, routes, and route dependencies.
- `setup_routes`: Registers all blueprints.
- `server_connect`: Creates the `ChatManager` for the licensed session user.
- `run`: Starts the Waitress web server.
