from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from adforge_renderer.database import DatabaseConfig
from adforge_renderer.database.models import PROJECT_NAME_MAX_LENGTH, normalize_project_name
from adforge_renderer.database.models import Base
from adforge_renderer.identity import VerifiedClerkPrincipal
from adforge_renderer.project_service import get_or_create_internal_user_id
from sqlalchemy.orm import sessionmaker
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local


def _local_disposable_test_config() -> DatabaseConfig | None:
    raw_url = os.environ.get("SPOTLOOM_TEST_DATABASE_URL")
    if not raw_url:
        return None
    config = DatabaseConfig.from_url(raw_url)
    if config.url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("PostgreSQL migration tests require a loopback database host.")
    if not config.url.database or not config.url.database.endswith("_test"):
        raise ValueError("PostgreSQL migration tests require a database ending in _test.")
    return config


def _insert_project(connection, owner_id, name: str) -> None:
    connection.execute(
        text(
            "INSERT INTO projects (id, owner_user_id, name) "
            "VALUES (:id, :owner_id, :name)"
        ),
        {"id": uuid4(), "owner_id": owner_id, "name": name},
    )


def test_initial_migration_upgrades_and_downgrades_disposable_local_postgresql() -> None:
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to an explicitly disposable local *_test database.")

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_migration_test_{uuid4().hex}"

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.commit()
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            assert inspect(connection).get_table_names() == []
            config.attributes["connection"] = connection

            command.upgrade(config, "head")
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version",
                "users",
                "external_identities",
                "projects",
            }

            inspector = inspect(connection)
            assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
            assert inspector.get_pk_constraint("external_identities")["constrained_columns"] == ["id"]
            assert inspector.get_pk_constraint("projects")["constrained_columns"] == ["id"]
            identity_columns = {
                column["name"]: column for column in inspector.get_columns("external_identities")
            }
            project_columns = {
                column["name"]: column for column in inspector.get_columns("projects")
            }
            assert identity_columns["issuer"]["nullable"] is False
            assert identity_columns["subject"]["nullable"] is False
            assert identity_columns["user_id"]["nullable"] is False
            assert project_columns["owner_user_id"]["nullable"] is False
            assert project_columns["name"]["type"].length == PROJECT_NAME_MAX_LENGTH
            assert any(
                set(constraint["column_names"]) == {"issuer", "subject"}
                for constraint in inspector.get_unique_constraints("external_identities")
            )
            assert any(
                foreign_key["constrained_columns"] == ["owner_user_id"]
                and foreign_key["referred_table"] == "users"
                for foreign_key in inspector.get_foreign_keys("projects")
            )
            assert any(
                foreign_key["constrained_columns"] == ["user_id"]
                and foreign_key["referred_table"] == "users"
                for foreign_key in inspector.get_foreign_keys("external_identities")
            )
            assert {index["name"] for index in inspector.get_indexes("projects")} == {
                "ix_projects_owner_created_id"
            }
            external_identity_indexes = inspector.get_indexes("external_identities")
            assert {
                index["name"]
                for index in external_identity_indexes
                if not index.get("duplicates_constraint")
            } == {"ix_external_identities_user_id"}
            name_constraint = next(
                constraint
                for constraint in inspector.get_check_constraints("projects")
                if constraint["name"] == "ck_projects_name_nonblank"
            )
            assert "btrim" in name_constraint["sqltext"]
            assert "char_length" in name_constraint["sqltext"]
            assert project_columns["updated_at"]["default"] is not None

            owner_id = uuid4()
            connection.execute(
                text("INSERT INTO users (id) VALUES (:owner_id)"),
                {"owner_id": owner_id},
            )
            connection.execute(
                text(
                    "INSERT INTO external_identities (id, issuer, subject, user_id) "
                    "VALUES (:id, :issuer, :subject, :owner_id)"
                ),
                {
                    "id": uuid4(),
                    "issuer": "https://issuer.example",
                    "subject": "subject-1",
                    "owner_id": owner_id,
                },
            )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO external_identities (id, issuer, subject, user_id) "
                            "VALUES (:id, :issuer, :subject, :owner_id)"
                        ),
                        {
                            "id": uuid4(),
                            "issuer": "https://issuer.example",
                            "subject": "subject-1",
                            "owner_id": owner_id,
                        },
                    )

            # The migration's fixed whitespace set covers representative ASCII
            # and Unicode whitespace; Python str.strip remains the app normalizer.
            for invalid_name in (
                "",
                " \t\n\r\f\v",
                " Northstar",
                "\u00a0\u2003",
                "\u202f",
            ):
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        _insert_project(connection, owner_id, invalid_name)

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    _insert_project(connection, uuid4(), "Missing owner")

            _insert_project(connection, owner_id, "N" * PROJECT_NAME_MAX_LENGTH)
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_project(connection, owner_id, "N" * (PROJECT_NAME_MAX_LENGTH + 1))

            non_ascii_blank = "\u00a0\u2003"
            with pytest.raises(ValueError):
                normalize_project_name(non_ascii_blank)
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_project(connection, owner_id, non_ascii_blank)
            unicode_padded = "\u00a0Northstar\u2003"
            assert normalize_project_name(unicode_padded) == "Northstar"
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_project(connection, owner_id, unicode_padded)
            _insert_project(connection, owner_id, normalize_project_name(unicode_padded))
            connection.commit()

            command.downgrade(config, "base")
            # Alembic retains its version table after downgrade, with no revision rows.
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    finally:
        config.attributes.pop("connection", None)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def test_concurrent_first_identity_mapping_uses_unique_pair_on_disposable_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise concurrent first login against PostgreSQL's unique constraint."""
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to an explicitly disposable local *_test database.")

    import adforge_renderer.project_service as project_service

    admin_engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_identity_race_{uuid4().hex}"
    worker_engine = None
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

        worker_engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)

        @event.listens_for(worker_engine, "connect")
        def _set_isolated_schema(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.close()

        Base.metadata.create_all(worker_engine)
        factory = sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False)
        principal = VerifiedClerkPrincipal(
            issuer="https://spotloom-test.clerk.accounts.dev",
            subject=f"concurrent-{uuid4().hex}",
        )
        barrier = Barrier(2)
        thread_state = local()
        original_lookup = project_service.find_internal_user_id

        def synchronized_initial_lookup(session, candidate):
            result = original_lookup(session, candidate)
            if result is None and not getattr(thread_state, "waited", False):
                thread_state.waited = True
                barrier.wait(timeout=10)
            return result

        monkeypatch.setattr(project_service, "find_internal_user_id", synchronized_initial_lookup)

        def resolve_id():
            with factory.begin() as session:
                return get_or_create_internal_user_id(session, principal)

        with ThreadPoolExecutor(max_workers=2) as executor:
            user_ids = list(executor.map(lambda _index: resolve_id(), range(2)))

        assert user_ids[0] == user_ids[1]
        with factory() as session:
            assert session.scalar(text("SELECT count(*) FROM users")) == 1
            assert session.scalar(text("SELECT count(*) FROM external_identities")) == 1
    finally:
        if worker_engine is not None:
            worker_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()
