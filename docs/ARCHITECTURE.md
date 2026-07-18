# Architecture and security

Kasugai is a self-hosted dashboard with deliberately narrow bridges to host
telemetry, Docker, local task execution, licensing, optional model providers,
and the Team Room service. This document explains where code and data run, what
crosses each boundary, and which controls must remain aligned.

## Component map

```text
Browser
  |
  | HTTP(S) / session cookie / route-specific CSRF controls
  v
Flask + Waitress dashboard --------------------> DeniLicense API
  |       |          |       |                   (login, claim, activation lease)
  |       |          |       +-----------------> GitHub / TLS IMAP
  |       |          |                           (optional bounded evidence)
  |       |          +-------------------------> OpenAI-compatible endpoint
  |       |                                      (private Ollama or hosted API)
  |       +------------------------------------> Go Team Room services
  |                                              (chat, file transfer, media)
  +<------------------------------------------- Workstation / Homelab / Launcher
                                                 outbound companion agents
```

In the combined Compose layout, the dashboard and Go server communicate on the
default private Compose network. DeniLicense is reached over the external
`denilicense-network`. The Ollama overlay adds a separate internal network. The
long-running Ollama container has no external egress there; only the one-shot
model-pull job receives an egress-capable network for model download. The
dashboard also remains on its ordinary Compose network and retains the egress
needed for licensing and explicitly configured providers.

## Runtime components

### Dashboard

The Python application is created by `src/wsgi.py` and served by Waitress in the
container. `main.py` is the native development launcher. Flask blueprints own
authentication, UI, project, agent, automation, security, and personal-module
routes.

The dashboard is intended to run as one logical replica. It uses SQLite-backed
stores plus in-process scheduler, rate-limit, readiness, and coordination state.
Running multiple dashboard replicas against the same volume is not a supported
high-availability design.

### Go Team Room server

`kasugai_server/main.go` starts chat on port 8008, file transfer on 50051, and
media/screen sharing on 50052. Users, rooms, messages, pending file data, and
media streams live only in the Go process's in-memory datastore and disappear
when it restarts. The combined stack exposes its ports only to other containers.
The dashboard-only/VPS topology requires a private tunnel, VPN, or authenticated
proxy boundary.

The JSON configuration includes a legacy `tls_config` object, but the current
server does not apply it when starting listeners. Keep `enabled` false; adding a
certificate/key path does not turn on TLS. The service also does not currently
authenticate clients at its own transport boundary. Room passwords are selected
by users and compared/stored in plaintext process memory; they are not a strong
network security boundary. Do not expose these ports to an untrusted network.

### Companion agents

All three companions initiate requests to dashboard endpoints and use separate
owner-bound bearer credentials. They require HTTPS for non-loopback origins;
plain HTTP is accepted only for localhost/loopback development. They do not
share credentials with the browser, DeniLicense, or one another. Windows DPAPI
protects their local records for the pairing user.

- Workstation has no action protocol.
- Homelab accepts only fixed log/restart operations after server, owner, local
  policy, and container-label gates agree.
- Launcher maps an opaque server task ID back to a locally defined strict task;
  executable details never enter the server catalog.

See [Companion agents](COMPANION_AGENTS.md) for the complete local controls.

## Authentication and authorization

### DeniLicense boundary

Kasugai sends account credentials to the configured DeniLicense login endpoint,
optionally redeems a claim code, and locates the active license matching the
configured product. It generates an Ed25519 installation identity and accepts
entitlements only from a verified `dllease1` lease bound to:

- the configured issuer;
- the configured product/audience;
- the selected license and activation;
- the installation public-key thumbprint;
- the current validity window.

Renewal uses a signed proof-of-possession challenge. The private installation
key remains in persistent `config.ini` and is not sent as a secret to the
browser.

### Browser session

The dashboard generates a persistent random Flask session-signing secret when
one is absent. Session cookies are HttpOnly and SameSite=Lax. Secure-cookie
behavior follows the trusted-proxy setting unless explicitly overridden.

Newer security-sensitive module mutations require a session-bound
`X-Kasugai-CSRF` token carried separately from the cookie. Project credential
and assistant-session mutations additionally perform the route's same-origin
check. These controls are route-specific: some legacy project and Team Room
mutations rely on the authenticated SameSite session and authorization checks
without the separate CSRF header. Do not treat the dashboard as safely
embeddable in an untrusted origin; keep the canonical origin and proxy boundary
tight.

### Owner scope and module gates

Owner identity is derived from the verified DeniLicense profile ID, falling
back to normalized email only when necessary. User-owned records, connectors,
companion agents, AI sessions, inbox overlays, knowledge items, and Personal Hub
items are queried and mutated under that owner key.

Module allowlists compare the authenticated profile ID and email. Project
sharing uses explicit invitation records and viewer/editor/owner permission
checks. An accepted share does not reveal the owner's global connections,
personal API keys, or unrelated projects.

## Data at rest

### Dashboard data volume

The explicit `kasugai_dashboard-data` volume contains `/data/config.ini`, logs,
and SQLite databases. Important material includes:

- DeniLicense installation private key, activation ID, and signed lease;
- Flask session secret;
- database encryption key;
- chat history;
- project data, invitation records, AI sessions, and personal OpenAI keys;
- per-user dashboard state, personal GitHub tokens, connectors, inbox overlay,
  Knowledge Vault, Personal Hub, automation, and agent state.

Application fields documented as encrypted use Fernet with the `[Database]
encryption_key`. Personal provider secrets are encrypted and never returned by
read APIs. Some operational metadata remains plaintext so records can be
indexed, ordered, expired, versioned, or owner-scoped.

Encryption at rest does not replace filesystem/volume protection. Anyone with
both the database and config (or a live process with read access) can access
decrypted application data. Losing the encryption key makes encrypted rows
unrecoverable.

### Resource and server volumes

- `kasugai_dashboard-resources` stores managed backgrounds and file-transfer
  resources under `/app/kasugai/resources`.
- `kasugai_server-data` persists the Go server log at `/data/server.log`; it
  does not persist rooms, messages, transferred file state, or media sessions.
- `kasugai_ollama-models` stores downloaded Ollama models when the overlay is
  used.

Treat dashboard data and resources as one recovery set. Preserve explicit
volume names when switching between combined and dashboard-only layouts.

### Native filesystem

Native runs default to `%USERPROFILE%\Kasugai`. Unlike the hardened container
entrypoint, `ConfigHandler` does not enforce Windows ACLs on native files.
Restrict the directory to the account running Kasugai and include it in the
operator's encrypted backup policy.

## Data in transit and external providers

### DeniLicense

The dashboard transmits login and activation operations to
`DENILICENSE_API_URL`. Use HTTPS outside a private local network. Lease
verification still depends on the exact logical issuer, not merely TLS.

### OpenAI-compatible inference

Project Assistant context, user prompts, and bounded conversation history are
sent only when an authorized user explicitly invokes AI. The Local AI Toolbox
also sends the current conversation's prompts and bounded history to the
administrator-configured compatible endpoint. With the Ollama overlay, this
traffic remains on the internal network. With hosted OpenAI or another remote
endpoint, it leaves the deployment and is governed by that provider's data and
billing policies.

Kasugai uses `POST /v1/chat/completions`, requests a structured JSON result, and
does not grant the model direct tool, filesystem, browser, or command access.
Project change suggestions are previewed, individually selectable, signed,
short-lived, and rejected after conflicting workspace changes. The user must
apply selected changes separately.

### GitHub and IMAP evidence

Deployment evidence retrieval is double-gated by owner allowlist and provider-
specific target/account checks. GitHub authentication is sent only for a
matching repository allowlist entry. IMAP logs in over TLS and selects INBOX
read-only; it bounds message count/body bytes and does not expose raw provider
credentials to project collaborators.

Evidence is compacted and bounded before it enters the model request. Raw
source bodies are not returned as browser API responses. Provider permissions
still matter: a credential with broad access has a larger blast radius even if
Kasugai currently performs only bounded reads.

### Personal GitHub connector

The personal notification connector is separate from deployment evidence. It
uses a per-owner encrypted classic token to call the authenticated user and
notifications endpoints. Inbox state changes in Kasugai do not mark or mutate
GitHub notifications.

## Container hardening

The checked-in Compose services:

- use read-only root filesystems;
- drop all Linux capabilities where declared;
- set `no-new-privileges`;
- use bounded tmpfs mounts for writable temporary data;
- persist only explicit data/resource/model paths;
- do not mount `/var/run/docker.sock`, the Windows Docker pipe, host `/proc`, or
  a host PID namespace;
- publish only dashboard port 8000 in the combined layout;
- bind that port to `127.0.0.1` by default.

The dashboard container begins as root only so the entrypoint can initialize
and permission persistent mounts. It then executes Waitress as the unprivileged
`kasugai` user. The entrypoint applies umask 077, directory mode 700, and file
mode 600 to managed config/database/log paths.

## Browser security controls

Routes apply restrictive response controls appropriate to their surfaces,
including Content Security Policy, no-sniff, frame denial, referrer policy,
permissions policy, and no-store behavior for sensitive pages/APIs. Frontend
code renders API-controlled values through text nodes or escaping rather than
trusted HTML sinks.

External links are constrained by feature:

- project and quick-launch connections reject embedded credentials;
- personal bookmarks require credential-free HTTPS;
- inbox GitHub destinations are canonical GitHub HTTPS repository links;
- launcher external destinations require simple credential-free HTTPS.

These validations reduce confused-deputy and secret-in-URL risks; they are not
a substitute for reviewing a destination before opening it.

## High-risk feature gates

Three server switches default off:

| Switch | Boundary |
| --- | --- |
| `KASUGAI_HOMELAB_ACTIONS_ENABLED` | Active Homelab log reads and restarts |
| `KASUGAI_LAUNCHER_RUNS_ENABLED` | Delivery of user-requested launcher runs |
| `KASUGAI_AUTOMATION_TASKS_ENABLED` | Automatic launcher-task delivery |

Enabling a switch makes a protocol path available; it does not erase owner,
local policy, label, task identity, confirmation, or CSRF checks. Review the
Network & Security Center after every configuration change.

## Reverse proxy boundary

For remote browser access:

1. Keep the published dashboard port on loopback.
2. Put a maintained HTTPS reverse proxy on the same trusted host/network.
3. Set a single canonical `KASUGAI_PUBLIC_URL`.
4. Forward/replace Host, scheme, client address, and port headers.
5. Set `KASUGAI_TRUST_PROXY=true` only when direct dashboard access is blocked.
6. Set Secure cookies and HSTS at the HTTPS boundary.
7. Apply request/body/time limits compatible with Kasugai's bounded uploads and
   long AI request timeout.

Do not expose Waitress on `0.0.0.0` to an untrusted network merely because an
upstream proxy also exists.

## Security-sensitive operational rules

- Back up configuration and databases together; never rotate the database
  encryption key independently of encrypted rows.
- Do not delete named volumes during routine updates.
- Revoke provider credentials before trying to scrub leaked copies.
- Revoke companion records when a device is lost.
- Keep host clocks synchronized; license, invitation, pairing, proposal, and
  token expiration checks depend on time.
- Do not place secrets in `.env` on shared systems when a mounted secret file is
  available.
- Treat logs and Homelab log excerpts as potentially sensitive even though
  common secrets are redacted and sizes are bounded.
- Keep local repository mounts and provider scopes as narrow as possible.

Operational procedures are in [Operations and troubleshooting](TROUBLESHOOTING.md),
and provider credential acquisition is in
[Credentials and external codes](CREDENTIALS.md).
