# Kasugai documentation

This directory contains task-oriented documentation for users, administrators,
operators, and contributors. Start with the path that matches what you are
trying to do.

## I am installing Kasugai

1. Read [Getting started](GETTING_STARTED.md).
2. Copy `.env.example` to `.env` and use the
   [configuration reference](CONFIGURATION.md) for each setting you change.
3. If a field asks for a token, API key, app password, claim code, or pairing
   code, use [Credentials and external codes](CREDENTIALS.md).
4. Before exposing the service beyond localhost, read
   [Architecture and security](ARCHITECTURE.md).

## I am using Kasugai

- [User guide](USER_GUIDE.md) explains projects, sharing, evidence, AI previews,
  Team Room, and every Home module as task-oriented workflows.
- The root [README](../README.md) provides the compact feature tour.
- [Credentials and external codes](CREDENTIALS.md) explains the personal
  GitHub and OpenAI controls visible in the UI.
- [Companion agents](COMPANION_AGENTS.md) explains the Workstation, Homelab,
  and Launcher settings and the target-computer installation steps.
- [Operations and troubleshooting](TROUBLESHOOTING.md) maps common messages to
  concrete checks.

## I operate a deployment

- [Configuration reference](CONFIGURATION.md) is the authoritative public
  setting inventory.
- [Architecture and security](ARCHITECTURE.md) describes network exposure,
  data ownership, encryption, external calls, and companion-agent boundaries.
- [Operations and troubleshooting](TROUBLESHOOTING.md) covers health checks,
  logs, updates, backups, restore expectations, and credential rotation.
- [Credentials and external codes](CREDENTIALS.md) includes least-privilege
  provider setup and Docker secret-file examples.

## I am contributing or debugging internals

The historical component notes under `src/docs/`, `src/routes/docs/`, and
`kasugai_server/python/docs/` describe older individual Python classes and route
groups. Several predate the current Go service, disabled legacy routes, or the
current security boundaries, so they are not authoritative until refreshed.
Use this documentation set and current code/tests for runtime behavior. The
root README's **Validation** section lists supported test and Compose validation
commands.

The active runtime entry points are:

| Entry point | Responsibility |
| --- | --- |
| `main.py` | Native dashboard launcher |
| `src/wsgi.py` | Production WSGI application used by Waitress |
| `kasugai_server/main.go` | Go Team Room chat, transfer, and media services |
| `workstation_agent/__main__.py` | Windows telemetry companion CLI |
| `homelab_agent/__main__.py` | Docker inventory/health/action companion CLI |
| `launcher_agent/__main__.py` | Local approved-task runner CLI |

## Documentation conventions

- Commands labeled PowerShell are intended for Windows PowerShell or
  PowerShell 7.
- Replace angle-bracket placeholders such as `<pairing-id>`; do not type the
  brackets.
- `owner@example.com` and `example/project` are examples, not defaults.
- Paths shown inside a container are distinct from host paths.
- A setting ending in `_FILE` contains the path to a secret file, not the
  secret itself.
- Security-sensitive defaults are described as they exist in the checked-in
  Compose and code. If an operator override changes them, the override becomes
  part of that deployment's security model.
