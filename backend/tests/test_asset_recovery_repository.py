from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import adforge_renderer.asset_recovery_repository as recovery_repository
from adforge_renderer.asset_recovery_repository import (
    AssetRecoveryConflict,
    AssetRecoveryRepository,
    RecoveryFence,
)
from adforge_renderer.database import DatabaseConfig
from adforge_renderer.database.models import (
    ASSET_RECOVERY_MAX_ATTEMPTS,
    Asset,
    AssetUploadIntent,
    AssetVersion,
)
from adforge_renderer.asset_contract import PrivateObjectVersionReference
from adforge_renderer.asset_service import AssetOperationConflict, AssetService, AssetServiceConfig
from adforge_renderer.local_asset_storage import LocalAssetStorageConfig, LocalPrivateAssetStorage


def test_recovery_fence_requires_complete_supported_values() -> None:
    token = uuid4()
    fence = RecoveryFence(token, 3, 7)

    assert fence.claim_token == token
    assert fence.claim_generation == 3
    assert fence.recovery_revision == 7
    assert fence.expected_state == "claimed"

    with pytest.raises(ValueError, match="claim token"):
        RecoveryFence("not-a-uuid", 1, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="generation"):
        RecoveryFence(token, True, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="revision"):
        RecoveryFence(token, 1, 0)
    with pytest.raises(ValueError, match="state"):
        RecoveryFence(token, 1, 1, "completed")


def test_worker_update_compares_all_four_fencing_fields() -> None:
    intent_id = uuid4()
    fence = RecoveryFence(uuid4(), 4, 9)
    statement = update(AssetUploadIntent).where(
        *AssetRecoveryRepository._fence_predicates(intent_id, fence)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "asset_upload_intents.id =" in sql
    assert "asset_upload_intents.recovery_claim_token =" in sql
    assert "asset_upload_intents.recovery_claim_generation =" in sql
    assert "asset_upload_intents.recovery_revision =" in sql
    assert "asset_upload_intents.recovery_state =" in sql


def test_maintenance_update_compares_recovery_snapshot_fence() -> None:
    intent = AssetUploadIntent(
        id=uuid4(),
        recovery_claim_token=uuid4(),
        recovery_claim_generation=4,
        recovery_revision=9,
        recovery_state="claimed",
    )
    statement = update(AssetUploadIntent).where(
        *AssetRecoveryRepository._snapshot_predicates(intent)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "asset_upload_intents.recovery_claim_token =" in sql
    assert "asset_upload_intents.recovery_claim_generation =" in sql
    assert "asset_upload_intents.recovery_revision =" in sql
    assert "asset_upload_intents.recovery_state =" in sql


def test_repository_uses_the_approved_sixty_second_renewal_cadence() -> None:
    assert str(recovery_repository._RENEWAL_CADENCE_SQL) == "INTERVAL '60 seconds'"


def _disposable_test_config() -> DatabaseConfig | None:
    raw_url = os.environ.get("SPOTLOOM_TEST_DATABASE_URL")
    if not raw_url:
        return None
    parsed = make_url(raw_url)
    config = DatabaseConfig.from_url(raw_url)
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in {"localhost", "127.0.0.1", "::1"}
        or parsed.port != 5432
        or parsed.database != "spotloom_test"
    ):
        raise ValueError("Recovery integration tests require loopback spotloom_test on port 5432.")
    return config


def _prepare_schema(engine, schema: str):
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    connection = engine.connect()
    connection.exec_driver_sql(f'SET search_path TO "{schema}"')
    connection.commit()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    connection.exec_driver_sql(f'SET search_path TO "{schema}"')
    connection.commit()
    return config, connection


def _seed_pending_intent(
    connection,
    label: str,
    *,
    expires_seconds: int = 3600,
    recovery_window_seconds: int = 24 * 60 * 60,
) -> tuple[object, object, object, object]:
    owner_id, project_id, asset_id, intent_id = uuid4(), uuid4(), uuid4(), uuid4()
    connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
    connection.execute(
        text("INSERT INTO projects (id, owner_user_id, name) VALUES (:id, :owner, :name)"),
        {"id": project_id, "owner": owner_id, "name": f"Recovery {label}"},
    )
    connection.execute(
        text("INSERT INTO project_asset_usage (project_id, quota_limit_bytes) VALUES (:project, 100000)"),
        {"project": project_id},
    )
    connection.execute(
        text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
        {"id": asset_id, "project": project_id},
    )
    connection.execute(
        text("""WITH timestamps AS (SELECT clock_timestamp() AS base_time)
            INSERT INTO asset_upload_intents
                (id, project_id, asset_id, idempotency_key, request_fingerprint,
                 staging_reference, reserved_bytes, created_at, expires_at, recovery_deadline_at)
            SELECT :id, :project, :asset, :key, :fingerprint, :staging, 100,
                   timestamps.base_time - INTERVAL '1 minute',
                   timestamps.base_time + (:expires_seconds * INTERVAL '1 second'),
                   timestamps.base_time + ((:expires_seconds + :window_seconds) * INTERVAL '1 second')
            FROM timestamps"""),
        {
            "id": intent_id,
            "project": project_id,
            "asset": asset_id,
            "key": f"recovery-{label}",
            "fingerprint": (label.encode().hex() * 32)[:64],
            "staging": f"staging-{label}",
            "expires_seconds": expires_seconds,
            "window_seconds": recovery_window_seconds,
        },
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
            operation_lease_expires_at = NULL, received_bytes = 32,
            observed_sha256_hex = :digest, transfer_completed_at = clock_timestamp(),
            recovery_state = 'pending', recovery_revision = recovery_revision + 1
            WHERE id = :id"""),
        {"id": intent_id, "digest": "a" * 64},
    )
    return project_id, asset_id, intent_id, owner_id


def _test_engine_and_schema(label: str):
    try:
        database_config = _disposable_test_config()
    except ValueError as exc:
        pytest.fail(str(exc))
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to loopback spotloom_test on port 5432.")
    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_recovery_repo_{label}_{uuid4().hex}"
    return engine, schema


def _cleanup_schema(engine, schema: str, config: Config, connection) -> None:
    config.attributes.pop("connection", None)
    connection.close()
    with engine.begin() as cleanup:
        cleanup.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    with engine.connect() as verify:
        remaining = verify.scalar(
            text("SELECT count(*) FROM pg_namespace WHERE nspname = :schema"),
            {"schema": schema},
        )
    assert remaining == 0
    engine.dispose()


def test_recovery_claim_renew_reclaim_and_retry_fencing_on_disposable_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, schema = _test_engine_and_schema("fences")
    config = None
    connection = None
    try:
        config, connection = _prepare_schema(engine, schema)
        _project, _asset, requeue_id, _owner = _seed_pending_intent(connection, "requeue")
        original_deadline = connection.scalar(
            text("SELECT recovery_deadline_at FROM asset_upload_intents WHERE id = :id"),
            {"id": requeue_id},
        )
        connection.commit()

        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            initial = repository.claim_next(lease_duration=timedelta(milliseconds=100))
            assert initial is not None and initial.intent_id == requeue_id
            assert initial.claim_generation == 1
            assert initial.attempt_count == 1
            lease_bounds = session.execute(
                text("""SELECT recovery_lease_expires_at <= recovery_lease_issued_at + INTERVAL '5 minutes',
                             recovery_lease_expires_at <= recovery_deadline_at
                      FROM asset_upload_intents WHERE id = :id"""),
                {"id": requeue_id},
            ).one()
            assert lease_bounds == (True, True)
            with pytest.raises(ValueError, match="five minutes"):
                repository.claim_next(lease_duration=timedelta(minutes=5, seconds=1))
            # A live lease is not stealable by a second claim request.
            assert repository.claim_next() is None
            session.commit()

        time.sleep(0.15)
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            reclaimed = repository.claim_next(lease_duration=timedelta(milliseconds=100))
            assert reclaimed is not None and reclaimed.intent_id == requeue_id
            assert reclaimed.claim_token != initial.claim_token
            assert reclaimed.claim_generation == initial.claim_generation + 1
            assert reclaimed.recovery_revision == initial.recovery_revision + 1
            assert reclaimed.attempt_count == initial.attempt_count + 1
            stale_requeue_fences = (
                initial.fence,
                RecoveryFence(reclaimed.claim_token, reclaimed.claim_generation + 1,
                              reclaimed.recovery_revision),
                RecoveryFence(reclaimed.claim_token, reclaimed.claim_generation,
                              reclaimed.recovery_revision + 1),
                RecoveryFence(reclaimed.claim_token, reclaimed.claim_generation,
                              reclaimed.recovery_revision, "pending"),
            )
            for stale_fence in stale_requeue_fences:
                assert repository.requeue_expired_claim(requeue_id, stale_fence) is None
            before = session.execute(
                text("SELECT recovery_revision, recovery_attempt_count, recovery_claim_generation "
                     "FROM asset_upload_intents WHERE id = :id"),
                {"id": requeue_id},
            ).one()
            assert repository.renew(requeue_id, initial.fence) is None
            assert repository.renew(
                requeue_id,
                RecoveryFence(reclaimed.claim_token, reclaimed.claim_generation + 1, reclaimed.recovery_revision),
            ) is None
            assert repository.renew(
                requeue_id,
                RecoveryFence(reclaimed.claim_token, reclaimed.claim_generation, reclaimed.recovery_revision + 1),
            ) is None
            assert repository.renew(
                requeue_id,
                RecoveryFence(
                    reclaimed.claim_token,
                    reclaimed.claim_generation,
                    reclaimed.recovery_revision,
                    "pending",
                ),
            ) is None
            after = session.execute(
                text("SELECT recovery_revision, recovery_attempt_count, recovery_claim_generation "
                     "FROM asset_upload_intents WHERE id = :id"),
                {"id": requeue_id},
            ).one()
            assert after == before
            session.commit()

        time.sleep(0.15)
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            assert repository.requeue_expired_claim(
                requeue_id,
                RecoveryFence(uuid4(), reclaimed.claim_generation, reclaimed.recovery_revision),
            ) is None
            requeued = repository.requeue_expired_claim(requeue_id, reclaimed.fence)
            assert requeued is not None and requeued.recovery_state == "pending"
            assert requeued.recovery_claim_token is None
            assert requeued.recovery_attempt_count == reclaimed.attempt_count
            assert requeued.recovery_deadline_at == original_deadline
            session.commit()

        # Later-created work has an earlier fixed recovery deadline than the
        # requeued item, making it the next deterministic candidate.
        _project, _asset, renew_id, _owner = _seed_pending_intent(
            connection, "renew", expires_seconds=60, recovery_window_seconds=10 * 60
        )
        connection.commit()

        # Keep this integration test short while exercising the same database
        # interval predicate. The unit test above protects the real 60-second
        # application cadence configured by the repository.
        monkeypatch.setattr(
            recovery_repository,
            "_RENEWAL_CADENCE_SQL",
            text("INTERVAL '1 second'"),
        )
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            renewal_claim = repository.claim_next()
            assert renewal_claim is not None and renewal_claim.intent_id == renew_id
            session.commit()
        connection.execute(text("SELECT pg_sleep(1.1)"))
        connection.commit()
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            renewed = repository.renew(renewal_claim.intent_id, renewal_claim.fence)
            assert renewed is not None
            assert renewed.claim_token == renewal_claim.claim_token
            assert renewed.claim_generation == renewal_claim.claim_generation
            assert renewed.recovery_revision == renewal_claim.recovery_revision + 1
            assert renewed.attempt_count == renewal_claim.attempt_count
            assert renewed.lease_expires_at > renewal_claim.lease_expires_at
            deadline = session.scalar(
                text("SELECT recovery_deadline_at FROM asset_upload_intents WHERE id = :id"),
                {"id": renew_id},
            )
            assert renewed.lease_expires_at <= deadline
            session.commit()

        # Ten automatic claims are permitted; the tenth active holder may
        # terminalize exhaustion, and an eleventh claim cannot be issued.
        _project, _asset, exhaustion_id, _owner = _seed_pending_intent(
            connection, "exhaust", expires_seconds=60, recovery_window_seconds=30 * 60
        )
        connection.commit()
        latest = None
        for attempt in range(ASSET_RECOVERY_MAX_ATTEMPTS):
            with Session(connection, autoflush=False, expire_on_commit=False) as session:
                latest = AssetRecoveryRepository(session).claim_next(
                    lease_duration=(
                        timedelta(seconds=5)
                        if attempt == ASSET_RECOVERY_MAX_ATTEMPTS - 1
                        else timedelta(milliseconds=50)
                    )
                )
                assert latest is not None and latest.intent_id == exhaustion_id
                assert latest.attempt_count == attempt + 1
                session.commit()
            if attempt < ASSET_RECOVERY_MAX_ATTEMPTS - 1:
                time.sleep(0.07)
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            stale_exhaustion_fences = (
                RecoveryFence(uuid4(), latest.claim_generation, latest.recovery_revision),
                RecoveryFence(latest.claim_token, latest.claim_generation + 1,
                              latest.recovery_revision),
                RecoveryFence(latest.claim_token, latest.claim_generation,
                              latest.recovery_revision + 1),
                RecoveryFence(latest.claim_token, latest.claim_generation,
                              latest.recovery_revision, "pending"),
            )
            for stale_fence in stale_exhaustion_fences:
                assert repository.mark_attempts_exhausted(exhaustion_id, stale_fence) is None
            retry_result = repository.record_retryable_failure(exhaustion_id, latest.fence)
            assert retry_result is not None
            exhausted = retry_result.intent
            assert exhausted is not None and exhausted.recovery_state == "exhausted"
            assert exhausted.recovery_outcome_code == "attempts_exhausted"
            other_claim = repository.claim_next()
            assert other_claim is not None and other_claim.intent_id != exhaustion_id
            session.rollback()
            session.commit()

        # Claim rollback restores the original pending row and is not committed
        # implicitly by the repository.
        _project, _asset, rollback_id, _owner = _seed_pending_intent(
            connection, "rollback", expires_seconds=3600, recovery_window_seconds=3600
        )
        connection.commit()
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            claim = AssetRecoveryRepository(session).claim_next()
            assert claim is not None and claim.intent_id == rollback_id
            session.rollback()
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            row = session.scalar(select(AssetUploadIntent).where(AssetUploadIntent.id == rollback_id))
            assert row is not None
            assert (row.recovery_state, row.recovery_attempt_count, row.recovery_claim_generation) == (
                "pending", 0, 0
            )
    finally:
        if config is not None and connection is not None:
            _cleanup_schema(engine, schema, config, connection)
        else:
            engine.dispose()


def test_recovery_completion_manual_and_deadline_transitions_on_disposable_postgresql() -> None:
    engine, schema = _test_engine_and_schema("terminal")
    config = None
    connection = None
    try:
        config, connection = _prepare_schema(engine, schema)
        project_id, asset_id, complete_id, _owner = _seed_pending_intent(connection, "complete")
        _project, _asset, manual_id, _owner = _seed_pending_intent(connection, "manual")
        _project, _asset, deadline_id, _owner = _seed_pending_intent(
            connection, "deadline", expires_seconds=3, recovery_window_seconds=8
        )
        connection.commit()

        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            deadline_claim = repository.claim_next(
                # Keep this setup claim live while the other two seeded rows
                # are claimed; the 20 ms leases below are reserved for the
                # explicit expiry/reclaim assertions.
                lease_duration=timedelta(seconds=1)
            )
            complete_claim = repository.claim_next()
            manual_claim = repository.claim_next()
            assert deadline_claim is not None and deadline_claim.intent_id == deadline_id
            assert complete_claim is not None and complete_claim.intent_id == complete_id
            assert manual_claim is not None and manual_claim.intent_id == manual_id
            # The storage finalizer owns this preceding operation transition;
            # this test prepares its exact immutable reference without doing I/O.
            session.execute(
                text("""UPDATE asset_upload_intents SET operation_state = 'finalizing',
                    operation_revision = operation_revision + 1,
                    final_storage_provider = 'test-private',
                    final_object_version_reference = 'opaque-recovery-test-version',
                    finalization_started_at = transfer_completed_at + INTERVAL '1 millisecond'
                    WHERE id = :id"""),
                {"id": complete_id},
            )
            stale_fences = (
                RecoveryFence(uuid4(), complete_claim.claim_generation, complete_claim.recovery_revision),
                RecoveryFence(complete_claim.claim_token, complete_claim.claim_generation + 1,
                              complete_claim.recovery_revision),
                RecoveryFence(complete_claim.claim_token, complete_claim.claim_generation,
                              complete_claim.recovery_revision + 1),
                RecoveryFence(complete_claim.claim_token, complete_claim.claim_generation,
                              complete_claim.recovery_revision, "pending"),
            )
            for stale_fence in stale_fences:
                assert repository.complete_finalization(complete_id, stale_fence) is None
            finalized = repository.complete_finalization(complete_id, complete_claim.fence)
            assert finalized is not None
            assert (finalized.operation_state, finalized.recovery_state) == ("finalized", "completed")
            assert finalized.recovery_claim_token is None
            session.execute(
                text("""INSERT INTO asset_versions
                    (id, project_id, asset_id, upload_intent_id, storage_provider,
                     object_version_reference, byte_size, detected_media_type, finalized_at)
                    VALUES (:id, :project, :asset, :intent, :provider, :reference,
                            :size, NULL, :finalized_at)"""),
                {
                    "id": uuid4(), "project": project_id, "asset": asset_id,
                    "intent": complete_id, "provider": finalized.final_storage_provider,
                    "reference": finalized.final_object_version_reference,
                    "size": finalized.received_bytes, "finalized_at": finalized.storage_finalized_at,
                },
            )
            stale_manual_fences = (
                RecoveryFence(uuid4(), manual_claim.claim_generation, manual_claim.recovery_revision),
                RecoveryFence(manual_claim.claim_token, manual_claim.claim_generation + 1,
                              manual_claim.recovery_revision),
                RecoveryFence(manual_claim.claim_token, manual_claim.claim_generation,
                              manual_claim.recovery_revision + 1),
                RecoveryFence(manual_claim.claim_token, manual_claim.claim_generation,
                              manual_claim.recovery_revision, "pending"),
            )
            for stale_fence in stale_manual_fences:
                assert repository.mark_manual(
                    manual_id, stale_fence, outcome_code="legacy_ambiguous"
                ) is None
            manual = repository.mark_manual(
                manual_id, manual_claim.fence, outcome_code="legacy_ambiguous"
            )
            assert manual is not None and manual.recovery_state == "manual"
            assert manual.recovery_outcome_code == "legacy_ambiguous"
            session.commit()

        # Exhaust all ten claims before the short immutable deadline. Once the
        # deadline has elapsed, exhaustion must defer to manual reconciliation.
        # Let the setup lease expire only after the other seeded rows were
        # claimed; subsequent 20 ms leases exercise explicit reclaim.
        time.sleep(1.05)
        for attempt in range(1, ASSET_RECOVERY_MAX_ATTEMPTS):
            time.sleep(0.03)
            with Session(connection, autoflush=False, expire_on_commit=False) as session:
                repository = AssetRecoveryRepository(session)
                deadline_claim = repository.claim_next(
                    lease_duration=timedelta(milliseconds=20)
                )
                assert deadline_claim is not None and deadline_claim.intent_id == deadline_id
                assert deadline_claim.attempt_count == attempt + 1
                session.commit()
        remaining = connection.scalar(
            text("SELECT GREATEST(0, EXTRACT(EPOCH FROM recovery_deadline_at - clock_timestamp())) "
                 "FROM asset_upload_intents WHERE id = :id"),
            {"id": deadline_id},
        )
        if remaining:
            time.sleep(float(remaining) + 0.05)
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            assert repository.mark_expired_attempts_exhausted(deadline_id) is None
            deadline_manual = repository.mark_deadline_elapsed(deadline_id)
            assert deadline_manual is not None
            assert deadline_manual.recovery_state == "manual"
            assert deadline_manual.recovery_outcome_code == "deadline_elapsed"
            session.commit()

        # A completed intent cannot commit without its exact version; the
        # deferred trigger aborts and rolls back the repository transition.
        _project, _asset, missing_version_id, _owner = _seed_pending_intent(connection, "missing-version")
        connection.commit()
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            missing_claim = repository.claim_next()
            assert missing_claim is not None and missing_claim.intent_id == missing_version_id
            session.execute(
                text("""UPDATE asset_upload_intents SET operation_state = 'finalizing',
                    operation_revision = operation_revision + 1,
                    final_storage_provider = 'test-private',
                    final_object_version_reference = 'missing-version-ref',
                    finalization_started_at = transfer_completed_at + INTERVAL '1 millisecond'
                    WHERE id = :id"""),
                {"id": missing_version_id},
            )
            assert repository.complete_finalization(missing_version_id, missing_claim.fence) is not None
            with pytest.raises(DBAPIError):
                session.commit()
            session.rollback()
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            row = session.scalar(select(AssetUploadIntent).where(AssetUploadIntent.id == missing_version_id))
            assert row is not None and row.operation_state == "uploaded"
            assert row.recovery_state == "pending"
    finally:
        if config is not None and connection is not None:
            _cleanup_schema(engine, schema, config, connection)
        else:
            engine.dispose()


def test_concurrent_recovery_repository_claim_has_one_winner_on_disposable_postgresql() -> None:
    engine, schema = _test_engine_and_schema("concurrent")
    config = None
    connection = None
    try:
        config, connection = _prepare_schema(engine, schema)
        _project, _asset, intent_id, _owner = _seed_pending_intent(connection, "concurrent")
        connection.commit()
        barrier = Barrier(2)

        def claim_once(_worker: int):
            with engine.connect() as worker_connection:
                worker_connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                worker_connection.commit()
                with Session(worker_connection, autoflush=False, expire_on_commit=False) as session:
                    barrier.wait(timeout=10)
                    claim = AssetRecoveryRepository(session).claim_next()
                    session.commit()
                    return claim

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(claim_once, (1, 2)))
        winners = [claim for claim in claims if claim is not None]
        assert len(winners) == 1
        assert winners[0].intent_id == intent_id
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            row = session.scalar(select(AssetUploadIntent).where(AssetUploadIntent.id == intent_id))
            assert row is not None
            assert (row.recovery_claim_generation, row.recovery_attempt_count) == (1, 1)
            assert row.recovery_claim_token == winners[0].claim_token
    finally:
        if config is not None and connection is not None:
            _cleanup_schema(engine, schema, config, connection)
        else:
            engine.dispose()


def test_retry_schedule_is_persisted_and_due_time_is_checked_atomically_on_postgresql() -> None:
    engine, schema = _test_engine_and_schema("retry-eligibility")
    config = None
    connection = None
    try:
        config, connection = _prepare_schema(engine, schema)
        _project, _asset, intent_id, _owner = _seed_pending_intent(connection, "retry-eligible")
        connection.commit()

        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session, random_source=lambda _low, high: high)
            first = repository.claim_next()
            assert first is not None and first.intent_id == intent_id
            stale_fences = (
                RecoveryFence(uuid4(), first.claim_generation, first.recovery_revision),
                RecoveryFence(first.claim_token, first.claim_generation + 1, first.recovery_revision),
                RecoveryFence(first.claim_token, first.claim_generation, first.recovery_revision + 1),
            )
            for stale in stale_fences:
                assert repository.record_retryable_failure(intent_id, stale) is None
            with pytest.raises(ValueError, match="active claimed"):
                repository.record_retryable_failure(
                    intent_id,
                    RecoveryFence(
                        first.claim_token,
                        first.claim_generation,
                        first.recovery_revision,
                        "pending",
                    ),
                )
            outcome = repository.record_retryable_failure(intent_id, first.fence)
            assert outcome is not None
            assert outcome.intent.recovery_state == "pending"
            assert outcome.next_retry_at is not None
            assert outcome.delay == timedelta(seconds=5)
            persisted = session.scalar(
                select(AssetUploadIntent.next_retry_at).where(AssetUploadIntent.id == intent_id)
            )
            assert persisted == outcome.next_retry_at
            session.commit()

        # A fresh Session cannot claim before the persisted retry time.
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            assert AssetRecoveryRepository(session).claim_next() is None
            session.commit()

        # Move only the test row's eligibility timestamp to the past using the
        # database clock; this avoids sleeping and tests the due-boundary CAS.
        connection.execute(
            text("UPDATE asset_upload_intents SET next_retry_at = clock_timestamp() - INTERVAL '1 second', "
                 "recovery_revision = recovery_revision + 1 WHERE id = :id"),
            {"id": intent_id},
        )
        connection.commit()
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            second = AssetRecoveryRepository(session).claim_next()
            assert second is not None and second.intent_id == intent_id
            assert second.attempt_count == 2
            assert session.scalar(
                select(AssetUploadIntent.next_retry_at).where(AssetUploadIntent.id == intent_id)
            ) is None
            session.commit()
    finally:
        if config is not None and connection is not None:
            _cleanup_schema(engine, schema, config, connection)
        else:
            engine.dispose()


def test_fenced_begin_finalization_uses_persisted_transfer_and_is_idempotent() -> None:
    engine, schema = _test_engine_and_schema("begin-finalization")
    config = None
    connection = None
    try:
        config, connection = _prepare_schema(engine, schema)
        _project, _asset, intent_id, _owner = _seed_pending_intent(connection, "begin-finalization")
        connection.commit()
        reference = PrivateObjectVersionReference(value="ver_begin-finalization-v1")

        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            claim = repository.claim_next(lease_duration=timedelta(milliseconds=100))
            assert claim is not None and claim.intent_id == intent_id
            stale_fences = (
                RecoveryFence(uuid4(), claim.claim_generation, claim.recovery_revision),
                RecoveryFence(claim.claim_token, claim.claim_generation + 1, claim.recovery_revision),
                RecoveryFence(claim.claim_token, claim.claim_generation, claim.recovery_revision + 1),
                RecoveryFence(claim.claim_token, claim.claim_generation, claim.recovery_revision, "pending"),
            )
            for stale in stale_fences:
                assert repository.begin_finalization(
                    intent_id, stale, storage_provider="local-private", object_version_reference=reference
                ) is None
            session.commit()

        # A claim whose lease expired cannot begin finalization. A replacement
        # claim advances generation/revision and fences the stale worker.
        time.sleep(0.15)
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session)
            assert repository.begin_finalization(
                intent_id, claim.fence, storage_provider="local-private", object_version_reference=reference
            ) is None
            reclaimed = repository.claim_next()
            assert reclaimed is not None and reclaimed.intent_id == intent_id
            assert reclaimed.claim_generation == claim.claim_generation + 1
            assert repository.begin_finalization(
                intent_id, claim.fence, storage_provider="local-private", object_version_reference=reference
            ) is None
            started = repository.begin_finalization(
                intent_id, reclaimed.fence,
                storage_provider="local-private", object_version_reference=reference
            )
            assert started is not None
            assert started.operation_state == "finalizing"
            assert started.final_storage_provider == "local-private"
            assert started.final_object_version_reference == reference.value
            assert started.finalization_started_at >= started.transfer_completed_at
            repeated = repository.begin_finalization(
                intent_id, reclaimed.fence,
                storage_provider="local-private", object_version_reference=reference
            )
            assert repeated is not None and repeated.finalization_started_at == started.finalization_started_at
            session.commit()
    finally:
        if config is not None and connection is not None:
            _cleanup_schema(engine, schema, config, connection)
        else:
            engine.dispose()


def test_recovered_upload_completion_is_atomic_idempotent_and_keeps_asset_quarantined(
    tmp_path: Path,
) -> None:
    engine, schema = _test_engine_and_schema("service-completion")
    config = None
    connection = None
    storage = LocalPrivateAssetStorage(LocalAssetStorageConfig(tmp_path / "private-assets"))
    try:
        config, connection = _prepare_schema(engine, schema)
        owner_id, project_id, asset_id, intent_id = (uuid4() for _ in range(4))
        connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
        connection.execute(
            text("INSERT INTO projects (id, owner_user_id, name) VALUES (:id, :owner, 'Recovery service')"),
            {"id": project_id, "owner": owner_id},
        )
        connection.execute(
            text("INSERT INTO project_asset_usage (project_id, quota_limit_bytes, reserved_bytes) "
                 "VALUES (:project, 100000, 100)"),
            {"project": project_id},
        )
        connection.execute(
            text("INSERT INTO assets (id, project_id, kind) VALUES (:id, :project, 'audio')"),
            {"id": asset_id, "project": project_id},
        )
        temporary = storage.allocate_temporary_reference(project_id=project_id, operation_id=intent_id)
        storage.create_temporary_object(temporary)
        payload = b"persisted storage facts drive recovered completion"
        observed = storage.write_temporary_object(temporary, [payload], max_bytes=1024)
        connection.execute(
            text("""INSERT INTO asset_upload_intents
                (id, project_id, asset_id, idempotency_key, request_fingerprint,
                 staging_reference, reserved_bytes, created_at, expires_at, recovery_deadline_at)
                VALUES (:id, :project, :asset, 'service-completion', :fingerprint,
                        :staging, 100, clock_timestamp() - INTERVAL '1 second',
                        clock_timestamp() + INTERVAL '2 seconds',
                        clock_timestamp() + INTERVAL '24 hours')"""),
            {"id": intent_id, "project": project_id, "asset": asset_id,
             "fingerprint": "e" * 64, "staging": temporary.value},
        )
        transfer_token = uuid4()
        connection.execute(
            text("""UPDATE asset_upload_intents SET operation_state = 'receiving',
                operation_revision = operation_revision + 1,
                operation_claim_generation = operation_claim_generation + 1,
                operation_claim_token = :token, operation_claimed_at = clock_timestamp(),
                operation_lease_expires_at = expires_at - INTERVAL '100 milliseconds'
                WHERE id = :id"""),
            {"id": intent_id, "token": transfer_token},
        )
        connection.execute(
            text("""UPDATE asset_upload_intents SET operation_state = 'uploaded',
                operation_revision = operation_revision + 1,
                operation_claim_token = NULL, operation_claimed_at = NULL,
                operation_lease_expires_at = NULL, received_bytes = :size,
                observed_sha256_hex = :digest, transfer_completed_at = clock_timestamp(),
                recovery_state = 'pending', recovery_revision = recovery_revision + 1
                WHERE id = :id"""),
            {"size": observed.byte_size, "digest": observed.sha256, "id": intent_id},
        )
        connection.commit()
        # Let the original upload window expire; transfer evidence was persisted
        # before expiry and the fixed recovery deadline remains open.
        time.sleep(2.05)
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            expired = AssetService(
                session,
                AssetServiceConfig(project_quota_limit_bytes=100_000, maximum_upload_intent_lifetime=timedelta(hours=1)),
            ).expire_upload_intent(project_id=project_id, asset_id=asset_id, intent_id=intent_id)
            assert expired is not None and expired.state == "expired"
            session.commit()

        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            claim = AssetRecoveryRepository(session).claim_next()
            assert claim is not None and claim.intent_id == intent_id
            version_reference = storage.new_object_version_reference()
            begun = AssetRecoveryRepository(session).begin_finalization(
                intent_id,
                claim.fence,
                storage_provider="local-private",
                object_version_reference=version_reference,
            )
            assert begun is not None and begun.operation_state == "finalizing"
            session.commit()

        # Filesystem work is outside the SQL transaction and preserves the temp.
        finalized = storage.finalize_temporary_object_preserving_temporary(
            temporary,
            version_reference,
            expected_sha256=observed.sha256,
            expected_byte_size=observed.byte_size,
        )
        assert finalized.temporary_preserved
        config_service = AssetServiceConfig(
            project_quota_limit_bytes=100_000,
            maximum_upload_intent_lifetime=timedelta(hours=1),
        )
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            service = AssetService(session, config_service, storage=storage)
            with pytest.raises(AssetOperationConflict):
                service.complete_recovered_upload(
                    project_id=project_id,
                    asset_id=asset_id,
                    intent_id=intent_id,
                    storage_provider="local-private",
                    finalized_object=replace(finalized, sha256="0" * 64),
                    fence=claim.fence,
                )
            with pytest.raises(AssetRecoveryConflict):
                service.complete_recovered_upload(
                    project_id=project_id,
                    asset_id=asset_id,
                    intent_id=intent_id,
                    storage_provider="local-private",
                    finalized_object=finalized,
                    fence=RecoveryFence(uuid4(), claim.claim_generation, claim.recovery_revision),
                )
            session.rollback()

        # A caller rollback after all service writes must leave the operation,
        # version history, and quota reservation unchanged.
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            service = AssetService(session, config_service, storage=storage)
            result = service.complete_recovered_upload(
                project_id=project_id,
                asset_id=asset_id,
                intent_id=intent_id,
                storage_provider="local-private",
                finalized_object=finalized,
                fence=claim.fence,
            )
            assert result is not None and result.created
            assert result.intent.operation_state == "finalized"
            assert result.intent.state == "finalized"
            assert result.version.byte_size == observed.byte_size
            assert result.version.validation_state == "quarantined"
            session.rollback()

        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            assert session.scalar(select(AssetVersion.id).where(AssetVersion.upload_intent_id == intent_id)) is None
            rolled_back_intent = session.get(AssetUploadIntent, intent_id)
            assert rolled_back_intent is not None
            assert (rolled_back_intent.operation_state, rolled_back_intent.state) == ("finalizing", "expired")
            quota = session.execute(
                text("SELECT used_bytes, reserved_bytes FROM project_asset_usage WHERE project_id = :project"),
                {"project": project_id},
            ).one()
            assert quota == (0, 100)
            session.commit()

        # Two fresh transactions racing the same completion serialize on the
        # project usage lock; one inserts/converts, the other verifies the exact
        # committed operation as an idempotent duplicate.
        completion_barrier = Barrier(2)

        def complete_once(_worker: int) -> bool:
            with engine.connect() as worker_connection:
                worker_connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                worker_connection.commit()
                with Session(worker_connection, autoflush=False, expire_on_commit=False) as session:
                    completion_barrier.wait(timeout=10)
                    completion = AssetService(session, config_service, storage=storage).complete_recovered_upload(
                        project_id=project_id,
                        asset_id=asset_id,
                        intent_id=intent_id,
                        storage_provider="local-private",
                        finalized_object=finalized,
                        fence=claim.fence,
                    )
                    assert completion is not None
                    session.commit()
                    return completion.created

        with ThreadPoolExecutor(max_workers=2) as executor:
            created_results = list(executor.map(complete_once, (1, 2)))
        assert sorted(created_results) == [False, True]

        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            usage = session.execute(
                text("SELECT used_bytes, reserved_bytes FROM project_asset_usage WHERE project_id = :project"),
                {"project": project_id},
            ).one()
            # Finalization converts the actual logical bytes to used quota and
            # releases the unused portion of the reservation exactly once.
            assert usage == (observed.byte_size, 0)
            asset = session.get(Asset, asset_id)
            assert asset is not None and asset.current_ready_version_id is None
            duplicate = AssetService(session, config_service).complete_recovered_upload(
                project_id=project_id,
                asset_id=asset_id,
                intent_id=intent_id,
                storage_provider="local-private",
                finalized_object=finalized,
                fence=claim.fence,
            )
            assert duplicate is not None and not duplicate.created
            assert session.scalar(
                select(AssetVersion.id).where(AssetVersion.upload_intent_id == intent_id)
            ) == duplicate.version.id
            session.commit()
        assert storage.inspect_temporary_object(temporary).complete
    finally:
        if config is not None and connection is not None:
            _cleanup_schema(engine, schema, config, connection)
        else:
            engine.dispose()


def test_retry_failure_enters_manual_when_next_jitter_would_exceed_deadline() -> None:
    engine, schema = _test_engine_and_schema("retry-deadline")
    config = None
    connection = None
    try:
        config, connection = _prepare_schema(engine, schema)
        _project, _asset, intent_id, _owner = _seed_pending_intent(
            connection, "retry-deadline", expires_seconds=1, recovery_window_seconds=1
        )
        deadline = connection.scalar(
            text("SELECT recovery_deadline_at FROM asset_upload_intents WHERE id = :id"),
            {"id": intent_id},
        )
        connection.commit()
        with Session(connection, autoflush=False, expire_on_commit=False) as session:
            repository = AssetRecoveryRepository(session, random_source=lambda _low, high: high)
            claim = repository.claim_next()
            assert claim is not None and claim.intent_id == intent_id
            outcome = repository.record_retryable_failure(intent_id, claim.fence)
            assert outcome is not None
            assert outcome.next_retry_at is None and outcome.delay is None
            assert outcome.intent.recovery_state == "manual"
            assert outcome.intent.recovery_deadline_at == deadline
            session.commit()
    finally:
        if config is not None and connection is not None:
            _cleanup_schema(engine, schema, config, connection)
        else:
            engine.dispose()
