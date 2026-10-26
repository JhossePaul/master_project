"""Fixtures compartidas: llaves de prueba de IAP."""

import time

import pytest
from api_backend.auth.iap import IAP_ISSUER
from api_backend.testing import AUDIENCE, KEY_ID, FakeTransport, IapKit
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from google.auth import crypt
from google.auth import jwt as google_jwt


def _pem_pair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public


@pytest.fixture(scope="session")
def iap_kit() -> IapKit:
    private, public = _pem_pair()
    _, other_public = _pem_pair()
    signer = crypt.ES256Signer.from_string(private, KEY_ID)

    def sign(**overrides: object) -> str:
        now = int(time.time())
        claims: dict[str, object] = {
            "iss": IAP_ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + 600,
            "email": "Ana@Example.com",
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return google_jwt.encode(signer, claims, {"kid": KEY_ID}).decode()

    return IapKit(
        transport=FakeTransport(public),
        other_transport=FakeTransport(other_public),
        sign=sign,
    )
