"""Thread-safe lazy database runtime for explicitly used API dependencies."""

from __future__ import annotations

from threading import Lock

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .config import DatabaseConfig
from .engine import create_database_engine, create_session_factory, dispose_database_engine


class LazyDatabaseRuntime:
    """Create one engine/session factory on first use, never during import/startup."""

    __slots__ = ("_engine", "_lock", "_session_factory")

    def __init__(self) -> None:
        self._lock = Lock()
        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    def session_factory(self) -> sessionmaker:
        factory = self._session_factory
        if factory is not None:
            return factory

        with self._lock:
            if self._session_factory is not None:
                return self._session_factory

            engine = create_database_engine(DatabaseConfig.from_environment())
            try:
                factory = create_session_factory(engine)
            except Exception:
                dispose_database_engine(engine)
                raise
            self._engine = engine
            self._session_factory = factory
            return factory

    def dispose(self) -> None:
        """Explicitly dispose the lazily-created engine during app shutdown."""
        with self._lock:
            engine = self._engine
            self._engine = None
            self._session_factory = None
        if engine is not None:
            dispose_database_engine(engine)
