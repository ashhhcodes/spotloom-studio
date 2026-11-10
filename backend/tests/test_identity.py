from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Annotated

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from clerk_backend_api.security.types import AuthStatus, RequestState, TokenVerificationErrorReason
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from adforge_renderer import api
from adforge_renderer.identity import (
    ClerkVerificationConfig,
    VerifiedClerkPrincipal,
    get_clerk_verification_config,
    require_verified_principal,
)
from adforge_renderer import environment


ISSUER = "https://spotloom-test.clerk.accounts.dev"
PARTY = "http://localhost:3000"
AUDIENCE = "spotloom-api"
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode("ascii")
_other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_now = datetime.now(timezone.utc)


def config(*, public_key: str = _public_key) -> ClerkVerificationConfig:
    return ClerkVerificationConfig(
        issuer=ISSUER,
        authorized_parties=(PARTY,),
        jwt_public_key=public_key,
        audience=AUDIENCE,
    )


def token(
    *,
    signing_key: object = _private_key,
    issuer: str = ISSUER,
    subject: str = "user_test_subject",
    audience: str = AUDIENCE,
    authorized_party: str = PARTY,
    expires_at: datetime = _now + timedelta(minutes=2),
    not_before: datetime = _now - timedelta(seconds=1),
    issued_at: datetime = _now,
) -> str:
    claims = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "azp": authorized_party,
        "sid": "sess_test_session",
        "iat": issued_at,
        "nbf": not_before,
        "exp": expires_at,
    }
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})


def make_client(*, fixed_config: ClerkVerificationConfig | None = None) -> TestClient:
    test_app = FastAPI()

    @test_app.get("/protected")
    def protected(
        principal: Annotated[VerifiedClerkPrincipal, Depends(require_verified_principal)],
    ) -> dict[str, str]:
        return {"issuer": principal.issuer, "subject": principal.subject}

    if fixed_config is not None:
        test_app.dependency_overrides[get_clerk_verification_config] = lambda: fixed_config
    return TestClient(test_app)


def test_missing_token_is_unauthorized() -> None:
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication credentials."}


def test_malformed_token_is_unauthorized_without_detail_leak() -> None:
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert "not-a-jwt" not in response.text


def test_invalid_signature_is_unauthorized() -> None:
    invalid = token(signing_key=_other_private_key)
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {invalid}"})

    assert response.status_code == 401


def test_sdk_rejection_logs_only_static_reason_category(caplog, monkeypatch) -> None:
    def rejected_request(_request, _options):
        return RequestState(
            status=AuthStatus.SIGNED_OUT,
            reason=TokenVerificationErrorReason.TOKEN_INVALID_SIGNATURE,
        )

    monkeypatch.setattr("adforge_renderer.identity.authenticate_request", rejected_request)
    caplog.set_level("WARNING", logger="adforge_renderer.identity")
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": "Bearer never-log-this-token"})

    assert response.status_code == 401
    assert "category=token-invalid-signature" in caplog.text
    assert "never-log-this-token" not in caplog.text


def test_unexpected_verifier_exception_logs_type_without_message(caplog, monkeypatch) -> None:
    def fail_with_sensitive_message(_request, _options):
        raise RuntimeError("sensitive token-like detail")

    monkeypatch.setattr("adforge_renderer.identity.authenticate_request", fail_with_sensitive_message)
    caplog.set_level("WARNING", logger="adforge_renderer.identity")
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": "Bearer never-log-this-token"})

    assert response.status_code == 401
    assert "category=verifier_exception error_type=RuntimeError" in caplog.text
    assert "sensitive token-like detail" not in caplog.text
    assert "never-log-this-token" not in caplog.text


def test_issuer_rejection_logs_fixed_category(caplog) -> None:
    caplog.set_level("WARNING", logger="adforge_renderer.identity")
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {token(issuer='https://other.clerk.accounts.dev')}"})

    assert response.status_code == 401
    assert "category=issuer_mismatch" in caplog.text


def test_expired_token_is_unauthorized() -> None:
    expired = token(expires_at=_now - timedelta(seconds=30))
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


def test_valid_token_returns_verified_issuer_and_subject_only() -> None:
    valid = token()
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {valid}"})

    assert response.status_code == 200
    assert response.json() == {"issuer": ISSUER, "subject": "user_test_subject"}


def test_wrong_issuer_is_rejected_after_signature_verification() -> None:
    wrong_issuer = token(issuer="https://other.clerk.accounts.dev")
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {wrong_issuer}"})

    assert response.status_code == 401


def test_unapproved_authorized_party_is_rejected() -> None:
    wrong_party = token(authorized_party="https://attacker.example")
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {wrong_party}"})

    assert response.status_code == 401


def test_wrong_configured_audience_is_rejected() -> None:
    wrong_audience = token(audience="another-api")
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {wrong_audience}"})

    assert response.status_code == 401


def test_future_not_before_token_is_unauthorized() -> None:
    not_active = token(not_before=_now + timedelta(minutes=1))
    with make_client(fixed_config=config()) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {not_active}"})

    assert response.status_code == 401


def test_environment_configuration_parses_public_key_and_required_allowlists(monkeypatch) -> None:
    monkeypatch.setenv("CLERK_JWT_KEY", _public_key.replace("\n", "\\n"))
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", f"{PARTY},https://studio.example")
    monkeypatch.setenv("CLERK_AUDIENCE", AUDIENCE)

    parsed = ClerkVerificationConfig.from_environment()

    assert parsed.issuer == ISSUER
    assert parsed.authorized_parties == (PARTY, "https://studio.example")
    assert parsed.audience == AUDIENCE
    assert parsed.jwt_public_key == _public_key.strip()


def test_environment_configuration_loads_backend_env_file_without_overriding_process(
    monkeypatch, tmp_path: Path
) -> None:
    dotenv_path = tmp_path / "backend" / ".env"
    dotenv_path.parent.mkdir()
    dotenv_path.write_text(
        "CLERK_JWT_KEY=" + json.dumps(_public_key) + "\n"
        "CLERK_ISSUER=" + ISSUER + "\n"
        "CLERK_AUTHORIZED_PARTIES=" + PARTY + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(environment, "_BACKEND_ENV_PATH", dotenv_path)
    for key in ("CLERK_JWT_KEY", "CLERK_ISSUER", "CLERK_AUTHORIZED_PARTIES", "CLERK_AUDIENCE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLERK_ISSUER", "https://process-override.example")

    parsed = ClerkVerificationConfig.from_environment()

    assert parsed.issuer == "https://process-override.example"
    assert parsed.authorized_parties == (PARTY,)
    assert parsed.jwt_public_key == _public_key.strip()


def test_missing_or_invalid_server_configuration_fails_closed(monkeypatch, tmp_path: Path) -> None:
    # Keep this test independent of a developer's real backend/.env file while
    # still exercising the production environment-loading call path.
    monkeypatch.setattr(environment, "_BACKEND_ENV_PATH", tmp_path / "missing" / ".env")
    for key in ("CLERK_JWT_KEY", "CLERK_ISSUER", "CLERK_AUTHORIZED_PARTIES", "CLERK_AUDIENCE"):
        monkeypatch.delenv(key, raising=False)
    get_clerk_verification_config.cache_clear()

    with make_client() as client:
        missing = client.get("/protected", headers={"Authorization": f"Bearer {token()}"})

    assert missing.status_code == 503
    assert missing.json() == {"detail": "Authentication verification is not configured."}

    monkeypatch.setenv("CLERK_JWT_KEY", "not a PEM key")
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", PARTY)
    get_clerk_verification_config.cache_clear()
    with make_client() as client:
        invalid = client.get("/protected", headers={"Authorization": f"Bearer {token()}"})
    get_clerk_verification_config.cache_clear()

    assert invalid.status_code == 503
    assert "not a PEM key" not in invalid.text


def test_protected_identity_endpoint_returns_only_verified_principal() -> None:
    prior = api.app.dependency_overrides.get(get_clerk_verification_config)
    api.app.dependency_overrides[get_clerk_verification_config] = lambda: config()
    try:
        with TestClient(api.app) as client:
            response = client.get("/auth/identity", headers={"Authorization": f"Bearer {token()}"})
    finally:
        if prior is None:
            api.app.dependency_overrides.pop(get_clerk_verification_config, None)
        else:
            api.app.dependency_overrides[get_clerk_verification_config] = prior

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "principal": {"issuer": ISSUER, "subject": "user_test_subject"},
    }


def test_protected_identity_endpoint_rejects_invalid_token() -> None:
    prior = api.app.dependency_overrides.get(get_clerk_verification_config)
    api.app.dependency_overrides[get_clerk_verification_config] = lambda: config()
    try:
        with TestClient(api.app) as client:
            response = client.get("/auth/identity", headers={"Authorization": "Bearer invalid-token"})
    finally:
        if prior is None:
            api.app.dependency_overrides.pop(get_clerk_verification_config, None)
        else:
            api.app.dependency_overrides[get_clerk_verification_config] = prior

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication credentials."}


def test_protected_identity_endpoint_rejects_signed_out_request() -> None:
    prior = api.app.dependency_overrides.get(get_clerk_verification_config)
    api.app.dependency_overrides[get_clerk_verification_config] = lambda: config()
    try:
        with TestClient(api.app) as client:
            response = client.get("/auth/identity")
    finally:
        if prior is None:
            api.app.dependency_overrides.pop(get_clerk_verification_config, None)
        else:
            api.app.dependency_overrides[get_clerk_verification_config] = prior

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication credentials."}
