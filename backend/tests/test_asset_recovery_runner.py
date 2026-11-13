from __future__ import annotations

import hashlib
import math
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event, Thread
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from adforge_renderer.asset_recovery_coordinator import (
    LocalUploadRecoveryCoordinator,
    RecoveryOutcome,
    RecoveryOutcomeKind,
)
from adforge_renderer.asset_recovery_repository import AssetRecoveryRepository
from adforge_renderer.asset_recovery_runner import (
    DEFAULT_MAX_OPERATIONS,
    DEFAULT_TIME_BUDGET_SECONDS,
    AssetRecoveryRunner,
    RecoveryRunResult,
    RecoveryRunnerStopReason,
)
from adforge_renderer.asset_service import AssetServiceConfig
from adforge_renderer.database import DatabaseConfig
from adforge_renderer.database.config import DatabaseConfigurationError
from adforge_renderer.local_asset_storage import (
    LocalAssetStorageConfig,
    LocalPrivateAssetStorage,
)


class _FakeCoordinator:
    def __init__(self, outcomes=()) -> None:
        self.outcomes = deque(outcomes)
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def run_once(self):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            value = self.outcomes.popleft()
            if isinstance(value, BaseException):
                raise value
            return value
        finally:
            self.active -= 1


def _outcome(kind: RecoveryOutcomeKind) -> RecoveryOutcome:
    return RecoveryOutcome(kind, intent_id=uuid4())


def test_runner_aggregates_actual_outcomes_and_stops_when_no_work() -> None:
    kinds = (
        RecoveryOutcomeKind.COMPLETED,
        RecoveryOutcomeKind.ALREADY_COMPLETED,
        RecoveryOutcomeKind.RETRY_SCHEDULED,
        RecoveryOutcomeKind.MANUAL_RECONCILIATION_REQUIRED,
        RecoveryOutcomeKind.STALE_CLAIM,
        RecoveryOutcomeKind.NOT_CLAIMABLE,
    )
    coordinator = _FakeCoordinator(_outcome(kind) for kind in kinds)

    result = AssetRecoveryRunner(coordinator).run()

    assert result.operations_attempted == 6
    assert result.completed == 1
    assert result.already_completed == 1
    assert result.retry_scheduled == 1
    assert result.manual_reconciliation_required == 1
    assert result.stale_claim == 1
    assert result.not_claimable == 1
    assert result.unexpected_failures == 0
    assert result.stop_reason is RecoveryRunnerStopReason.NO_ELIGIBLE_WORK
    assert not result.operation_limit_reached
    assert coordinator.calls == 6
    assert coordinator.max_active == 1


def test_runner_returns_valid_empty_queue_result() -> None:
    coordinator = _FakeCoordinator((_outcome(RecoveryOutcomeKind.NOT_CLAIMABLE),))
    result = AssetRecoveryRunner(coordinator).run()
    assert result.operations_attempted == 1
    assert result.not_claimable == 1
    assert result.stop_reason is RecoveryRunnerStopReason.NO_ELIGIBLE_WORK


def test_runner_default_operation_limit_is_finite_and_sequential() -> None:
    coordinator = _FakeCoordinator(
        _outcome(RecoveryOutcomeKind.COMPLETED)
        for _ in range(DEFAULT_MAX_OPERATIONS + 1)
    )

    result = AssetRecoveryRunner(coordinator, time_budget_seconds=None).run()

    assert result.operations_attempted == DEFAULT_MAX_OPERATIONS
    assert result.completed == DEFAULT_MAX_OPERATIONS
    assert result.operation_limit_reached
    assert result.stop_reason is RecoveryRunnerStopReason.OPERATION_LIMIT_REACHED
    assert coordinator.max_active == 1


def test_runner_does_not_call_coordinator_when_budget_is_exhausted_before_call() -> None:
    ticks = iter((0.0, DEFAULT_TIME_BUDGET_SECONDS))
    coordinator = _FakeCoordinator()

    result = AssetRecoveryRunner(
        coordinator, monotonic_clock=lambda: next(ticks)
    ).run()

    assert result.operations_attempted == 0
    assert result.time_budget_exhausted
    assert not result.time_budget_exceeded_after_operation
    assert result.stop_reason is RecoveryRunnerStopReason.TIME_BUDGET_EXHAUSTED
    assert coordinator.calls == 0


def test_runner_reports_soft_budget_overrun_after_inflight_operation() -> None:
    ticks = iter((0.0, 0.0, DEFAULT_TIME_BUDGET_SECONDS + 1.0))
    coordinator = _FakeCoordinator((_outcome(RecoveryOutcomeKind.COMPLETED),))

    result = AssetRecoveryRunner(
        coordinator, monotonic_clock=lambda: next(ticks)
    ).run()

    assert result.operations_attempted == 1
    assert result.completed == 1
    assert not result.time_budget_exhausted
    assert result.time_budget_exceeded_after_operation
    assert result.stop_reason is RecoveryRunnerStopReason.TIME_BUDGET_EXCEEDED_AFTER_OPERATION
    assert coordinator.calls == 1


def test_runner_reports_budget_overrun_when_inflight_call_raises() -> None:
    ticks = iter((0.0, 0.0, DEFAULT_TIME_BUDGET_SECONDS + 1.0))
    coordinator = _FakeCoordinator((RuntimeError("private detail"),))

    result = AssetRecoveryRunner(
        coordinator, monotonic_clock=lambda: next(ticks)
    ).run()

    assert result.unexpected_failures == 1
    assert result.time_budget_exceeded_after_operation
    assert not result.time_budget_exhausted
    assert result.stop_reason is RecoveryRunnerStopReason.UNEXPECTED_ERROR


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (RuntimeError("do not leak this text"), "unexpected_error"),
        (ValueError("secret-looking error"), "unexpected_error"),
        (SQLAlchemyError("database details"), "database_error"),
        (DatabaseConfigurationError("configuration details"), "configuration_error"),
    ],
)
def test_runner_stops_on_exception_without_exposing_exception_message(error, category) -> None:
    coordinator = _FakeCoordinator((error, _outcome(RecoveryOutcomeKind.COMPLETED)))

    result = AssetRecoveryRunner(coordinator).run()

    assert result.operations_attempted == 1
    assert result.unexpected_failures == 1
    assert result.failure_category == category
    assert result.stop_reason is RecoveryRunnerStopReason.UNEXPECTED_ERROR
    assert "leak" not in repr(result)
    assert "secret-looking" not in repr(result)
    assert coordinator.calls == 1


@pytest.mark.parametrize("process_exception", [KeyboardInterrupt, SystemExit])
def test_runner_does_not_swallow_process_control_exceptions(process_exception) -> None:
    coordinator = _FakeCoordinator((process_exception(),))
    with pytest.raises(process_exception):
        AssetRecoveryRunner(coordinator).run()


def test_runner_rejects_parallel_run_on_same_instance() -> None:
    entered = Event()
    release = Event()

    class BlockingCoordinator:
        def run_once(self):
            entered.set()
            assert release.wait(timeout=5)
            return _outcome(RecoveryOutcomeKind.NOT_CLAIMABLE)

    runner = AssetRecoveryRunner(BlockingCoordinator())
    worker_error: list[BaseException] = []

    def invoke() -> None:
        try:
            runner.run()
        except BaseException as exc:  # test thread transport only
            worker_error.append(exc)

    worker = Thread(target=invoke)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        with pytest.raises(RuntimeError, match="already active"):
            runner.run()
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert worker_error == []


@pytest.mark.parametrize(
    ("max_operations", "budget"),
    [
        (0, 1), (-1, 1), (True, 1), (DEFAULT_MAX_OPERATIONS + 1, 1),
        (1, 0), (1, -1), (1, math.inf), (1, math.nan), (1, True),
    ],
)
def test_runner_rejects_invalid_bounds(max_operations, budget) -> None:
    with pytest.raises(ValueError):
        AssetRecoveryRunner(
            _FakeCoordinator(), max_operations=max_operations,
            time_budget_seconds=budget,
        )


@pytest.mark.parametrize("clock_value", [True, math.inf, math.nan])
def test_runner_rejects_invalid_monotonic_clock_values(clock_value) -> None:
    coordinator = _FakeCoordinator()
    with pytest.raises(RuntimeError, match="Monotonic clock"):
        AssetRecoveryRunner(
            coordinator, monotonic_clock=lambda: clock_value
        ).run()
    assert coordinator.calls == 0


def test_runner_rejects_monotonic_clock_going_backwards() -> None:
    ticks = iter((10.0, 9.0))
    coordinator = _FakeCoordinator()
    with pytest.raises(RuntimeError, match="moved backwards"):
        AssetRecoveryRunner(
            coordinator, monotonic_clock=lambda: next(ticks)
        ).run()
    assert coordinator.calls == 0


def test_run_result_is_immutable_and_validates_counter_invariant() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="Outcome counters"):
        RecoveryRunResult(
            uuid4(), now, now, 1, 0, 0, 0, 0, 0, 0, 0, None,
            RecoveryRunnerStopReason.OPERATION_LIMIT_REACHED,
            False, False, False,
        )


def _isolated_test_config() -> DatabaseConfig | None:
    raw = os.environ.get("SPOTLOOM_TEST_DATABASE_URL")
    if not raw:
        return None
    url = make_url(raw)
    if (
        url.drivername != "postgresql+psycopg"
        or (url.host or "").lower() not in {"localhost", "127.0.0.1", "::1"}
        or url.port != 5432
        or url.database != "spotloom_test"
    ):
        raise ValueError("Recovery runner integration requires loopback spotloom_test on port 5432.")
    return DatabaseConfig.from_url(raw)


def test_runner_processes_only_coordinator_claims_and_accounts_on_postgresql(
    tmp_path: Path,
) -> None:
    database_config = _isolated_test_config()
    if database_config is None:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to loopback spotloom_test on port 5432.")

    engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    schema = f"spotloom_runner_{uuid4().hex}"
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    connection = None
    race_engine = None
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

        owner_id, project_id = uuid4(), uuid4()
        payloads = (b"runner operation one", b"runner operation two")
        retry_payload = b"runner retry waits for its persisted due time"
        storage = LocalPrivateAssetStorage(
            LocalAssetStorageConfig(tmp_path / "runner-private-storage")
        )
        intents = []
        staging_refs = []
        for payload in payloads:
            intent_id = uuid4()
            asset_id = uuid4()
            staging = storage.allocate_temporary_reference(
                project_id=project_id, operation_id=intent_id
            )
            storage.create_temporary_object(staging)
            observation = storage.write_temporary_object(staging, [payload], max_bytes=256)
            intents.append((intent_id, asset_id, payload, observation.sha256))
            staging_refs.append(staging)

        with connection.begin():
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner_id})
            connection.execute(
                text("INSERT INTO projects (id, owner_user_id, name) VALUES (:id, :owner, 'Runner')"),
                {"id": project_id, "owner": owner_id},
            )
            connection.execute(
                text("INSERT INTO project_asset_usage "
                     "(project_id, quota_limit_bytes, used_bytes, reserved_bytes) "
                     "VALUES (:project, 1000, 0, :reserved)"),
                {
                    "project": project_id,
                    "reserved": sum(map(len, payloads)) + len(retry_payload),
                },
            )
            for (intent_id, asset_id, payload, digest), staging in zip(intents, staging_refs):
                connection.execute(
                    text("INSERT INTO assets (id, project_id, kind) "
                         "VALUES (:id, :project, 'audio')"),
                    {"id": asset_id, "project": project_id},
                )
                connection.execute(
                    text("""WITH t AS (SELECT clock_timestamp() AS now)
                        INSERT INTO asset_upload_intents
                        (id, project_id, asset_id, idempotency_key, request_fingerprint,
                         staging_reference, reserved_bytes, created_at, expires_at,
                         recovery_deadline_at)
                        SELECT :id, :project, :asset, :key, :fingerprint, :staging,
                               :reserved, t.now - INTERVAL '2 minutes',
                               t.now + INTERVAL '1 hour', t.now + INTERVAL '25 hours'
                        FROM t"""),
                    {
                        "id": intent_id, "project": project_id, "asset": asset_id,
                        "key": f"runner-{intent_id.hex}",
                        "fingerprint": hashlib.sha256(payload).hexdigest(),
                        "staging": staging.value, "reserved": len(payload),
                    },
                )
                token = uuid4()
                connection.execute(
                    text("""UPDATE asset_upload_intents SET
                        operation_state='receiving', operation_revision=operation_revision+1,
                        operation_claim_generation=operation_claim_generation+1,
                        operation_claim_token=:token, operation_claimed_at=clock_timestamp(),
                        operation_lease_expires_at=clock_timestamp()+INTERVAL '30 minutes'
                        WHERE id=:id"""),
                    {"id": intent_id, "token": token},
                )
                connection.execute(
                    text("""UPDATE asset_upload_intents SET
                        operation_state='uploaded', operation_revision=operation_revision+1,
                        operation_claim_token=NULL, operation_claimed_at=NULL,
                        operation_lease_expires_at=NULL, received_bytes=:size,
                        observed_sha256_hex=:digest,
                        transfer_completed_at=clock_timestamp()-INTERVAL '1 minute',
                        recovery_state='pending', recovery_revision=recovery_revision+1
                        WHERE id=:id"""),
                    {"id": intent_id, "size": len(payload), "digest": digest},
                )
            retry_intent_id, retry_asset_id = uuid4(), uuid4()
            retry_staging = storage.allocate_temporary_reference(
                project_id=project_id, operation_id=retry_intent_id
            )
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) "
                     "VALUES (:id, :project, 'audio')"),
                {"id": retry_asset_id, "project": project_id},
            )
            connection.execute(
                text("""WITH t AS (SELECT clock_timestamp() AS now)
                    INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, created_at, expires_at,
                     recovery_deadline_at)
                    SELECT :id, :project, :asset, :key, :fingerprint, :staging,
                           :reserved, t.now - INTERVAL '2 minutes',
                           t.now + INTERVAL '1 hour', t.now + INTERVAL '25 hours'
                    FROM t"""),
                {
                    "id": retry_intent_id,
                    "project": project_id,
                    "asset": retry_asset_id,
                    "key": f"runner-retry-{retry_intent_id.hex}",
                    "fingerprint": hashlib.sha256(retry_payload).hexdigest(),
                    "staging": retry_staging.value,
                    "reserved": len(retry_payload),
                },
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state='receiving', operation_revision=operation_revision+1,
                    operation_claim_generation=operation_claim_generation+1,
                    operation_claim_token=:token, operation_claimed_at=clock_timestamp(),
                    operation_lease_expires_at=clock_timestamp()+INTERVAL '30 minutes'
                    WHERE id=:id"""),
                {"id": retry_intent_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state='uploaded', operation_revision=operation_revision+1,
                    operation_claim_token=NULL, operation_claimed_at=NULL,
                    operation_lease_expires_at=NULL, received_bytes=:size,
                    observed_sha256_hex=:digest,
                    transfer_completed_at=clock_timestamp()-INTERVAL '1 minute',
                    recovery_state='pending', recovery_revision=recovery_revision+1
                    WHERE id=:id"""),
                {
                    "id": retry_intent_id,
                    "size": len(retry_payload),
                    "digest": hashlib.sha256(retry_payload).hexdigest(),
                },
            )

        factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
        coordinator = LocalUploadRecoveryCoordinator(
            factory,
            AssetServiceConfig(1000, timedelta(hours=2)),
            storage,
            repository_factory=lambda session: AssetRecoveryRepository(
                session, random_source=lambda lower, upper: upper
            ),
        )
        result = AssetRecoveryRunner(
            coordinator, max_operations=5, time_budget_seconds=30
        ).run()

        assert result.operations_attempted == 4
        assert result.completed == 2
        assert result.retry_scheduled == 1
        assert result.not_claimable == 1
        assert result.stop_reason is RecoveryRunnerStopReason.NO_ELIGIBLE_WORK
        assert connection.scalar(
            text("SELECT count(*) FROM asset_versions WHERE project_id=:project"),
            {"project": project_id},
        ) == 2
        assert connection.execute(
            text("SELECT used_bytes, reserved_bytes FROM project_asset_usage WHERE project_id=:project"),
            {"project": project_id},
        ).one() == (sum(map(len, payloads)), len(retry_payload))
        assert all(storage.inspect_temporary_object(ref).complete for ref in staging_refs)
        assert connection.execute(
            text("SELECT recovery_state, recovery_attempt_count, "
                 "next_retry_at > clock_timestamp() FROM asset_upload_intents WHERE id=:id"),
            {"id": retry_intent_id},
        ).one() == ("pending", 1, True)
        connection.commit()

        # Separate invocations may race, but the coordinator's fenced claim
        # and idempotent finalizer must complete this operation only once.
        race_payload = b"one operation shared by two independent runner calls"
        race_intent_id, race_asset_id = uuid4(), uuid4()
        race_staging = storage.allocate_temporary_reference(
            project_id=project_id, operation_id=race_intent_id
        )
        storage.create_temporary_object(race_staging)
        race_observation = storage.write_temporary_object(
            race_staging, [race_payload], max_bytes=256
        )
        with connection.begin():
            connection.execute(
                text("UPDATE project_asset_usage SET reserved_bytes=reserved_bytes+:size "
                     "WHERE project_id=:project"),
                {"size": len(race_payload), "project": project_id},
            )
            connection.execute(
                text("INSERT INTO assets (id, project_id, kind) "
                     "VALUES (:id, :project, 'audio')"),
                {"id": race_asset_id, "project": project_id},
            )
            connection.execute(
                text("""WITH t AS (SELECT clock_timestamp() AS now)
                    INSERT INTO asset_upload_intents
                    (id, project_id, asset_id, idempotency_key, request_fingerprint,
                     staging_reference, reserved_bytes, created_at, expires_at,
                     recovery_deadline_at)
                    SELECT :id, :project, :asset, :key, :fingerprint, :staging,
                           :reserved, t.now - INTERVAL '2 minutes',
                           t.now + INTERVAL '1 hour', t.now + INTERVAL '25 hours'
                    FROM t"""),
                {
                    "id": race_intent_id,
                    "project": project_id,
                    "asset": race_asset_id,
                    "key": f"runner-race-{race_intent_id.hex}",
                    "fingerprint": race_observation.sha256,
                    "staging": race_staging.value,
                    "reserved": len(race_payload),
                },
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state='receiving', operation_revision=operation_revision+1,
                    operation_claim_generation=operation_claim_generation+1,
                    operation_claim_token=:token, operation_claimed_at=clock_timestamp(),
                    operation_lease_expires_at=clock_timestamp()+INTERVAL '30 minutes'
                    WHERE id=:id"""),
                {"id": race_intent_id, "token": uuid4()},
            )
            connection.execute(
                text("""UPDATE asset_upload_intents SET
                    operation_state='uploaded', operation_revision=operation_revision+1,
                    operation_claim_token=NULL, operation_claimed_at=NULL,
                    operation_lease_expires_at=NULL, received_bytes=:size,
                    observed_sha256_hex=:digest,
                    transfer_completed_at=clock_timestamp()-INTERVAL '1 minute',
                    recovery_state='pending', recovery_revision=recovery_revision+1
                    WHERE id=:id"""),
                {
                    "id": race_intent_id,
                    "size": len(race_payload),
                    "digest": race_observation.sha256,
                },
            )
        connection.commit()

        race_engine = create_engine(
            database_config.url,
            connect_args={"options": f"-csearch_path={schema}"},
            hide_parameters=True,
            pool_pre_ping=True,
        )
        race_factory = sessionmaker(
            bind=race_engine, autoflush=False, expire_on_commit=False
        )
        start_gate = Barrier(2)

        def invoke_racing_runner():
            race_coordinator = LocalUploadRecoveryCoordinator(
                race_factory,
                AssetServiceConfig(1000, timedelta(hours=2)),
                storage,
                repository_factory=lambda session: AssetRecoveryRepository(
                    session, random_source=lambda lower, upper: upper
                ),
            )
            start_gate.wait(timeout=5)
            return AssetRecoveryRunner(
                race_coordinator, max_operations=2, time_budget_seconds=30
            ).run()

        with ThreadPoolExecutor(max_workers=2) as pool:
            race_results = list(pool.map(lambda _index: invoke_racing_runner(), range(2)))
        assert sum(result.completed for result in race_results) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM asset_versions WHERE upload_intent_id=:id"),
            {"id": race_intent_id},
        ) == 1
        assert connection.execute(
            text("SELECT used_bytes, reserved_bytes FROM project_asset_usage WHERE project_id=:project"),
            {"project": project_id},
        ).one() == (
            sum(map(len, payloads)) + len(race_payload),
            len(retry_payload),
        )
        connection.commit()
    finally:
        alembic_config.attributes.pop("connection", None)
        if race_engine is not None:
            race_engine.dispose()
        if connection is not None:
            connection.close()
        with engine.begin() as cleanup:
            cleanup.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        with engine.connect() as verify:
            assert verify.scalar(
                text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"),
                {"schema": schema},
            ) == 0
        engine.dispose()
