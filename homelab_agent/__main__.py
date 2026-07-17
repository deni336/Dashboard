"""Command-line entry point for the standalone Kasugai homelab agent."""

from __future__ import annotations

import argparse
import getpass
import logging
import logging.handlers
import os
import socket
import time
from pathlib import Path

from . import AGENT_VERSION
from .actions import ActionExecutor, uncertain_result
from .client import AgentClientError, HomelabClient
from .collector import HomelabCollector, platform_description
from .config import (
    ConfigError,
    default_config_document,
    default_config_path,
    load_config,
)
from .credentials import (
    AgentCredentials,
    CredentialError,
    CredentialStore,
    default_credential_path,
    new_resource_key_secret,
)


LOGGER = logging.getLogger("kasugai.homelab_agent")


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
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
    except (CredentialError, OSError):
        LOGGER.debug("File logging is unavailable")


def _display_name(value: str | None) -> str:
    display_name = (value or socket.gethostname() or "Homelab").strip()
    if (
        not display_name
        or len(display_name) > 80
        or any(ord(character) < 32 or ord(character) == 127 for character in display_name)
    ):
        raise CredentialError("display name must contain 1 to 80 printable characters")
    return display_name


def pair_agent(args: argparse.Namespace, store: CredentialStore) -> int:
    if store.exists() and not args.replace:
        raise CredentialError("this homelab is already paired; pass --replace to replace it")
    config = load_config(args.config)
    code = os.environ.pop("KASUGAI_HOMELAB_PAIRING_CODE", None)
    if not code:
        code = getpass.getpass("One-time homelab pairing code: ")
    client = HomelabClient(args.server)
    result = client.pair(
        pairing_id=args.pairing_id,
        code=code.strip(),
        display_name=_display_name(args.display_name),
        platform=platform_description(),
        capabilities=config.capabilities,
    )
    code = ""
    store.save(
        AgentCredentials(
            server_url=client.server_url,
            agent_id=result.agent_id,
            token=result.token,
            snapshot_interval_seconds=result.snapshot_interval_seconds,
            action_poll_interval_seconds=result.action_poll_interval_seconds,
            resource_key_secret=new_resource_key_secret(),
        )
    )
    LOGGER.info("Homelab paired successfully (agent %s)", result.agent_id)
    return 0


def _deliver_pending(store: CredentialStore) -> bool:
    credentials = store.load()
    pending = credentials.pending_result
    if pending is None:
        return True
    client = HomelabClient(credentials.server_url)
    client.push_action_result(
        credentials.agent_id,
        credentials.token,
        pending["action_id"],
        pending["payload"],
    )
    store.clear_pending_result(pending["action_id"])
    LOGGER.info("Action result delivered")
    return True


def _poll_action(
    store: CredentialStore,
    config_path: Path | str | None,
    collector: HomelabCollector,
) -> None:
    if not _deliver_pending(store):
        return
    credentials = store.load()
    client = HomelabClient(credentials.server_url)
    claim = client.claim_action(credentials.agent_id, credentials.token)
    if claim is None:
        return

    # Persist a conservative result before touching Docker. If this process
    # exits mid-operation, startup reports uncertainty and never repeats it.
    store.save_pending_result(claim.action_id, uncertain_result(claim))
    executor = ActionExecutor(collector.docker, lambda: load_config(config_path))
    result = executor.execute(claim)
    store.save_pending_result(claim.action_id, result)
    _deliver_pending(store)


def _push_snapshot(
    store: CredentialStore,
    config_path: Path | str | None,
    collector: HomelabCollector,
) -> None:
    credentials, sequence = store.reserve_sequence()
    config = load_config(config_path)
    snapshot = collector.collect(sequence, config)
    HomelabClient(credentials.server_url).push_snapshot(
        credentials.agent_id, credentials.token, snapshot
    )
    LOGGER.info("Homelab snapshot %d accepted", sequence)


def run_agent(args: argparse.Namespace, store: CredentialStore) -> int:
    initial_credentials = store.load()
    collector = HomelabCollector(initial_credentials.resource_key_secret)
    next_snapshot = 0.0
    next_action = 0.0
    failures = 0
    attempted_snapshot = False
    attempted_action = False
    once_failed = False
    while True:
        now = time.monotonic()
        if now >= next_snapshot:
            attempted_snapshot = True
            try:
                _push_snapshot(store, args.config, collector)
                failures = 0
            except (AgentClientError, CredentialError, ConfigError):
                failures += 1
                once_failed = True
                LOGGER.warning("Homelab snapshot update failed")
            except (OSError, RuntimeError, ValueError):
                failures += 1
                once_failed = True
                LOGGER.warning("Homelab snapshot collection failed")
            credentials = store.load()
            next_snapshot = now + credentials.snapshot_interval_seconds
        if now >= next_action:
            attempted_action = True
            try:
                _poll_action(store, args.config, collector)
                failures = 0
            except (AgentClientError, CredentialError, ConfigError):
                failures += 1
                once_failed = True
                LOGGER.warning("Homelab action poll failed")
            except (OSError, RuntimeError, ValueError):
                failures += 1
                once_failed = True
                LOGGER.warning("Homelab action processing failed")
            credentials = store.load()
            next_action = now + credentials.action_poll_interval_seconds
        if args.once and attempted_snapshot and attempted_action:
            return 1 if once_failed else 0
        delay = max(0.1, min(next_snapshot, next_action) - time.monotonic())
        if failures:
            delay = max(delay, min(30 * failures, 300))
        time.sleep(min(delay, 60))


def show_status(store: CredentialStore, config_path: Path | str | None) -> int:
    if not store.exists():
        print("Not paired")
        return 1
    credentials = store.load()
    config = load_config(config_path)
    print(f"Paired homelab agent: {credentials.agent_id}")
    print(f"Dashboard: {credentials.server_url}")
    print(f"Snapshot interval: {credentials.snapshot_interval_seconds} seconds")
    print(f"Action poll interval: {credentials.action_poll_interval_seconds} seconds")
    print(f"Last reserved sequence: {credentials.sequence}")
    print(f"Inventory enabled locally: {str(config.inventory_enabled).lower()}")
    print(f"Log access enabled locally: {str(config.allow_logs).lower()}")
    print(f"Restart enabled locally: {str(config.allow_restart).lower()}")
    print(f"Configured health checks: {len(config.health_checks)}")
    print(f"Pending action result: {'yes' if credentials.pending_result else 'no'}")
    return 0


def init_config(args: argparse.Namespace) -> int:
    path = Path(args.config) if args.config is not None else default_config_path()
    if path.exists() and not args.force:
        raise ConfigError("homelab policy already exists; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(default_config_document(), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ConfigError("homelab policy could not be initialized") from exc
    print(f"Disabled-by-default homelab policy created: {path}")
    return 0


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="local policy JSON path; never supplied by the dashboard")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kasugai outbound-only Docker and homelab agent")
    parser.add_argument("--version", action="version", version=AGENT_VERSION)
    parser.add_argument("--verbose", action="store_true", help="enable diagnostic logging")
    commands = parser.add_subparsers(dest="command", required=True)

    pair = commands.add_parser("pair", help="pair this homelab with a dashboard")
    pair.add_argument("--server", required=True, help="HTTPS dashboard base URL")
    pair.add_argument("--pairing-id", required=True, help="pairing request ID shown by the dashboard")
    pair.add_argument("--display-name", help="friendly homelab name")
    pair.add_argument("--replace", action="store_true", help="replace an existing pairing")
    _add_config_argument(pair)

    run = commands.add_parser("run", help="push inventory and poll outbound actions")
    run.add_argument("--once", action="store_true", help="perform one snapshot and action poll")
    _add_config_argument(run)

    status = commands.add_parser("status", help="show pairing and local policy without secrets")
    _add_config_argument(status)

    initialize = commands.add_parser("init-config", help="create a disabled-by-default local policy")
    initialize.add_argument("--force", action="store_true", help="replace the local policy")
    _add_config_argument(initialize)

    commands.add_parser("unpair", help="delete only this agent's protected pairing")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        if args.command == "init-config":
            return init_config(args)
        store = CredentialStore()
        if args.command == "pair":
            return pair_agent(args, store)
        if args.command == "run":
            return run_agent(args, store)
        if args.command == "status":
            return show_status(store, args.config)
        if args.command == "unpair":
            store.delete()
            LOGGER.info("Local homelab pairing removed")
            return 0
    except (AgentClientError, CredentialError, ConfigError) as exc:
        LOGGER.error("%s", str(exc))
        return 2
    except KeyboardInterrupt:
        LOGGER.info("Homelab agent stopped")
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
