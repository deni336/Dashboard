# Configuration reference

Kasugai is configured through environment variables, a persistent `config.ini`,
Compose overlays, and two companion-agent policy files. This reference covers
the supported operator-facing settings and explains which layer owns each one.

Start from `.env.example`; do not copy examples from generated Compose output,
because that output may contain resolved secrets.

## Configuration layers and precedence

1. **Process environment** controls feature flags, allowlists, external
   credentials, timeouts, and most Compose wiring.
2. **Container entrypoint mapping** writes selected nonblank environment values
   into `/data/config.ini` when the dashboard container starts.
3. **Persistent `config.ini`** stores application paths, generated encryption
   and session keys, DeniLicense activation identity, and native defaults.
4. **Per-user encrypted database settings** store personal GitHub and OpenAI
   credentials and user-created dashboard data.
5. **Companion local policy** controls Homelab permissions and Launcher task
   definitions on the target computer; the dashboard cannot edit these files.

For secrets with a direct variable and a `_FILE` variable, the nonblank direct
value wins. Populate only one. The `_FILE` variable contains a path readable
inside the dashboard process, not the secret itself.

Native `python main.py` runs do not parse `.env` automatically. Export variables
in the launching process or use `config.ini` where supported.

## Value syntax

### Booleans

Boolean feature settings accept case-insensitive `1`, `true`, `yes`, or `on` as
true. Values such as `0` or `false` are false. Use `true` and `false` in `.env`
for clarity.

### User allowlists

User allowlists are comma-separated DeniLicense profile IDs or email addresses.
Matching is case-insensitive after trimming whitespace:

```ini
KASUGAI_DEVELOPER_ALLOWED_USERS=user-uuid,owner@example.com
```

For ordinary module allowlists, an empty value allows every authenticated user
to whom the valid DeniLicense lease grants application access. Two AI lists are
intentionally stricter:

- Empty `KASUGAI_AI_ALLOWED_USERS` means no user can use the deployment-wide
  hosted OpenAI fallback.
- Empty `KASUGAI_AI_SOURCE_ALLOWED_USERS` disables deployment GitHub/IMAP
  evidence retrieval for everyone.

### Repository paths

Native `KASUGAI_REPOSITORY_ROOTS` and
`KASUGAI_REPOSITORY_ALLOWED_ROOTS` accept paths separated by the operating
system path separator (`;` on Windows, `:` on Linux). Docker's repository
overlay supplies the single container path `/repositories` automatically.

### URLs

External/base URLs must not embed a username, password, fragment, or—where
documented—query string. Use HTTPS for any traffic that leaves a trusted local
or private network. Companion server URLs must be only a dashboard origin, such
as `https://kasugai.example.com`, without a path credential.

## Licensing

| Variable | Default | Meaning |
| --- | --- | --- |
| `DENILICENSE_API_URL` | `http://denilicense-api:8080` | Address the dashboard uses to call DeniLicense |
| `DENILICENSE_ISSUER` | `http://127.0.0.1:8080` | Exact issuer expected in signed activation leases |
| `DENILICENSE_PRODUCT_CODE` | `KASUGAI` | Product code selected during license lookup and activation |
| `DENILICENSE_ACTIVATION_LABEL` | `Kasugai Dashboard` | Friendly installation label sent during activation |

The API URL and issuer may legitimately differ. The issuer must exactly match
the authority used by DeniLicense to sign leases; do not change it merely to
make the URL routable from a container.

These `DENILICENSE_*` variables are mapped into `config.ini` by the supplied
Docker entrypoint. A native `python main.py` launch reads the matching
`[Licensing]` options (`apiurl`, `issuer`, `productcode`, and
`activationlabel`) from `config.ini`; it does not map these environment names
itself.

DeniLicense account passwords and claim codes are not environment variables.
Users enter them on the login page. See [Credentials and external codes](CREDENTIALS.md).

## Dashboard network and browser security

| Variable | Default | Meaning |
| --- | --- | --- |
| `KASUGAI_DASHBOARD_BIND_HOST` | `127.0.0.1` | Host interface used by Compose to publish dashboard port 8000 |
| `KASUGAI_PUBLIC_URL` | blank | Canonical external origin used to build invitation links |
| `KASUGAI_TRUST_PROXY` | `false` | Trust exactly one proxy hop's forwarded host/protocol/address headers |
| `KASUGAI_SESSION_COOKIE_SECURE` | inferred from trust-proxy | Explicit Secure-cookie override |

Recommended reverse-proxy deployment:

```ini
KASUGAI_DASHBOARD_BIND_HOST=127.0.0.1
KASUGAI_PUBLIC_URL=https://kasugai.example.com
KASUGAI_TRUST_PROXY=true
KASUGAI_SESSION_COOKIE_SECURE=true
```

Enable `KASUGAI_TRUST_PROXY` only when untrusted clients cannot connect directly
to Waitress. Kasugai then trusts one proxy hop via Werkzeug `ProxyFix`. The
proxy must replace, not append untrusted client-provided forwarding headers.

Setting Secure cookies to true while serving plain HTTP prevents the browser
from returning the session cookie. Leaving `KASUGAI_PUBLIC_URL` blank uses the
current request origin, which is convenient locally but unsuitable when a proxy
can present multiple hostnames.

`KASUGAI_DASHBOARD_BIND_HOST` is Compose port interpolation, and the supplied
container entrypoint maps `KASUGAI_PUBLIC_URL` into `[WebServer] publicurl`.
Native launches instead use `[WebServer] address` and `publicurl` directly.
`KASUGAI_TRUST_PROXY` and `KASUGAI_SESSION_COOKIE_SECURE` are runtime
environment controls in both modes.

## Team Room and dashboard-only topology

The combined stack fixes these values to the internal `kasugai-server` service.
The dashboard-only stack exposes them as variables:

| Variable | Required/default | Meaning |
| --- | --- | --- |
| `KASUGAI_DASHBOARD_IMAGE` | `kasugai-dashboard:latest` | Dashboard image tag for dashboard-only Compose |
| `KASUGAI_SERVER_HOST` | required | Private/VPN hostname of the Go Team Room service |
| `KASUGAI_SERVER_PORT` | `8008` | Go chat service port |
| `KASUGAI_FILE_TRANSFER_HOST` | server host | File-transfer service hostname |
| `KASUGAI_FILE_TRANSFER_PORT` | `50051` | File-transfer gRPC port |
| `KASUGAI_MEDIA_PORT` | `50052` | Media/screen-share service port |
| `KASUGAI_SERVER_IMAGE` | `kasugai-server-vps:latest` | Standalone VPS Go-service image/tag; the example uses a GHCR image |
| `KASUGAI_PUBLISH_HOST` | `127.0.0.1` | Host interface used by standalone VPS Compose for all three Go ports |

The standalone Go service currently does not provide transport authentication
or TLS. Bind it to loopback or a private VPN address and enforce the network
boundary with a tunnel, authenticated proxy, or firewall. Do not expose ports
8008, 50051, or 50052 broadly.

## AI provider

| Variable | Default | Meaning |
| --- | --- | --- |
| `KASUGAI_AI_PROVIDER` | `disabled` in core Compose | `disabled`, `ollama`, or `openai` |
| `KASUGAI_AI_BASE_URL` | provider-dependent | OpenAI-compatible API base URL |
| `KASUGAI_AI_MODEL` | `gpt-oss:20b` | Exact model ID pinned to new conversations |
| `OPENAI_MODEL` | blank | Native/custom-environment legacy fallback for hosted `openai` only when `KASUGAI_AI_MODEL` is blank; checked-in Compose does not forward it |
| `KASUGAI_AI_TIMEOUT_SECONDS` | `300` | Upstream operation timeout, valid range 5–900 seconds |
| `KASUGAI_AI_REQUEST_BUDGET_SECONDS` | `330` | Whole assistant request budget, valid range 10–1200 seconds |
| `KASUGAI_AI_API_KEY` | blank | Direct bearer credential for private/local compatible endpoint |
| `KASUGAI_AI_API_KEY_FILE` | blank | File containing that private/local endpoint credential |
| `OPENAI_API_KEY` | blank | Direct hosted OpenAI deployment fallback |
| `OPENAI_API_KEY_FILE` | blank | File containing hosted OpenAI deployment fallback |
| `KASUGAI_AI_ALLOWED_USERS` | blank/none | Users permitted to consume the hosted deployment fallback |
| `KASUGAI_AI_SOURCE_ALLOWED_USERS` | blank/none | Project owners permitted to retrieve deployment GitHub/IMAP evidence |

Provider behavior:

- `disabled`: AI routes report that no model service is configured.
- `ollama`: uses the private/local base URL and optional
  `KASUGAI_AI_API_KEY(_FILE)`. The supplied overlay sets the internal Ollama
  URL and deliberately clears this credential.
- `openai`: defaults to `https://api.openai.com/v1` when no non-Ollama base URL
  is persisted. A personal encrypted user key wins; otherwise an allowlisted
  user may use `OPENAI_API_KEY(_FILE)`.

Keep the total request budget higher than the upstream timeout so Kasugai has
time to validate and save the result after inference. Changing provider/model
does not rewrite existing conversation identity; start a new chat when the
saved session belongs to a different backend.

The Local AI Toolbox deliberately operates only when the effective provider is
`ollama`. It uses that compatible endpoint but maintains separate per-user
sessions and feature access controls. It does not consume personal hosted keys
or the `OPENAI_API_KEY(_FILE)` fallback when the provider is `openai`.

## Ollama overlay

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_IMAGE` | `ollama/ollama:0.31.2` | Ollama container image |
| `OLLAMA_CONTEXT_LENGTH` | `32768` | Runtime context length supplied to Ollama |

The overlay also applies fixed safety/resource settings: one loaded model, one
parallel request, bounded queue, q8 KV cache, flash attention, and
`OLLAMA_NO_CLOUD=1`. The long-running Ollama service joins only an internal
network. The explicit one-shot `ollama-pull` profile receives egress to download
weights.

Changing `KASUGAI_AI_MODEL` requires rerunning the model-pull command so the
health check can find that exact model in the persistent model volume.

## Deployment source credentials

| Variable | Default | Meaning |
| --- | --- | --- |
| `GITHUB_TOKEN` | blank | Direct deployment token for GitHub project evidence |
| `GITHUB_TOKEN_FILE` | blank | File containing the deployment GitHub token |
| `KASUGAI_GITHUB_TOKEN_ALLOWLIST` | blank | Comma-separated `owner/repository` or `owner/*` targets |
| `KASUGAI_IMAP_HOST` | `imap.gmail.com` in `.env.example` | TLS IMAP hostname |
| `KASUGAI_IMAP_PORT` | `993` | TLS IMAP port, valid TCP port 1–65535 |
| `KASUGAI_IMAP_USERNAME` | blank | Complete mailbox account name/address |
| `KASUGAI_IMAP_PASSWORD` | blank | Direct app-specific IMAP password |
| `KASUGAI_IMAP_PASSWORD_FILE` | blank | File containing the app-specific password |

These sources are used only when the project owner is listed in
`KASUGAI_AI_SOURCE_ALLOWED_USERS` and asks the assistant to include the linked
source. The GitHub token is sent only for an allowlist match. A project email
connection's Account field must match `KASUGAI_IMAP_USERNAME`.

The personal GitHub notification token entered in Settings is distinct and is
stored per user; it does not use `GITHUB_TOKEN`. Provider setup is detailed in
[Credentials and external codes](CREDENTIALS.md).

## Developer Cockpit and repository access

| Variable | Default | Meaning |
| --- | --- | --- |
| `KASUGAI_DEVELOPER_ALLOWED_USERS` | blank/all | User access to Developer Cockpit routes/settings |
| `KASUGAI_REPOSITORY_ROOTS` | blank | Roots initially scanned and offered to the dashboard |
| `KASUGAI_REPOSITORY_ALLOWED_ROOTS` | roots value | Hard boundary inside which UI-added roots must remain |
| `KASUGAI_REPOSITORY_HOST_PATH` | unset | Narrow host folder bound read-only by repository overlay |

The standard Compose stack mounts no source code. With
`docker-compose.repositories.yml`, the host path is mounted at `/repositories`
read-only and both container-visible root variables become `/repositories`.

Avoid exposing credential stores, `.ssh`, browser profiles, home directories,
or entire drives. Repository inspection does not need the Docker socket.

## Workstation Monitor

| Variable | Default | Valid range/meaning |
| --- | --- | --- |
| `KASUGAI_WORKSTATION_ENABLED` | `true` | Enable routes and module |
| `KASUGAI_WORKSTATION_ALLOWED_USERS` | blank/all | Permitted owners |
| `KASUGAI_WORKSTATION_RETENTION_HOURS` | `24` | 1–168 hours of raw samples |
| `KASUGAI_WORKSTATION_MAX_AGENTS` | `8` | 1–64 agents per owner |
| `KASUGAI_WORKSTATION_INTERVAL_SECONDS` | `10` | 5–60 second collection interval issued at pairing |

## Docker & Homelab

| Variable | Default | Valid range/meaning |
| --- | --- | --- |
| `KASUGAI_HOMELAB_ENABLED` | `true` | Enable routes and module |
| `KASUGAI_HOMELAB_ALLOWED_USERS` | blank/all | Permitted owners |
| `KASUGAI_HOMELAB_MAX_AGENTS` | `8` | 1–64 agents per owner |
| `KASUGAI_HOMELAB_INTERVAL_SECONDS` | `15` | 5–3600 second snapshot interval |
| `KASUGAI_HOMELAB_ACTION_POLL_SECONDS` | `5` | 2–60 second outbound action poll interval |
| `KASUGAI_HOMELAB_SAMPLE_RETENTION_HOURS` | `168` | 1–8760 hours of samples |
| `KASUGAI_HOMELAB_ACTIONS_ENABLED` | `false` | Server-wide kill switch for active Docker operations |

The server flag does not grant an operation by itself. Effective logs/restart
access is the intersection of server flag, owner authorization, local agent
policy, and freshly rechecked container labels. See
[Companion agents](COMPANION_AGENTS.md).

## Universal Launcher

| Variable | Default | Valid range/meaning |
| --- | --- | --- |
| `KASUGAI_LAUNCHER_ENABLED` | `true` | Enable routes and module |
| `KASUGAI_LAUNCHER_ALLOWED_USERS` | blank/all | Permitted owners |
| `KASUGAI_LAUNCHER_MAX_AGENTS` | `8` | 1–64 runners per owner |
| `KASUGAI_LAUNCHER_CATALOG_INTERVAL_SECONDS` | `30` | 10–3600 second catalog refresh interval |
| `KASUGAI_LAUNCHER_POLL_SECONDS` | `5` | 2–60 second run poll interval |
| `KASUGAI_LAUNCHER_RUNS_ENABLED` | `false` | Server-wide kill switch for queued task execution |

The dashboard receives presentation metadata and opaque IDs, not executable
paths or arguments. The runner's protected local policy remains authoritative.

## Automation

| Variable | Default | Valid range/meaning |
| --- | --- | --- |
| `KASUGAI_AUTOMATION_ENABLED` | `true` | Enable routes and scheduler |
| `KASUGAI_AUTOMATION_ALLOWED_USERS` | blank/all | Permitted owners |
| `KASUGAI_AUTOMATION_SCHEDULER_SECONDS` | `15` | 5–300 second scheduler cadence |
| `KASUGAI_AUTOMATION_TASKS_ENABLED` | `false` | Second kill switch for automatic launcher delivery |

Automatic launcher delivery can target only a currently published local task
that does not require confirmation. Both launcher execution and automation task
delivery switches must be enabled; the runner policy still controls execution.

## Other feature gates

Each module has an enable switch and an optional ordinary user allowlist:

| Module | Enable variable | Allowlist variable | Defaults |
| --- | --- | --- | --- |
| Unified Nerd Inbox | `KASUGAI_INBOX_ENABLED` | `KASUGAI_INBOX_ALLOWED_USERS` | enabled, all authenticated users |
| Knowledge Vault | `KASUGAI_KNOWLEDGE_ENABLED` | `KASUGAI_KNOWLEDGE_ALLOWED_USERS` | enabled, all authenticated users |
| Network & Security Center | `KASUGAI_SECURITY_ENABLED` | `KASUGAI_SECURITY_ALLOWED_USERS` | enabled, all authenticated users |
| Local AI Toolbox | `KASUGAI_AI_TOOLBOX_ENABLED` | `KASUGAI_AI_TOOLBOX_ALLOWED_USERS` | enabled, all authenticated users |
| Personal Hub | `KASUGAI_PERSONAL_HUB_ENABLED` | `KASUGAI_PERSONAL_HUB_ALLOWED_USERS` | enabled, all authenticated users |

Disabling a module removes access to its routes; it does not automatically
delete the module's existing owner-scoped data.

## Native and persistent `config.ini`

The default native path is `%USERPROFILE%\Kasugai\config.ini`.
`KASUGAI_CONFIG_FILE` selects another absolute or user-relative path. The
container fixes the path to `/data/config.ini` in its persistent data volume.

### `[Application]`

| Option | Default | Meaning |
| --- | --- | --- |
| `buttons` | blank | Legacy serialized quick-launch button data |
| `resourcefolder` | `backgrounds/` | Managed background image directory relative to config, or absolute |

### `[AI]`

| Option | Native default | Meaning |
| --- | --- | --- |
| `provider` | `ollama` | Persisted provider fallback |
| `baseurl` | `http://127.0.0.1:11434/v1` | Persisted compatible endpoint base URL |
| `model` | `gpt-oss:20b` | Persisted model ID |

Compose maps the corresponding non-secret environment settings into this
section at container start.

### `[Licensing]`

| Option | Native default | Meaning |
| --- | --- | --- |
| `apiurl` | `http://127.0.0.1:8080` | DeniLicense API address |
| `issuer` | `http://127.0.0.1:8080` | Signed lease issuer |
| `productcode` | `KASUGAI` | Product identifier |
| `activationlabel` | `Kasugai Dashboard` | Friendly installation label |
| `deviceprivatekey` | blank/generated | Generated installation private key; never copy casually |
| `activationid` | blank | Persisted DeniLicense activation reference |
| `activationlease` | blank | Last verified signed activation lease |

The last three values are application-managed. Do not hand-edit them. Use the
provided migration helper when intentionally moving a native activation into
the Docker volume.

### `[WebServer]`

| Option | Native default | Meaning |
| --- | --- | --- |
| `port` | `8000` | Waitress/dashboard listen port |
| `address` | `localhost` | Native listen address; container forces `0.0.0.0` internally |
| `kasaddress` | `localhost` | Team Room chat service host |
| `kasport` | `8008` | Team Room chat service port |
| `mediaport` | `50052` | Screen/media service port |
| `publicurl` | blank | Canonical invitation origin |
| `sessionsecret` | generated | Flask session-signing secret |

### `[FileTransfer]`

| Option | Native default | Meaning |
| --- | --- | --- |
| `uploadfolder` | `kasugai/resources/` | Received/uploaded resource directory |
| `address` | `localhost` | File-transfer service host |
| `port` | `50051` | File-transfer gRPC port |

### `[Database]`

| Option | Default | Meaning |
| --- | --- | --- |
| `dbpath` | `chat_history.db` | Chat database path |
| `projectdbpath` | `project_manager.db` | Project database path |
| `dashboarddbpath` | `personal_dashboard.db` | Personal modules/connectors database path |
| `encryption_key` | generated | Fernet key for encrypted application fields and credentials |

Relative paths are resolved beside `config.ini`. Losing or replacing the
encryption key makes existing encrypted fields and personal credentials
unreadable, even if the database files survive.

### `[Logging]`

| Option | Default | Meaning |
| --- | --- | --- |
| `path` | `kasugai/logs/` | Log directory relative to config, or absolute |
| `loglevel` | `INFO` | Python logging level |

## Compose overlays

Compose files are intentionally additive:

| File | Adds/changes |
| --- | --- |
| `docker-compose.yml` | Combined dashboard and Go Team Room services |
| `docker-compose.dashboard.yml` | Dashboard connected to an external private Team Room host |
| `docker-compose.ollama.yml` | Private Ollama service and one-shot model pull profile |
| `docker-compose.ollama.nvidia.yml` | NVIDIA device reservation for Ollama |
| `docker-compose.repositories.yml` | One narrow read-only repository bind mount |

Pass the same ordered `-f` list to `config`, `run`, `up`, `stop`, and other
commands for a particular layout. Compose project/volume names are explicit so
the combined and dashboard-only layouts preserve shared dashboard data.

## Validate configuration

Render each layout you plan to use:

```powershell
docker compose config
docker compose -f docker-compose.yml -f docker-compose.ollama.yml config
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml config
$env:KASUGAI_REPOSITORY_HOST_PATH = (Get-Location).Path
docker compose -f docker-compose.yml -f docker-compose.repositories.yml config
```

`docker compose config` resolves direct environment secrets into its output.
Inspect it locally and do not attach unredacted output to an issue. A successful
render proves syntax/interpolation, not provider connectivity or credential
validity.
