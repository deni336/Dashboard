# Kasugai Dashboard

Kasugai is a Flask dashboard and Go gRPC service for project management, chat, file transfer, and screen sharing. Access is gated by a device-bound DeniLicense activation lease.

## Requirements

- Python 3.14
- Go 1.24 or newer for the gRPC service
- A running DeniLicense service with a product and license for the configured product code
- Docker Desktop and Docker Compose for the container workflow

## DeniLicense behavior

Kasugai follows the DeniLicense v1.1 product integration contract:

- Account login and optional one-time claim code
- Existing directly assigned licenses without a claim code
- Ed25519 installation identity and activation-seat approval
- `dllease1` signature verification using the DeniLicense JWK set
- Exact issuer, product, installation-key, and lease-time binding
- Proof-of-possession renewal before lease expiry
- Entitlements accepted only from verified signed lease claims

The DeniLicense package is pinned to a specific repository commit in `requirements.txt` so shared builds use the same client contract.

## Project workspace

Open **Projects** from the dashboard navigation to manage a user-scoped portfolio. The workspace includes:

- Project status, health, priority, schedule, budget, and progress
- Tasks and milestones with owners, due dates, and overdue indicators
- Risk, assumption, issue, dependency, and decision logs
- Meeting notes, attendees, decisions, action items, and next steps
- Stakeholder influence and engagement tracking
- Email invitations with viewer or editor access
- Global or project-specific links for GitHub, Gmail, Calendar, Drive, Teams, Slack, Jira, Notion, and other web tools

Project data is stored in `project_manager.db`. Descriptions, meeting content, RAID details, stakeholder notes, connection account labels, and invited email addresses are encrypted at rest with the `[Database] encryption_key`. Every owned project is keyed to the authenticated DeniLicense user ID; each user receives a private portfolio and can reuse project codes used by another owner. Accepted shares are added separately through the collaboration access table.

Connections are validated HTTPS/HTTP shortcuts, not per-user OAuth integrations, and URLs containing embedded credentials are rejected. Each authenticated user can save a personal OpenAI API key from the key control in the Projects top bar. Personal keys are encrypted in `project_manager.db`, scoped to that user's authenticated ID, and never returned by the API after saving. An optional deployment-wide OpenAI key can still be supplied to the dashboard container as a controlled fallback.

### Sharing projects

Project owners can open the **Share project** control, enter an email address, and choose **Viewer** or **Editor** access. Kasugai creates a one-time invitation link valid for seven days. Copy the link or use **Email invitation** to open the system mail client with a prepared message. Kasugai does not send email through an SMTP provider.

The recipient must sign in with the exact invited email address and must have their own valid DeniLicense access to the configured Kasugai product. Viewers have read-only access. Editors can update project content but cannot share or delete the project. Portfolio-level connection links remain private; only project-specific links are visible to collaborators. Owners can change a collaborator's role, issue a new pending invitation link, or revoke access at any time.

## Local setup

Create an environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start the DeniLicense application, then create or edit `%USERPROFILE%\Kasugai\config.ini`:

```ini
[Licensing]
apiurl = http://127.0.0.1:8080
issuer = http://127.0.0.1:8080
productcode = KASUGAI
activationlabel = Kasugai Dashboard
deviceprivatekey =
```

`productcode` must exactly match the DeniLicense product. `issuer` must exactly match the DeniLicense `DENILICENSE_ACTIVATION_ISSUER`; it is a signed logical identity and may differ from the address used to reach the API.

Start the Go service in one terminal:

```powershell
Set-Location kasugai_server
go run .
```

Start the dashboard from the repository root in another terminal:

```powershell
python main.py
```

Open `http://localhost:8000`.

## Docker Compose

DeniLicense v1.1 exposes its API to other containers on the external `denilicense-network`. Start DeniLicense first so that network exists:

```powershell
Set-Location ..\DeniLicense
docker compose up --build -d --wait
```

Create a `.env` file for Kasugai:

```ini
DENILICENSE_API_URL=http://denilicense-api:8080
DENILICENSE_ISSUER=http://127.0.0.1:8080
DENILICENSE_PRODUCT_CODE=KASUGAI
KASUGAI_PUBLIC_URL=
KASUGAI_DASHBOARD_BIND_HOST=127.0.0.1
KASUGAI_TRUST_PROXY=false
KASUGAI_SESSION_COOKIE_SECURE=
OPENAI_API_KEY=
OPENAI_API_KEY_FILE=
OPENAI_MODEL=gpt-5.6-sol
KASUGAI_AI_ALLOWED_USERS=owner@example.com
KASUGAI_AI_SOURCE_ALLOWED_USERS=owner@example.com
GITHUB_TOKEN=
GITHUB_TOKEN_FILE=
KASUGAI_GITHUB_TOKEN_ALLOWLIST=your-org/project,your-org/*
KASUGAI_IMAP_HOST=imap.gmail.com
KASUGAI_IMAP_PORT=993
KASUGAI_IMAP_USERNAME=
KASUGAI_IMAP_PASSWORD=
KASUGAI_IMAP_PASSWORD_FILE=
```

Set `KASUGAI_PUBLIC_URL` to the externally reachable origin used by invitees, for example `https://kasugai.example.com`. Leaving it blank builds invitation links from the current request host, which is suitable for local use.

The project AI copilot uses the OpenAI Responses API and defaults to
[`gpt-5.6-sol`](https://developers.openai.com/api/docs/guides/latest-model), the
current explicit GPT-5.6 flagship target. Every authenticated user can open
**OpenAI API key settings** in the Projects top bar and submit their own key.
Kasugai encrypts that key server-side and uses it only for that user's preview
requests, including when the user is editing a shared project. The key is never
returned to the browser, project owner, or another collaborator. Personal keys
take precedence over the optional deployment `OPENAI_API_KEY`. The deployment
key is used only for accounts explicitly listed in `KASUGAI_AI_ALLOWED_USERS`,
which preserves the previous administrator-managed setup without silently
moving a personal-key failure onto the server's billing account.

This is OpenAI API-key authentication, not a ChatGPT login or subscription
connection. Requests use the limits and billing of the OpenAI API project that
issued the selected key. Serve Kasugai through HTTPS before accepting personal
keys in production. [OpenAI recommends keeping API keys in a secure server-side
location](https://developers.openai.com/api/docs/guides/production-best-practices#api-keys)
rather than exposing or hard-coding them in client code.

Public GitHub repositories can be read without a token. When `GITHUB_TOKEN` is set, it is sent only for
repositories or organizations explicitly listed in
`KASUGAI_GITHUB_TOKEN_ALLOWLIST` (`owner/repo` or `owner/*`). Gmail connections
use the configured read-only IMAP mailbox; for Gmail, use an app password rather
than the primary account password. The connection's nonblank Account field must
exactly match `KASUGAI_IMAP_USERNAME`. Project workspace context is sent to
OpenAI only when an authorized editor generates a preview. Deployment-wide
GitHub and IMAP sources are available only when that project owner also appears
in `KASUGAI_AI_SOURCE_ALLOWED_USERS`; leave this separate list empty to disable
all linked-source retrieval. Shared editors and other AI-enabled owners cannot
exercise those credentials. Raw source bodies
are not returned to the browser. Proposals expire after 15 minutes, are rejected
if the project or targeted records changed, and are not written until the editor
selects and confirms the individual actions.

The AI copilot runs in the Flask dashboard container, not the standalone Go
chat/media VPS container. Environment values must be supplied by Compose or the
process manager; running `python main.py` directly does not load `.env`
automatically.

For production deployment-wide credentials, prefer the corresponding `*_FILE`
settings and mount each credential as a Docker secret or read-only file. When
both forms are present, the direct environment value takes precedence. Personal
OpenAI keys are managed through the authenticated UI and encrypted with the
persisted `[Database] encryption_key`. Do not commit credential files or delete
the dashboard data volume that holds the database and encryption key.

Then build and start Kasugai:

```powershell
docker compose up --build -d
```

If this machine already ran Kasugai outside Docker and that installation owns
the DeniLicense seat, import its identity into the persistent Docker volume
once:

```powershell
.\scripts\migrate-docker-license.ps1
```

The helper defaults to `%USERPROFILE%\Kasugai\config.ini`, mounts it read-only,
and copies only `deviceprivatekey`, `activationid`, and `activationlease`. It
does not copy API endpoints, database paths, session secrets, encryption keys,
or OpenAI credentials, and it never overwrites an already activated Docker
identity. Use `-LegacyConfig <path>` for a different native config or `-Stack
dashboard-only` with `docker-compose.dashboard.yml`.

Open `http://localhost:8000`. The Go ports remain internal to the Kasugai Compose
network; only the dashboard port is published. By default it is published on
`127.0.0.1`, so it is reachable only from the Docker host.

For production, keep `KASUGAI_DASHBOARD_BIND_HOST=127.0.0.1` and place an
HTTPS reverse proxy such as Caddy, nginx, or Traefik on the same host in front
of `http://127.0.0.1:8000`. Terminate TLS at the proxy, forward the original
`Host` and `X-Forwarded-Proto` headers, and set `KASUGAI_PUBLIC_URL` to the
public HTTPS origin, for example `https://kasugai.example.com`. Set
`KASUGAI_TRUST_PROXY=true` only in this topology: it trusts forwarding headers
from exactly one proxy hop, so the dashboard port must remain inaccessible to
untrusted clients. Secure session cookies default to the trust-proxy setting;
`KASUGAI_SESSION_COOKIE_SECURE` can override that default, but setting it to
`true` on plain HTTP prevents browsers from returning the session cookie.

If the reverse proxy runs in another container, attach it to the Kasugai
network and proxy to the `dashboard` service directly instead of publishing the
dashboard on a public interface. Do not set
`KASUGAI_DASHBOARD_BIND_HOST=0.0.0.0` unless a host firewall restricts access
and TLS is provided upstream.

### Standalone server on a VPS

The Go chat, file-transfer, and media service has its own build context in
`kasugai_server/`. From that directory, copy `.env.vps.example` to `.env`, set
`KASUGAI_SERVER_IMAGE` to your registry tag, then build and push it:

```powershell
docker compose -f compose.vps.yml build
docker compose -f compose.vps.yml push
```

On the VPS, copy `compose.vps.yml` and `.env`, then run:

```sh
docker compose -f compose.vps.yml pull
docker compose -f compose.vps.yml up -d
```

The gRPC service does not currently authenticate connections or terminate TLS.
The VPS Compose file therefore binds to `127.0.0.1` by default. Use an SSH
tunnel, authenticated TCP proxy, or private VPN such as WireGuard, and set
`KASUGAI_PUBLISH_HOST` to the private VPN address. Do not expose ports 8008,
50051, and 50052 broadly without firewall restrictions.

Run the dashboard separately with `docker-compose.dashboard.yml`. Set
`KASUGAI_SERVER_HOST` to the VPS private hostname or VPN address; the chat,
file-transfer, and media ports default to 8008, 50051, and 50052 respectively.
The combined and dashboard-only stacks intentionally share the explicit
`kasugai_dashboard-data` and `kasugai_dashboard-resources` volume names, so
switching layouts preserves the license identity, databases, and uploads.
Then start only the dashboard stack:

```powershell
docker compose -f docker-compose.dashboard.yml up --build -d
```

If licensing environment values change, recreate the dashboard so its persisted config is refreshed:

```powershell
docker compose -f docker-compose.dashboard.yml up --build --force-recreate -d dashboard
```

## Configuration

The default local configuration is stored at `%USERPROFILE%\Kasugai\config.ini`.
Container configuration is persisted in the `dashboard-data` volume at
`/data/config.ini`. Chat history, project data, encryption keys, the web-session
secret, and the DeniLicense activation identity are stored in the same volume.

Important sections are:

- `[Licensing]`: DeniLicense API, signed issuer, product, label, and installation key
- `[WebServer]`: dashboard, public invitation origin, and Kasugai gRPC addresses
- `[FileTransfer]`: upload path and file-transfer service address
- `[Database]`: encrypted chat-history and project-workspace database settings
- `[Logging]`: log path and level

The installation private key, activation reference, and web-session secret are generated or saved in the persistent config volume. Keep that volume private and persistent; deleting it creates a new installation identity and may consume another activation seat. Normal image rebuilds reuse the existing activation rather than requesting another seat.

## Validation

Run the focused Python tests:

```powershell
python -m unittest discover -s tests -v
```

Validate and build the container application:

```powershell
docker compose config
docker compose build
```
