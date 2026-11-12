from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import adforge_renderer.asset_recovery_repository as recovery_repository
from adforge_renderer.asset_recovery_coordinator import (
    LOCAL_STORAGE_PROVIDER,
    LocalUploadRecoveryCoordinator,
    RecoveryOutcomeKind,
)
from adforge_renderer.asset_service import AssetServiceConfig
from adforge_renderer.database import DatabaseConfig
from adforge_renderer.local_asset_storage import (
    LocalAssetStorageConfig,
    LocalPrivateAssetStorage,
)


def _isolated_test_config() -> DatabaseConfig | None:
    raw_url = os.environ.get("SPOTLOOM_TEST_DATABASE_URL")
    if not raw_url:
        return None
    parsed = make_url(raw_url)
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in {"localhost", "127.0.0.1", "::1"}
        or parsed.port != 5432
        or parsed.database != "spotloom_test"
    ):
        raise ValueError("Asset recovery integration tests require loopback spotloom_test on port 5432.")
    return DatabaseConfig.from_url(raw_url)


def test_local_recovery_coordinator_finalizes_and_accounts_once_on_disposable_postgresql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_config = _isolated_test_config()
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to loopback spotloom_test on port 5432.")

    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_recovery_coordinator_{uuid4().hex}"
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    connection = None
    try:
        with engine.begin() as setup:
            setup.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection = engine.connect()
        connection.exec_driver_sql(f'SET search_path TO "{schema}"')
        connection.commit()
        alembic_config.attributes["connection"] = connection
        command.upgrade(alembic_config, "head")
        connection.exec_driver_sql(f'SET search_path TO "{schema}"')
        connection.commit()

        owner_id, project_id, asset_id, intent_id = (uuid4() for _ in range(4))
        payload = b"bounded recovery coordinator verification bytes"
        digest = hashlib.sha256(payload).hexdigest()
        storage = LocalPrivateAssetStorage(
            LocalAssetStorageConfig(tmp_path / "private-recovery-store")
        )
        staging = storage.allocate_temporary_reference(
            project_id=project_id, operation_id=intent_id
        )
        storage.create_temporary_object(staging)
        observed = storage.write_temporary_object(staging, [payload], max_bytes=256)
        assert observed.byte_size == len(payload)

        with connection.begin():
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
            connection.execute(
                text("INSERT INTO projects (id, owner_user_id, name) VALUES (:id, :owner, 'Recovery')"),
                {"id": project_id, "owner": owner_id},
            )
            connection.execute(
                text("INSERT INTO project_asset_usage "
                     "(project_id, quota_limit_bytes, used_bytes, reserved_bytes) "
                     "VALUES (:project, 1000, 0, 100)"),
                {"project": project_id},
            )
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) "
                     "VALUES (:id, :project, 'audio')"),
                {"id": asset_id, "project": project_id},
            )
            connection.execute(
                text("""WITH times AS (SELECT clock_timestamp() AS base_time)
                    INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, created_at, expires_at,
                     recovery_deadline_at)
                    SELECT :id, :project, :asset, 'coordinator-test', :fingerprint,
                     :staging, 100, base_time - INTERVAL '2 minutes',
                     base_time + INTERVAL '1 hour',
                     base_time + INTERVAL '25 hours' FROM times"""),
                {
                    "id": intent_id,
                    "project": project_id,
                    "asset": asset_id,
                    "fingerprint": "a" * 64,
                    "staging": staging.value,
                },
            )
            operation_token = uuid4()
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                    operation_lease_expires_at = clock_timestamp() + INTERVAL '30 minutes'
                    WHERE id = :id"""),
                {"id": intent_id, "token": operation_token},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = :byte_count,
                    observed_sha256_hex = :digest,
                    transfer_completed_at = clock_timestamp() - INTERVAL '1 minute',
                    recovery_state = 'pending', recovery_revision = recovery_revision + 1
                    WHERE id = :id"""),
                {"id": intent_id, "byte_count": len(payload), "digest": digest},
            )

        factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
        # Fast-forward only the test's cadence gate; PostgreSQL still validates
        # a live, bounded lease renewal and the coordinator uses the renewed fence.
        monkeypatch.setattr(
            recovery_repository, "_RENEWAL_CADENCE_SQL", text("INTERVAL '0 seconds'")
        )
        monotonic_values = iter((0.0, 61.0))
        coordinator = LocalUploadRecoveryCoordinator(
            factory,
            AssetServiceConfig(1000, timedelta(hours=2)),
            storage,
            monotonic_clock=lambda: next(monotonic_values),
        )
        outcome = coordinator.run_once()
        assert outcome.kind is RecoveryOutcomeKind.COMPLETED
        assert outcome.intent_id == intent_id

        assert storage.inspect_temporary_object(staging).complete is True
        version_row = connection.execute(
            text("SELECT storage_provider, byte_size, validation_state "
                 "FROM asset_versions WHERE upload_intent_id = :id"),
            {"id": intent_id},
        ).one()
        assert version_row == (LOCAL_STORAGE_PROVIDER, len(payload), "quarantined")
        accounting = connection.execute(
            text("SELECT used_bytes, reserved_bytes FROM project_asset_usage "
                 "WHERE project_id = :project"),
            {"project": project_id},
        ).one()
        assert accounting == (len(payload), 0)
        operation = connection.execute(
            text("SELECT operation_state, recovery_state, state, recovery_revision "
                 "FROM asset_upload_intents "
                 "WHERE id = :id"),
            {"id": intent_id},
        ).one()
        assert operation == ("finalized", "completed", "finalized", 4)

        # A completed operation is no longer claimable and its quota/version
        # state remains exactly once after another coordinator invocation.
        assert coordinator.run_once().kind is RecoveryOutcomeKind.NOT_CLAIMABLE
        assert connection.scalar(
            text("SELECT count(*) FROM asset_versions WHERE upload_intent_id = :id"),
            {"id": intent_id},
        ) == 1
        assert connection.scalar(
            text("SELECT used_bytes FROM project_asset_usage WHERE project_id = :id"),
            {"id": project_id},
        ) == len(payload)
        connection.commit()

        # A missing temporary/final object is persisted as a bounded retry,
        # retaining its reservation and never attempting physical cleanup.
        retry_asset_id, retry_intent_id = uuid4(), uuid4()
        retry_staging = storage.allocate_temporary_reference(
            project_id=project_id, operation_id=retry_intent_id
        )
        with connection.begin():
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) "
                     "VALUES (:id, :project, 'audio')"),
                {"id": retry_asset_id, "project": project_id},
            )
            connection.execute(
                text("UPDATE project_asset_usage SET reserved_bytes = 100 "
                     "WHERE project_id = :project"),
                {"project": project_id},
            )
            connection.execute(
                text("""WITH times AS (SELECT clock_timestamp() AS base_time)
                    INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, created_at, expires_at,
                     recovery_deadline_at)
                    SELECT :id, :project, :asset, 'coordinator-retry', :fingerprint,
                     :staging, 100, base_time - INTERVAL '2 minutes',
                     base_time + INTERVAL '1 hour', base_time + INTERVAL '25 hours'
                    FROM times"""),
                {
                    "id": retry_intent_id,
                    "project": project_id,
                    "asset": retry_asset_id,
                    "fingerprint": "b" * 64,
                    "staging": retry_staging.value,
                },
            )
            retry_token = uuid4()
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'receiving', operation_revision = operation_revision + 1,
                    operation_claim_generation = operation_claim_generation + 1,
                    operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                    operation_lease_expires_at = clock_timestamp() + INTERVAL '30 minutes'
                    WHERE id = :id"""),
                {"id": retry_intent_id, "token": retry_token},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state = 'uploaded', operation_revision = operation_revision + 1,
                    operation_claim_token = NULL, operation_claimed_at = NULL,
                    operation_lease_expires_at = NULL, received_bytes = :byte_count,
                    observed_sha256_hex = :digest,
                    transfer_completed_at = clock_timestamp() - INTERVAL '1 minute',
                    recovery_state = 'pending', recovery_revision = recovery_revision + 1
                    WHERE id = :id"""),
                {
                    "id": retry_intent_id,
                    "byte_count": len(payload),
                    "digest": digest,
                },
            )
        retry_coordinator = LocalUploadRecoveryCoordinator(
            factory,
            AssetServiceConfig(1000, timedelta(hours=2)),
            storage,
        )
        retry_outcome = retry_coordinator.run_once()
        assert retry_outcome.kind is RecoveryOutcomeKind.RETRY_SCHEDULED
        assert retry_outcome.intent_id == retry_intent_id
        retry_state = connection.execute(
            text("SELECT recovery_state, next_retry_at > clock_timestamp(), "
                 "operation_state, reserved_bytes FROM asset_upload_intents "
                 "WHERE id = :id"),
            {"id": retry_intent_id},
        ).one()
        assert retry_state == ("pending", True, "finalizing", 100)
        connection.commit()

        # Simulate a restarted invocation after the retry becomes eligible and
        # the exact temporary bytes become readable; the persisted final ref is
        # reused rather than allocating a new version identity.
        storage.create_temporary_object(retry_staging)
        storage.write_temporary_object(retry_staging, [payload], max_bytes=256)
        connection.execute(
            text("UPDATE asset_upload_intents SET next_retry_at = clock_timestamp() - "
                 "INTERVAL '1 second', recovery_revision = recovery_revision + 1 "
                 "WHERE id = :id"),
            {"id": retry_intent_id},
        )
        connection.commit()
        resumed = retry_coordinator.run_once()
        assert resumed.kind is RecoveryOutcomeKind.COMPLETED
        assert resumed.intent_id == retry_intent_id
        retry_version_count = connection.scalar(
            text("SELECT count(*) FROM asset_versions WHERE upload_intent_id = :id"),
            {"id": retry_intent_id},
        )
        assert retry_version_count == 1
        assert connection.scalar(
            text("SELECT used_bytes FROM project_asset_usage WHERE project_id = :id"),
            {"id": project_id},
        ) == len(payload) * 2
    finally:
        alembic_config.attributes.pop("connection", None)
        if connection is not None:
            connection.close()
        with engine.begin() as cleanup:
            cleanup.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        with engine.connect() as verify:
            assert verify.scalar(
                text("SELECT count(*) FROM pg_namespace WHERE nspname = :schema"),
                {"schema": schema},
            ) == 0
        engine.dispose()
