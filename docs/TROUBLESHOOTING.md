# Operations and troubleshooting

This runbook starts with low-risk observations, then narrows failures by
boundary. It applies to the combined Compose stack, dashboard-only Compose,
native development, and the three Windows companion agents.

Do not paste `.env`, rendered Compose configuration, `config.ini`, database
files, pairing responses, Authorization headers, provider response bodies, or
full URLs containing private hostnames into a ticket. Those artifacts can
contain credentials, installation keys, signed leases, user data, or network
details.

## Establish the deployment shape first

Record which layout and ordered overlay list started the current containers.
Every later `config`, `ps`, `logs`, `stop`, and `up` command should use that same
list.

| Layout | Compose prefix |
| --- | --- |
| Combined core | `docker compose -f docker-compose.yml` |
| Combined with CPU Ollama | `docker compose -f docker-compose.yml -f docker-compose.ollama.yml` |
| Combined with NVIDIA Ollama | `docker compose -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.ollama.nvidia.yml` |
| Combined with repository mount | Add `-f docker-compose.repositories.yml` after the base file and before/alongside the other intended overlays |
| Dashboard-only | `docker compose -f docker-compose.dashboard.yml` plus the intended Ollama/repository overlays |

Compose merges files in order. A bare `docker compose` command can inspect or
replace a different project from the one you meant when the running layout used
another base file.

## Five-minute first response

From the repository root, using the correct Compose prefix:

```powershell
docker compose ps
docker compose logs --tail 150 dashboard
docker compose logs --tail 150 kasugai-server
docker compose config --services
docker network inspect denilicense-network
```

For dashboard-only Compose, omit the nonexistent local `kasugai-server` log
command and check the remote/VPS service separately. `docker compose config`
can include resolved direct secret values; inspect it locally and do not attach
the full output to a report.

Then test the browser-facing boundary from the Docker host:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/login -UseBasicParsing
```

A successful login-page response proves only that the dashboard listener is
reachable. It does not prove DeniLicense, Team Room, AI, GitHub, IMAP, or an
agent is healthy.

## Container states and startup failures

### The dashboard container is restarting

1. Read the first error in `docker compose logs dashboard`; later messages can
   be secondary failures.
2. Confirm `kasugai_dashboard-data` is writable by the container entrypoint and
   not mounted read-only by an extra override.
3. Check that the persistent `config.ini` is parseable and that its database
   encryption key was not replaced independently of the databases.
4. Validate the effective Compose model locally with `docker compose config`.
5. If an override uses `_FILE`, confirm the file is mounted at exactly the path
   visible inside the container. A host path is not automatically a container
   path.

The supplied image intentionally has a read-only root filesystem. Persistent
writes belong under `/data` or `/app/kasugai/resources`; temporary writes belong
under the declared `/tmp` tmpfs. An extension that writes elsewhere will fail.

### Compose says `denilicense-network` does not exist

The network is external and owned by the DeniLicense deployment. Start
DeniLicense first, or create/connect the correctly named network through that
deployment. Do not casually replace it with a similarly named network: both
services must join the same Docker network and the dashboard must resolve the
host in `DENILICENSE_API_URL`.

### Port 8000 is already in use

Find the existing listener before changing anything:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

Stop the unintended process or use an explicit, reviewed port mapping in a
local Compose override. Keep the published address on `127.0.0.1` when a local
reverse proxy owns public access.

### A health check remains `starting` or becomes `unhealthy`

- Dashboard health checks request `/login` on loopback inside its container.
  Inspect application startup logs and persistent-config access.
- The Go service health check verifies listeners on 8008, 50051, and 50052.
  Inspect `kasugai-server` logs; one missing listener makes the service
  unhealthy.
- Ollama health calls `ollama show` for the exact configured model. Pull that
  exact model into the persistent volume with the `model-pull` profile, then
  start with the identical overlay list.

## Configuration does not appear to change

The container entrypoint maps selected **nonblank** environment values into
persistent `/data/config.ini`. A later blank Compose value does not erase a
previously persisted nonblank AI or licensing value. Use the
[configuration reference](CONFIGURATION.md) to identify the owning layer, then
change the persisted setting deliberately or restore a reviewed configuration.

Other common causes:

- Native `python main.py` does not read `.env`; export process variables or edit
  the supported `config.ini` option.
- An environment secret that contains only whitespace is treated as blank, so
  its `_FILE` form is used.
- A nonblank direct secret wins over its `_FILE` form.
- Changing `.env` does not mutate an existing container; recreate it with
  `docker compose up -d` using the correct overlays.
- Changing an agent policy file affects only the local agent, not the dashboard
  container.

## Login and DeniLicense

### `Could not reach DeniLicense`

1. Confirm the DeniLicense API is running.
2. From Compose, use the container-reachable API URL, normally
   `http://denilicense-api:8080`; do not substitute the host's loopback address
   unless the container can actually reach it there.
3. Inspect `denilicense-network` membership and DNS naming.
4. For a remote API, verify TLS trust and firewall policy without disabling
   certificate validation.

`DENILICENSE_API_URL` is the network destination. `DENILICENSE_ISSUER` is a
signed logical identity and can legitimately be different. Changing the issuer
to make networking work causes lease verification to fail.

### `No active DeniLicense license for product ...`

- Verify the configured product code exactly matches the DeniLicense product.
- Confirm the license is active, within its validity window, and assigned to
  the signing-in customer.
- If it is unassigned, use a claim code issued for that product and customer.
- A DeniLicense platform/operator account is not a customer account for claim
  redemption.

### A claim code is rejected

Copy the complete code exactly as issued. Check whether it was already
consumed, is malformed/incomplete, is being used by a non-customer account, or
belongs to a license that is inactive, not yet valid, expired, or revoked. If
requests were rate-limited, wait before retrying; otherwise obtain help or a
replacement from the operator of the DeniLicense service shown on the login
page. There is no public universal Kasugai code site.

### Activation or lease errors after moving the deployment

The dashboard data volume holds the device private key, activation ID, and
signed lease as one identity. Restoring only a database or generating a new
`config.ini` separates that identity and can consume another activation seat.
Restore the entire dashboard-data recovery set. If the original identity is
irrecoverable, ask the DeniLicense administrator to revoke/release the stale
activation before retrying.

### Login succeeds and immediately returns to the login page

Inspect browser cookies and proxy behavior:

- The public browser origin must be consistent; avoid switching between host
  names, ports, and HTTP/HTTPS mid-session.
- When HTTPS terminates at a proxy, set `KASUGAI_TRUST_PROXY=true` only after
  blocking direct client access to Waitress and forwarding the original scheme
  and host correctly.
- A Secure session cookie is not sent over HTTP. Use HTTPS at the public
  boundary or correct an accidental secure-cookie override for loopback-only
  development.
- Preserve a stable `sessionsecret` in the dashboard data volume; replacing it
  invalidates all current sessions.

## A module or control is missing

First distinguish licensing from deployment policy. Most module allowlists are
comma-separated DeniLicense profile IDs or email addresses; an empty ordinary
module allowlist permits all authenticated licensed users.

Check the matching enabled flag and allowlist:

| Surface | Gate |
| --- | --- |
| Developer/GitHub | `KASUGAI_DEVELOPER_ALLOWED_USERS` |
| Workstation | `KASUGAI_WORKSTATION_ENABLED` and `KASUGAI_WORKSTATION_ALLOWED_USERS` |
| Homelab | `KASUGAI_HOMELAB_ENABLED` and `KASUGAI_HOMELAB_ALLOWED_USERS` |
| Launcher | `KASUGAI_LAUNCHER_ENABLED` and `KASUGAI_LAUNCHER_ALLOWED_USERS` |
| Automation | `KASUGAI_AUTOMATION_ENABLED` and `KASUGAI_AUTOMATION_ALLOWED_USERS` |
| Inbox, Vault, Security, Toolbox, Personal Hub | Their respective `*_ENABLED` and `*_ALLOWED_USERS` values |

The personal OpenAI key control is a special case: it appears only when the
effective provider is `openai`. The deployment OpenAI fallback is another
special case: an empty `KASUGAI_AI_ALLOWED_USERS` denies fallback use to
everyone.

After changing a process-level gate, recreate/restart the dashboard. Creating a
new provider token cannot bypass a Kasugai allowlist.

## Project Assistant and Local AI Toolbox

### Use the readiness status to choose a branch

| Status/symptom | Checks |
| --- | --- |
| Disabled/not configured | Set a supported provider and base URL, or add the Ollama overlay |
| Model missing | Pull the exact `KASUGAI_AI_MODEL` into the Ollama volume |
| Unavailable/timeout | Check provider DNS, network, model service, and the paired timeout/request-budget values |
| 401 credential rejected | Check the credential source for the effective provider; do not move a hosted key into the private-key namespace |
| 403 denied | Check key permissions, project/model access, organization policy, and billing state |
| Invalid/structured response | Confirm the endpoint implements Kasugai's OpenAI-compatible Chat Completions request and structured JSON response |
| Saved-chat backend mismatch | Start a new chat for the new provider/model rather than reusing the old session |

Provider credential namespaces are intentionally distinct:

- `provider=openai`: personal encrypted key first, then `OPENAI_API_KEY(_FILE)`
  only for a user in `KASUGAI_AI_ALLOWED_USERS`.
- `provider=ollama`: optional private compatible-endpoint credential from
  `KASUGAI_AI_API_KEY(_FILE)`.
- Supplied local Ollama: no credential.

The Local AI Toolbox supports only the effective `ollama` provider. A valid
hosted OpenAI personal or deployment key does not enable the Toolbox.

For hosted OpenAI, replace the local default `gpt-oss:20b` with a model ID that
exists in the selected OpenAI API project. A personal key is encrypted on save;
hosted readiness checks only that a credential is present and does not contact
OpenAI. Only an actual assistant request proves key/model access. If a mounted hosted
`OPENAI_API_KEY_FILE` is missing or unreadable, the fallback appears
unavailable; verify the mount path inside the container. Also remove any stale
nonblank direct `OPENAI_API_KEY`, because it takes precedence over the file.

### Hosted key is valid but requests fail

API billing is separate from a ChatGPT subscription. Verify the selected API
project, model availability, usage limit/budget, and key permission for model
requests to `POST /v1/chat/completions`. Kasugai does not need an organization
admin key. See [Credentials and external codes](CREDENTIALS.md) for exact key
creation and rotation steps.

### Local generation is slow or times out

- Inspect Ollama logs and host CPU/GPU memory pressure.
- Confirm the model fits the intended hardware and the NVIDIA overlay is loaded
  on an NVIDIA deployment.
- Increase `KASUGAI_AI_TIMEOUT_SECONDS` and
  `KASUGAI_AI_REQUEST_BUDGET_SECONDS` together, keeping the whole-request budget
  higher.
- Do not raise timeouts to conceal a missing/unhealthy model; the readiness
  check should first report ready.

## Project connections and evidence

Project connections are credential-free bookmarks. A GitHub/Gmail connection
does not store an OAuth token, password, or API key, and a URL containing
embedded credentials is rejected.

### Personal GitHub notification connection fails

- Use a personal access token **(classic)** with only the `notifications` scope.
  Fine-grained tokens do not support GitHub's notifications endpoint.
- Check token expiration/revocation and any organization SAML SSO authorization
  required for the account.
- Ensure the user passes `KASUGAI_DEVELOPER_ALLOWED_USERS`.
- If Kasugai disconnects/rejects it, create a new finite-lived token; stored
  tokens are never displayed for recovery.

The initial connection validates the token against GitHub's user endpoint. A
classic token missing `notifications` can therefore connect successfully but
fail when the feed is fetched; verify the scope as well as the identity check.

### Deployment GitHub evidence is empty or unauthorized

1. Confirm the project connection is a canonical
   `https://github.com/owner/repository` target.
2. Add only that repository (or reviewed `owner/*`) to
   `KASUGAI_GITHUB_TOKEN_ALLOWLIST`.
3. Ensure the project owner—not merely a shared editor—appears in
   `KASUGAI_AI_SOURCE_ALLOWED_USERS`.
4. For private repositories, verify the fine-grained token selects the
   repository and has Contents and Issues read access. Organization approval or
   SAML authorization may still be required.
5. Recreate the dashboard after changing deployment secret mounts.

Kasugai never attaches the deployment repository token to account-only public
event connections. Public repositories can work anonymously but remain subject
to GitHub rate limits.

### Gmail evidence fails

- Use the generated Google app password, not the normal account password.
- Confirm 2-Step Verification remains enabled and that the account is eligible
  for app passwords.
- The connection's nonblank Account value must match
  `KASUGAI_IMAP_USERNAME` case-insensitively.
- Use `imap.gmail.com` on port 993 and preserve TLS verification.
- A Google password change revokes app passwords; create and mount a new one.
- Managed-domain policy, Advanced Protection, or security-key-only 2-Step
  Verification can make app passwords unavailable. Kasugai has no Google OAuth
  fallback.

Kasugai selects INBOX read-only and performs bounded peek reads, but the app
password remains a sensitive mailbox credential. Rotate it after suspected
exposure.

## Team Room, files, and screen sharing

### Drawer opens but room operations fail

- Combined stack: confirm `kasugai-server` is healthy and all three internal
  ports listen.
- Dashboard-only stack: confirm dashboard host/ports point to the private VPS
  or VPN address and the route permits 8008, 50051, and 50052.
- Inspect both dashboard and Go service logs.
- Do not expose those Go ports directly to an untrusted network. The current Go
  service has no transport authentication and does not apply the legacy
  `tls_config` fields.

Room passwords are user-selected room controls, not external codes and not a
strong network boundary. Users, rooms, messages, pending file bytes, and media
state are in memory. Restarting the Go service clears them; the `server-data`
volume persists only `/data/server.log`.

### File transfer fails

The dashboard rejects missing or oversized files; the route limit is 100 MiB.
Check the reverse proxy's body limit and timeout as well as the dashboard's
resource volume. Do not raise proxy limits without reviewing storage and abuse
controls.

### Screen sharing cannot start

Verify the media port separately from chat and file transfer, and check browser
permission/UI errors. In a remote topology, confirm the private boundary carries
the media service too. A healthy chat listener alone does not prove media
reachability.

## Companion-agent pairing and status

Use [Companion agents](COMPANION_AGENTS.md) for exact installed paths and venv
diagnostics.

### Pairing code rejected

- Pairing codes last ten minutes, are one-use, and allow five wrong attempts.
- Creating a newer pairing invalidates the prior unused pairing for that owner.
- The pairing ID in the displayed command is not the one-time code.
- Run the relative installer command from a checkout's repository root and
  enter the code only in its hidden prompt.
- Check the module enabled flag, owner allowlist, dashboard origin, and target
  clock/network.

### `credentials.json` cannot be decrypted

DPAPI binds it to the Windows user and machine that paired. Run the scheduled
task and diagnostic CLI as that same user. A copied file cannot be migrated to
another account/computer; revoke the old agent and pair the destination.

### Agent is offline

1. Inspect its current-user Task Scheduler entry.
2. Read its rotated `agent.log` under `%LOCALAPPDATA%\Kasugai\<agent>`.
3. Run the installed venv's `python.exe -m <agent> status`, then `run --once`.
4. Check DNS/TLS from that user context. Non-loopback origins require HTTPS;
   cross-origin redirects and URLs containing credentials/query/fragment are
   rejected.
5. A 401 after prior success can mean an invalid or revoked agent credential;
   re-pair when revocation/corruption is confirmed. A 403 is a permission or
   policy denial, so check the owner/module/action gates before replacing a
   valid pairing. A 404 can indicate that the module route is disabled.

### Homelab inventory is empty

- Set local `inventory_enabled` to true and validate the JSON policy.
- Add `io.kasugai.monitor=true` to only the intended containers.
- Ensure the scheduled-task user can invoke the local Docker CLI.
- Labels are rechecked from fresh inventory; stale dashboard display cannot
  grant an action.

Logs require the monitor and logs labels, local `read_logs=true`, and
`KASUGAI_HOMELAB_ACTIONS_ENABLED=true`. Restart additionally requires the
restart label, local `restart=true`, and user confirmation. There is no exec,
shell, stop, delete, prune, pull, or arbitrary-argument protocol.

### Launcher catalog is empty or a run is unavailable

- Enable and validate the local `policy.json`.
- Use absolute executable and optional working-directory paths that exist for
  the scheduled-task user.
- Wait for the next catalog interval after a valid edit.
- User-requested delivery requires `KASUGAI_LAUNCHER_RUNS_ENABLED=true`.
- Automation delivery additionally requires
  `KASUGAI_AUTOMATION_TASKS_ENABLED=true`, and the task must not require
  interactive confirmation.

The dashboard cannot provide an executable, arguments, environment, stdin, or
shell fragment. If a needed command cannot be expressed as a strict local task,
do not weaken the runner; wrap and audit it locally as an explicit executable.

## Automation and inbox

### A rule is enabled but does not run

- Confirm `KASUGAI_AUTOMATION_ENABLED=true`, the owner allowlist, and that the
  dashboard process has remained running long enough for the configured
  scheduler interval.
- The native launcher and production WSGI entry point both start the scheduler;
  avoid running multiple dashboard replicas against the same data volume.
- Interval/daily rules advance past missed occurrences rather than replaying an
  unbounded backlog.
- Metric rules fire on a false-to-true edge and then respect cooldown. A metric
  already over threshold is not a continuous stream of new occurrences.
- Check Automation history for a bounded failure summary.

### An automated launcher task does not run

Both remote-execution switches must be true, the runner must be online with a
current published task, and the local task must have
`requires_confirmation=false`. Automation cannot bypass the local policy or
turn an interactive task into an unattended one.

### Inbox reports one provider failure

Connectors fail independently. A GitHub, agent, or homelab warning does not mean
the entire inbox is corrupt. Fix the named source, refresh after its cache/poll
interval, and remember that archiving or marking a GitHub item read changes only
Kasugai's overlay—not GitHub.

## Repository discovery

If repositories do not appear:

- Core Compose intentionally mounts no source tree. Set a narrow
  `KASUGAI_REPOSITORY_HOST_PATH` and include
  `docker-compose.repositories.yml`.
- Check both repository-root variables in native/custom deployments; a path
  must be under the allowed boundary.
- Mount the directory read-only and avoid an entire drive, user profile, SSH
  folder, or secrets tree.
- Confirm the directory is a Git repository and the dashboard container/user
  can traverse it.

Kasugai returns bounded branch/change summaries, not filenames or arbitrary Git
command output.

## Reverse proxy and public URLs

- Keep Waitress published on loopback and make the proxy the only remote entry.
- Set one canonical `KASUGAI_PUBLIC_URL`, including scheme and nondefault port
  when applicable; it determines share/invitation links.
- Forward or replace Host, original scheme, client address, and port headers.
- Trust proxy headers only when clients cannot connect around that proxy.
- Match proxy upload and AI timeouts to reviewed Kasugai limits; do not disable
  timeouts globally.
- Terminate maintained HTTPS at the boundary and enable HSTS there after the
  HTTPS origin is stable.

Wrong invitation hosts normally indicate a blank/incorrect public URL or
untrusted forwarded host, not a bad invitation token. Issue a new invitation
after fixing the canonical origin if the old link was distributed incorrectly.

## Back up before updates

Kasugai is a coordinated recovery set. Back up at least:

- `kasugai_dashboard-data`: `config.ini`, installation identity/lease,
  encryption/session keys, logs, and SQLite databases;
- `kasugai_dashboard-resources`: managed backgrounds and transfer resources;
- `kasugai_ollama-models` when redownloading model weights is undesirable;
- deployment `.env`, secret-file definitions, proxy configuration, and the
  exact Compose/overlay versions, using an encrypted operator backup system.

`kasugai_server-data` contains only the Go server log. It does not recover Team
Room users, rooms, messages, file bytes, or media sessions.

For a consistent manual snapshot:

1. Record the running image/code revision and ordered Compose files.
2. Stop the exact layout without `-v`.
3. Snapshot/export each named volume with trusted backup tooling.
4. Store `.env` and secret files separately with restricted access; do not place
   plaintext secrets inside an ordinary source archive.
5. Start the exact layout and complete the smoke checks below.
6. Periodically restore into an isolated test deployment. An untested archive
   is not a recovery plan.

Never use `docker compose down -v` as a routine stop or update. Restore dashboard
data and resources together, and never generate a new database encryption key
over restored encrypted rows. Do not restore into a running or nonempty volume
without an explicit rollback plan.

## Safe update checklist

1. Back up the coordinated recovery set.
2. Review release/code and `.env.example` changes.
3. Render the effective configuration locally with the exact overlay list.
4. Pull/build and run `docker compose ... up --build -d --wait`; named volumes
   remain attached.
5. Inspect logs and complete the smoke test.
6. Keep the prior image/revision and backup available until the deployment has
   operated normally through its important workflows.

Smoke test:

- DeniLicense login and lease validation.
- Home, Projects, and Settings.
- Team Room chat/file/media reachability as applicable.
- AI readiness only for the configured provider.
- Personal GitHub and deployment evidence only when configured.
- One status cycle from each paired companion.
- One non-destructive automation notification rule; do not use a remote task as
  the first post-update test.

## Rotate a credential safely

Follow the provider-specific instructions in
[Credentials and external codes](CREDENTIALS.md). In general: revoke a suspected
leak first, create the narrow replacement, update the personal store or mounted
secret, recreate the dashboard when deployment-managed, verify the integration,
and remove obsolete copies. A “configured” badge proves only that secret
material exists; Kasugai intentionally cannot display it for recovery.

## Prepare a safe support report

Include:

- Kasugai revision/version and deployment layout.
- Operating system, Docker/Compose versions, and whether a reverse proxy is
  present.
- A redacted `docker compose ps` result.
- Service names and health states.
- The first relevant error plus a short surrounding log window with emails,
  hostnames, repository names, room names, IDs, and tokens redacted.
- The effective provider name and model ID, but no key or private endpoint URL.
- Whether the issue reproduces in a fresh browser session or one agent
  `run --once` cycle.

Exclude:

- `.env`, `config.ini`, databases, credential/agent policy files, Docker
  inspection output containing environment values, full Compose rendering,
  cookies, CSRF tokens, invitation links, claim/pairing codes, API keys, app
  passwords, signed activation leases, and DPAPI records.

When redacting, replace the entire secret rather than leaving prefixes/suffixes
that can be correlated with provider logs.
