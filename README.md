# Kasugai Dashboard

Kasugai is a self-hosted personal command center for developers. Its Flask
dashboard combines a developer cockpit, workstation and homelab telemetry,
safe task launching and automation, a unified inbox, encrypted knowledge and
personal hubs, local AI tools, and a full project workspace. Chat, file
transfer, and screen sharing live together in the Go-backed Team Room. Access
is gated by a device-bound DeniLicense activation lease.

## Documentation

The README is the feature tour and deployment overview. The expanded guides are
organized by task in the [documentation index](docs/README.md):

- [Getting started](docs/GETTING_STARTED.md) — first deployment and first login
- [User guide](docs/USER_GUIDE.md) — day-to-day workflows across every module
- [Configuration reference](docs/CONFIGURATION.md) — environment variables,
  `config.ini`, Compose overlays, allowlists, and precedence
- [Credentials and external codes](docs/CREDENTIALS.md) — exactly where to get
  every key, token, password, claim code, and pairing code
- [Companion agents](docs/COMPANION_AGENTS.md) — install, policy, update,
  troubleshoot, revoke, and uninstall the three outbound agents
- [Architecture and security](docs/ARCHITECTURE.md) — components, data flow,
  trust boundaries, persistence, and threat controls
- [Operations and troubleshooting](docs/TROUBLESHOOTING.md) — health checks,
  upgrades, backups, recovery, and common failures

## Requirements

- Python 3.14
- Go 1.22.6 or a newer toolchain compatible with `kasugai_server/go.mod`
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

Connections are validated HTTPS/HTTP shortcuts, not per-user OAuth integrations, and URLs containing embedded credentials are rejected. When the effective provider is `openai`, each authenticated user can save a personal OpenAI API key from the key control in the Projects top bar. Personal keys are encrypted in `project_manager.db`, scoped to that user's authenticated ID, and never returned by the API after saving. An optional deployment-wide OpenAI key can still be supplied to the dashboard container as a controlled fallback.

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

## Developer Cockpit

Home opens on the Developer Cockpit: a compact command center with repository
health, favorites, GitHub notifications, quick-launch shortcuts, Projects, and
Team Room. Repository discovery is deliberately read-only. Kasugai runs a small,
fixed set of non-interactive Git inspection commands and returns branch and
change counts without exposing changed filenames or absolute host paths.

Repository roots must be explicitly allowed. A native installation can set
`KASUGAI_REPOSITORY_ROOTS` and `KASUGAI_REPOSITORY_ALLOWED_ROOTS` to one or more
paths separated by the platform path separator. In Docker, use the opt-in
repository overlay described below; the standard Compose stack does not mount
any host source code. `KASUGAI_DEVELOPER_ALLOWED_USERS` can further restrict the
feature to comma-separated DeniLicense profile IDs or email addresses.

Each signed-in user allowed by `KASUGAI_DEVELOPER_ALLOWED_USERS` can connect a
personal GitHub token from **Settings → Developer**. Kasugai validates it against GitHub, encrypts it in
`personal_dashboard.db`, and never returns it to the browser. The connection is
used for that user's notification feed only.

## Workstation Monitor

The Workstation Monitor uses a small outbound-only Windows companion agent. It
pushes aggregate CPU, memory, NVIDIA GPU, fixed-disk, network, uptime, and
battery telemetry to the ordinary dashboard URL. It never opens a listening
port and does not collect filenames, command lines, usernames, IP or MAC
addresses, open ports, environment variables, or browser history. This keeps
the Docker dashboard unprivileged and avoids host PID, `/proc`, and Docker-socket
mounts.

Open **Settings → Workstations**, create a one-use pairing code, and run the
displayed installer command from this repository on the Windows computer. The
installer creates a dedicated virtual environment under the current user's
`%LOCALAPPDATA%`, protects the agent token with Windows DPAPI, and registers a
limited, current-user scheduled task. Pairing codes expire after ten minutes.
To install directly from PowerShell:

```powershell
.\scripts\install-workstation-agent.ps1 `
    -ServerUrl http://127.0.0.1:8000 `
    -PairingId <pairing-id-from-settings>
```

The installer securely prompts for the one-time code; it is not placed in shell
history. For development without a scheduled task, install
`requirements-agent.txt`, then use `python -m workstation_agent pair` followed
by `python -m workstation_agent run`. Remove the task and application with:

```powershell
.\scripts\uninstall-workstation-agent.ps1
```

Pass `-RemoveCredentials` only when the local DPAPI-protected pairing should
also be erased. Revoking a workstation in Kasugai invalidates its server token
immediately. Raw telemetry history is retained for 24 hours by default.

## Docker & Homelab

The Docker & Homelab module uses a second outbound-only credential and agent.
The dashboard container never receives the Docker socket, Windows Docker pipe,
host PID namespace, or a remote Docker daemon address. The host agent invokes a
small fixed Docker CLI allowlist, strips IDs, addresses, mounts, commands,
environment variables, registry credentials, arbitrary labels, and raw errors,
then sends only an encrypted, owner-scoped inventory.

Monitoring is disabled in the local agent policy by default. Create
`%LOCALAPPDATA%\Kasugai\homelab-agent\config.json` from this safe starting point:

```json
{
  "version": 1,
  "inventory_enabled": true,
  "grants": {"read_logs": false, "restart": false},
  "health_checks": []
}
```

With the default labeled scope, a container appears only when it opts in:

```yaml
labels:
  io.kasugai.monitor: "true"
  io.kasugai.logs: "true"
  io.kasugai.actions: "restart"
```

The latter two labels do not grant anything alone. Logs require the local
`read_logs` policy and the server's
`KASUGAI_HOMELAB_ACTIONS_ENABLED=true` kill switch; restart requires that same
server switch plus the local `restart` policy. The host re-reads inventory
and labels immediately before acting. Browser requests contain only an opaque
resource key and the fixed operation `read_logs` or `restart`; exec, shell,
pull, stop, delete, prune, Compose operations, custom signals, paths, and
arguments are not part of the protocol.

Open **Settings → Homelab**, create a pairing code, then install the agent on the
Docker host:

```powershell
.\scripts\install-homelab-agent.ps1 `
    -ServerUrl http://127.0.0.1:8000 `
    -PairingId <pairing-id-from-settings>
```

The one-time code is entered through a hidden prompt. Health checks are also
configured only in the local policy, preventing the web dashboard from becoming
a network scanner. HTTP checks follow no redirects, retain no response body,
and report a friendly name, status, latency, and bounded failure/protocol
metadata—never the target URL or response body.

## Universal Launcher

Press **Ctrl+K** anywhere on Home to search dashboard destinations,
repositories, HTTPS bookmarks, and tasks published by a paired computer. Local
tasks use a third, independent outbound-only companion credential. The browser
can queue only a server-issued opaque task ID; executable paths, arguments,
working directories, environment, and timeouts remain in the computer's local
policy and are never uploaded to Kasugai.

Open **Settings → Launcher**, create a one-use pairing code, then install the
runner for the Windows user that should execute the tasks:

```powershell
.\scripts\install-launcher-agent.ps1 `
    -ServerUrl http://127.0.0.1:8000 `
    -PairingId <pairing-id-from-settings>
```

The installer creates
`%LOCALAPPDATA%\Kasugai\launcher-agent\policy.json` disabled and empty. Define
tasks only by editing that local file. A minimal policy looks like:

```json
{
  "schema_version": 1,
  "enabled": true,
  "tasks": [
    {
      "id": "focused-tests",
      "title": "Run focused tests",
      "description": "Runs the approved local test command.",
      "category": "development",
      "icon": "test-tube-2",
      "requires_confirmation": true,
      "executable": "C:\\Projects\\Dashboard\\.venv\\Scripts\\python.exe",
      "args": ["-m", "pytest", "tests/test_launcher_runner.py", "-q"],
      "cwd": "C:\\Projects\\Dashboard",
      "timeout_seconds": 120
    }
  ]
}
```

Validate changes with `python -m launcher_agent config validate`. The agent
re-loads and revalidates this file after each claim, executes an absolute
executable with `shell=False`, filters inherited environment to a fixed
OS path/profile/temp allowlist, supplies no
stdin, and kills work that exceeds its time or 64 KiB output limit. Task
delivery also requires `KASUGAI_LAUNCHER_RUNS_ENABLED=true` on the dashboard;
it is off by default. Tasks marked `requires_confirmation` use a short-lived,
one-use browser confirmation. Remove the scheduled task with:

```powershell
.\scripts\uninstall-launcher-agent.ps1
```

## Automation Engine

The Automation Engine turns dashboard state into predictable rules without
accepting code, shell fragments, arbitrary URLs, or user-written SQL. Build and
manage rules from **Settings → Automation**. Version 1 supports:

- Interval and daily schedules.
- New developer, workstation, homelab, launcher, or automation events.
- CPU, memory, disk, unhealthy-container, failed-health-check, and available-
  image-update thresholds.
- Dashboard notifications.
- Optional delivery of a locally approved launcher task that does not require
  interactive confirmation.

Rules and run summaries are owner scoped and encrypted. Metric rules fire on
the false-to-true edge, event rules advance a durable cursor, schedules advance
past missed occurrences, and every rule has a cooldown. Atomic claims prevent
two scheduler cycles from running the same occurrence.

The scheduler is enabled with `KASUGAI_AUTOMATION_ENABLED=true`. Automatically
delivering launcher work additionally requires both
`KASUGAI_AUTOMATION_TASKS_ENABLED=true` and
`KASUGAI_LAUNCHER_RUNS_ENABLED=true`; both execution gates default off. A
launcher task that requires confirmation is never eligible for automation.

## Unified Nerd Inbox

The Unified Nerd Inbox combines durable launcher and automation activity with
live workstation, homelab, runner, and unread GitHub signals. Use the topbar
badge or section **06** to filter by source/state, search the bounded feed, pin
important items, snooze them, archive them, or mark a source read.

Inbox organization is a Kasugai-only overlay. Marking a GitHub item read,
snoozing an unhealthy container alert, or archiving an offline-agent warning
does not mutate GitHub, Docker, or a companion agent. Public item IDs are
owner-specific HMAC values, and raw database IDs, agent IDs, resource keys, and
GitHub notification IDs are not returned. Local destinations are hard-coded to
known dashboard sections; external destinations are limited to canonical,
credential-free `https://github.com/<owner>/<repository>` links.

Connector failures are isolated and disclosed in the feed while healthy
sources continue to load. GitHub reads use a short per-owner cache so refreshing
the inbox does not issue an API request on every poll. Enable the module with
`KASUGAI_INBOX_ENABLED=true` and optionally restrict it with
`KASUGAI_INBOX_ALLOWED_USERS`.

## Knowledge Vault

Section **07** adds an owner-scoped library for notes and reusable code
snippets. Search by title, body, or tag; filter by entry type or pinned state;
and copy snippets without leaving the dashboard. Snippets are displayed only
as plain text: Kasugai never executes them, and Markdown or HTML is never
rendered in the vault.

Titles, content, tags, and language metadata are encrypted with the shared
dashboard data key. Owner identifiers, random item IDs, note-versus-snippet
type, pinned state, versions, timestamps, item counts, edit frequency, and
approximate encrypted payload sizes remain visible to the local SQLite store.
Search is a bounded, literal scan after decryption, so the database contains no
plaintext full-text index.

Updates and deletes use optimistic versions. If the same entry changes in
another browser, Kasugai returns a conflict and refreshes the newer copy instead
of silently overwriting it. Enable the module with
`KASUGAI_KNOWLEDGE_ENABLED=true` and optionally restrict it with
`KASUGAI_KNOWLEDGE_ALLOWED_USERS`.

## Network & Security Center

Section **08** provides a passive, read-only posture view assembled from data
Kasugai already has. It summarizes workstation network throughput and resource
pressure, agent connectivity, Docker service health, failed checks, pending
image updates, runner availability, session-cookie posture, proxy trust,
encrypted storage, and the three remote-execution kill switches.

The center does not scan the LAN, probe ports, open sockets, contact arbitrary
hosts, or expose IP addresses, container resource keys, task arguments, or
decrypted telemetry. Each source fails independently, so an unavailable agent
collector reduces coverage without preventing the other summaries from
loading. The score is an explainable convenience rather than a vulnerability
assessment; every deduction has a visible check and recommendation.

Enable the center with `KASUGAI_SECURITY_ENABLED=true` and optionally restrict
it with `KASUGAI_SECURITY_ALLOWED_USERS`. A production HTTPS deployment should
use secure session cookies. If `KASUGAI_TRUST_PROXY=true`, clients must not be
able to bypass the trusted reverse proxy and connect to Waitress directly.

## Local AI Toolbox

Section **09** provides encrypted, owner-scoped conversations with the local
Ollama model already configured for Ask Kasugai. Fixed modes cover general
assistance, explanation, review, refactoring, tests, documentation, regular
expressions, and SQL. The browser cannot choose an endpoint, model, system
prompt, temperature, or tool definition.

The toolbox receives only the text entered in that conversation. It cannot
browse, inspect repository files, open URLs, execute code or shell commands,
query a database, or apply changes. Model output is displayed as inert plain
text rather than rendered Markdown or HTML. Conversation titles, modes, and
messages are encrypted at rest; owner IDs, random session IDs, versions,
timestamps, session counts, and approximate ciphertext sizes remain visible to
the local database.

Inference text leaves the dashboard container only for the administrator-
configured private Ollama endpoint. Core-only Compose reports the model as not
configured; add the Ollama overlays described below to enable Send. The toolbox
does not use personal hosted-API credentials. Enable its UI/API with
`KASUGAI_AI_TOOLBOX_ENABLED=true` and optionally restrict it with
`KASUGAI_AI_TOOLBOX_ALLOWED_USERS`.

## Personal Hub

Section **10** rounds out the developer dashboard with encrypted reminders,
countdowns, habit check-ins, HTTPS bookmarks, and a browser-side focus timer.
Personal items are owner scoped and use optimistic versions so concurrent edits
cannot silently overwrite one another. Bookmark targets are validated but never
fetched by the server; opening one remains an explicit browser action.

Titles, notes, due dates, target dates, bookmark URLs, reminder completion,
habit cadence, and check-in dates are encrypted at rest. Owner IDs, random item
IDs, item types, versions, timestamps, counts, edit frequency, and approximate
ciphertext sizes remain visible to the local database. Habit check-ins can be
toggled only within a bounded date window, and stale browser writes return a
conflict instead of replacing newer state.

Enable the hub with `KASUGAI_PERSONAL_HUB_ENABLED=true` and optionally restrict
it with `KASUGAI_PERSONAL_HUB_ALLOWED_USERS`. It does not request notification,
calendar, location, or contact permissions and does not mutate an external
service.

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

Create `.env` from the complete, commented example:

```powershell
Copy-Item .env.example .env
```

At minimum, review the DeniLicense URL, issuer, product, activation label,
dashboard bind/public URL, and selected AI provider before starting. Leave
optional OpenAI, GitHub, and IMAP secrets blank until you intentionally enable
those integrations. Use the
[configuration reference](docs/CONFIGURATION.md) rather than treating a partial
README excerpt as an environment inventory.

Set `KASUGAI_PUBLIC_URL` to the externally reachable origin used by invitees, for example `https://kasugai.example.com`. Leaving it blank builds invitation links from the current request host, which is suitable for local use.

### Opt in to local repository inspection

The dashboard container has no source-code access by default. To expose one
narrow projects folder as a read-only bind mount, set its host path in `.env`:

```ini
KASUGAI_REPOSITORY_HOST_PATH=C:/Projects
```

Then include the repository overlay when starting or rebuilding Kasugai:

```powershell
docker compose -f docker-compose.yml -f docker-compose.repositories.yml up --build -d --wait
```

The overlay maps that folder to `/repositories:ro` and sets both repository
root variables to the container-visible path. Do not point it at an entire drive
or user profile. The dashboard never needs the Docker socket for repository
inspection.

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
repository targets explicitly listed in
`KASUGAI_GITHUB_TOKEN_ALLOWLIST` (`owner/repo` or `owner/*`). For Gmail, Kasugai
performs bounded read-only IMAP operations; use an app password rather than the
primary account password. The connection's nonblank Account field must
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
file. When both forms are present, a nonblank direct environment value takes
precedence; a blank direct value permits the file form. Do not commit credential files or delete the dashboard data volume
that holds the database and encryption key.

The Ollama commands above start the complete AI-enabled stack. To start only the
core Kasugai services without the local inference container, use the command
below. Core-only Compose explicitly reports Ask Kasugai as disabled
instead of pointing at an absent model service:

```powershell
docker compose up --build -d
```

Inside the dashboard container, nonblank Compose environment values are
authoritative and update the persisted `[AI]` provider, base URL, and model on
restart. A blank value does not erase an older nonblank persisted value; edit
the persistent configuration deliberately when clearing one. Native
non-container runs continue to use those values from `config.ini`.

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

If that tag is on GHCR, follow the least-privilege token and `docker login`
steps in [Credentials and external codes](docs/CREDENTIALS.md#optional-ghcr-credential-for-the-vps-image-workflow).

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
`/data/config.ini`. Chat history, project data, personal-dashboard data,
encryption keys, the web-session secret, and the DeniLicense activation identity
are stored in the same volume.

Important sections are:

- `[Application]`: quick-launch buttons and the stable resource folder for shared background images
- `[AI]`: inference provider, private API base URL, and downloadable model name
- `[Licensing]`: DeniLicense API, signed issuer, product, label, and installation key
- `[WebServer]`: dashboard, public invitation origin, and Kasugai gRPC addresses
- `[FileTransfer]`: upload path and file-transfer service address
- `[Database]`: encrypted chat-history, project-workspace, and personal-dashboard database settings
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

Run the Python suite:

```powershell
python -m unittest discover -s tests -v
```

Run the browser-module contract tests with Node's built-in test runner:

```powershell
node --test tests/test_*_frontend.js
```

Go validation and the current legacy integration-test prerequisites are
documented in [the Team Room server README](kasugai_server/README.md#validate-changes).

Validate and build the container application:

```powershell
docker compose config
docker compose build
docker compose -f docker-compose.yml -f docker-compose.ollama.yml config
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml config
$env:KASUGAI_REPOSITORY_HOST_PATH = (Get-Location).Path
docker compose -f docker-compose.yml -f docker-compose.repositories.yml config
```

These validation commands render the configuration only; they do not pull the
Ollama image or model weights.
