# Getting started

This guide takes a new installation from prerequisites to a verified first
login. The combined Docker Compose stack is the recommended path because it
keeps the dashboard, Team Room services, storage, and optional Ollama model on
declared networks and persistent volumes.

## Choose a deployment layout

| Layout | Use it when | Entry command |
| --- | --- | --- |
| Combined Compose | Dashboard and Team Room run on one Docker host | `docker compose up --build -d --wait` |
| Dashboard-only Compose | Team Room services run on a private VPS/VPN host | `docker compose -f docker-compose.dashboard.yml up --build -d --wait` |
| Native development | You are modifying Python/Go code locally | `python main.py` plus `go run .` in `kasugai_server` |

The optional Ollama overlays work with either Compose layout. Companion agents
are installed later on Windows machines and connect outbound to the ordinary
dashboard URL.

## Prerequisites

For the combined Compose path:

- Docker Desktop or Docker Engine with Docker Compose v2.
- A running DeniLicense v1.1 deployment.
- A DeniLicense product whose code exactly matches the Kasugai product setting,
  normally `KASUGAI`.
- An active license assigned to the first user, or a claim code issued by the
  DeniLicense administrator.
- Enough persistent storage for dashboard data, uploaded resources, and—when
  enabled—Ollama model weights.

For native development, also install Python 3.14 and a Go toolchain compatible
with `kasugai_server/go.mod`. The three Windows companion agents require Python
3.10 or newer on their target machines; their installers create isolated
virtual environments.

## 1. Prepare DeniLicense

Kasugai does not create licenses. In the DeniLicense administration service:

1. Create or identify the Kasugai product.
2. Confirm its exact product code.
3. Create an active license.
4. Either issue a one-time claim code for that customer, or have the customer
   request the KASUGAI license and approve that request to assign it directly.
5. Record the API address and the signed activation issuer. The issuer is a
   logical identity embedded in signed leases and may differ from the address
   containers use to reach the API.

The DeniLicense login email/password and optional claim code are entered only
on Kasugai's login page. See [Credentials and external codes](CREDENTIALS.md)
for the user and administrator workflows.

## 2. Create the environment file

From the repository root:

```powershell
Copy-Item .env.example .env
```

At minimum, review:

```ini
DENILICENSE_API_URL=http://denilicense-api:8080
DENILICENSE_ISSUER=http://127.0.0.1:8080
DENILICENSE_PRODUCT_CODE=KASUGAI
DENILICENSE_ACTIVATION_LABEL=Kasugai Dashboard
KASUGAI_DASHBOARD_BIND_HOST=127.0.0.1
KASUGAI_AI_PROVIDER=disabled
```

`DENILICENSE_API_URL` must be reachable from the dashboard container.
`DENILICENSE_ISSUER` must match the issuer configured by DeniLicense exactly.
Keep the dashboard bound to loopback unless a firewall and trusted HTTPS proxy
provide the public boundary.

All integrations beyond licensing are optional. Leave OpenAI, GitHub, and IMAP
secrets blank for the first start. The [configuration reference](CONFIGURATION.md)
explains every public variable and the [credentials guide](CREDENTIALS.md)
explains how to obtain optional provider values.

For dashboard-only Compose, also set the private/VPN address of the separately
running Team Room server before validation:

```ini
KASUGAI_SERVER_HOST=kasugai-server.internal
KASUGAI_SERVER_PORT=8008
KASUGAI_FILE_TRANSFER_HOST=kasugai-server.internal
KASUGAI_FILE_TRANSFER_PORT=50051
KASUGAI_MEDIA_PORT=50052
```

`KASUGAI_SERVER_HOST` is required by `docker-compose.dashboard.yml`. When file
transfer uses the same host, `KASUGAI_FILE_TRANSFER_HOST` may be left blank so
Compose inherits the server host. These services have no transport
authentication of their own; keep them behind the private boundary described
in [Architecture and security](ARCHITECTURE.md).

## 3. Start DeniLicense and its network

The primary Compose stack joins the external `denilicense-network`; it does not
create or own that network. Start the DeniLicense stack first. In a sibling
checkout, the usual flow is:

```powershell
Set-Location ..\DeniLicense
docker compose up --build -d --wait
Set-Location ..\Dashboard
```

If your DeniLicense deployment is managed another way, ensure an external
Docker network named `denilicense-network` exists and that the API is reachable
under `DENILICENSE_API_URL` before starting Kasugai.

## 4. Validate and start the core stack

Render the effective Compose configuration first:

```powershell
docker compose config
```

This command can reveal missing interpolation values and port conflicts. Do not
share its output when direct secret environment values are populated.

Start the dashboard and Team Room services:

```powershell
docker compose up --build -d --wait
```

Check status:

```powershell
docker compose ps
docker compose logs --tail 100 dashboard
docker compose logs --tail 100 kasugai-server
```

Open `http://localhost:8000`. The default `127.0.0.1` bind is intentionally
reachable only from the Docker host.

## 5. Complete the first login

1. Enter the DeniLicense customer email and password.
2. If the license is already assigned to this account, leave **Claim Code**
   blank.
3. If the DeniLicense administrator issued a claim code, enter the complete
   value exactly as issued.
4. Choose **Verify License**.

On first activation, Kasugai generates an Ed25519 installation identity,
requests an activation, verifies the signed lease, and stores the identity and
lease in the persistent dashboard-data volume. Subsequent starts reuse that
identity. Do not delete the volume during normal updates.

## 6. Verify the basic application

After login, perform a small smoke test:

- Home and Projects load without redirecting back to login.
- Team Room opens. When using the combined stack, room operations can reach the
  internal Go service.
- Settings opens and shows the Workstation, Homelab, and Launcher sections.
- Network & Security Center reports the intended high-risk feature switches.
- `docker compose ps` reports the expected services as healthy/running.

Optional modules can be configured after this baseline works. This makes it
easier to distinguish a core deployment issue from a provider credential issue.

## 7. Optional: enable private local AI

The core stack reports AI as disabled. To use the supplied private Ollama
service, pull the configured model once and start with the overlay. On an NVIDIA
host:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml --profile model-pull run --rm ollama-pull
docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml up --build -d --wait
```

For CPU-only operation, omit `docker-compose.ollama.nvidia.yml` from both
commands. The model volume is persistent. Never publish Ollama port 11434 to an
untrusted network; the supplied service stays private to the Compose network.

To use hosted OpenAI instead, follow the distinct hosted-provider setup in
[Credentials and external codes](CREDENTIALS.md) and set an appropriate hosted
model ID. Do not put a hosted OpenAI key in `KASUGAI_AI_API_KEY`; that variable
authenticates private/local compatible endpoints.

## 8. Optional: expose a repository folder

The default dashboard container cannot see host source code. To expose one
narrow folder read-only:

```ini
KASUGAI_REPOSITORY_HOST_PATH=C:/Projects
```

Then start with the repository overlay:

```powershell
docker compose -f docker-compose.yml -f docker-compose.repositories.yml up --build -d --wait
```

Do not mount an entire drive, user profile, SSH folder, or secrets directory.
The dashboard performs only a bounded set of non-interactive Git inspection
commands, but the mounted file boundary should still be minimal.

## 9. Optional: pair companion agents

Open the relevant Settings tab, create a pairing, and run the displayed command
on the target Windows machine. Enter the one-time code only in the hidden local
prompt. Each agent is independent:

- Workstation: aggregate host telemetry.
- Homelab: locally approved Docker inventory, health checks, logs, and restart.
- Launcher: locally allowlisted executable tasks.

Continue with [Companion agents](COMPANION_AGENTS.md) before enabling Homelab
grants or Launcher execution.

## Native development setup

Create a Python environment from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create or edit `%USERPROFILE%\Kasugai\config.ini`:

```ini
[Licensing]
apiurl = http://127.0.0.1:8080
issuer = http://127.0.0.1:8080
productcode = KASUGAI
activationlabel = Kasugai Dashboard
deviceprivatekey =
activationid =
activationlease =
```

Start the Go service in one terminal:

```powershell
Set-Location kasugai_server
go run .
```

Start the dashboard in another terminal from the repository root:

```powershell
python main.py
```

The Python process does not automatically load `.env`. Set needed environment
variables in the process environment or use `config.ini` for supported native
settings.

For test-local state that should not touch `%USERPROFILE%`, set
`KASUGAI_CONFIG_FILE` to a path in a disposable directory before importing the
application.

## Stop, restart, and update safely

Stop without deleting data:

```powershell
docker compose stop
```

When a layout uses overlays, repeat the exact same ordered `-f` list used for
`up`; a bare command addresses only the base combined layout. For example:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ollama.yml stop
```

Rebuild/recreate while preserving volumes:

```powershell
docker compose up --build -d --wait
```

Again, reuse the layout's complete ordered overlay list when rebuilding.

Do not use `docker compose down -v` for a routine stop or upgrade. `-v` removes
named volumes holding the installation identity, activation lease, encryption
key, databases, uploaded resources, and possibly Ollama model weights.

Before a material upgrade, follow the backup procedure in
[Operations and troubleshooting](TROUBLESHOOTING.md).

## Next steps

- Review every setting you changed in [Configuration reference](CONFIGURATION.md).
- Use secret files and rotate provider credentials as described in
  [Credentials and external codes](CREDENTIALS.md).
- Read [Architecture and security](ARCHITECTURE.md) before enabling public
  access, remote actions, or task delivery.
- Keep [Operations and troubleshooting](TROUBLESHOOTING.md) with the deployment
  runbook.
