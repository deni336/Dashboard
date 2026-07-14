import uuid
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from flask import Flask
from denilicense.client import JWK, RenewalChallenge
from denilicense.crypto.common import b64url_encode
from denilicense.crypto.keys import ACTIVATION_RECEIPT_SIGNER, SigningKey
from denilicense.crypto.lease import LeaseClaims, device_key_thumbprint, sign_lease
from denilicense.crypto.renewal import verify_renewal_signature

from src.auth_manager import AuthManager, LicenseError
from src.routes.auth_routes import auth_bp, init_auth_routes


LICENSE_ID = "33333333-3333-4333-8333-333333333333"
ACTIVATION_ID = "44444444-4444-4444-8444-444444444444"


class FakeConfig:
    def __init__(self, product_code="KASUGAI"):
        self.values = {
            ("Licensing", "apiurl"): "https://api.example",
            ("Licensing", "issuer"): "https://issuer.example",
            ("Licensing", "productcode"): product_code,
            ("Licensing", "activationlabel"): "Kasugai test",
            ("Licensing", "deviceprivatekey"): "",
        }

    def get(self, section, option, fallback=None):
        return self.values.get((section, option), fallback)

    def set(self, section, option, value):
        self.values[(section, option)] = value


class FakeAuthManager(AuthManager):
    def __init__(self, product_code="KASUGAI"):
        super().__init__(None, FakeConfig(product_code))
        self.signer = SigningKey.generate(ACTIVATION_RECEIPT_SIGNER)
        self.posts = []
        self.user_role = "customer"

    def _get(self, path, access_token=None):
        if path == "/api/v1/licenses":
            return {
                "items": [{
                    "id": LICENSE_ID,
                    "productCode": "KASUGAI",
                    "state": "active",
                }]
            }
        if path == "/.well-known/denilicense-activation-keys.json":
            return {"keys": [JWK.from_public_key(self.signer.public_bytes).to_dict()]}
        raise AssertionError(f"unexpected GET {path}")

    def _post(self, path, payload, access_token=None):
        self.posts.append(path)
        if path == "/api/v1/auth/login":
            return {
                "accessToken": "access-token",
                "user": {
                    "id": "user-id",
                    "email": "customer@example.com",
                    "role": self.user_role,
                },
            }
        if path == "/api/v1/licenses/claim":
            return {"license": {"id": LICENSE_ID}}
        if path == f"/api/v1/licenses/{LICENSE_ID}/activations":
            return {
                "license": {
                    "id": LICENSE_ID,
                    "productCode": "KASUGAI",
                    "state": "active",
                },
                "activation": {"id": ACTIVATION_ID, "licenseId": LICENSE_ID},
                "lease": self._signed_lease(),
            }
        if path == "/api/v1/activation-challenges":
            nonce = b64url_encode(bytes(range(32)))
            challenge_id = "55555555-5555-4555-8555-555555555555"
            transcript = (
                b"DeniLicense\x00activation-renewal\x00v1\x00"
                + challenge_id.encode()
                + b"\x00"
                + ACTIVATION_ID.encode()
                + b"\x00"
                + nonce.encode()
            )
            return {
                "challengeId": challenge_id,
                "activationId": ACTIVATION_ID,
                "nonce": nonce,
                "expiresAt": "2099-01-01T00:00:00Z",
                "algorithm": "Ed25519",
                "transcript": b64url_encode(transcript),
            }
        if path == "/api/v1/activation-challenges/complete":
            challenge = RenewalChallenge(
                payload["challengeId"],
                ACTIVATION_ID,
                payload["nonce"],
                "Ed25519",
                self._challenge_transcript(payload["challengeId"], payload["nonce"]),
            )
            verify_renewal_signature(
                self._device_public_key_bytes(),
                challenge,
                payload["signature"],
            )
            return {"activation": {"id": ACTIVATION_ID}, "lease": self._signed_lease()}
        raise AssertionError(f"unexpected POST {path}")

    def _signed_lease(self):
        now = datetime.now(UTC) - timedelta(seconds=1)
        claims = LeaseClaims(
            issuer=self.issuer,
            key_id=self.signer.key_id,
            jwt_id=str(uuid.uuid4()),
            license_id=LICENSE_ID,
            activation_id=ACTIVATION_ID,
            audience=self.product_code,
            license_revision=1,
            device_key_thumbprint=device_key_thumbprint(self._device_public_key_bytes()),
            entitlements={"feature.chat": True, "limits.rooms": 10},
            issued_at=now,
            not_before=now,
            expires_at=now + timedelta(hours=1),
        )
        return sign_lease(claims, self.signer)

    @staticmethod
    def _challenge_transcript(challenge_id, nonce):
        transcript = (
            b"DeniLicense\x00activation-renewal\x00v1\x00"
            + challenge_id.encode()
            + b"\x00"
            + ACTIVATION_ID.encode()
            + b"\x00"
            + nonce.encode()
        )
        return b64url_encode(transcript)


class AuthManagerTests(unittest.TestCase):
    def test_authentication_accepts_only_verified_signed_claims(self):
        manager = FakeAuthManager()

        result = manager.authenticate("customer@example.com", "password")

        self.assertEqual(result["claims"]["id"], LICENSE_ID)
        self.assertEqual(result["claims"]["activationId"], ACTIVATION_ID)
        self.assertEqual(result["claims"]["productCode"], "KASUGAI")
        self.assertEqual(result["claims"]["entitlements"]["feature.chat"], True)

    def test_invalid_session_lease_is_replaced_by_signed_renewal(self):
        manager = FakeAuthManager()

        renewed = manager.validate_or_renew({
            "licenseId": LICENSE_ID,
            "activationId": ACTIVATION_ID,
            "lease": "tampered",
        })

        self.assertTrue(renewed["lease"].startswith("dllease1."))
        self.assertIn("/api/v1/activation-challenges", manager.posts)
        self.assertIn("/api/v1/activation-challenges/complete", manager.posts)

    def test_wrong_signed_issuer_is_rejected(self):
        manager = FakeAuthManager()
        lease = manager._signed_lease()
        manager.issuer = "https://wrong-issuer.example"

        with self.assertRaisesRegex(LicenseError, "lease verification failed"):
            manager._verify_lease(lease)

    def test_product_mismatch_lists_available_product_codes(self):
        manager = FakeAuthManager(product_code="UNLIMITED")

        with self.assertRaisesRegex(
            LicenseError,
            "No active DeniLicense license for product 'UNLIMITED'.*KASUGAI",
        ):
            manager._find_product_license("access-token")

    def test_claim_code_requires_a_customer_account(self):
        manager = FakeAuthManager()
        manager.user_role = "platform_owner"

        with self.assertRaisesRegex(LicenseError, "customer account"):
            manager.authenticate("owner@example.com", "password", "CLAIM-CODE")

        self.assertNotIn("/api/v1/licenses/claim", manager.posts)

    def test_unlicensed_requests_are_redirected_to_login(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        manager = Mock(product_code="KASUGAI", api_url="https://api.example")

        @app.route("/private")
        def private():
            return "private"

        with patch("src.routes.auth_routes.AuthManager", return_value=manager):
            init_auth_routes(app, FakeConfig(), lambda: None)
        app.register_blueprint(auth_bp)

        response = app.test_client().get("/private")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))


if __name__ == "__main__":
    unittest.main()
