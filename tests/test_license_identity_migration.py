import configparser
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from denilicense.crypto.common import b64url_encode
from denilicense.crypto.keys import ACTIVATION_RECEIPT_SIGNER, SigningKey
from denilicense.crypto.lease import LeaseClaims, device_key_thumbprint, sign_lease

from src.license_identity_migration import (
    DESTINATION_ACTIVE,
    MIGRATED,
    SOURCE_INCOMPLETE,
    LicenseIdentityMigrationError,
    migrate_license_identity,
)


ISSUER = "https://license.example"
PRODUCT = "KASUGAI"


def _activation_identity():
    device_key = Ed25519PrivateKey.generate()
    private_bytes = device_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = device_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    activation_id = str(uuid.uuid4())
    now = datetime.now(UTC) - timedelta(days=2)
    signer = SigningKey.generate(ACTIVATION_RECEIPT_SIGNER)
    claims = LeaseClaims(
        issuer=ISSUER,
        key_id=signer.key_id,
        jwt_id=str(uuid.uuid4()),
        license_id=str(uuid.uuid4()),
        activation_id=activation_id,
        audience=PRODUCT,
        license_revision=1,
        device_key_thumbprint=device_key_thumbprint(public_bytes),
        entitlements={"feature.chat": True},
        issued_at=now,
        not_before=now,
        # Expired leases are intentionally migratable: possession of the device
        # key lets the application renew the existing activation after startup.
        expires_at=now + timedelta(hours=1),
    )
    return {
        "deviceprivatekey": b64url_encode(private_bytes),
        "activationid": activation_id,
        "activationlease": sign_lease(claims, signer),
    }


def _write_config(path: Path, identity=None, *, marker: str):
    identity = identity or {
        "deviceprivatekey": "",
        "activationid": "",
        "activationlease": "",
    }
    config = configparser.ConfigParser(interpolation=None)
    config["Licensing"] = {
        "apiurl": f"https://{marker}-api.example",
        "issuer": ISSUER,
        "productcode": PRODUCT,
        **identity,
    }
    config["WebServer"] = {"sessionsecret": f"{marker}-session-secret"}
    config["Database"] = {
        "dbpath": f"{marker}.db",
        "encryption_key": f"{marker}-database-key",
    }
    config["AI"] = {"apikey": f"{marker}-openai-key"}
    with path.open("w", encoding="utf-8") as stream:
        config.write(stream)


def _read_config(path: Path):
    config = configparser.ConfigParser(interpolation=None)
    config.read(path, encoding="utf-8")
    return config


class LicenseIdentityMigrationTests(unittest.TestCase):
    def test_only_activation_identity_is_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.ini"
            destination = Path(directory) / "config.ini"
            identity = _activation_identity()
            _write_config(source, identity, marker="legacy")
            _write_config(destination, marker="current")

            result = migrate_license_identity(source, destination)

            self.assertEqual(result, MIGRATED)
            migrated = _read_config(destination)
            for field, value in identity.items():
                self.assertEqual(migrated.get("Licensing", field), value)
            self.assertEqual(migrated.get("Licensing", "apiurl"), "https://current-api.example")
            self.assertEqual(migrated.get("WebServer", "sessionsecret"), "current-session-secret")
            self.assertEqual(migrated.get("Database", "dbpath"), "current.db")
            self.assertEqual(migrated.get("Database", "encryption_key"), "current-database-key")
            self.assertEqual(migrated.get("AI", "apikey"), "current-openai-key")

    def test_existing_activation_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.ini"
            destination = Path(directory) / "config.ini"
            _write_config(source, _activation_identity(), marker="legacy")
            _write_config(destination, _activation_identity(), marker="current")
            original = destination.read_bytes()

            result = migrate_license_identity(source, destination)

            self.assertEqual(result, DESTINATION_ACTIVE)
            self.assertEqual(destination.read_bytes(), original)

    def test_existing_activation_without_cached_lease_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.ini"
            destination = Path(directory) / "config.ini"
            _write_config(source, _activation_identity(), marker="legacy")
            existing = _activation_identity()
            existing["activationlease"] = ""
            _write_config(destination, existing, marker="current")
            original = destination.read_bytes()

            result = migrate_license_identity(source, destination)

            self.assertEqual(result, DESTINATION_ACTIVE)
            self.assertEqual(destination.read_bytes(), original)

    def test_incomplete_source_does_not_modify_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.ini"
            destination = Path(directory) / "config.ini"
            identity = _activation_identity()
            identity["activationlease"] = ""
            _write_config(source, identity, marker="legacy")
            _write_config(destination, marker="current")
            original = destination.read_bytes()

            result = migrate_license_identity(source, destination)

            self.assertEqual(result, SOURCE_INCOMPLETE)
            self.assertEqual(destination.read_bytes(), original)

    def test_mismatched_device_key_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.ini"
            destination = Path(directory) / "config.ini"
            first_identity = _activation_identity()
            second_identity = _activation_identity()
            first_identity["deviceprivatekey"] = second_identity["deviceprivatekey"]
            _write_config(source, first_identity, marker="legacy")
            _write_config(destination, marker="current")
            original = destination.read_bytes()

            with self.assertRaisesRegex(
                LicenseIdentityMigrationError,
                "device key does not match",
            ):
                migrate_license_identity(source, destination)

            self.assertEqual(destination.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
