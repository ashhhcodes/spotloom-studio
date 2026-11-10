from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from adforge_renderer.database import (
    DatabaseConfig,
    DatabaseConfigurationError,
    create_database_engine,
    create_session_factory,
    dispose_database_engine,
)
from adforge_renderer.database.models import (
    PROJECT_NAME_MAX_LENGTH,
    Base,
    ExternalIdentity,
    Project,
    User,
    normalize_project_name,
)


def test_database_configuration_requires_a_postgresql_url_without_leaking_it() -> None:
    secret_url = "postgresql://user:do-not-print@localhost"

    with pytest.raises(DatabaseConfigurationError) as missing:
        DatabaseConfig.from_environment({})
    with pytest.raises(DatabaseConfigurationError) as malformed:
        DatabaseConfig.from_url(secret_url)
    with pytest.raises(DatabaseConfigurationError) as wrong_driver:
        DatabaseConfig.from_url("sqlite:///not-postgresql.db")

    assert "do-not-print" not in str(missing.value)
    assert "do-not-print" not in str(malformed.value)
    assert "do-not-print" not in str(wrong_driver.value)


def test_database_configuration_normalizes_postgres_scheme_and_hides_credentials() -> None:
    config = DatabaseConfig.from_url(
        "postgresql://spotloom:private-password@127.0.0.1:5432/spotloom_dev"
    )

    assert config.url.drivername == "postgresql+psycopg"
    assert config.url.database == "spotloom_dev"
    assert "private-password" not in repr(config)


def test_import_engine_session_factory_and_resource_construction_do_not_connect() -> None:
    script = """
import sqlalchemy
def forbidden(*args, **kwargs):
    raise AssertionError('database engine created during import')
sqlalchemy.create_engine = forbidden
import adforge_renderer.database
import adforge_renderer.database.engine
"""
    backend_dir = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(backend_dir), existing_path) if item
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    engine = create_database_engine(
        DatabaseConfig.from_url("postgresql+psycopg://user:pass@127.0.0.1/spotloom_dev")
    )
    factory = create_session_factory(engine)
    session = factory()
    try:
        assert engine.pool.checkedout() == 0
    finally:
        session.close()
        dispose_database_engine(engine)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Northstar  ", "Northstar"),
        ("x" * PROJECT_NAME_MAX_LENGTH, "x" * PROJECT_NAME_MAX_LENGTH),
    ],
)
def test_project_name_is_trimmed_and_bounded(value: str, expected: str) -> None:
    assert normalize_project_name(value) == expected


@pytest.mark.parametrize("value", ["", " \t\n ", "x" * (PROJECT_NAME_MAX_LENGTH + 1)])
def test_project_name_rejects_blank_or_overlong_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_project_name(value)


def test_project_name_normalization_handles_unicode_whitespace() -> None:
    assert normalize_project_name("\u00a0\u2003Northstar\u00a0\u2003") == "Northstar"
    with pytest.raises(ValueError):
        normalize_project_name("\u00a0\u2003")


def test_initial_metadata_has_required_keys_constraints_and_indexes() -> None:
    assert set(Base.metadata.tables) == {
        "users", "external_identities", "projects", "project_creative_workspaces"
    }

    users = Base.metadata.tables[User.__tablename__]
    identities = Base.metadata.tables[ExternalIdentity.__tablename__]
    projects = Base.metadata.tables[Project.__tablename__]

    assert users.c.id.primary_key
    assert users.c.created_at.nullable is False
    assert {"id", "issuer", "subject", "user_id", "created_at"} == set(
        identities.c.keys()
    )
    assert identities.c.issuer.nullable is False
    assert identities.c.subject.nullable is False
    assert identities.c.user_id.nullable is False
    assert any(
        isinstance(constraint, UniqueConstraint)
        and set(constraint.columns.keys()) == {"issuer", "subject"}
        for constraint in identities.constraints
    )
    assert any(isinstance(constraint, ForeignKeyConstraint) for constraint in identities.constraints)
    assert {"id", "owner_user_id", "name", "created_at", "updated_at"} == set(
        projects.c.keys()
    )
    assert projects.c.name.type.length == PROJECT_NAME_MAX_LENGTH
    assert projects.c.owner_user_id.nullable is False
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and {foreign_key.parent.name for foreign_key in constraint.elements}
        == {"owner_user_id"}
        for constraint in projects.constraints
    )
    name_check = next(
        constraint
        for constraint in projects.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_projects_name_nonblank"
    )
    assert "btrim" in str(name_check.sqltext)
    assert "char_length" in str(name_check.sqltext)
    assert {index.name for index in projects.indexes} == {"ix_projects_owner_created_id"}
    assert {index.name for index in identities.indexes} == {"ix_external_identities_user_id"}
    assert projects.c.updated_at.onupdate is not None


def test_alembic_has_one_discoverable_initial_revision() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "20261111_0002"
    revision = scripts.get_revision("20261111_0002")
    assert revision is not None
    assert revision.down_revision == "20261101_0001"
    assert "20261111_0002_project_creative_workspace.py" in revision.path
