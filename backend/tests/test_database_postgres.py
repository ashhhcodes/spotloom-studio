from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, create_engine, event, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.sql.elements import conv

from adforge_renderer.database import DatabaseConfig
from adforge_renderer.database.models import PROJECT_NAME_MAX_LENGTH, normalize_project_name
from adforge_renderer.database.models import (
    Asset,
    AssetUploadIntent,
    Base,
    Project,
    ProjectAssetUsage,
    User,
)
from adforge_renderer.identity import VerifiedClerkPrincipal
from adforge_renderer.project_service import get_or_create_internal_user_id
from adforge_renderer.asset_service import (
    AssetQuotaExceeded,
    AssetService,
    AssetServiceConfig,
)
from adforge_renderer.asset_storage_provider import TemporaryObjectReference
from adforge_renderer.local_asset_storage import LocalAssetStorageConfig, LocalPrivateAssetStorage
from sqlalchemy.orm import sessionmaker
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local


class _ReferenceAllocator:
    def allocate_temporary_reference(
        self, *, project_id: UUID, operation_id: UUID
    ) -> TemporaryObjectReference:
        return TemporaryObjectReference(f"tmp_{operation_id.hex}", project_id, operation_id)


def _local_disposable_test_config() -> DatabaseConfig | None:
    raw_url = os.environ.get("SPOTLOOM_TEST_DATABASE_URL")
    if not raw_url:
        return None
    config = DatabaseConfig.from_url(raw_url)
    if config.url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("PostgreSQL migration tests require a loopback database host.")
    if config.url.port != 5432:
        raise ValueError("PostgreSQL migration tests require port 5432.")
    if config.url.database != "spotloom_test":
        raise ValueError("Destructive PostgreSQL integration tests require exactly spotloom_test.")
    return config


def test_destructive_postgresql_guard_requires_exact_spotloom_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SPOTLOOM_TEST_DATABASE_URL",
        "postgresql+psycopg://test-user:test-password@localhost:5432/another_test",
    )
    with pytest.raises(ValueError, match="exactly spotloom_test"):
        _local_disposable_test_config()

    monkeypatch.setenv(
        "SPOTLOOM_TEST_DATABASE_URL",
        "postgresql+psycopg://test-user:test-password@localhost:5432/spotloom_test",
    )
    assert _local_disposable_test_config() is not None


def _insert_project(connection, owner_id, name: str) -> None:
    connection.execute(
        text(
            "INSERT INTO projects (id, owner_user_id, name) "
            "VALUES (:id, :owner_id, :name)"
        ),
        {"id": uuid4(), "owner_id": owner_id, "name": name},
    )


def _complete_upload_operation(connection, *, intent_id, object_reference, digest) -> None:
    """Move a test intent through transfer and independent recovery claims."""
    connection.execute(
        text("""UPDATE asset_upload_intents SET
            operation_state = 'receiving', operation_revision = operation_revision + 1,
            operation_claim_generation = operation_claim_generation + 1,
            operation_claim_token = :claim, operation_claimed_at = CURRENT_TIMESTAMP,
            operation_lease_expires_at = expires_at - INTERVAL '1 minute'
            WHERE id = :id"""),
        {"id": intent_id, "claim": uuid4()},
    )
    connection.execute(
        text("""UPDATE asset_upload_intents SET
            operation_state = 'uploaded', operation_revision = operation_revision + 1,
            operation_claim_token = NULL, operation_claimed_at = NULL,
            operation_lease_expires_at = NULL, received_bytes = 16,
            observed_sha256_hex = :digest, transfer_completed_at = CURRENT_TIMESTAMP,
            recovery_state = 'pending', recovery_revision = recovery_revision + 1
            WHERE id = :id"""),
        {"id": intent_id, "digest": digest},
    )
    connection.execute(
        text("""UPDATE asset_upload_intents SET
            operation_state = 'finalizing', operation_revision = operation_revision + 1,
            recovery_state = 'claimed', recovery_revision = recovery_revision + 1,
            recovery_claim_generation = recovery_claim_generation + 1,
            recovery_claim_token = :claim, recovery_claimed_at = CURRENT_TIMESTAMP,
            recovery_lease_issued_at = CURRENT_TIMESTAMP,
            recovery_lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '4 minutes',
            recovery_attempt_count = recovery_attempt_count + 1,
            final_storage_provider = 'local-dev', final_object_version_reference = :object_reference,
            finalization_started_at = CURRENT_TIMESTAMP
            WHERE id = :id"""),
        {"id": intent_id, "claim": uuid4(), "object_reference": object_reference},
    )
    connection.execute(
        text("""UPDATE asset_upload_intents SET
            operation_state = 'finalized', operation_revision = operation_revision + 1,
            recovery_state = 'completed', recovery_revision = recovery_revision + 1,
            recovery_claim_token = NULL, recovery_claimed_at = NULL,
            recovery_lease_issued_at = NULL, recovery_lease_expires_at = NULL,
            storage_finalized_at = CURRENT_TIMESTAMP
            WHERE id = :id"""),
        {"id": intent_id},
    )


def test_asset_migration_upgrades_and_downgrades_disposable_local_postgresql() -> None:
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

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

            command.upgrade(config, "20261111_0002")
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version",
                "users",
                "external_identities",
                "projects",
                "project_creative_workspaces",
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

            prior_project_count = connection.scalar(text("SELECT count(*) FROM projects"))
            prior_user_count = connection.scalar(text("SELECT count(*) FROM users"))
            prior_workspace_count = connection.scalar(text("SELECT count(*) FROM project_creative_workspaces"))

            command.upgrade(config, "head")
            asset_tables = {
                "project_asset_usage", "assets", "asset_upload_intents", "asset_versions",
                "asset_validation_attempts", "asset_validation_evidence", "asset_evidence_revocations",
            }
            assert asset_tables <= set(inspect(connection).get_table_names())
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0008_cleanup_receipt"
            assert all(
                connection.scalar(text(f"SELECT count(*) FROM {table_name}")) == 0
                for table_name in asset_tables
            )
            upload_columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("asset_upload_intents")
            }
            assert {
                "operation_state", "operation_revision", "operation_claim_generation",
                "operation_claim_token", "operation_claimed_at", "operation_lease_expires_at",
                "recovery_deadline_at", "recovery_state", "recovery_revision",
                "recovery_claim_generation", "recovery_claim_token", "recovery_claimed_at",
                "recovery_lease_issued_at", "recovery_lease_expires_at", "recovery_attempt_count",
                "recovery_finished_at", "recovery_outcome_code",
                "next_retry_at",
                "observed_sha256_hex", "transfer_completed_at", "final_storage_provider",
                "final_object_version_reference", "finalization_started_at", "storage_finalized_at",
                "cleanup_state", "cleanup_revision", "cleanup_claim_generation",
                "cleanup_claim_token", "cleanup_claimed_at", "cleanup_lease_expires_at",
                "cleanup_confirmed_at", "cleanup_completed_claim_token",
                "cleanup_completed_claim_generation", "cleanup_completed_revision",
            } <= set(upload_columns)
            version_columns = {
                column["name"] for column in inspect(connection).get_columns("asset_versions")
            }
            assert {
                "cleanup_claim_token", "cleanup_claim_generation",
                "cleanup_completed_claim_token", "cleanup_completed_claim_generation",
                "cleanup_completed_revision",
            } <= version_columns
            recovery_deadline_column = next(
                column for column in inspect(connection).get_columns("asset_upload_intents")
                if column["name"] == "recovery_deadline_at"
            )
            assert recovery_deadline_column["default"] is None
            assert inspect(connection).get_columns("asset_versions")[
                next(index for index, column in enumerate(inspect(connection).get_columns("asset_versions")) if column["name"] == "detected_media_type")
            ]["nullable"] is True
            upload_indexes = {
                item["name"] for item in inspect(connection).get_indexes("asset_upload_intents")
            }
            assert {
                "uq_upload_intents_final_storage_version",
                "ix_upload_intents_expired_operation_lease",
                "ix_upload_intents_pending_cleanup",
                "ix_upload_intents_recovery_due",
                "ix_upload_intents_expired_recovery_lease",
            } <= upload_indexes
            recovery_due_index = next(
                item for item in inspect(connection).get_indexes("asset_upload_intents")
                if item["name"] == "ix_upload_intents_recovery_due"
            )
            assert recovery_due_index["column_names"] == [
                "recovery_state", "next_retry_at", "recovery_deadline_at"
            ]
            upload_checks = {
                item["name"] for item in inspect(connection).get_check_constraints("asset_upload_intents")
            }
            assert {
                "ck_asset_upload_intents_operation_state_supported",
                "ck_asset_upload_intents_operation_lease_bounded",
                "ck_asset_upload_intents_active_transfer_claim_required",
                "ck_asset_upload_intents_recovery_deadline_max_window",
                "ck_asset_upload_intents_recovery_attempt_count_bounded",
                "ck_asset_upload_intents_recovery_claim_lease_consistent",
                "ck_asset_upload_intents_recovery_finalized_consistent",
                "ck_asset_upload_intents_transfer_digest_hex",
                "ck_asset_upload_intents_completed_transfer_observed",
                "ck_asset_upload_intents_finalization_after_transfer",
                "ck_asset_upload_intents_storage_finalized_after_start",
                "ck_asset_upload_intents_cleanup_confirmation_consistent",
                "ck_asset_upload_intents_next_retry_pending_before_deadline",
            } <= upload_checks
            for table_name in asset_tables:
                expected_checks = {
                    inspect(connection).dialect.identifier_preparer.truncate_and_render_constraint_name(
                        conv(constraint.name), _alembic_quote=False
                    )
                    for constraint in Base.metadata.tables[table_name].constraints
                    if isinstance(constraint, CheckConstraint)
                }
                actual_checks = {
                    item["name"] for item in inspect(connection).get_check_constraints(table_name)
                }
                assert actual_checks == expected_checks
            claim_state_check = next(
                item for item in inspect(connection).get_check_constraints("asset_upload_intents")
                if item["name"] == "ck_asset_upload_intents_recovery_claim_state_consistent"
            )
            assert "recovery_state" in claim_state_check["sqltext"]
            assert "'claimed'" in claim_state_check["sqltext"]
            assert "recovery_claim_token IS NOT NULL" in claim_state_check["sqltext"]
            trigger_names = {
                row[0]
                for row in connection.execute(
                    text("""SELECT tgname FROM pg_trigger
                        WHERE NOT tgisinternal AND tgrelid IN (
                            'asset_versions'::regclass, 'assets'::regclass,
                            'asset_upload_intents'::regclass,
                            'asset_validation_attempts'::regclass, 'asset_validation_evidence'::regclass,
                            'asset_evidence_revocations'::regclass
                        )""")
                )
            }
            assert trigger_names == {
                    "trg_asset_cleanup_receipt_guard",
                    "trg_asset_version_cleanup_receipt_guard",
                "trg_asset_versions_immutable_identity",
                "trg_assets_current_version_must_be_ready_insert",
                "trg_assets_current_version_must_be_ready_update",
                "trg_asset_versions_retain_current_ready",
                "trg_asset_versions_detected_media_type_guard",
                "trg_asset_upload_operation_guard",
                "trg_asset_upload_recovery_guard",
                "trg_asset_versions_upload_binding_guard",
                "trg_finalized_upload_has_version",
                "trg_asset_validation_attempts_immutable_identity",
                "trg_asset_validation_evidence_exact_version",
                "trg_asset_validation_evidence_immutable",
                "trg_asset_evidence_revocation_blocks_readiness",
            }

            inspector = inspect(connection)
            expected_composite_fks = {
                ("asset_upload_intents", ("project_id", "asset_id"), "assets", ("project_id", "id")),
                ("asset_versions", ("project_id", "asset_id"), "assets", ("project_id", "id")),
                ("asset_versions", ("project_id", "asset_id", "upload_intent_id"), "asset_upload_intents", ("project_id", "asset_id", "id")),
                ("asset_validation_attempts", ("project_id", "asset_id", "version_id"), "asset_versions", ("project_id", "asset_id", "id")),
                ("asset_validation_evidence", ("project_id", "asset_id", "version_id", "attempt_id"), "asset_validation_attempts", ("project_id", "asset_id", "version_id", "id")),
                ("asset_validation_evidence", ("project_id", "asset_id", "version_id"), "asset_versions", ("project_id", "asset_id", "id")),
                ("asset_versions", ("project_id", "asset_id", "id", "accepted_evidence_id"), "asset_validation_evidence", ("project_id", "asset_id", "version_id", "id")),
                ("assets", ("project_id", "id", "current_ready_version_id"), "asset_versions", ("project_id", "asset_id", "id")),
            }
            actual_composite_fks = set()
            for table_name, local, remote_table, remote in expected_composite_fks:
                for fk in inspector.get_foreign_keys(table_name):
                    if tuple(fk["constrained_columns"]) == local:
                        actual_composite_fks.add((table_name, local, fk["referred_table"], tuple(fk["referred_columns"])))
            assert actual_composite_fks == expected_composite_fks
            for table_name, local_columns, _remote_table, _remote_columns in expected_composite_fks:
                fk = next(
                    item for item in inspector.get_foreign_keys(table_name)
                    if tuple(item["constrained_columns"]) == local_columns
                )
                assert fk["options"].get("ondelete") == "RESTRICT"

            # The finalized identity trigger permits lifecycle changes but rejects rebinding.
            asset_project_id, asset_id = uuid4(), uuid4()
            upload_id, upload_id_2 = uuid4(), uuid4()
            version_id, version_id_2 = uuid4(), uuid4()
            connection.execute(
                text("INSERT INTO projects (id, owner_user_id, name) VALUES (:id, :owner, 'Asset schema test')"),
                {"id": asset_project_id, "owner": owner_id},
            )
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
                {"id": asset_id, "project": asset_project_id},
            )
            connection.execute(
                text("INSERT INTO project_asset_usage (project_id, quota_limit_bytes, used_bytes, reserved_bytes) "
                     "VALUES (:project, 100000, 16, 8)"),
                {"project": asset_project_id},
            )
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                    VALUES (:id, :project, :asset, 'key-1', :fingerprint,
                            'opaque-staging-reference', 1024, CURRENT_TIMESTAMP + INTERVAL '1 hour',
                            CURRENT_TIMESTAMP + INTERVAL '25 hours')"""),
                {"id": upload_id, "project": asset_project_id, "asset": asset_id, "fingerprint": "a" * 64},
            )
            _complete_upload_operation(
                connection, intent_id=upload_id,
                object_reference="opaque-version-a", digest="a" * 64,
            )
            connection.execute(
                text("""INSERT INTO asset_versions
                    (id, project_id, asset_id, upload_intent_id, storage_provider,
                     object_version_reference, byte_size, detected_media_type, finalized_at)
                    VALUES (:id, :project, :asset, :upload, 'local-dev', 'opaque-version-a',
                            16, 'audio/wav', CURRENT_TIMESTAMP)"""),
                {"id": version_id, "project": asset_project_id, "asset": asset_id, "upload": upload_id},
            )
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                    VALUES (:id, :project, :asset, 'key-2', :fingerprint,
                            'opaque-staging-reference-2', 1024, CURRENT_TIMESTAMP + INTERVAL '1 hour',
                            CURRENT_TIMESTAMP + INTERVAL '25 hours')"""),
                {"id": upload_id_2, "project": asset_project_id, "asset": asset_id, "fingerprint": "b" * 64},
            )
            _complete_upload_operation(
                connection, intent_id=upload_id_2,
                object_reference="opaque-version-second", digest="b" * 64,
            )
            connection.execute(
                text("""INSERT INTO asset_versions
                    (id, project_id, asset_id, upload_intent_id, storage_provider,
                     object_version_reference, byte_size, detected_media_type, finalized_at)
                    VALUES (:id, :project, :asset, :upload, 'local-dev', 'opaque-version-second',
                            16, 'audio/wav', CURRENT_TIMESTAMP)"""),
                {"id": version_id_2, "project": asset_project_id, "asset": asset_id, "upload": upload_id_2},
            )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_upload_intents SET operation_state = 'open', "
                             "operation_revision = operation_revision + 1 WHERE id = :id"),
                        {"id": upload_id},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_upload_intents SET operation_revision = -1 WHERE id = :id"),
                        {"id": upload_id},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("INSERT INTO asset_versions "
                             "(id, project_id, asset_id, upload_intent_id, storage_provider, "
                             "object_version_reference, byte_size, detected_media_type, finalized_at) "
                             "VALUES (:id, :project, :asset, :upload, 'local-dev', 'wrong-reference', "
                             "16, 'audio/wav', CURRENT_TIMESTAMP)"),
                        {"id": uuid4(), "project": asset_project_id, "asset": asset_id, "upload": upload_id},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_upload_intents SET cleanup_state = 'confirmed', "
                             "cleanup_revision = cleanup_revision + 1 WHERE id = :id"),
                        {"id": upload_id},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    duplicate_intent = uuid4()
                    connection.execute(
                        text("""INSERT INTO asset_upload_intents
                            (id, project_id, asset_id, idempotency_key, request_fingerprint,
                             staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                            VALUES (:id, :project, :asset, 'key-duplicate-ref', :fingerprint,
                                    'opaque-staging-reference-duplicate', 1024,
                                    CURRENT_TIMESTAMP + INTERVAL '1 hour',
                                    CURRENT_TIMESTAMP + INTERVAL '25 hours')"""),
                        {"id": duplicate_intent, "project": asset_project_id, "asset": asset_id,
                         "fingerprint": "d" * 64},
                    )
                    _complete_upload_operation(
                        connection, intent_id=duplicate_intent,
                        object_reference="opaque-version-a", digest="d" * 64,
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    invalid_digest_intent = uuid4()
                    connection.execute(
                        text("""INSERT INTO asset_upload_intents
                            (id, project_id, asset_id, idempotency_key, request_fingerprint,
                             staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                            VALUES (:id, :project, :asset, 'key-invalid-digest', :fingerprint,
                                    'opaque-staging-reference-invalid', 1024,
                                    CURRENT_TIMESTAMP + INTERVAL '1 hour',
                                    CURRENT_TIMESTAMP + INTERVAL '25 hours')"""),
                        {"id": invalid_digest_intent, "project": asset_project_id, "asset": asset_id,
                         "fingerprint": "e" * 64},
                    )
                    connection.execute(
                        text("UPDATE asset_upload_intents SET received_bytes = 1, "
                             "observed_sha256_hex = :digest, transfer_completed_at = CURRENT_TIMESTAMP, "
                             "operation_revision = operation_revision + 1 WHERE id = :id"),
                        {"id": invalid_digest_intent, "digest": "z" * 64},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    unclaimed_intent = uuid4()
                    connection.execute(
                        text("""INSERT INTO asset_upload_intents
                            (id, project_id, asset_id, idempotency_key, request_fingerprint,
                             staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                            VALUES (:id, :project, :asset, 'key-unclaimed', :fingerprint,
                                    'opaque-staging-reference-unclaimed', 1024,
                                    CURRENT_TIMESTAMP + INTERVAL '1 hour',
                                    CURRENT_TIMESTAMP + INTERVAL '25 hours')"""),
                        {"id": unclaimed_intent, "project": asset_project_id, "asset": asset_id,
                         "fingerprint": "1" * 64},
                    )
                    connection.execute(
                        text("UPDATE asset_upload_intents SET operation_state = 'receiving', "
                             "operation_revision = operation_revision + 1 WHERE id = :id"),
                        {"id": unclaimed_intent},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    latest_intent = uuid4()
                    connection.execute(
                        text("""INSERT INTO asset_upload_intents
                            (id, project_id, asset_id, idempotency_key, request_fingerprint,
                             staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                            VALUES (:id, :project, :asset, 'key-latest', :fingerprint,
                                    'opaque-staging-reference-latest', 1024,
                                    CURRENT_TIMESTAMP + INTERVAL '1 hour',
                                    CURRENT_TIMESTAMP + INTERVAL '25 hours')"""),
                        {"id": latest_intent, "project": asset_project_id, "asset": asset_id,
                         "fingerprint": "f" * 64},
                    )
                    _complete_upload_operation(
                        connection, intent_id=latest_intent,
                        object_reference="latest", digest="f" * 64,
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_upload_intents SET cleanup_state = 'pending', "
                             "cleanup_revision = cleanup_revision + 1 WHERE id = :id"),
                        {"id": upload_id_2},
                    )
                    connection.execute(
                        text("UPDATE asset_upload_intents SET cleanup_state = 'confirmed', "
                             "cleanup_revision = cleanup_revision + 1 WHERE id = :id"),
                        {"id": upload_id_2},
                    )
            # Upload finalization may persist a quarantined version without
            # claiming that a media type has been detected.
            null_type_savepoint = connection.begin_nested()
            upload_id_3, version_id_3 = uuid4(), uuid4()
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                    VALUES (:id, :project, :asset, 'key-3', :fingerprint,
                            'opaque-staging-reference-3', 1024, CURRENT_TIMESTAMP + INTERVAL '1 hour',
                            CURRENT_TIMESTAMP + INTERVAL '25 hours')"""),
                {"id": upload_id_3, "project": asset_project_id, "asset": asset_id, "fingerprint": "c" * 64},
            )
            _complete_upload_operation(
                connection, intent_id=upload_id_3,
                object_reference="opaque-version-untyped", digest="c" * 64,
            )
            connection.execute(
                text("""INSERT INTO asset_versions
                    (id, project_id, asset_id, upload_intent_id, storage_provider,
                     object_version_reference, byte_size, detected_media_type, finalized_at)
                    VALUES (:id, :project, :asset, :upload, 'local-dev',
                            'opaque-version-untyped', 16, NULL, CURRENT_TIMESTAMP)"""),
                {"id": version_id_3, "project": asset_project_id, "asset": asset_id, "upload": upload_id_3},
            )
            assert connection.scalar(
                text("SELECT detected_media_type FROM asset_versions WHERE id = :id"),
                {"id": version_id_3},
            ) is None
            null_type_savepoint.rollback()
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_versions SET object_version_reference = 'opaque-version-b' WHERE id = :id"),
                        {"id": version_id},
                    )
            attempt_id, attempt_id_2, evidence_id = uuid4(), uuid4(), uuid4()
            for attempt_id_value, version_id_value, attempt_number in (
                (attempt_id, version_id, 1), (attempt_id_2, version_id_2, 1)
            ):
                connection.execute(
                    text("""INSERT INTO asset_validation_attempts
                        (id, project_id, asset_id, version_id, attempt_number, state,
                         profile_id, profile_version, validator_identity, validator_build, started_at, completed_at)
                        VALUES (:id, :project, :asset, :version, :number, 'succeeded',
                                'wav-narrow-v1', '1', 'test-validator', 'test-build', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""),
                    {
                        "id": attempt_id_value, "project": asset_project_id, "asset": asset_id,
                        "version": version_id_value, "number": attempt_number,
                    },
                )
            connection.execute(
                text("""INSERT INTO asset_validation_evidence
                    (id, project_id, asset_id, version_id, attempt_id, storage_provider,
                     object_version_reference, sha256_hex, observed_byte_count, profile_id,
                     profile_version, validator_identity, validator_build, evidence_payload, validated_at)
                    VALUES (:id, :project, :asset, :version, :attempt, 'local-dev',
                            'opaque-version-a', :digest, 16, 'wav-narrow-v1', '1',
                            'test-validator', 'test-build', CAST('{}' AS json), CURRENT_TIMESTAMP)"""),
                {
                    "id": evidence_id, "project": asset_project_id, "asset": asset_id,
                    "version": version_id, "attempt": attempt_id, "digest": "a" * 64,
                },
            )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("""INSERT INTO asset_validation_evidence
                            (id, project_id, asset_id, version_id, attempt_id, storage_provider,
                             object_version_reference, sha256_hex, observed_byte_count, profile_id,
                             profile_version, validator_identity, validator_build, evidence_payload, validated_at)
                            VALUES (:id, :project, :asset, :version, :attempt, 'local-dev',
                                    'opaque-version-second', :digest, 15, 'wav-narrow-v1', '1',
                                    'test-validator', 'test-build', CAST('{}' AS json), CURRENT_TIMESTAMP)"""),
                        {
                            "id": uuid4(), "project": asset_project_id, "asset": asset_id,
                            "version": version_id_2, "attempt": attempt_id_2, "digest": "b" * 64,
                        },
                    )
            connection.execute(
                text("UPDATE asset_versions SET current_attempt_id = :attempt, accepted_evidence_id = :evidence, validation_state = 'ready' WHERE id = :version"),
                {"attempt": attempt_id, "evidence": evidence_id, "version": version_id},
            )
            connection.execute(
                text("UPDATE assets SET current_ready_version_id = :version WHERE id = :asset"),
                {"version": version_id, "asset": asset_id},
            )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE assets SET current_ready_version_id = :version WHERE id = :asset"),
                        {"version": version_id_2, "asset": asset_id},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_versions SET validation_state = 'rejected' WHERE id = :version"),
                        {"version": version_id},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_versions SET accepted_evidence_id = :evidence, validation_state = 'ready' WHERE id = :version"),
                        {"evidence": evidence_id, "version": version_id_2},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text("DELETE FROM projects WHERE id = :id"), {"id": asset_project_id})
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text("DELETE FROM asset_validation_evidence WHERE id = :id"), {"id": evidence_id})
            connection.execute(
                text("INSERT INTO asset_evidence_revocations (evidence_id, revoked_by, reason_code) VALUES (:id, 'test-service', 'test-revocation')"),
                {"id": evidence_id},
            )
            assert connection.scalar(
                text("SELECT current_ready_version_id FROM assets WHERE id = :id"), {"id": asset_id}
            ) is None
            assert connection.execute(
                text("SELECT validation_state, accepted_evidence_id FROM asset_versions WHERE id = :id"),
                {"id": version_id},
            ).one() == ("revoked", None)

            # Existing Milestone 11 rows survive the additive migration and its downgrade.
            connection.commit()
            # Downgrading only the new additive revision preserves the Gate 2A/B
            # asset records, including the exact finalized upload/version binding.
            command.downgrade(config, "20261112_0003_asset_persistence")
            assert connection.scalar(text("SELECT count(*) FROM asset_upload_intents")) == 2
            assert connection.scalar(text("SELECT count(*) FROM asset_versions")) == 2
            assert connection.scalar(text("SELECT count(*) FROM asset_validation_evidence")) == 1
            assert connection.scalar(text("SELECT count(*) FROM assets")) == 1
            assert connection.execute(
                text("SELECT quota_limit_bytes, used_bytes, reserved_bytes FROM project_asset_usage "
                     "WHERE project_id = :project"),
                {"project": asset_project_id},
            ).one() == (100000, 16, 8)
            assert "operation_state" not in {column["name"] for column in inspect(connection).get_columns("asset_upload_intents")}
            assert inspect(connection).get_columns("asset_versions")[
                next(index for index, column in enumerate(inspect(connection).get_columns("asset_versions")) if column["name"] == "detected_media_type")
            ]["nullable"] is False
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261112_0003_asset_persistence"

            command.downgrade(config, "20261111_0002")
            assert not (asset_tables & set(inspect(connection).get_table_names()))
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version", "users", "external_identities", "projects", "project_creative_workspaces"
            }
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261111_0002"
            assert connection.scalar(text("SELECT count(*) FROM projects")) == prior_project_count + 1
            assert connection.scalar(text("SELECT count(*) FROM users")) == prior_user_count
            assert connection.scalar(text("SELECT count(*) FROM project_creative_workspaces")) == prior_workspace_count
            assert connection.scalar(
                text("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = current_schema()
                      AND p.proname IN ('spotloom_asset_version_identity_guard',
                        'spotloom_asset_detected_media_type_guard', 'spotloom_asset_upload_operation_guard',
                        'spotloom_asset_upload_recovery_guard',
                        'spotloom_asset_version_upload_binding_guard', 'spotloom_finalized_upload_has_version_guard',
                        'spotloom_asset_ready_pointer_guard', 'spotloom_retain_current_ready_version',
                        'spotloom_asset_attempt_identity_guard', 'spotloom_asset_evidence_guard',
                        'spotloom_asset_evidence_binding_guard', 'spotloom_asset_evidence_revocation_guard')""")
            ) == 0
            connection.commit()
    finally:
        config.attributes.pop("connection", None)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def test_durable_upload_operation_migration_preserves_gate2b_rows_on_disposable_postgresql() -> None:
    """Upgrade/downgrade 0004 around existing Gate 2A/B asset records."""
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_upload_operation_migration_{uuid4().hex}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            config.attributes["connection"] = connection
            command.upgrade(config, "20261112_0003_asset_persistence")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()

            owner_id, project_id, asset_id, intent_id, version_id = (uuid4() for _ in range(5))
            with connection.begin():
                connection.execute(
                    text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id}
                )
                _insert_project(connection, owner_id, "Pre-existing asset row")
                project_id = connection.scalar(text("SELECT id FROM projects WHERE name = 'Pre-existing asset row'"))
                connection.execute(
                    text("INSERT INTO project_asset_usage "
                         "(project_id, quota_limit_bytes, used_bytes, reserved_bytes) "
                         "VALUES (:project, 9000, 123, 45)"),
                    {"project": project_id},
                )
                connection.execute(
                    text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
                    {"id": asset_id, "project": project_id},
                )
                connection.execute(
                    text("""INSERT INTO asset_upload_intents
                        (id, project_id, asset_id, idempotency_key, request_fingerprint,
                         staging_reference, reserved_bytes, received_bytes, state, expires_at, finalized_at)
                        VALUES (:id, :project, :asset, 'migration-preserved', :fingerprint,
                                'opaque-existing-staging', 200, 123, 'finalized',
                                CURRENT_TIMESTAMP + INTERVAL '1 hour', CURRENT_TIMESTAMP)"""),
                    {"id": intent_id, "project": project_id, "asset": asset_id, "fingerprint": "a" * 64},
                )
                connection.execute(
                    text("""INSERT INTO asset_versions
                        (id, project_id, asset_id, upload_intent_id, storage_provider,
                         object_version_reference, byte_size, detected_media_type, finalized_at)
                        VALUES (:id, :project, :asset, :intent, 'local-dev', 'opaque-existing-version',
                                123, 'audio/wav', CURRENT_TIMESTAMP)"""),
                    {"id": version_id, "project": project_id, "asset": asset_id, "intent": intent_id},
                )

            command.upgrade(config, "20261112_0004_asset_upload_ops")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            assert connection.scalar(text("SELECT count(*) FROM asset_upload_intents")) == 1
            assert connection.scalar(text("SELECT count(*) FROM asset_versions")) == 1
            assert connection.execute(
                text("SELECT state, received_bytes FROM asset_upload_intents WHERE id = :id"),
                {"id": intent_id},
            ).one() == ("finalized", 123)
            assert connection.execute(
                text("SELECT object_version_reference, byte_size, detected_media_type "
                     "FROM asset_versions WHERE id = :id"),
                {"id": version_id},
            ).one() == ("opaque-existing-version", 123, "audio/wav")
            assert connection.execute(
                text("SELECT quota_limit_bytes, used_bytes, reserved_bytes "
                     "FROM project_asset_usage WHERE project_id = :id"),
                {"id": project_id},
            ).one() == (9000, 123, 45)
            assert connection.scalar(
                text("SELECT operation_state FROM asset_upload_intents WHERE id = :id"),
                {"id": intent_id},
            ) == "open"  # Storage operation has not been proven by the old accounting state.

            command.downgrade(config, "20261112_0003_asset_persistence")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            assert connection.scalar(text("SELECT count(*) FROM asset_upload_intents")) == 1
            assert connection.scalar(text("SELECT count(*) FROM asset_versions")) == 1
            assert connection.scalar(
                text("SELECT count(*) FROM project_asset_usage WHERE project_id = :id "
                     "AND quota_limit_bytes = 9000 AND used_bytes = 123 AND reserved_bytes = 45"),
                {"id": project_id},
            ) == 1
            assert "operation_state" not in {
                column["name"] for column in inspect(connection).get_columns("asset_upload_intents")
            }
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261112_0003_asset_persistence"
    finally:
        config.attributes.pop("connection", None)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def test_upload_recovery_migration_backfills_legacy_states_and_refuses_unsafe_downgrade() -> None:
    """Backfill 0004 intent states without losing active or ambiguous recovery work."""
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_upload_recovery_backfill_{uuid4().hex}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            config.attributes["connection"] = connection
            command.upgrade(config, "20261112_0004_asset_upload_ops")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()

            owner_id, project_id, asset_id = uuid4(), uuid4(), uuid4()
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
            _insert_project(connection, owner_id, "Recovery migration fixture")
            project_id = connection.scalar(
                text("SELECT id FROM projects WHERE name = 'Recovery migration fixture'")
            )
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
                {"id": asset_id, "project": project_id},
            )

            def insert_intent(key: str) -> UUID:
                intent_id = uuid4()
                connection.execute(
                    text("""INSERT INTO asset_upload_intents
                        (id, project_id, asset_id, idempotency_key, request_fingerprint,
                         staging_reference, reserved_bytes, expires_at)
                        VALUES (:id, :project, :asset, :key, :fingerprint, :staging, 100,
                                clock_timestamp() + INTERVAL '1 hour')"""),
                    {
                        "id": intent_id, "project": project_id, "asset": asset_id,
                        "key": key, "fingerprint": (key.encode().hex() * 32)[:64],
                        "staging": f"staging-{key}",
                    },
                )
                return intent_id

            open_id = insert_intent("recovery-open")

            expired_id = insert_intent("recovery-expired")
            connection.execute(
                text("UPDATE asset_upload_intents SET operation_state = 'expired', "
                     "operation_revision = operation_revision + 1 WHERE id = :id"),
                {"id": expired_id},
            )

            cancelled_id = insert_intent("recovery-cancelled")
            connection.execute(
                text("UPDATE asset_upload_intents SET operation_state = 'cancelled', "
                     "operation_revision = operation_revision + 1 WHERE id = :id"),
                {"id": cancelled_id},
            )

            receiving_id = insert_intent("recovery-receiving")
            receiving_token = uuid4()
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp() - INTERVAL '2 minutes',
                    operation_lease_expires_at = clock_timestamp() - INTERVAL '1 minute'
                    WHERE id = :id"""),
                {"id": receiving_id, "token": receiving_token},
            )
            connection.execute(
                text("UPDATE asset_upload_intents SET cleanup_state = 'pending', "
                     "cleanup_revision = cleanup_revision + 1 WHERE id = :id"),
                {"id": receiving_id},
            )

            uploaded_id = insert_intent("recovery-uploaded")
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp() - INTERVAL '2 minutes',
                    operation_lease_expires_at = clock_timestamp() - INTERVAL '1 minute'
                    WHERE id = :id"""),
                {"id": uploaded_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = 12,
                    observed_sha256_hex = :digest, transfer_completed_at = clock_timestamp()
                    WHERE id = :id"""),
                {"id": uploaded_id, "digest": "a" * 64},
            )

            finalizing_id = insert_intent("recovery-finalizing")
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp() - INTERVAL '2 minutes',
                    operation_lease_expires_at = clock_timestamp() - INTERVAL '1 minute'
                    WHERE id = :id"""),
                {"id": finalizing_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = 12,
                    observed_sha256_hex = :digest, transfer_completed_at = clock_timestamp()
                    WHERE id = :id"""),
                {"id": finalizing_id, "digest": "b" * 64},
            )
            old_finalizing_token = uuid4()
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'finalizing', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp() - INTERVAL '2 minutes',
                    operation_lease_expires_at = clock_timestamp() - INTERVAL '1 minute',
                    final_storage_provider = 'local-dev', final_object_version_reference = 'legacy-finalizing-v1',
                    finalization_started_at = transfer_completed_at
                    WHERE id = :id"""),
                {"id": finalizing_id, "token": old_finalizing_token},
            )

            failed_id = insert_intent("recovery-failed-ambiguous")
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp() - INTERVAL '2 minutes',
                    operation_lease_expires_at = clock_timestamp() - INTERVAL '1 minute'
                    WHERE id = :id"""),
                {"id": failed_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = 12,
                    observed_sha256_hex = :digest, transfer_completed_at = clock_timestamp()
                    WHERE id = :id"""),
                {"id": failed_id, "digest": "c" * 64},
            )
            failed_token = uuid4()
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'finalizing', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp() - INTERVAL '2 minutes',
                    operation_lease_expires_at = clock_timestamp() - INTERVAL '1 minute',
                    final_storage_provider = 'local-dev', final_object_version_reference = 'legacy-failed-v1',
                    finalization_started_at = transfer_completed_at
                    WHERE id = :id"""),
                {"id": failed_id, "token": failed_token},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'failed', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL WHERE id = :id"""),
                {"id": failed_id},
            )
            connection.commit()

            command.upgrade(config, "head")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0008_cleanup_receipt"
            rows = {
                row[0]: row[1:]
                for row in connection.execute(text("""SELECT id, operation_state, recovery_state,
                    recovery_attempt_count, recovery_claim_generation, recovery_claim_token,
                    operation_claim_token, cleanup_state FROM asset_upload_intents"""))
            }
            assert rows[open_id] == ("open", "not_required", 0, 0, None, None, "not_required")
            assert rows[expired_id] == ("expired", "not_required", 0, 0, None, None, "not_required")
            assert rows[cancelled_id] == ("cancelled", "not_required", 0, 0, None, None, "not_required")
            assert rows[receiving_id] == (
                "receiving", "not_required", 0, 0, None, receiving_token, "pending"
            )
            assert rows[uploaded_id] == ("uploaded", "pending", 0, 0, None, None, "not_required")
            assert rows[finalizing_id] == (
                "finalizing", "claimed", 1, 2, old_finalizing_token, None, "not_required"
            )
            assert rows[failed_id] == (
                "failed", "manual", 0, 0, None, None, "not_required"
            )
            assert connection.scalar(
                text("SELECT recovery_deadline_at = expires_at + INTERVAL '24 hours' "
                     "FROM asset_upload_intents WHERE id = :id"),
                {"id": open_id},
            ) is True
            assert connection.scalar(
                text("SELECT observed_sha256_hex FROM asset_upload_intents WHERE id = :id"),
                {"id": receiving_id},
            ) is None

            with pytest.raises(DBAPIError):
                command.downgrade(config, "20261112_0004_asset_upload_ops")
            connection.rollback()
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0008_cleanup_receipt"
    finally:
        config.attributes.pop("connection", None)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def test_upload_recovery_migration_refuses_legacy_transfer_completed_after_expiry() -> None:
    """The migration must preserve history and refuse incompatible legacy data."""
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_recovery_expired_transfer_{uuid4().hex}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    intent_id = uuid4()
    project_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            config.attributes["connection"] = connection
            command.upgrade(config, "20261112_0004_asset_upload_ops")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()

            owner_id, asset_id = uuid4(), uuid4()
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
            _insert_project(connection, owner_id, "Expired transfer migration fixture")
            project_id = connection.scalar(
                text("SELECT id FROM projects WHERE name = 'Expired transfer migration fixture'")
            )
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
                {"id": asset_id, "project": project_id},
            )
            connection.execute(
                text("""INSERT INTO project_asset_usage
                    (project_id, quota_limit_bytes, used_bytes, reserved_bytes)
                    VALUES (:project, 1000, 0, 100)"""),
                {"project": project_id},
            )
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, expires_at)
                    VALUES (:id, :project, :asset, 'legacy-expired-completion', :fingerprint,
                            'legacy-staging', 100, clock_timestamp() + INTERVAL '1 hour')"""),
                {"id": intent_id, "project": project_id, "asset": asset_id,
                 "fingerprint": "c" * 64},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                    operation_lease_expires_at = expires_at - INTERVAL '1 second'
                    WHERE id = :id"""),
                {"id": intent_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = 16,
                    observed_sha256_hex = :digest,
                    transfer_completed_at = expires_at + INTERVAL '1 second'
                    WHERE id = :id"""),
                {"id": intent_id, "digest": "c" * 64},
            )
            connection.commit()

            with pytest.raises(DBAPIError) as raised:
                command.upgrade(config, "head")
            assert "transfer_completed_at > expires_at" in str(raised.value.orig)
            connection.rollback()
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()

            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261112_0004_asset_upload_ops"
            assert "recovery_deadline_at" not in {
                column["name"] for column in inspect(connection).get_columns("asset_upload_intents")
            }
            assert connection.scalar(
                text("SELECT transfer_completed_at > expires_at FROM asset_upload_intents WHERE id = :id"),
                {"id": intent_id},
            ) is True
            assert connection.scalar(
                text("SELECT reserved_bytes FROM project_asset_usage WHERE project_id = :id"),
                {"id": project_id},
            ) == 100
    finally:
        config.attributes.pop("connection", None)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def test_recovery_lease_expiry_deadline_renewal_and_attempt_bounds_on_disposable_postgresql() -> None:
    """Exercise the recovery trigger using only a disposable isolated schema."""
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_recovery_lease_test_{uuid4().hex}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            owner_id, project_id, asset_id, intent_id = (uuid4() for _ in range(4))
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
            _insert_project(connection, owner_id, "Recovery lease test")
            project_id = connection.scalar(text("SELECT id FROM projects WHERE name = 'Recovery lease test'"))
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
                {"id": asset_id, "project": project_id},
            )
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                    VALUES (:id, :project, :asset, 'recovery-lease', :fingerprint,
                            'recovery-staging', 100, clock_timestamp() + INTERVAL '3 seconds',
                            clock_timestamp() + INTERVAL '1 hour')"""),
                {"id": intent_id, "project": project_id, "asset": asset_id, "fingerprint": "d" * 64},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                    operation_lease_expires_at = expires_at - INTERVAL '100 milliseconds'
                    WHERE id = :id"""),
                {"id": intent_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = 16,
                    observed_sha256_hex = :digest, transfer_completed_at = clock_timestamp(),
                    recovery_state = 'pending', recovery_revision = recovery_revision + 1
                    WHERE id = :id"""),
                {"id": intent_id, "digest": "e" * 64},
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_upload_intents SET expires_at = expires_at + INTERVAL '1 second' "
                             "WHERE id = :id"), {"id": intent_id},
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_upload_intents SET recovery_deadline_at = "
                             "recovery_deadline_at + INTERVAL '1 second' WHERE id = :id"),
                        {"id": intent_id},
                    )

            connection.execute(text("SELECT pg_sleep(3.1)"))
            first_token = uuid4()
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'finalizing', operation_revision = operation_revision + 1,
                    recovery_state = 'claimed', recovery_revision = recovery_revision + 1,
                    recovery_claim_generation = recovery_claim_generation + 1,
                    recovery_claim_token = :token, recovery_attempt_count = recovery_attempt_count + 1,
                    recovery_lease_expires_at = clock_timestamp() + INTERVAL '1 second',
                    final_storage_provider = 'local-dev', final_object_version_reference = 'recovery-exact-v1',
                    finalization_started_at = clock_timestamp()
                    WHERE id = :id AND operation_state = 'uploaded' AND recovery_state = 'pending'"""),
                {"id": intent_id, "token": first_token},
            )
            assert connection.execute(
                text("SELECT recovery_attempt_count, recovery_claim_generation "
                     "FROM asset_upload_intents WHERE id = :id"), {"id": intent_id},
            ).one() == (1, 1)

            # The database allows server-side recovery after upload expiry, but
            # caps an individual claim and renewal at five minutes.
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("""UPDATE asset_upload_intents SET
                            recovery_revision = recovery_revision + 1,
                            recovery_claim_generation = recovery_claim_generation + 1,
                            recovery_claim_token = :replacement,
                            recovery_attempt_count = recovery_attempt_count + 1,
                            recovery_lease_expires_at = clock_timestamp() + INTERVAL '1 minute'
                            WHERE id = :id"""),
                        {"id": intent_id, "replacement": uuid4()},
                    )
            original_claim = connection.execute(
                text("""SELECT recovery_claim_token, recovery_claim_generation,
                    recovery_attempt_count, recovery_revision,
                    recovery_lease_expires_at > clock_timestamp()
                    FROM asset_upload_intents WHERE id = :id"""),
                {"id": intent_id},
            ).one()
            assert original_claim == (first_token, 1, 1, 2, True)

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE asset_upload_intents SET "
                             "recovery_lease_expires_at = clock_timestamp() + INTERVAL '5 minutes 1 second', "
                             "recovery_revision = recovery_revision + 1 WHERE id = :id"),
                        {"id": intent_id},
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("""UPDATE asset_upload_intents SET
                            recovery_state = 'pending', recovery_revision = recovery_revision + 1,
                            recovery_claim_token = NULL, recovery_claimed_at = NULL,
                            recovery_lease_issued_at = NULL, recovery_lease_expires_at = NULL
                            WHERE id = :id AND recovery_claim_token = :token"""),
                        {"id": intent_id, "token": first_token},
                    )
            connection.execute(
                text("UPDATE asset_upload_intents SET "
                     "recovery_lease_expires_at = clock_timestamp() + INTERVAL '100 milliseconds', "
                     "recovery_revision = recovery_revision + 1 WHERE id = :id"),
                {"id": intent_id},
            )
            assert connection.scalar(
                text("SELECT recovery_attempt_count FROM asset_upload_intents WHERE id = :id"),
                {"id": intent_id},
            ) == 1
            connection.execute(text("SELECT pg_sleep(0.15)"))

            current_token = first_token
            for expected_attempt in range(2, 11):
                replacement = uuid4()
                changed = connection.execute(
                    text("""UPDATE asset_upload_intents SET
                        recovery_revision = recovery_revision + 1,
                        recovery_claim_generation = recovery_claim_generation + 1,
                        recovery_claim_token = :new_token,
                        recovery_attempt_count = recovery_attempt_count + 1,
                        recovery_lease_expires_at = clock_timestamp() + INTERVAL '100 milliseconds'
                        WHERE id = :id AND recovery_state = 'claimed'
                          AND recovery_claim_token = :old_token
                          AND recovery_lease_expires_at <= clock_timestamp()"""),
                    {"id": intent_id, "old_token": current_token, "new_token": replacement},
                )
                assert changed.rowcount == 1
                assert connection.scalar(
                    text("SELECT recovery_attempt_count FROM asset_upload_intents WHERE id = :id"),
                    {"id": intent_id},
                ) == expected_attempt
                current_token = replacement
                if expected_attempt < 10:
                    connection.execute(text("SELECT pg_sleep(0.15)"))

            stale_update = connection.execute(
                text("""UPDATE asset_upload_intents SET recovery_state = 'manual',
                    recovery_revision = recovery_revision + 1
                    WHERE id = :id AND recovery_claim_token = :stale_token
                      AND recovery_claim_generation = 1"""),
                {"id": intent_id, "stale_token": first_token},
            )
            assert stale_update.rowcount == 0
            connection.execute(text("SELECT pg_sleep(0.15)"))
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("""UPDATE asset_upload_intents SET
                            recovery_revision = recovery_revision + 1,
                            recovery_claim_generation = recovery_claim_generation + 1,
                            recovery_claim_token = :token, recovery_attempt_count = recovery_attempt_count + 1,
                            recovery_lease_expires_at = clock_timestamp() + INTERVAL '1 minute'
                            WHERE id = :id"""),
                        {"id": intent_id, "token": uuid4()},
                    )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    recovery_state = 'exhausted', recovery_revision = recovery_revision + 1,
                    recovery_claim_token = NULL, recovery_claimed_at = NULL,
                    recovery_lease_issued_at = NULL, recovery_lease_expires_at = NULL,
                    recovery_outcome_code = 'attempts_exhausted'
                    WHERE id = :id AND recovery_claim_token = :token"""),
                {"id": intent_id, "token": current_token},
            )
            assert connection.execute(
                text("SELECT recovery_state, recovery_attempt_count, recovery_finished_at IS NOT NULL "
                     "FROM asset_upload_intents WHERE id = :id"), {"id": intent_id},
            ).one() == ("exhausted", 10, True)

            # A valid transfer whose fixed recovery deadline has elapsed is no
            # longer eligible for an automatic claim.
            deadline_elapsed_id = uuid4()
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, created_at, expires_at, recovery_deadline_at)
                    VALUES (:id, :project, :asset, 'recovery-deadline-elapsed', :fingerprint,
                            'deadline-staging', 100, clock_timestamp() - INTERVAL '1 second',
                            clock_timestamp() + INTERVAL '2 seconds',
                            clock_timestamp() + INTERVAL '3 seconds')"""),
                {"id": deadline_elapsed_id, "project": project_id,
                 "asset": asset_id, "fingerprint": "a" * 64},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                    operation_lease_expires_at = expires_at - INTERVAL '100 milliseconds'
                    WHERE id = :id"""),
                {"id": deadline_elapsed_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL,
                    received_bytes = 16, observed_sha256_hex = :digest,
                    transfer_completed_at = clock_timestamp(),
                    recovery_state = 'pending', recovery_revision = recovery_revision + 1
                    WHERE id = :id"""),
                {"id": deadline_elapsed_id, "digest": "b" * 64},
            )
            connection.execute(text("SELECT pg_sleep(3.1)"))
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("""UPDATE asset_upload_intents SET
                            operation_state = 'finalizing', operation_revision = operation_revision + 1,
                            recovery_state = 'claimed', recovery_revision = recovery_revision + 1,
                            recovery_claim_generation = recovery_claim_generation + 1,
                            recovery_claim_token = :token, recovery_attempt_count = recovery_attempt_count + 1,
                            recovery_lease_expires_at = clock_timestamp() + INTERVAL '1 minute',
                            final_storage_provider = 'local-dev',
                            final_object_version_reference = 'deadline-expired-final-v1',
                            finalization_started_at = clock_timestamp()
                            WHERE id = :id AND recovery_state = 'pending'"""),
                        {"id": deadline_elapsed_id, "token": uuid4()},
                    )

            # A complete transfer may be recovered after upload expiry, but an
            # incomplete expired intent cannot acquire a receiving claim.
            expired_id = uuid4()
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                    VALUES (:id, :project, :asset, 'expired-byte-rejection', :fingerprint,
                            'expired-staging', 100, clock_timestamp() - INTERVAL '1 second',
                            clock_timestamp() + INTERVAL '1 hour')"""),
                {"id": expired_id, "project": project_id, "asset": asset_id, "fingerprint": "f" * 64},
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("""UPDATE asset_upload_intents SET
                            operation_state = 'receiving', operation_revision = operation_revision + 1,
                            operation_claim_generation = operation_claim_generation + 1,
                            operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                            operation_lease_expires_at = expires_at - INTERVAL '100 milliseconds'
                            WHERE id = :id"""),
                        {"id": expired_id, "token": uuid4()},
                    )
    finally:
        config.attributes.pop("connection", None)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def test_concurrent_recovery_claims_have_one_winner_on_disposable_postgresql() -> None:
    """A row-lock/CAS recovery claim must not be granted twice."""
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_recovery_claim_race_{uuid4().hex}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            owner_id, project_id, asset_id, intent_id = (uuid4() for _ in range(4))
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
            _insert_project(connection, owner_id, "Recovery race test")
            project_id = connection.scalar(text("SELECT id FROM projects WHERE name = 'Recovery race test'"))
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
                {"id": asset_id, "project": project_id},
            )
            connection.execute(
                text("""INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                         staging_reference, reserved_bytes, expires_at, recovery_deadline_at)
                    VALUES (:id, :project, :asset, 'recovery-race', :fingerprint,
                                'recovery-race-staging', 100, clock_timestamp() + INTERVAL '1 hour',
                                clock_timestamp() + INTERVAL '20 hours')"""),
                {"id": intent_id, "project": project_id, "asset": asset_id, "fingerprint": "9" * 64},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                    operation_lease_expires_at = expires_at - INTERVAL '1 minute'
                    WHERE id = :id"""),
                {"id": intent_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = 16,
                    observed_sha256_hex = :digest, transfer_completed_at = clock_timestamp(),
                    recovery_state = 'pending', recovery_revision = recovery_revision + 1
                    WHERE id = :id"""),
                {"id": intent_id, "digest": "9" * 64},
            )
            connection.commit()

        barrier = Barrier(2)

        def claim_once(token):
            with engine.connect() as worker:
                worker.exec_driver_sql(f'SET search_path TO "{schema}"')
                worker.commit()
                barrier.wait(timeout=10)
                with worker.begin():
                    result = worker.execute(
                        text("""UPDATE asset_upload_intents SET
                            operation_state = 'finalizing', operation_revision = operation_revision + 1,
                            recovery_state = 'claimed', recovery_revision = recovery_revision + 1,
                            recovery_claim_generation = recovery_claim_generation + 1,
                            recovery_claim_token = :token, recovery_attempt_count = recovery_attempt_count + 1,
                            recovery_lease_expires_at = clock_timestamp() + INTERVAL '4 minutes',
                            final_storage_provider = 'local-dev',
                            final_object_version_reference = 'recovery-race-final-v1',
                            finalization_started_at = clock_timestamp()
                            WHERE id = :id AND operation_state = 'uploaded'
                              AND recovery_state = 'pending' AND recovery_revision = 1"""),
                        {"id": intent_id, "token": token},
                    )
                    return result.rowcount

        tokens = (uuid4(), uuid4())
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(claim_once, tokens))
        assert sorted(outcomes) == [0, 1]
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            row = connection.execute(
                text("SELECT recovery_attempt_count, recovery_claim_generation, recovery_claim_token "
                     "FROM asset_upload_intents WHERE id = :id"), {"id": intent_id},
            ).one()
            assert row[0:2] == (1, 1)
            assert row[2] in tokens
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
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

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


def test_asset_upload_intent_quota_concurrency_on_disposable_spotloom_test(tmp_path: Path) -> None:
    """Verify per-project row locking serializes idempotency and quota races."""
    try:
        database_config = _local_disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database on port 5432.")

    admin_engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_asset_service_{uuid4().hex}"
    worker_engine = None
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

        backend_dir = Path(__file__).resolve().parents[1]
        alembic_config = Config(str(backend_dir / "alembic.ini"))
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()

        worker_engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)

        @event.listens_for(worker_engine, "connect")
        def _set_asset_schema(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.close()

        factory = sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        config = AssetServiceConfig(1000, timedelta(hours=1))
        storage = LocalPrivateAssetStorage(LocalAssetStorageConfig(tmp_path / "private-assets"))
        with factory.begin() as session:
            user = User()
            session.add(user)
            session.flush()
            project = Project(owner_user_id=user.id, name="Asset concurrency")
            session.add(project)
            session.flush()
            owner_id, project_id = user.id, project.id
            asset = AssetService(session, config).create_asset(
                project_id=project_id, owner_user_id=owner_id, kind="audio"
            )
            assert asset is not None
            asset_id = asset.id

        start = Barrier(2)

        def create_identical_intent(_index: int):
            with factory.begin() as session:
                start.wait(timeout=10)
                return AssetService(
                    session, config, clock=lambda: now, storage=storage
                ).create_upload_intent(
                    project_id=project_id,
                    asset_id=asset_id,
                    owner_user_id=owner_id,
                    idempotency_key="same-request",
                    reserved_bytes=300,
                    lifetime=timedelta(minutes=30),
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            same_key_results = list(executor.map(create_identical_intent, range(2)))
        assert same_key_results[0].intent.id == same_key_results[1].intent.id
        assert sorted(result.created for result in same_key_results) == [False, True]

        race_barrier = Barrier(2)

        def reserve_race(key: str):
            try:
                with factory.begin() as session:
                    race_barrier.wait(timeout=10)
                    result = AssetService(
                        session, config, clock=lambda: now, storage=storage
                    ).create_upload_intent(
                        project_id=project_id,
                        asset_id=asset_id,
                        owner_user_id=owner_id,
                        idempotency_key=key,
                        reserved_bytes=400,
                        lifetime=timedelta(minutes=30),
                    )
                    return result is not None
            except AssetQuotaExceeded:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            race_results = list(executor.map(reserve_race, ("race-a", "race-b")))
        assert sorted(race_results) == [False, True]

        with factory.begin() as session:
            usage = session.get(ProjectAssetUsage, project_id)
            assert usage is not None
            assert (usage.used_bytes, usage.reserved_bytes) == (0, 700)
            main_intent = session.scalar(
                select(AssetUploadIntent).where(
                    AssetUploadIntent.project_id == project_id,
                    AssetUploadIntent.idempotency_key == "same-request",
                )
            )
            service = AssetService(session, config, clock=lambda: now, storage=storage)
            finalized = service.reconcile_finalized_upload(
                project_id=project_id,
                asset_id=asset_id,
                intent_id=main_intent.id,
                actual_bytes=250,
            )
            assert finalized.received_bytes == 250
            assert (usage.used_bytes, usage.reserved_bytes) == (250, 400)
            assert service.reconcile_finalized_upload(
                project_id=project_id,
                asset_id=asset_id,
                intent_id=main_intent.id,
                actual_bytes=250,
            ) is finalized

            expiring = session.scalar(
                select(AssetUploadIntent).where(
                    AssetUploadIntent.project_id == project_id,
                    AssetUploadIntent.idempotency_key == "race-a",
                )
            ) or session.scalar(
                select(AssetUploadIntent).where(
                    AssetUploadIntent.project_id == project_id,
                    AssetUploadIntent.idempotency_key == "race-b",
                )
            )
            late_service = AssetService(
                session,
                config,
                clock=lambda: expiring.expires_at + timedelta(seconds=1),
                storage=storage,
            )
            expiring_id = expiring.id
            expiring_at = expiring.expires_at
            temp_reference = TemporaryObjectReference(
                expiring.staging_reference, project_id, expiring.id
            )
            expired_intent = late_service.expire_upload_intent(
                project_id=project_id, asset_id=asset_id, intent_id=expiring.id
            )
            assert expired_intent is not None and expired_intent.state == "expired"
            assert usage.reserved_bytes == 400

        # Do storage I/O outside database transactions and row locks.
        storage.create_temporary_object(temp_reference)
        storage.write_temporary_object(temp_reference, [b"expired transfer"], max_bytes=128)
        claim_token = uuid4()
        with factory.begin() as session:
            session.execute(text("UPDATE asset_upload_intents SET cleanup_state = 'pending', "
                                 "cleanup_revision = cleanup_revision + 1 WHERE id = :id"),
                            {"id": expiring_id})
            session.execute(text("UPDATE asset_upload_intents SET cleanup_state = 'claimed', "
                                 "cleanup_revision = cleanup_revision + 1, "
                                 "cleanup_claim_generation = cleanup_claim_generation + 1, "
                                 "cleanup_claim_token = :token, cleanup_claimed_at = clock_timestamp(), "
                                 "cleanup_lease_expires_at = clock_timestamp() + INTERVAL '1 minute' "
                                 "WHERE id = :id"),
                            {"id": expiring_id, "token": claim_token})
            claim_revision = session.scalar(
                text("SELECT cleanup_revision FROM asset_upload_intents WHERE id = :id"),
                {"id": expiring_id},
            )
            assert claim_revision is not None
            claim_generation = session.scalar(
                text("SELECT cleanup_claim_generation FROM asset_upload_intents WHERE id = :id"),
                {"id": expiring_id},
            )
            assert claim_token is not None and claim_generation == 1
        confirmation = storage.delete_temporary_object(
            temp_reference, project_id=project_id, asset_id=asset_id,
            intent_id=expiring_id, claim_token=claim_token,
            cleanup_revision=claim_revision, cleanup_generation=claim_generation,
        )
        with factory.begin() as session:
            session.execute(text("UPDATE asset_upload_intents SET cleanup_state = 'confirmed', "
                                 "cleanup_revision = cleanup_revision + 1, cleanup_claim_token = NULL, "
                                 "cleanup_claimed_at = NULL, cleanup_lease_expires_at = NULL, "
                                 "cleanup_confirmed_at = clock_timestamp() WHERE id = :id"),
                            {"id": expiring_id})
            expiring = session.get(AssetUploadIntent, expiring_id)
            session.refresh(expiring)
            assert expiring.state == "expired"
            assert expiring.cleanup_completed_claim_token == claim_token
            assert expiring.cleanup_completed_claim_generation == claim_generation
            assert expiring.cleanup_completed_revision == claim_revision
            late_service = AssetService(
                session, config,
                clock=lambda: expiring_at + timedelta(seconds=1),
                storage=storage,
            )
            late_service.release_reservation_after_cleanup(
                project_id=project_id,
                asset_id=asset_id,
                intent_id=expiring_id,
                confirmation=confirmation,
            )
            usage = session.get(ProjectAssetUsage, project_id)
            assert usage.reserved_bytes == 0
            assert usage.used_bytes == 250

        with admin_engine.connect() as migration_connection:
            migration_connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            migration_connection.commit()
            alembic_config.attributes["connection"] = migration_connection
            with pytest.raises(RuntimeError, match="durable cleanup claim data exists"):
                command.downgrade(alembic_config, "20261112_0007_asset_retry")
            migration_connection.rollback()
            migration_connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            migration_connection.commit()
            assert migration_connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0008_cleanup_receipt"
            migration_connection.commit()
    finally:
        if worker_engine is not None:
            worker_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()
