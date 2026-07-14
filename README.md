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
- Global or project-specific links for GitHub, Gmail, Calendar, Drive, Teams, Slack, Jira, Notion, and other web tools

Project data is stored in `project_manager.db`. Descriptions, meeting content, RAID details, stakeholder notes, and connection account labels are encrypted at rest with the `[Database] encryption_key`. Records are scoped to the authenticated DeniLicense user.

Connections are validated HTTPS/HTTP shortcuts, not OAuth integrations. Kasugai does not store third-party access tokens or passwords, and URLs containing embedded credentials are rejected.

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
```

Then build and start Kasugai:

```powershell
docker compose up --build -d
```

Open `http://localhost:8000`. The Go ports remain internal to the Kasugai Compose network; only the dashboard port is published.

If licensing environment values change, recreate the dashboard so its persisted config is refreshed:

```powershell
docker compose up --build --force-recreate -d dashboard
```

## Configuration

The default local configuration is stored at `%USERPROFILE%\Kasugai\config.ini`. Container configuration is persisted in the `dashboard-data` volume at `/root/Kasugai/config.ini`.

Important sections are:

- `[Licensing]`: DeniLicense API, signed issuer, product, label, and installation key
- `[WebServer]`: dashboard and Kasugai gRPC addresses
- `[FileTransfer]`: upload path and file-transfer service address
- `[Database]`: encrypted chat-history and project-workspace database settings
- `[Logging]`: log path and level

The installation private key is generated on first activation. Keep the config volume private and persistent; deleting it creates a new installation identity and may consume another activation seat.

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
