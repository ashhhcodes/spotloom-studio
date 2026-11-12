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
    Asset,
    AssetEvidenceRevocation,
    AssetUploadIntent,
    AssetValidationAttempt,
    AssetValidationEvidence,
    AssetVersion,
    ASSET_RECOVERY_LEASE_RENEWAL_INTERVAL,
    ASSET_RECOVERY_MAX_ATTEMPTS,
    ASSET_RECOVERY_MAX_LEASE,
    ASSET_RECOVERY_MAX_WINDOW,
    PROJECT_NAME_MAX_LENGTH,
    Base,
    ExternalIdentity,
    Project,
    ProjectAssetUsage,
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
        "users", "external_identities", "projects", "project_creative_workspaces",
        "project_asset_usage", "assets", "asset_upload_intents", "asset_versions",
        "asset_validation_attempts", "asset_validation_evidence", "asset_evidence_revocations",
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

    assert scripts.get_current_head() == "20261112_0005_asset_recovery"
    recovery_revision = scripts.get_revision("20261112_0005_asset_recovery")
    assert recovery_revision is not None
    assert recovery_revision.down_revision == "20261112_0004_asset_upload_ops"
    revision = scripts.get_revision("20261112_0004_asset_upload_ops")
    assert revision is not None
    assert revision.down_revision == "20261112_0003_asset_persistence"
    previous_revision = scripts.get_revision("20261112_0003_asset_persistence")
    assert previous_revision is not None
    assert previous_revision.down_revision == "20261111_0002"
    assert "20261112_0003_asset_persistence.py" in previous_revision.path


def test_upload_operation_metadata_models_claims_observations_and_cleanup_separately() -> None:
    uploads = Base.metadata.tables[AssetUploadIntent.__tablename__]
    versions = Base.metadata.tables[AssetVersion.__tablename__]

    required_columns = {
        "operation_state", "operation_revision", "operation_updated_at",
        "operation_claim_generation", "operation_claim_token", "operation_claimed_at",
        "operation_lease_expires_at", "observed_sha256_hex", "transfer_completed_at",
        "recovery_deadline_at", "recovery_state", "recovery_revision",
        "recovery_claim_generation", "recovery_claim_token", "recovery_claimed_at",
        "recovery_lease_issued_at", "recovery_lease_expires_at", "recovery_attempt_count",
        "recovery_finished_at", "recovery_outcome_code",
        "final_storage_provider", "final_object_version_reference", "finalization_started_at",
        "storage_finalized_at", "cleanup_state", "cleanup_revision", "cleanup_updated_at",
        "cleanup_claim_generation", "cleanup_claim_token", "cleanup_claimed_at",
        "cleanup_lease_expires_at", "cleanup_confirmed_at",
    }
    assert required_columns <= set(uploads.c.keys())
    assert uploads.c.operation_state.server_default is not None
    assert uploads.c.operation_claim_token.nullable
    assert uploads.c.recovery_deadline_at.server_default is None
    assert uploads.c.recovery_deadline_at.default is not None
    assert uploads.c.observed_sha256_hex.nullable
    assert uploads.c.final_object_version_reference.nullable
    assert uploads.c.cleanup_confirmed_at.nullable
    assert versions.c.detected_media_type.nullable

    checks = {
        constraint.name
        for constraint in uploads.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_asset_upload_intents_operation_state_supported",
        "ck_asset_upload_intents_operation_revision_nonnegative",
        "ck_asset_upload_intents_operation_claim_lease_consistent",
        "ck_asset_upload_intents_operation_lease_bounded",
        "ck_asset_upload_intents_active_transfer_claim_required",
        "ck_asset_upload_intents_recovery_state_supported",
        "ck_asset_upload_intents_recovery_claim_state_consistent",
        "ck_asset_upload_intents_recovery_deadline_after_expiry",
        "ck_asset_upload_intents_recovery_deadline_max_window",
        "ck_asset_upload_intents_recovery_claim_lease_consistent",
        "ck_asset_upload_intents_recovery_lease_bounded",
        "ck_asset_upload_intents_recovery_attempt_count_bounded",
        "ck_asset_upload_intents_recovery_finished_state_consistent",
        "ck_asset_upload_intents_recovery_finalized_consistent",
        "ck_asset_upload_intents_transfer_completed_before_expiry",
        "ck_asset_upload_intents_transfer_observation_consistent",
        "ck_asset_upload_intents_completed_transfer_observed",
        "ck_asset_upload_intents_final_reference_pair_consistent",
        "ck_asset_upload_intents_storage_finalization_timestamp_consistent",
        "ck_asset_upload_intents_storage_finalized_after_start",
        "ck_asset_upload_intents_cleanup_state_supported",
        "ck_asset_upload_intents_cleanup_confirmation_consistent",
    } <= checks
    recovery_claim_check = next(
        check for check in uploads.constraints
        if isinstance(check, CheckConstraint)
        and check.name == "ck_asset_upload_intents_recovery_claim_state_consistent"
    )
    assert "recovery_state = 'claimed'" in str(recovery_claim_check.sqltext)
    assert "recovery_claim_token IS NOT NULL" in str(recovery_claim_check.sqltext)
    assert ASSET_RECOVERY_MAX_WINDOW.total_seconds() == 24 * 60 * 60
    assert ASSET_RECOVERY_MAX_LEASE.total_seconds() == 5 * 60
    assert ASSET_RECOVERY_LEASE_RENEWAL_INTERVAL.total_seconds() == 60
    assert ASSET_RECOVERY_MAX_ATTEMPTS == 10
    assert {
        "uq_upload_intents_final_storage_version",
        "ix_upload_intents_expired_operation_lease",
        "ix_upload_intents_pending_cleanup",
        "ix_upload_intents_recovery_due",
        "ix_upload_intents_expired_recovery_lease",
    } <= {index.name for index in uploads.indexes}
def test_asset_metadata_has_project_scoped_immutable_history_constraints() -> None:
    expected_tables = {
        "project_asset_usage",
        "assets",
        "asset_upload_intents",
        "asset_versions",
        "asset_validation_attempts",
        "asset_validation_evidence",
        "asset_evidence_revocations",
    }
    assert expected_tables <= set(Base.metadata.tables)

    usage = Base.metadata.tables[ProjectAssetUsage.__tablename__]
    assets = Base.metadata.tables[Asset.__tablename__]
    uploads = Base.metadata.tables[AssetUploadIntent.__tablename__]
    versions = Base.metadata.tables[AssetVersion.__tablename__]
    attempts = Base.metadata.tables[AssetValidationAttempt.__tablename__]
    evidence = Base.metadata.tables[AssetValidationEvidence.__tablename__]
    revocations = Base.metadata.tables[AssetEvidenceRevocation.__tablename__]

    assert "quota_limit_bytes" in usage.c
    assert usage.c.quota_limit_bytes.server_default is None
    assert assets.c.current_ready_version_id.nullable
    assert assets.c.deleted_at.nullable
    assert uploads.c.idempotency_key.nullable is False
    assert versions.c.object_version_reference.nullable is False
    assert versions.c.finalized_at.nullable is False
    assert versions.c.accepted_evidence_id.nullable
    assert attempts.c.attempt_number.nullable is False
    assert evidence.c.sha256_hex.nullable is False
    assert evidence.c.validator_identity.nullable is False
    assert revocations.c.evidence_id.primary_key

    def composite_fk(table, local_columns, referred_table, remote_columns):
        return any(
            isinstance(constraint, ForeignKeyConstraint)
            and [element.parent.name for element in constraint.elements] == local_columns
            and [element.column.table.name for element in constraint.elements]
            == [referred_table] * len(local_columns)
            and [element.column.name for element in constraint.elements] == remote_columns
            and all(element.ondelete == "RESTRICT" for element in constraint.elements)
            for constraint in table.constraints
        )

    assert composite_fk(uploads, ["project_id", "asset_id"], "assets", ["project_id", "id"])
    assert composite_fk(
        versions, ["project_id", "asset_id", "upload_intent_id"], "asset_upload_intents",
        ["project_id", "asset_id", "id"],
    )
    assert composite_fk(
        attempts, ["project_id", "asset_id", "version_id"], "asset_versions",
        ["project_id", "asset_id", "id"],
    )
    assert composite_fk(
        evidence, ["project_id", "asset_id", "version_id", "attempt_id"], "asset_validation_attempts",
        ["project_id", "asset_id", "version_id", "id"],
    )
    assert composite_fk(
        evidence, ["project_id", "asset_id", "version_id"], "asset_versions",
        ["project_id", "asset_id", "id"],
    )
    assert composite_fk(
        versions, ["project_id", "asset_id", "id", "accepted_evidence_id"], "asset_validation_evidence",
        ["project_id", "asset_id", "version_id", "id"],
    )
    assert composite_fk(
        assets, ["project_id", "id", "current_ready_version_id"], "asset_versions",
        ["project_id", "asset_id", "id"],
    )

    check_names = {
        constraint.name
        for table in (usage, assets, uploads, versions, attempts, evidence, revocations)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_assets_kind_supported" in check_names
    assert "ck_assets_ck_assets_kind_supported" not in check_names
    assert {
        "uq_asset_versions_storage_version",
        "uq_asset_versions_upload_intent",
    } <= {constraint.name for constraint in versions.constraints if isinstance(constraint, UniqueConstraint)}
    assert any(index.unique and index.name == "uq_validation_attempts_one_active_per_version" for index in attempts.indexes)

    # Every foreign key added for assets is restrictive; history has no CASCADE path.
    for table in (usage, assets, uploads, versions, attempts, evidence, revocations):
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                assert all(element.ondelete == "RESTRICT" for element in constraint.elements)
