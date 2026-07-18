# Kasugai Team Room server

This directory contains the active Go service behind Kasugai's Team Room. It
starts three gRPC listeners over one shared in-memory datastore:

| Service | Default address | Implemented operations |
| --- | --- | --- |
| Chat, users, and rooms | `localhost:8008` | Register/update/list users, create/list/join/leave rooms, send and stream text messages |
| File transfer | `localhost:50051` | Initiate a transfer, stream chunks, receive metadata, and stream received chunks |
| Media | `localhost:50052` | Bidirectional media stream, end stream, and VoIP signaling |

The generated Go protocol types live under `pkg/kasugai/`; shared service
implementations are under `pkg/server/`. The dashboard connects through the
Python gRPC client code bundled into its image.

## Run for native development

From this directory:

```powershell
go run .
```

The process reads `config.json` from its working directory. A first positional
argument overrides only the chat address:

```powershell
go run . 127.0.0.1:8008
```

Edit `config.json` to change all three listener addresses, logging, or the
client limit. The current `tls_config` object is retained for configuration
compatibility but is not applied when listeners start. Keep `enabled` false;
certificate paths do not enable TLS in the current service.

## Run in Docker

The root `docker-compose.yml` builds this service as `kasugai-server` and keeps
all three ports on the private Compose network. Its log is persisted in the
named `kasugai_server-data` volume at `/data/server.log`.

For a separate private VPS/VPN deployment, use `compose.vps.yml` and
`.env.vps.example`, then configure the dashboard with
`docker-compose.dashboard.yml`. See the root
[getting-started guide](../docs/GETTING_STARTED.md) and
[configuration reference](../docs/CONFIGURATION.md).

## Security and persistence limits

- The service currently has no transport authentication and does not enable
  TLS. Do not publish ports 8008, 50051, or 50052 to an untrusted network. Use a
  private Compose network, loopback tunnel, VPN, or authenticated proxy
  boundary.
- Room passwords are user-selected and held/compared in plaintext process
  memory. They are a room control, not a network security boundary.
- Users, rooms, messages, pending file bytes, and media state live only in
  memory and disappear on restart. The Docker volume persists the log only.
- Treat transferred files as untrusted application data; this service does not
  perform malware scanning.

The complete trust-boundary discussion is in
[Architecture and security](../docs/ARCHITECTURE.md).

## Validate changes

The full `go test ./...` tree currently includes legacy integration tests that
expect a server already listening on `localhost:8008`, a Windows capture test
that requires an interactive desktop, and server tests whose logger fixture
still needs isolation. It is therefore not a clean headless release gate yet.
Run the packages relevant to a change and stabilize those fixtures before
treating a full-tree result as authoritative; for example, the standalone
utility package is self-contained:

```powershell
go test ./pkg/utils
```

Static analysis also has known Windows unsafe-pointer and copied-protobuf-lock
findings. Resolve and review those findings before using a clean `go vet ./...`
run as a release gate.

The older Python server modules under `python/` and their component notes are
legacy compatibility/reference code. The root Docker build and current
deployment guides use `main.go` and the Go packages in this directory.
