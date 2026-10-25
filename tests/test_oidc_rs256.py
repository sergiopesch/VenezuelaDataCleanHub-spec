import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from vdch.config import Settings
from vdch.security import _decode_oidc_token


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

    def fake_fetch_data(_client):
        return {"keys": [jwk]}

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fake_fetch_data)

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
