"""Explicitly initialized PostgreSQL persistence primitives.

Importing this package creates no engine, session, connection, or schema.
"""

from .config import DatabaseConfig, DatabaseConfigurationError
from .engine import (
    DatabaseOperationError,
    create_database_engine,
    create_session_factory,
    dispose_database_engine,
    get_session_dependency,
    session_transaction,
)
from .runtime import LazyDatabaseRuntime

__all__ = [
    "DatabaseConfig",
    "DatabaseConfigurationError",
    "DatabaseOperationError",
    "LazyDatabaseRuntime",
    "create_database_engine",
    "create_session_factory",
    "dispose_database_engine",
    "get_session_dependency",
    "session_transaction",
]
