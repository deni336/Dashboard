# Kasugai Dashboard

Kasugai is a Flask dashboard and Go gRPC service for project management, with chat, file transfer, and screen sharing unified in the Team Room. Access is gated by a device-bound DeniLicense activation lease.

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

## Team Room

Open **Team Room** from either Home or Projects to collaborate without leaving
the current workspace. The right-side drawer combines room selection, chat,
inline file offers, file history, and screen sharing in one place. Join or
create a room before sending messages, transferring files, or starting a screen
share. The drawer can stay open while you review project work and closes without
navigating away from the page.

The `/team-room` URL opens the drawer on Home. The legacy `/screenshare` URL is
kept as a compatibility deep link and now opens the same Team Room with its
screen-sharing area expanded; it is no longer a separate application page.

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
KASUGAI_AI_PROVIDER=disabled
KASUGAI_AI_BASE_URL=
KASUGAI_AI_MODEL=gpt-oss:20b
KASUGAI_AI_API_KEY=
KASUGAI_AI_API_KEY_FILE=
KASUGAI_AI_TIMEOUT_SECONDS=300
KASUGAI_AI_REQUEST_BUDGET_SECONDS=330
KASUGAI_AI_ALLOWED_USERS=
KASUGAI_AI_SOURCE_ALLOWED_USERS=owner@example.com
OLLAMA_IMAGE=ollama/ollama:0.31.2
OLLAMA_CONTEXT_LENGTH=32768
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

Ask Kasugai defaults to a self-hosted
[`gpt-oss`](https://openai.com/open-models/) model through Ollama. It does not
need an OpenAI API key, ChatGPT account, or OpenAI API billing. Ollama is shared
as an inference service, while Kasugai owns conversation identity and access
control so one authenticated user's session is never used as another user's
context. `KASUGAI_AI_API_KEY` stays blank for local Ollama; it and its `_FILE`
variant exist only for an administrator who deliberately points
`KASUGAI_AI_BASE_URL` at an authenticated, OpenAI-compatible private endpoint.
All authenticated project editors can invoke the local model. The 300-second
upstream timeout accounts for CPU-offloaded local generation; if CPU inference
times out, increase `KASUGAI_AI_TIMEOUT_SECONDS` and
`KASUGAI_AI_REQUEST_BUDGET_SECONDS` together, keeping the request budget higher.
The base Compose files use the `disabled` value shown above; adding
`docker-compose.ollama.yml` overrides it with the private Ollama endpoint.

OpenAI currently publishes these downloadable general-purpose reasoning models:

| Model | Hardware guidance | Kasugai use |
| --- | --- | --- |
| `gpt-oss-20b` | About 16 GB of VRAM or unified memory; CPU offload is supported but slower | Default and recommended |
| `gpt-oss-120b` | At least 60 GB of VRAM or unified memory; intended for an H100-class or multi-GPU host | Not suitable for this workstation |

Both are text-only, Apache-2.0 open-weight models with a native 128K context
window. OpenAI also publishes 20B and 120B `gpt-oss-safeguard` variants for
safety-policy classification; those are not general chatbot replacements. See
OpenAI's [gpt-oss Ollama guide](https://developers.openai.com/cookbook/articles/gpt-oss/run-locally-ollama)
for the upstream model and runtime guidance.

This workstation has 64 GB of system RAM, but its RTX 3060 Laptop GPU has only
6 GB of VRAM and Docker Desktop currently exposes about 32 GB of RAM. The 20B
model will therefore split work between the GPU and CPU and will be noticeably
slower than it would be on a 16 GB-or-larger GPU. The supplied override limits
Ollama to one loaded model and one parallel request, and uses a 32K runtime
context to stay within this machine's practical memory envelope. If it runs out
of memory, set `OLLAMA_CONTEXT_LENGTH=16384`; for better throughput, move the
same override to a GPU VPS with at least 16 GB of VRAM. Do not select the 120B
model on this machine.

### Download and run gpt-oss with Ollama

Ollama is optional and lives in `docker-compose.ollama.yml`; NVIDIA GPU access
is isolated in `docker-compose.ollama.nvidia.yml` so CPU-only hosts can omit that
file. The service publishes no host port. The dashboard reaches it on a private,
internal Compose network, its model files persist in the explicit
`kasugai_ollama-models` volume, and the long-running model server has no outbound
network. Only the explicit one-shot `ollama-pull` job joins the ordinary bridge
network needed to download model weights. `OLLAMA_NO_CLOUD=1` prevents Ollama
from using cloud-hosted models.

The model is deliberately not downloaded during an image build or normal
application update. On this NVIDIA workstation, pull the 20B weights once and
then start the stack. The Ollama health check requires that exact configured
model to exist before the dashboard starts:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml --profile model-pull run --rm ollama-pull
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml up --build -d --wait
```

Use the same persistent model volume with the standalone dashboard layout:

```powershell
$env:KASUGAI_SERVER_HOST = "your-vps-or-private-vpn-host"
docker compose -f docker-compose.dashboard.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml --profile model-pull run --rm ollama-pull
docker compose -f docker-compose.dashboard.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml up --build -d --wait
```

On a CPU-only host, omit `-f docker-compose.ollama.nvidia.yml` from both
commands. CPU-only inference works but is substantially slower. After startup,
inspect actual GPU/CPU offload and the loaded context size with:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml exec -e OLLAMA_HOST=127.0.0.1:11434 ollama ollama ps
```

Never publish port 11434 directly to the internet: Ollama's local server does
not provide application user authentication. If the inference service must run
on a different host, connect it to the dashboard through a private VPN or an
authenticated TLS proxy and set `KASUGAI_AI_BASE_URL` to that private endpoint.

To update the Ollama image or model, change `OLLAMA_IMAGE` or
`KASUGAI_AI_MODEL`, stop the `ollama` service, rerun the one-shot pull command,
and start the stack again. Never use `docker compose down -v` for a routine
update or stop: it destroys the selected Kasugai stack's named volumes,
including the dashboard installation identity and license activation, encrypted
configuration, projects and chats, uploaded resources, server data, and model
weights. Losing the dashboard identity can consume another activation seat.

Use `up` to update containers while preserving their volumes:

```powershell
# Core services only
docker compose up --build -d --wait

# AI-enabled stack (omit the NVIDIA override on a CPU-only host)
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml up --build -d --wait
```

Use `stop` when you only want to stop containers without deleting data:

```powershell
docker compose stop
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml stop
```

Public GitHub repositories can be read without a token. When `GITHUB_TOKEN` is set, it is sent only for
repositories or organizations explicitly listed in
`KASUGAI_GITHUB_TOKEN_ALLOWLIST` (`owner/repo` or `owner/*`). Gmail connections
use the configured read-only IMAP mailbox; for Gmail, use an app password rather
than the primary account password. The connection's nonblank Account field must
exactly match `KASUGAI_IMAP_USERNAME`. Project workspace context is sent to the
configured private Ollama service only when an authorized editor generates a
preview. Deployment-wide GitHub and IMAP sources are available only when that
project owner also appears
in `KASUGAI_AI_SOURCE_ALLOWED_USERS`; leave this separate list empty to disable
all linked-source retrieval. Shared editors and other AI-enabled owners cannot
exercise those credentials. Raw source bodies
are not returned to the browser. Proposals expire after 15 minutes, are rejected
if the project or targeted records changed, and are not written until the editor
selects and confirms the individual actions.

Ask Kasugai runs in the Flask dashboard container, not the standalone Go
chat/media VPS container. Environment values must be supplied by Compose or the
process manager; running `python main.py` directly does not load `.env`
automatically.

For production deployment-wide source credentials, prefer the corresponding
`*_FILE` settings and mount each credential as a Docker secret or read-only
file. When both forms are present, the direct environment value takes
precedence. Do not commit credential files or delete the dashboard data volume
that holds the database and encryption key.

The Ollama commands above start the complete AI-enabled stack. To start only the
core Kasugai services without the local inference container, use the command
below. Core-only Compose explicitly reports Ask Kasugai as disabled
instead of pointing at an absent model service:

```powershell
docker compose up --build -d
```

Inside the dashboard container, Compose environment values are authoritative
and update the persisted `[AI]` provider, base URL, and model on every restart.
Native non-container runs continue to use those values from `config.ini`.

If this machine already ran Kasugai outside Docker and that installation owns
the DeniLicense seat, import its identity into the persistent Docker volume
once:

```powershell
.\scripts\migrate-docker-license.ps1
```

The helper defaults to `%USERPROFILE%\Kasugai\config.ini`, mounts it read-only,
and copies only `deviceprivatekey`, `activationid`, and `activationlease`. It
does not copy API endpoints, database paths, session secrets, encryption keys,
or AI credentials, and it never overwrites an already activated Docker
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

- `[Application]`: quick-launch buttons and the stable resource folder for shared background images
- `[AI]`: inference provider, private API base URL, and downloadable model name
- `[Licensing]`: DeniLicense API, signed issuer, product, label, and installation key
- `[WebServer]`: dashboard, public invitation origin, and Kasugai gRPC addresses
- `[FileTransfer]`: upload path and file-transfer service address
- `[Database]`: encrypted chat-history and project-workspace database settings
- `[Logging]`: log path and level

Kasugai accepts static JPG/JPEG, PNG, and WebP backgrounds up to 20 MB and 40
megapixels, and displays the selected image across Home and Projects, including
while the Team Room drawer is open.
Uploads are fully decoded before they replace the current background; animated,
corrupt, or truncated images and files whose contents do not match their
extension are rejected. The browser uses the stable `/resources/background`
URL, which serves each image with its native MIME type. `/resources/bg.jpg`
remains as a virtual compatibility alias and may therefore return PNG or WebP
content with the corresponding native MIME type. In Docker, backgrounds are
stored in the dedicated `/app/kasugai/resources/backgrounds/` directory inside
the persistent `kasugai_dashboard-resources` volume, separate from file-transfer
downloads, and survive dashboard rebuilds.

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
docker compose -f docker-compose.yml -f docker-compose.ollama.yml config
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml config
```

These validation commands render the configuration only; they do not pull the
Ollama image or model weights.
