import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from vdch.config import Settings
from vdch.security import _decode_oidc_token


class JwksResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def make_rs256_token(
    private_key,
    *,
    audience: str = "vdch-api",
    expires_delta=timedelta(minutes=5),
):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "https://issuer.example.test",
            "aud": audience,
            "sub": "user-1",
            "preferred_username": "user-1",
            "scope": "operator",
            "iat": now,
            "exp": now + expires_delta,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )


def test_oidc_rs256_jwks_verification_and_claim_failures(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "test-key-1", "use": "sig", "alg": "RS256"})
    settings = Settings(
        database_url="sqlite:///:memory:",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="vdch-api",
        oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        oidc_algorithms="RS256",
    )

    def fake_urlopen(*_args, **_kwargs):
        return JwksResponse({"keys": [jwk]})

    monkeypatch.setattr("jwt.jwks_client.urllib.request.urlopen", fake_urlopen)

    claims = _decode_oidc_token(settings, make_rs256_token(private_key))
    assert claims["sub"] == "user-1"

    with pytest.raises(HTTPException) as wrong_audience:
        _decode_oidc_token(
            settings,
            make_rs256_token(private_key, audience="other-api"),
        )
    assert wrong_audience.value.status_code == 401

    with pytest.raises(HTTPException) as expired:
        _decode_oidc_token(
            settings,
            make_rs256_token(private_key, expires_delta=timedelta(minutes=-1)),
        )
    assert expired.value.status_code == 401
