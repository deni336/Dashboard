"""Command-line entry point for the Kasugai workstation agent."""

from __future__ import annotations

import argparse
import getpass
import logging
import logging.handlers
import os
import socket
import time

from . import AGENT_VERSION
from .client import AgentClientError, WorkstationClient
from .collector import WorkstationCollector, agent_capabilities, platform_description
from .credentials import AgentCredentials, CredentialError, CredentialStore, default_credential_path


LOGGER = logging.getLogger("kasugai.workstation_agent")


def _configure_logging(verbose: bool = False) -> None:
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    LOGGER.addHandler(stream)
    try:
        log_path = default_credential_path().parent.parent / "agent.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        LOGGER.addHandler(file_handler)
    except (CredentialError, OSError):
        LOGGER.debug("File logging is unavailable")


def _display_name(value: str | None) -> str:
    name = (value or socket.gethostname() or "Windows workstation").strip()
    if not name or len(name) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise CredentialError("display name must contain 1 to 80 printable characters")
    return name


def pair_agent(args: argparse.Namespace, store: CredentialStore) -> int:
    if store.exists() and not args.replace:
        raise CredentialError("this user is already paired; pass --replace to replace the credentials")
    code = os.environ.pop("KASUGAI_PAIRING_CODE", None)
    if not code:
        code = getpass.getpass("One-time pairing code: ")
    code = code.strip()
    client = WorkstationClient(args.server)
    result = client.pair(
        pairing_id=args.pairing_id,
        code=code,
        display_name=_display_name(args.display_name),
        platform=platform_description(),
        capabilities=agent_capabilities(),
    )
    # Remove the best-effort local reference promptly; the server invalidates
    # the one-time code after a successful pairing.
    code = ""
    store.save(
        AgentCredentials(
            server_url=client.server_url,
            agent_id=result.agent_id,
            token=result.token,
            interval_seconds=result.interval_seconds,
            sequence=0,
        )
    )
    LOGGER.info("Workstation paired successfully (agent %s)", result.agent_id)
    return 0


def run_agent(args: argparse.Namespace, store: CredentialStore) -> int:
    failures = 0
    collector = WorkstationCollector(include_nvidia=not args.no_nvidia)
    while True:
        try:
            credentials, sequence = store.reserve_sequence()
            snapshot = collector.collect(sequence)
            client = WorkstationClient(credentials.server_url)
            client.push_snapshot(credentials.agent_id, credentials.token, snapshot)
            failures = 0
            LOGGER.info("Telemetry snapshot %d accepted", sequence)
        except (CredentialError, AgentClientError) as exc:
            failures += 1
            # All custom exceptions deliberately avoid tokens, pairing codes,
            # payloads, and URLs.  Do not log tracebacks or exception repr here.
            LOGGER.warning("Telemetry update failed: %s", str(exc))
            if args.once:
                return 1
        except (OSError, RuntimeError, ValueError):
            failures += 1
            LOGGER.warning("Telemetry collection failed")
            if args.once:
                return 1
        if args.once:
            return 0
        try:
            current = store.load()
            interval = current.interval_seconds
        except CredentialError:
            interval = 60
        # Client requests already have bounded retries. A small capped failure
        # backoff avoids a rapid loop if credential storage itself is damaged.
        delay = max(interval, min(30 * failures, 300))
        time.sleep(delay)


def show_status(store: CredentialStore) -> int:
    if not store.exists():
        print("Not paired")
        return 1
    credentials = store.load()
    print(f"Paired agent: {credentials.agent_id}")
    print(f"Dashboard: {credentials.server_url}")
    print(f"Interval: {credentials.interval_seconds} seconds")
    print(f"Last reserved sequence: {credentials.sequence}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kasugai outbound workstation telemetry agent")
    parser.add_argument("--version", action="version", version=AGENT_VERSION)
    parser.add_argument("--verbose", action="store_true", help="enable diagnostic logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pair = subparsers.add_parser("pair", help="pair this Windows user with a dashboard")
    pair.add_argument("--server", required=True, help="HTTPS dashboard base URL")
    pair.add_argument("--pairing-id", required=True, help="pairing request ID shown by the dashboard")
    pair.add_argument("--display-name", help="friendly workstation name")
    pair.add_argument("--replace", action="store_true", help="replace an existing pairing")

    run = subparsers.add_parser("run", help="collect and push telemetry")
    run.add_argument("--once", action="store_true", help="send one snapshot and exit")
    run.add_argument("--no-nvidia", action="store_true", help="disable optional NVIDIA telemetry")

    subparsers.add_parser("status", help="show pairing state without displaying the token")
    subparsers.add_parser("unpair", help="delete this user's local protected credentials")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        store = CredentialStore()
        if args.command == "pair":
            return pair_agent(args, store)
        if args.command == "run":
            return run_agent(args, store)
        if args.command == "status":
            return show_status(store)
        if args.command == "unpair":
            store.delete()
            LOGGER.info("Local workstation pairing removed")
            return 0
    except (CredentialError, AgentClientError) as exc:
        LOGGER.error("%s", str(exc))
        return 2
    except KeyboardInterrupt:
        LOGGER.info("Workstation agent stopped")
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
