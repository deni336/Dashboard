"""Command-line interface for the outbound launcher companion."""

from __future__ import annotations

import argparse
import getpass
import logging
import logging.handlers
import os
import platform
import socket
import time
from pathlib import Path

from . import AGENT_VERSION
from .actions import TaskExecutor, uncertain_result
from .catalog import build_catalog
from .client import AgentClientError, LauncherClient
from .config import (
    ConfigError,
    LauncherPolicy,
    default_config_path,
    initialize_config,
    load_config,
)
from .credentials import (
    AgentCredentials,
    CredentialError,
    CredentialStore,
    default_credential_path,
    new_task_key_secret,
)


LOGGER = logging.getLogger("kasugai.launcher_agent")


def _configure_logging(verbose: bool = False) -> None:
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    LOGGER.addHandler(stream)
    try:
        path = default_credential_path().parent.parent / "agent.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
    except (CredentialError, OSError):
        LOGGER.debug("File logging is unavailable")


def _display_name(value: str | None) -> str:
    result = (value or socket.gethostname() or "Launcher runner").strip()
    if not result or len(result) > 80 or any(ord(character) < 32 for character in result):
        raise CredentialError("display name must contain 1 to 80 printable characters")
    return result


def _platform_description() -> str:
    result = platform.platform(aliased=True, terse=True).strip() or "Windows"
    result = "".join(character for character in result if ord(character) >= 32)[:160]
    return result or "Windows"


def pair_agent(args: argparse.Namespace, store: CredentialStore) -> int:
    if store.exists() and not args.replace:
        raise CredentialError("this launcher is already paired; use --replace to replace it")
    code = os.environ.pop("KASUGAI_LAUNCHER_PAIRING_CODE", None)
    if not code:
        code = getpass.getpass("One-time launcher pairing code: ")
    code = code.strip()
    client = LauncherClient(args.server)
    result = client.pair(
        pairing_id=args.pairing_id,
        code=code,
        display_name=_display_name(args.display_name),
        platform=_platform_description(),
        capabilities=["run_tasks", "catalog_v1", "fixed_tasks_v1"],
    )
    code = ""
    store.save(
        AgentCredentials(
            server_url=client.server_url,
            agent_id=result.agent_id,
            token=result.token,
            catalog_interval_seconds=result.catalog_interval_seconds,
            poll_interval_seconds=result.poll_interval_seconds,
            task_key_secret=new_task_key_secret(),
        )
    )
    LOGGER.info("Launcher agent paired successfully (agent %s)", result.agent_id)
    return 0


def _deliver_pending(store: CredentialStore) -> None:
    credentials = store.load()
    pending = credentials.pending_result
    if pending is None:
        return
    LauncherClient(credentials.server_url).push_result(
        credentials.agent_id,
        credentials.token,
        pending["run_id"],
        pending["payload"],
    )
    store.clear_pending_result(pending["run_id"])
    LOGGER.info("Launcher result delivered")


def _push_catalog(store: CredentialStore, config_path: Path | str | None) -> None:
    credentials, sequence = store.reserve_sequence()
    try:
        policy = load_config(config_path)
    except ConfigError:
        # Publish an empty catalog to remove stale runnable tasks, then remain
        # fail-closed until the local file validates again.
        policy = LauncherPolicy(enabled=False, tasks=())
        LOGGER.warning("Launcher policy is invalid; publishing an empty catalog")
    payload = build_catalog(policy, credentials.task_key_secret, sequence)
    LauncherClient(credentials.server_url).push_catalog(
        credentials.agent_id, credentials.token, payload
    )
    LOGGER.info("Launcher catalog %d accepted", sequence)


def _poll_run(store: CredentialStore, config_path: Path | str | None) -> None:
    _deliver_pending(store)
    credentials = store.load()
    client = LauncherClient(credentials.server_url)
    claim = client.claim_run(credentials.agent_id, credentials.token)
    if claim is None:
        return
    # Persist uncertainty before touching the process table. If execution is
    # interrupted, startup sends this result and never repeats the task.
    store.save_pending_result(claim.run_id, uncertain_result(claim))
    executor = TaskExecutor(
        lambda: load_config(config_path),
        credentials.task_key_secret,
    )
    result = executor.execute(claim)
    store.save_pending_result(claim.run_id, result)
    _deliver_pending(store)


def run_agent(args: argparse.Namespace, store: CredentialStore) -> int:
    credentials = store.load()
    next_catalog = 0.0
    next_poll = 0.0
    catalog_attempted = False
    poll_attempted = False
    once_failed = False
    failures = 0
    while True:
        now = time.monotonic()
        if now >= next_catalog:
            catalog_attempted = True
            try:
                _push_catalog(store, args.config)
                failures = 0
            except (AgentClientError, CredentialError, ConfigError, OSError, ValueError):
                failures += 1
                once_failed = True
                LOGGER.warning("Launcher catalog update failed")
            credentials = store.load()
            next_catalog = now + credentials.catalog_interval_seconds
        if now >= next_poll:
            poll_attempted = True
            try:
                _poll_run(store, args.config)
                failures = 0
            except (AgentClientError, CredentialError, ConfigError, OSError, ValueError):
                failures += 1
                once_failed = True
                LOGGER.warning("Launcher run poll failed")
            credentials = store.load()
            next_poll = now + credentials.poll_interval_seconds
        if args.once and catalog_attempted and poll_attempted:
            return 1 if once_failed else 0
        delay = max(0.1, min(next_catalog, next_poll) - time.monotonic())
        if failures:
            delay = max(delay, min(30 * failures, 300))
        time.sleep(min(delay, 60))


def show_status(args: argparse.Namespace, store: CredentialStore) -> int:
    if not store.exists():
        print("Not paired")
        return 1
    credentials = store.load()
    print(f"Paired launcher agent: {credentials.agent_id}")
    print(f"Dashboard: {credentials.server_url}")
    print(f"Catalog interval: {credentials.catalog_interval_seconds} seconds")
    print(f"Run poll interval: {credentials.poll_interval_seconds} seconds")
    print(f"Last reserved catalog sequence: {credentials.sequence}")
    print(f"Pending result: {'yes' if credentials.pending_result else 'no'}")
    try:
        policy = load_config(args.config)
        print(f"Local execution enabled: {str(policy.enabled).lower()}")
        print(f"Locally approved tasks: {len(policy.tasks)}")
    except ConfigError:
        print("Local policy: invalid or unavailable")
    return 0


def config_command(args: argparse.Namespace) -> int:
    path = Path(args.config) if args.config is not None else default_config_path()
    if args.config_action == "init":
        created = initialize_config(path, force=args.force)
        print(f"Disabled launcher policy created: {created}")
        return 0
    if args.config_action == "validate":
        policy = load_config(path)
        print(
            f"Valid launcher policy: enabled={str(policy.enabled).lower()}, tasks={len(policy.tasks)}"
        )
        return 0
    if args.config_action == "path":
        print(path)
        return 0
    raise ConfigError("unknown launcher config command")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kasugai outbound-only approved task runner")
    parser.add_argument("--version", action="version", version=AGENT_VERSION)
    parser.add_argument("--verbose", action="store_true", help="enable diagnostic logging")
    commands = parser.add_subparsers(dest="command", required=True)

    pair = commands.add_parser("pair", help="pair this local runner with a dashboard")
    pair.add_argument("--server", required=True, help="HTTPS dashboard base URL")
    pair.add_argument("--pairing-id", required=True, help="pairing request ID shown by dashboard")
    pair.add_argument("--display-name", help="friendly runner name")
    pair.add_argument("--replace", action="store_true", help="replace existing pairing")

    run = commands.add_parser("run", help="publish tasks and poll outbound for approved runs")
    run.add_argument("--once", action="store_true", help="perform one catalog push and run poll")
    run.add_argument("--config", help="local policy path; never supplied by the dashboard")

    status = commands.add_parser("status", help="show safe pairing and local policy status")
    status.add_argument("--config", help="local policy path")
    commands.add_parser("unpair", help="delete only this runner's protected credentials")

    config = commands.add_parser("config", help="initialize or validate local launcher policy")
    config_actions = config.add_subparsers(dest="config_action", required=True)
    config_init = config_actions.add_parser("init", help="create a disabled empty policy")
    config_init.add_argument("--config", help="local policy path")
    config_init.add_argument("--force", action="store_true", help="replace an existing policy")
    config_validate = config_actions.add_parser("validate", help="validate local policy")
    config_validate.add_argument("--config", help="local policy path")
    config_path = config_actions.add_parser("path", help="print local policy path")
    config_path.add_argument("--config", help="local policy path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        if args.command == "config":
            return config_command(args)
        store = CredentialStore()
        if args.command == "pair":
            return pair_agent(args, store)
        if args.command == "run":
            return run_agent(args, store)
        if args.command == "status":
            return show_status(args, store)
        if args.command == "unpair":
            store.delete()
            LOGGER.info("Local launcher pairing removed")
            return 0
    except (AgentClientError, CredentialError, ConfigError) as exc:
        LOGGER.error("%s", str(exc))
        return 2
    except KeyboardInterrupt:
        LOGGER.info("Launcher agent stopped")
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
