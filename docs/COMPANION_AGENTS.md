# Companion agents

Kasugai uses three independent outbound-only Windows companions. They let a
containerized dashboard receive host telemetry or request tightly bounded local
actions without mounting host process data, a Docker control socket, or a task
execution interface into the dashboard container.

Each companion has its own pairing, long-lived token, scheduled task, install
directory, and server-side revocation record. Pair only the capabilities you
need.

## Capability summary

| Agent | Sends to Kasugai | Can receive | Local authority |
| --- | --- | --- | --- |
| Workstation | Aggregate CPU, memory, GPU, disk, network, uptime, battery | Sampling interval | Fixed collector; no action protocol |
| Homelab | Sanitized Docker inventory and configured health-check results | Fixed `read_logs` or `restart` requests | Local JSON grants plus fresh container labels |
| Launcher | Titles/descriptions/categories/icons and opaque task IDs | Run request for one published opaque ID | Strict local JSON task definition |

All traffic is initiated by the agent toward the dashboard URL. The agents do
not open a listening port.

## Shared prerequisites

- Windows 10/11 or Windows Server with Task Scheduler.
- Python 3.10 or newer available through the `py -3` launcher. A custom
  `-PythonLauncher` must also support the installer's appended `-3` argument.
- A checkout of this repository on the target machine. The Settings page shows
  commands; it does not download source files.
- Network access from the target machine to the dashboard origin.
- A valid Kasugai login whose module allowlist permits pairing.
- PowerShell permission to create a current-user scheduled task.

The agents require HTTPS for non-loopback dashboard origins. Plain HTTP is
accepted only for localhost/loopback development. They reject URLs containing
credentials, queries, or fragments and reject cross-origin redirects.

## How pairing works

1. The signed-in owner creates a pending pairing in the matching Settings tab.
2. Kasugai displays a pairing ID, a separate one-time code, an expiry, and a
   target-side command.
3. The command includes the pairing ID. The agent prompts invisibly for the
   code using `getpass`; the code is not placed in command history.
4. The server accepts the pairing once, issues an agent ID and token, and binds
   them to the authenticated owner.
5. The agent encrypts its credential record with Windows DPAPI for the current
   user and begins using bearer-authenticated outbound requests.

A pairing lasts ten minutes, permits at most five wrong code attempts, and can
be redeemed once. Creating a newer pending pairing for the same owner
invalidates the previous unused pairing. The pairing ID is not sufficient
without the code.

Do not set the optional pairing-code environment variables for an interactive
install: `KASUGAI_PAIRING_CODE`, `KASUGAI_HOMELAB_PAIRING_CODE`, and
`KASUGAI_LAUNCHER_PAIRING_CODE`. They exist for controlled automation but can
be exposed through process environments. The hidden prompt is the recommended
workflow.

## Workstation agent

### Install and pair

Open **Settings → Workstations → Create pairing code**, then run the displayed
command from the repository root. Its expanded form is:

```powershell
.\scripts\install-workstation-agent.ps1 `
    -ServerUrl https://kasugai.example.com `
    -PairingId <pairing-id>
```

Enter the separate one-time code when prompted. All three companion installers
accept the same optional parameters:

- `-DisplayName`: friendly dashboard label; defaults to the computer name.
- `-PythonLauncher`: Python launcher command; defaults to `py`.
- `-ReplacePairing`: explicitly replace a credential already on this computer.
  The installer also adds replacement mode automatically when its normal
  credential file already exists.

The installer creates:

| Item | Location/name |
| --- | --- |
| Application copy | `%LOCALAPPDATA%\Kasugai\workstation-agent\app` |
| Virtual environment | `%LOCALAPPDATA%\Kasugai\workstation-agent\venv` |
| DPAPI credential | `%LOCALAPPDATA%\Kasugai\workstation-agent\data\credentials.json` |
| Logs | `%LOCALAPPDATA%\Kasugai\workstation-agent\agent.log` (rotated) |
| Scheduled task | `Kasugai Workstation Agent` |

The scheduled task runs at logon as the current user with limited privileges.

### Collected data

The collector sends aggregate CPU and memory utilization, load/process count
where available, fixed-disk capacity/usage and I/O rates, aggregate network byte
rates, uptime, battery state, and optional `nvidia-smi` GPU metrics. It does not
enumerate filenames, command lines, usernames, IP/MAC addresses, ports,
environment variables, browser history, or process details.

### Local diagnostics

For an installed agent, use its private virtual-environment interpreter:

```powershell
& "$env:LOCALAPPDATA\Kasugai\workstation-agent\venv\Scripts\python.exe" -m workstation_agent status
& "$env:LOCALAPPDATA\Kasugai\workstation-agent\venv\Scripts\python.exe" -m workstation_agent run --once
& "$env:LOCALAPPDATA\Kasugai\workstation-agent\venv\Scripts\python.exe" -m workstation_agent --verbose run --once
```

`status` never prints the token. Use `--no-nvidia` on `run` when an installed
NVIDIA tool is broken or must not be invoked. In a development checkout where
`requirements-agent.txt` is installed, the equivalent bare `python -m ...`
commands are valid.

### Update or remove

Rerun the installer without pairing arguments to refresh application files and
dependencies while preserving the DPAPI pairing:

```powershell
.\scripts\install-workstation-agent.ps1
```

Remove code and the scheduled task while preserving pairing:

```powershell
.\scripts\uninstall-workstation-agent.ps1
```

Permanently delete the local protected pairing as well:

```powershell
.\scripts\uninstall-workstation-agent.ps1 -RemoveCredentials
```

Server-side revocation in Settings invalidates the token immediately. For a
retired/lost computer, revoke server-side even if you cannot run the uninstaller.

## Homelab agent

### Install and pair

Open **Settings → Homelab → Create homelab pairing**, then run:

```powershell
.\scripts\install-homelab-agent.ps1 `
    -ServerUrl https://kasugai.example.com `
    -PairingId <pairing-id>
```

The installer creates a disabled policy before pairing, copies only the agent
package, creates a minimal virtual environment, and registers the current-user
task `Kasugai Homelab Agent`.

The shared `-DisplayName`, `-PythonLauncher`, and `-ReplacePairing` options
described under Workstation apply here too.

| Item | Location |
| --- | --- |
| Application | `%LOCALAPPDATA%\Kasugai\homelab-agent\app` |
| Virtual environment | `%LOCALAPPDATA%\Kasugai\homelab-agent\venv` |
| DPAPI credential/state | `%LOCALAPPDATA%\Kasugai\homelab-agent\data\credentials.json` |
| Local policy | `%LOCALAPPDATA%\Kasugai\homelab-agent\config.json` |
| Logs | `%LOCALAPPDATA%\Kasugai\homelab-agent\agent.log` (rotated) |

The locally installed Docker CLI must be usable by the same Windows user. The
agent invokes the CLI; it does not connect to an arbitrary daemon URL or expose
the Windows Docker pipe to the dashboard.

### Local policy

Pairing grants no Docker visibility. Start from:

```json
{
  "version": 1,
  "inventory_enabled": true,
  "grants": {
    "read_logs": false,
    "restart": false
  },
  "health_checks": []
}
```

`inventory_enabled` permits the sanitized inventory collector. `read_logs` and
`restart` are independent grants. The file accepts no other top-level or grant
fields and is reloaded during operation.

Containers are visible/actionable only when labels opt in:

```yaml
labels:
  io.kasugai.monitor: "true"
  io.kasugai.logs: "true"
  io.kasugai.actions: "restart"
```

Effective access is an intersection:

| Operation | Required conditions |
| --- | --- |
| Inventory | `inventory_enabled=true` and `io.kasugai.monitor=true` |
| Log excerpt | monitored label, `io.kasugai.logs=true`, local `read_logs=true`, server `KASUGAI_HOMELAB_ACTIONS_ENABLED=true` |
| Restart | monitored label, restart label, local `restart=true`, server `KASUGAI_HOMELAB_ACTIONS_ENABLED=true`, user confirmation |

The host rechecks labels and local policy immediately before an action. The
protocol does not support exec, shell, stop, delete, prune, pull, Compose
commands, paths, arbitrary signals, or arguments.

### Health checks

Health checks are defined only in the local policy:

```json
{
  "name": "Home service",
  "url": "https://service.internal/health",
  "timeout_seconds": 3,
  "expected_statuses": [200, 204]
}
```

Rules:

- At most 32 checks; names must be unique and 1–80 printable characters.
- URL scheme must be explicit HTTP or HTTPS.
- Credentials, queries, and fragments are rejected.
- Timeout is 0.5–10 seconds.
- `expected_statuses` has 1–16 codes from 100 through 599; omitting it accepts
  200–399.
- The collector follows no redirects, retains no response body, and reports the
  friendly name, checked time, availability, HTTP status, latency,
  consecutive-failure count, bounded error code, and fixed/opaque protocol
  metadata. It never reports the URL or response body.

Because the host performs these requests, review each target as a local network
access grant. The browser cannot add targets.

### Validate, run, update, and remove

```powershell
& "$env:LOCALAPPDATA\Kasugai\homelab-agent\venv\Scripts\python.exe" -m homelab_agent status
& "$env:LOCALAPPDATA\Kasugai\homelab-agent\venv\Scripts\python.exe" -m homelab_agent run --once
& "$env:LOCALAPPDATA\Kasugai\homelab-agent\venv\Scripts\python.exe" -m homelab_agent --verbose run --once
```

`status` parses and summarizes the policy without showing secrets. A malformed
policy fails closed. Bare `python -m ...` is appropriate only in a development
checkout with `requirements-homelab-agent.txt` installed.

Refresh code while keeping pairing and policy:

```powershell
.\scripts\install-homelab-agent.ps1
```

Remove code/task but preserve both protected pairing and policy:

```powershell
.\scripts\uninstall-homelab-agent.ps1
```

Add `-RemoveCredentials`, `-RemovePolicy`, or both only when those local records
should be erased. Revoke server-side separately.

## Launcher agent

### Install and pair

Open **Settings → Launcher → Create runner pairing**, then run:

```powershell
.\scripts\install-launcher-agent.ps1 `
    -ServerUrl https://kasugai.example.com `
    -PairingId <pairing-id>
```

The installer creates a disabled empty policy and scheduled task
`Kasugai Launcher Agent`.

The shared `-DisplayName`, `-PythonLauncher`, and `-ReplacePairing` options
described under Workstation apply here too.

| Item | Location |
| --- | --- |
| Application | `%LOCALAPPDATA%\Kasugai\launcher-agent\app` |
| Virtual environment | `%LOCALAPPDATA%\Kasugai\launcher-agent\venv` |
| DPAPI credential/state | `%LOCALAPPDATA%\Kasugai\launcher-agent\data\credentials.json` |
| Local task policy | `%LOCALAPPDATA%\Kasugai\launcher-agent\policy.json` |
| Logs | `%LOCALAPPDATA%\Kasugai\launcher-agent\agent.log` (rotated) |

### Task policy

Every task must contain exactly the documented fields:

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

Constraints include:

- Maximum 128 tasks and 64 arguments per task.
- Unique local IDs; bounded printable presentation strings.
- Absolute executable and optional working-directory paths.
- Timeout from 1 through 300 seconds.
- No environment field, shell fragment, stdin, or dashboard-provided argument.

Validate after editing:

```powershell
& "$env:LOCALAPPDATA\Kasugai\launcher-agent\venv\Scripts\python.exe" -m launcher_agent config validate
& "$env:LOCALAPPDATA\Kasugai\launcher-agent\venv\Scripts\python.exe" -m launcher_agent status
```

The agent validates the policy before publishing and again immediately before
execution. It uses `shell=False`, filters the inherited environment to a fixed
OS path/profile/temp allowlist, closes stdin, bounds captured output to 64 KiB,
strips terminal controls, redacts common password/token patterns, and terminates
work at the configured timeout.

### Execution gates

A task can run only when:

1. The launcher module and owner are enabled/allowed.
2. `KASUGAI_LAUNCHER_RUNS_ENABLED=true` on the server.
3. The paired runner is online and has published the current opaque task ID.
4. Its local policy remains enabled and contains the same task.
5. The user approves a confirmation preview when
   `requires_confirmation=true`.

Automations add a second gate: `KASUGAI_AUTOMATION_TASKS_ENABLED=true`, and the
target task must not require interactive confirmation.

### Update or remove

Refresh code while preserving pairing/policy:

```powershell
.\scripts\install-launcher-agent.ps1
```

Remove code/task but preserve pairing/policy:

```powershell
.\scripts\uninstall-launcher-agent.ps1
```

Use `-RemoveCredentials` and/or `-RemovePolicy` for permanent local deletion,
and revoke the runner in Settings to invalidate its server credential.

## Development-mode direct pairing

The APIs and CLIs also support direct pairing after dependencies are already
installed. This is useful for development, not the normal end-user install:

```powershell
python -m workstation_agent pair --server http://127.0.0.1:8000 --pairing-id <id>
python -m homelab_agent pair --server http://127.0.0.1:8000 --pairing-id <id>
python -m launcher_agent pair --server http://127.0.0.1:8000 --pairing-id <id>
```

Then use `run --once` for a single cycle or `run` for the persistent loop. The
install scripts remain preferable because they create isolated dependencies and
consistent scheduled tasks.

## Troubleshooting checklist

- **Code rejected:** create a new pairing; confirm owner/module allowlist,
  expiry, and that the displayed pairing ID matches the command.
- **Credentials cannot be opened:** run as the Windows user that paired; DPAPI
  records do not transfer between users or machines.
- **Agent offline:** inspect the named scheduled task, then `agent.log`; verify
  DNS/TLS and dashboard reachability from the target machine.
- **401 after working previously:** the credential may be invalid or revoked;
  create a new pairing when revocation/corruption is confirmed and rerun the
  installer with its new pairing ID. It detects the existing credential and
  replaces it; `-ReplacePairing` is an optional explicit signal.
- **403:** check owner, module, local-policy, and action gates before replacing a
  valid pairing; this is a permission/policy response rather than proof of
  revocation.
- **Homelab empty:** enable inventory locally, add the monitor label, and verify
  Docker CLI access for the scheduled-task user.
- **Launcher empty:** enable the policy, validate it, ensure absolute paths
  exist for the scheduled-task user, and let the next catalog interval pass.
- **Actions disabled:** check every gate, not just the browser control.

See [Operations and troubleshooting](TROUBLESHOOTING.md) for dashboard-side
diagnostics and provider-independent recovery guidance.
