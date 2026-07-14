# Auth Routes Documentation

## Summary
`init_auth_routes` registers the DeniLicense-backed login and logout routes for the Flask app.

## Flow
- `GET /login` renders the license login form.
- `POST /login` verifies DeniLicense account credentials, optionally claims a license code, finds a matching active product license, activates this installation, and cryptographically verifies the returned signed lease before creating the Kasugai session.
- A Flask request guard verifies the signed lease on protected requests and renews leases nearing expiry with DeniLicense's proof-of-possession challenge flow.
- `GET /authorize` redirects to `/login` for compatibility with older callback links.
- `GET|POST /logout` clears the local Flask session.

## Configuration
The route uses `AuthManager`, which reads the DeniLicense API URL, logical activation issuer, product code, activation label, and installation key from the `[Licensing]` section of `config.ini`.
