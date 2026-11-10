"""Typed, secret-safe configuration for explicit PostgreSQL initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from collections.abc import Mapping

from sqlalchemy.engine import URL, make_url

from adforge_renderer.environment import load_backend_environment


class DatabaseConfigurationError(ValueError):
    """Safe configuration error that never includes the supplied URL."""


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    """Validated PostgreSQL URL; its credential-bearing value is hidden in repr."""

    url: URL = field(repr=False)

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> DatabaseConfig:
        """Read DATABASE_URL when persistence is explicitly initialized."""
        source = os.environ if environ is None else environ
        if environ is None:
            load_backend_environment()
            source = os.environ
        raw_url = source.get("DATABASE_URL")
        if not isinstance(raw_url, str) or not raw_url or raw_url != raw_url.strip():
            raise DatabaseConfigurationError(
                "DATABASE_URL is required and must be a valid PostgreSQL URL."
            )
        return cls.from_url(raw_url)

    @classmethod
    def from_url(cls, raw_url: str) -> DatabaseConfig:
        """Validate an explicit URL without retaining it in errors or reprs."""
        if not isinstance(raw_url, str) or not raw_url or raw_url != raw_url.strip():
            raise DatabaseConfigurationError("Database URL is invalid.")
        try:
            parsed = make_url(raw_url)
        except Exception:
            raise DatabaseConfigurationError("Database URL is invalid.") from None

        if parsed.drivername == "postgresql":
            parsed = parsed.set(drivername="postgresql+psycopg")
        if parsed.drivername != "postgresql+psycopg" or not parsed.database:
            raise DatabaseConfigurationError(
                "DATABASE_URL must identify a PostgreSQL database using psycopg."
            )
        return cls(url=parsed)
