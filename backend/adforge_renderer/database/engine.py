"""Factories for database resources; nothing is initialized at module import."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeAlias

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .config import DatabaseConfig, DatabaseConfigurationError


class DatabaseOperationError(RuntimeError):
    """Sanitized database failure without driver messages or URL details."""


SessionFactory: TypeAlias = sessionmaker[Session]


def create_database_engine(config: DatabaseConfig) -> Engine:
    """Construct a lazy PostgreSQL engine; this function does not connect."""
    if not isinstance(config, DatabaseConfig):
        raise DatabaseConfigurationError("Valid database configuration is required.")
    try:
        return create_engine(
            config.url,
            echo=False,
            hide_parameters=True,
            pool_pre_ping=True,
        )
    except Exception:
        # Driver/engine exceptions may contain a URL or other configuration data.
        raise DatabaseConfigurationError(
            "The PostgreSQL engine could not be configured."
        ) from None


def create_session_factory(engine: Engine) -> SessionFactory:
    """Create a session factory without opening a connection."""
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def session_transaction(session_factory: SessionFactory) -> Iterator[Session]:
    """Run one explicit transaction, rolling back on failure and sanitizing DB errors."""
    try:
        with session_factory.begin() as session:
            yield session
    except SQLAlchemyError:
        raise DatabaseOperationError("The database operation failed.") from None


def get_session_dependency(
    session_factory: SessionFactory,
) -> Callable[[], Iterator[Session]]:
    """Build a FastAPI-compatible request dependency with explicit transaction scope."""
    def dependency() -> Iterator[Session]:
        with session_transaction(session_factory) as session:
            yield session

    return dependency


def dispose_database_engine(engine: Engine) -> None:
    """Explicitly dispose a previously created engine without logging details."""
    try:
        engine.dispose()
    except SQLAlchemyError:
        raise DatabaseOperationError("The database engine could not be disposed.") from None
