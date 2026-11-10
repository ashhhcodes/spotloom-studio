"""Alembic environment; connections are opened only by explicit commands."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from adforge_renderer.database import (
    DatabaseConfig,
    DatabaseOperationError,
    create_database_engine,
    dispose_database_engine,
)
from adforge_renderer.database.models import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Offline SQL output is disabled to avoid embedding connection details."""
    raise RuntimeError("Offline migrations are disabled; use an explicit online migration command.")


def run_migrations_online() -> None:
    """Run migrations over a supplied test connection or explicit env config."""
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        _run_migrations(supplied_connection)
        return

    database_config = DatabaseConfig.from_environment()
    engine = create_database_engine(database_config)
    try:
        with engine.connect() as connection:
            _run_migrations(connection)
    except SQLAlchemyError:
        raise DatabaseOperationError("The migration database operation failed.") from None
    finally:
        dispose_database_engine(engine)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
