import base64
import json
import socket
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from denilicense.client import (
    JWKS,
    RenewalChallenge,
    VerifyOptions,
    device_key_thumbprint,
    sign_renewal_challenge,
    verify_lease_jwk,
)


MAX_RESPONSE_BYTES = 1024 * 1024
JWKS_CACHE_SECONDS = 300
LEASE_RENEWAL_WINDOW = timedelta(minutes=15)


class LicenseError(Exception):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AuthManager:
    """DeniLicense-backed account, activation, and signed-lease gate."""

    def __init__(self, app, config_handler):
        self.config = config_handler
        self.api_url = self.config.get(
            'Licensing',
            'apiurl',
            fallback='http://127.0.0.1:8080'
        ).rstrip('/')
        self.issuer = self.config.get(
            'Licensing',
            'issuer',
            fallback=self.api_url
        ).rstrip('/')
        self.product_code = self.config.get('Licensing', 'productcode', fallback='KASUGAI').upper()
        self.activation_label = self.config.get(
            'Licensing',
            'activationlabel',
            fallback=f"Kasugai Dashboard ({socket.gethostname()})"
        )
        self._opener = urllib.request.build_opener(_NoRedirectHandler())
        self._jwks = None
        self._jwks_loaded_at = 0.0

    def authenticate(self, email, password, claim_code=''):
        if not email or not password:
            raise LicenseError("Email and password are required.")

        token_response = self._post('/api/v1/auth/login', {
            'email': email,
            'password': password,
        })
        access_token = token_response['accessToken']
        user = token_response.get('user') or self._get('/api/v1/auth/me', access_token).get('user', {})

        claim_code = claim_code.strip()
        if claim_code:
            if user.get('role') != 'customer':
                raise LicenseError(
                    "Claim codes can only be redeemed by an active DeniLicense customer account. "
                    "Sign in with a customer account, or leave Claim Code blank to use a license "
                    "already assigned to this account."
                )
            try:
                self._post('/api/v1/licenses/claim', {'claimCode': claim_code}, access_token)
            except LicenseError as exc:
                if str(exc) == "The request was not valid.":
                    raise LicenseError(
                        "The claim code was not accepted. Verify the complete case-sensitive code "
                        "and confirm that it has not already been claimed."
                    ) from exc
                raise

        license_record = self._find_product_license(access_token)
        activation_response = self._post(
            f"/api/v1/licenses/{license_record['id']}/activations",
            {
                'devicePublicKey': self._device_public_key_text(),
                'label': self.activation_label,
            },
            access_token
        )
        activation = activation_response.get('activation')
        lease = activation_response.get('lease')
        license_record = activation_response.get('license', license_record)
        if not activation or not lease:
            raise LicenseError("DeniLicense did not return an activation and signed lease.")

        claims = self._verify_lease(lease)
        if claims.license_id != license_record.get('id') or claims.activation_id != activation.get('id'):
            raise LicenseError("DeniLicense returned an activation that does not match its signed lease.")

        verified_claims = self._claims_dict(claims)
        return {
            'profile': {
                'id': user.get('id'),
                'email': user.get('email', email),
                'name': user.get('email', email),
                'license': verified_claims,
            },
            'license': license_record,
            'activation': activation,
            'lease': lease,
            'claims': verified_claims,
        }

    def validate_or_renew(self, license_session):
        if not isinstance(license_session, dict):
            raise LicenseError("The DeniLicense session is missing.")
        lease = license_session.get('lease')
        activation_id = license_session.get('activationId')
        if not lease or not activation_id:
            raise LicenseError("The DeniLicense session is incomplete.")

        try:
            claims = self._verify_lease(lease)
        except LicenseError:
            lease, claims = self._renew_lease(activation_id)
        else:
            if claims.expires_at <= datetime.now(UTC) + LEASE_RENEWAL_WINDOW:
                lease, claims = self._renew_lease(activation_id)

        if claims.activation_id != activation_id:
            raise LicenseError("The renewed DeniLicense lease belongs to a different activation.")
        return {
            'licenseId': claims.license_id,
            'activationId': claims.activation_id,
            'lease': lease,
            'claims': self._claims_dict(claims),
        }

    def _renew_lease(self, activation_id):
        response = self._post('/api/v1/activation-challenges', {'activationId': activation_id})
        try:
            challenge = RenewalChallenge(
                challenge_id=response['challengeId'],
                activation_id=response['activationId'],
                nonce=response['nonce'],
                algorithm=response['algorithm'],
                transcript=response['transcript'],
            )
            signature = sign_renewal_challenge(
                self._device_private_key(),
                challenge,
                expected_activation_id=activation_id,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LicenseError(f"DeniLicense returned an invalid renewal challenge: {exc}") from exc

        renewed = self._post('/api/v1/activation-challenges/complete', {
            'challengeId': challenge.challenge_id,
            'nonce': challenge.nonce,
            'signature': signature,
        })
        lease = renewed.get('lease')
        if not lease:
            raise LicenseError("DeniLicense did not return a renewed signed lease.")
        return lease, self._verify_lease(lease, force_jwks_refresh=True)

    def _verify_lease(self, lease, force_jwks_refresh=False):
        try:
            jwks = self._load_jwks(force=force_jwks_refresh)
            key = jwks.lookup(self._untrusted_key_id(lease))
            return verify_lease_jwk(
                lease,
                key,
                VerifyOptions(
                    expected_issuer=self.issuer,
                    expected_audience=self.product_code,
                    expected_device_key_thumbprint=device_key_thumbprint(self._device_public_key_bytes()),
                    clock_leeway=timedelta(minutes=1),
                ),
            )
        except LicenseError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            if not force_jwks_refresh:
                try:
                    return self._verify_lease(lease, force_jwks_refresh=True)
                except LicenseError:
                    pass
            raise LicenseError(f"DeniLicense lease verification failed: {exc}") from exc

    def _load_jwks(self, force=False):
        now = time.monotonic()
        if force or self._jwks is None or now - self._jwks_loaded_at >= JWKS_CACHE_SECONDS:
            try:
                self._jwks = JWKS.from_dict(
                    self._get('/.well-known/denilicense-activation-keys.json')
                )
            except (TypeError, ValueError) as exc:
                raise LicenseError(f"DeniLicense returned an invalid activation key set: {exc}") from exc
            self._jwks_loaded_at = now
        return self._jwks

    def _find_product_license(self, access_token):
        response = self._get('/api/v1/licenses', access_token)
        items = response.get('items', [])
        for item in items:
            if item.get('productCode') == self.product_code and item.get('state') == 'active':
                return item
        available = sorted({
            item.get('productCode')
            for item in items
            if item.get('state') == 'active' and item.get('productCode')
        })
        suffix = f" Active products on this account: {', '.join(available)}." if available else ''
        raise LicenseError(
            f"No active DeniLicense license for product '{self.product_code}'."
            f"{suffix} Enter a claim code or contact the license administrator."
        )

    def _device_public_key_text(self):
        return self._b64url(self._device_public_key_bytes())

    def _device_public_key_bytes(self):
        return self._device_private_key().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

    def _device_private_key(self):
        encoded = self.config.get('Licensing', 'deviceprivatekey', fallback='')
        if encoded:
            try:
                return Ed25519PrivateKey.from_private_bytes(self._unb64url(encoded))
            except Exception as exc:
                raise LicenseError("Stored DeniLicense device key is invalid.") from exc

        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        self.config.set('Licensing', 'deviceprivatekey', self._b64url(private_bytes))
        return private_key

    def _get(self, path, access_token=None):
        return self._request('GET', path, access_token=access_token)

    def _post(self, path, payload, access_token=None):
        return self._request('POST', path, payload=payload, access_token=access_token)

    def _request(self, method, path, payload=None, access_token=None):
        body = None
        headers = {'Accept': 'application/json'}
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'

        request = urllib.request.Request(
            f'{self.api_url}{path}',
            data=body,
            headers=headers,
            method=method
        )
        try:
            with self._opener.open(request, timeout=10) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    raise LicenseError("DeniLicense response exceeded the allowed size.")
                return json.loads(response_body.decode('utf-8')) if response_body else {}
        except urllib.error.HTTPError as exc:
            raise LicenseError(self._problem_message(exc)) from exc
        except urllib.error.URLError as exc:
            raise LicenseError(f"Could not reach DeniLicense at {self.api_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LicenseError(f"Timed out contacting DeniLicense at {self.api_url}.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LicenseError("DeniLicense returned an invalid JSON response.") from exc

    @staticmethod
    def _claims_dict(claims):
        return {
            'id': claims.license_id,
            'activationId': claims.activation_id,
            'productCode': claims.audience,
            'revision': claims.license_revision,
            'expiresAt': AuthManager._rfc3339(claims.expires_at),
            'entitlements': dict(claims.entitlements),
        }

    @staticmethod
    def _untrusted_key_id(lease):
        if not isinstance(lease, str) or len(lease) > 24 * 1024:
            raise ValueError("malformed activation lease")
        parts = lease.split('.')
        if len(parts) != 3 or parts[0] != 'dllease1':
            raise ValueError("malformed activation lease")
        encoded = parts[1]
        payload = base64.b64decode(
            encoded + '=' * (-len(encoded) % 4),
            altchars=b'-_',
            validate=True,
        )
        value = json.loads(payload)
        if not isinstance(value, dict) or not isinstance(value.get('kid'), str):
            raise ValueError("malformed activation lease")
        return value['kid']

    @staticmethod
    def _problem_message(error):
        try:
            payload = json.loads(error.read(MAX_RESPONSE_BYTES + 1).decode('utf-8'))
        except Exception:
            return f"DeniLicense request failed with HTTP {error.code}."
        return payload.get('detail') or payload.get('title') or payload.get('code') or (
            f"DeniLicense request failed with HTTP {error.code}."
        )

    @staticmethod
    def _rfc3339(value):
        return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')

    @staticmethod
    def _b64url(data):
        return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')

    @staticmethod
    def _unb64url(value):
        return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
