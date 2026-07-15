"""One-time migration of a device-bound DeniLicense activation identity.

This module deliberately migrates only the three values needed to renew an
existing activation.  It never imports service endpoints or application
secrets from the legacy configuration.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import configparser
import hmac
import io
import os
import stat
import sys
import tempfile
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from denilicense.client import ActivationClaims, device_key_thumbprint


MAX_CONFIG_BYTES = 1024 * 1024
MAX_LEASE_BYTES = 16 * 1024
IDENTITY_FIELDS = ("deviceprivatekey", "activationid", "activationlease")

MIGRATED = "migrated"
DESTINATION_ACTIVE = "destination-active"
SOURCE_INCOMPLETE = "source-incomplete"


class LicenseIdentityMigrationError(ValueError):
    """Raised when an explicitly requested migration is unsafe to perform."""


def _read_config(path: Path, description: str) -> tuple[configparser.ConfigParser, bytes]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LicenseIdentityMigrationError(f"{description} configuration is not available") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise LicenseIdentityMigrationError(f"{description} configuration must be a regular file")
    if metadata.st_size > MAX_CONFIG_BYTES:
        raise LicenseIdentityMigrationError(f"{description} configuration is too large")

    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        config = configparser.ConfigParser(interpolation=None)
        config.read_file(io.StringIO(text))
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise LicenseIdentityMigrationError(
            f"{description} configuration could not be parsed"
        ) from exc
    return config, raw


def _identity(config: configparser.ConfigParser) -> dict[str, str]:
    return {
        field: config.get("Licensing", field, fallback="").strip()
        for field in IDENTITY_FIELDS
    }


def _complete(identity: dict[str, str]) -> bool:
    return all(identity[field] for field in IDENTITY_FIELDS)


def _already_activated(identity: dict[str, str]) -> bool:
    # A saved activation ID plus its proof-of-possession key can renew a missing
    # or expired lease, so it must be treated as an existing activation.
    return bool(identity["deviceprivatekey"] and identity["activationid"])


def _b64url_decode(value: str, description: str, expected_size: int | None = None) -> bytes:
    if not value or any(character.isspace() for character in value):
        raise LicenseIdentityMigrationError(f"legacy {description} is invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise LicenseIdentityMigrationError(f"legacy {description} is invalid") from exc
    if expected_size is not None and len(decoded) != expected_size:
        raise LicenseIdentityMigrationError(f"legacy {description} is invalid")
    return decoded


def _validate_source_identity(
    identity: dict[str, str],
    destination: configparser.ConfigParser,
) -> None:
    try:
        activation_id = str(uuid.UUID(identity["activationid"]))
    except (ValueError, AttributeError) as exc:
        raise LicenseIdentityMigrationError("legacy activation ID is invalid") from exc
    if not hmac.compare_digest(activation_id, identity["activationid"].lower()):
        raise LicenseIdentityMigrationError("legacy activation ID is invalid")

    private_bytes = _b64url_decode(
        identity["deviceprivatekey"],
        "device private key",
        expected_size=32,
    )
    try:
        public_bytes = Ed25519PrivateKey.from_private_bytes(private_bytes).public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    except ValueError as exc:
        raise LicenseIdentityMigrationError("legacy device private key is invalid") from exc

    lease = identity["activationlease"]
    if len(lease.encode("utf-8")) > MAX_LEASE_BYTES:
        raise LicenseIdentityMigrationError("legacy activation lease is invalid")
    parts = lease.split(".")
    if len(parts) != 3 or parts[0] != "dllease1":
        raise LicenseIdentityMigrationError("legacy activation lease is invalid")
    payload = _b64url_decode(parts[1], "activation lease")
    _b64url_decode(parts[2], "activation lease signature", expected_size=64)
    try:
        claims = ActivationClaims.from_payload(payload)
    except Exception as exc:
        raise LicenseIdentityMigrationError("legacy activation lease is invalid") from exc

    if not hmac.compare_digest(claims.activation_id, activation_id):
        raise LicenseIdentityMigrationError("legacy activation identity does not match its lease")
    expected_thumbprint = device_key_thumbprint(public_bytes)
    if not hmac.compare_digest(claims.device_key_thumbprint, expected_thumbprint):
        raise LicenseIdentityMigrationError("legacy device key does not match its lease")

    product_code = destination.get("Licensing", "productcode", fallback="").strip().upper()
    issuer = destination.get("Licensing", "issuer", fallback="").strip().rstrip("/")
    if not product_code or not issuer:
        raise LicenseIdentityMigrationError(
            "destination licensing context is incomplete"
        )
    if not hmac.compare_digest(claims.audience, product_code):
        raise LicenseIdentityMigrationError(
            "legacy activation is for a different product"
        )
    if not hmac.compare_digest(claims.issuer.rstrip("/"), issuer):
        raise LicenseIdentityMigrationError(
            "legacy activation is from a different issuer"
        )


def _atomic_write(
    destination_path: Path,
    config: configparser.ConfigParser,
    original_bytes: bytes,
) -> None:
    # Recheck immediately before replacement so a concurrent startup cannot
    # silently overwrite a configuration that changed after we inspected it.
    try:
        if destination_path.read_bytes() != original_bytes:
            raise LicenseIdentityMigrationError(
                "destination configuration changed during migration"
            )
        destination_metadata = destination_path.stat(follow_symlinks=False)
    except OSError as exc:
        raise LicenseIdentityMigrationError(
            "destination configuration changed during migration"
        ) from exc

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".tmp",
        dir=destination_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        if hasattr(os, "fchown"):
            try:
                os.fchown(descriptor, destination_metadata.st_uid, destination_metadata.st_gid)
            except PermissionError:
                pass
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            config.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination_path)

        try:
            directory_descriptor = os.open(destination_path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_descriptor)
        except OSError:
            pass
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def migrate_license_identity(source: str | os.PathLike, destination: str | os.PathLike) -> str:
    """Migrate one internally consistent legacy activation into ``destination``.

    The operation is idempotent.  A destination containing a device key and
    activation ID is retained byte-for-byte because it can renew a missing
    lease.  An incomplete legacy identity makes no change.  Invalid or
    context-mismatched identities raise an error.
    """

    source_path = Path(source)
    destination_path = Path(destination)
    try:
        if source_path.resolve(strict=False) == destination_path.resolve(strict=False):
            raise LicenseIdentityMigrationError(
                "legacy and destination configurations must be different files"
            )
    except OSError as exc:
        raise LicenseIdentityMigrationError("configuration paths could not be resolved") from exc

    destination_config, destination_bytes = _read_config(destination_path, "destination")
    if _already_activated(_identity(destination_config)):
        return DESTINATION_ACTIVE

    source_config, _ = _read_config(source_path, "legacy")
    source_identity = _identity(source_config)
    if not _complete(source_identity):
        return SOURCE_INCOMPLETE
    _validate_source_identity(source_identity, destination_config)

    if not destination_config.has_section("Licensing"):
        destination_config.add_section("Licensing")
    for field in IDENTITY_FIELDS:
        destination_config.set("Licensing", field, source_identity[field])
    _atomic_write(destination_path, destination_config, destination_bytes)
    return MIGRATED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely import an existing DeniLicense activation identity."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    arguments = parser.parse_args(argv)

    try:
        result = migrate_license_identity(arguments.source, arguments.destination)
    except LicenseIdentityMigrationError as exc:
        print(f"ERROR: legacy license identity was not imported: {exc}", file=sys.stderr)
        return 1

    if result == MIGRATED:
        print("Imported the existing DeniLicense activation identity.")
    elif result == DESTINATION_ACTIVE:
        print("Retained the existing DeniLicense activation identity.")
    else:
        print(
            "WARNING: the legacy configuration has no complete activation identity; nothing was imported.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
