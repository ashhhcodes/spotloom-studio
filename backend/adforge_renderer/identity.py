"""Clerk session verification primitives for future protected API routes.

This module verifies identity only. It does not resolve an internal user,
authorize project access, or protect routes unless a route explicitly depends
on ``require_verified_principal``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import ipaddress
import logging
import os
from urllib.parse import urlsplit

from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import Depends, HTTPException, Request, status

from adforge_renderer.environment import load_backend_environment


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifiedClerkPrincipal:
    """External Clerk identity extracted only after successful verification."""

    issuer: str
    subject: str


@dataclass(frozen=True)
class ClerkVerificationConfig:
    """Explicit verification settings; the public key is omitted from repr."""

    issuer: str
    authorized_parties: tuple[str, ...]
    jwt_public_key: str = field(repr=False)
    audience: str | None = None

    @classmethod
    def from_environment(cls) -> ClerkVerificationConfig:
        """Load and validate required configuration without exposing values."""
        load_backend_environment()
        raw_key = os.environ.get("CLERK_JWT_KEY", "")
        issuer = os.environ.get("CLERK_ISSUER", "")
        raw_parties = os.environ.get("CLERK_AUTHORIZED_PARTIES", "")
        audience = os.environ.get("CLERK_AUDIENCE")

        jwt_public_key = raw_key.replace("\\n", "\n").strip()
        if not jwt_public_key or not _is_valid_issuer(issuer):
            raise ValueError("Required Clerk verification settings are invalid.")
        try:
            parsed_key = serialization.load_pem_public_key(jwt_public_key.encode("utf-8"))
        except (TypeError, ValueError):
            raise ValueError("Required Clerk verification settings are invalid.") from None
        if not isinstance(parsed_key, RSAPublicKey) or parsed_key.key_size < 2048:
            raise ValueError("Required Clerk verification settings are invalid.")

        parties = tuple(part.strip() for part in raw_parties.split(","))
        if not parties or any(not _is_valid_party(party) for party in parties):
            raise ValueError("Required Clerk verification settings are invalid.")
        if len(set(parties)) != len(parties):
            raise ValueError("Required Clerk verification settings are invalid.")

        normalized_audience = audience.strip() if audience is not None else None
        if normalized_audience == "":
            raise ValueError("Required Clerk verification settings are invalid.")

        return cls(
            issuer=issuer,
            authorized_parties=parties,
            jwt_public_key=jwt_public_key,
            audience=normalized_audience,
        )


def _is_valid_issuer(value: str) -> bool:
    if not value or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.path == ""
            and parsed.query == ""
            and parsed.fragment == ""
        )
    except ValueError:
        return False


def _is_valid_party(value: str) -> bool:
    if not value or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        host = parsed.hostname
        local_http = parsed.scheme == "http" and host is not None and _is_loopback_host(host)
        return (
            (parsed.scheme == "https" or local_http)
            and bool(host)
            and parsed.username is None
            and parsed.password is None
            and parsed.path == ""
            and parsed.query == ""
            and parsed.fragment == ""
        )
    except ValueError:
        return False


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@lru_cache(maxsize=1)
def get_clerk_verification_config() -> ClerkVerificationConfig:
    """FastAPI config dependency; misconfiguration fails closed with 503."""
    try:
        return ClerkVerificationConfig.from_environment()
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication verification is not configured.",
        ) from None


def require_verified_principal(
    request: Request,
    config: ClerkVerificationConfig = Depends(get_clerk_verification_config),
) -> VerifiedClerkPrincipal:
    """Verify a Clerk session JWT and return its verified issuer/subject pair.

    The maintained Clerk SDK enforces RS256 signatures, expiry/not-before,
    configured audience, the authorized-party allowlist, and the session-token
    type. Its current verifier intentionally does not check ``iss``, so this
    dependency compares that claim after signature verification.
    """
    try:
        result = authenticate_request(
            request,
            AuthenticateRequestOptions(
                jwt_key=config.jwt_public_key,
                audience=config.audience,
                authorized_parties=list(config.authorized_parties),
                accepts_token=["session_token"],
                clock_skew_in_ms=0,
            ),
        )
    except Exception as error:
        # Never log the exception message: SDK errors may include request data.
        logger.warning(
            "Clerk session rejected: category=verifier_exception error_type=%s",
            type(error).__name__,
        )
        raise _unauthorized() from None

    payload = result.payload
    if not result.is_signed_in or not isinstance(payload, dict):
        reason = result.reason
        # Clerk SDK reason codes are fixed enum values, unlike caller data.
        category = reason.value[0] if reason is not None else "verification_failed"
        logger.warning("Clerk session rejected: category=%s", category)
        raise _unauthorized()

    issuer = payload.get("iss")
    subject = payload.get("sub")
    if type(issuer) is not str or issuer != config.issuer:
        logger.warning("Clerk session rejected: category=issuer_mismatch")
        raise _unauthorized()
    if type(subject) is not str or not subject.strip():
        logger.warning("Clerk session rejected: category=subject_missing_or_invalid")
        raise _unauthorized()
    if not _has_valid_required_time_claims(payload):
        logger.warning("Clerk session rejected: category=required_time_claims_invalid")
        raise _unauthorized()

    return VerifiedClerkPrincipal(issuer=issuer, subject=subject)


def _has_valid_required_time_claims(payload: dict[str, object]) -> bool:
    """Require standard session time claims; the SDK verifies their values."""
    return all(
        type(payload.get(claim)) in {int, float}
        for claim in ("iat", "nbf", "exp")
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
