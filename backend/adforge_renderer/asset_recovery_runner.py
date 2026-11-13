"""Explicit, bounded invocations of the local asset recovery coordinator.

The runner is development-only and is never started by application import or
startup. Each coordinator call remains authoritative for claim discovery and
fencing; this module only bounds and summarizes one caller-requested run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from threading import Lock
from time import monotonic
from typing import Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from .asset_recovery_coordinator import RecoveryOutcome, RecoveryOutcomeKind
from .database.config import DatabaseConfigurationError
from .database.engine import DatabaseOperationError


DEFAULT_MAX_OPERATIONS = 10
DEFAULT_TIME_BUDGET_SECONDS = 60.0


class RecoveryRunnerStopReason(StrEnum):
    OPERATION_LIMIT_REACHED = "operation_limit_reached"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    TIME_BUDGET_EXCEEDED_AFTER_OPERATION = "time_budget_exceeded_after_operation"
    NO_ELIGIBLE_WORK = "no_eligible_work"
    UNEXPECTED_ERROR = "unexpected_error"


class RecoveryCoordinator(Protocol):
    """The existing one-operation coordinator contract used by the runner."""

    def run_once(self) -> RecoveryOutcome: ...


@dataclass(frozen=True, slots=True)
class RecoveryRunResult:
    """Immutable, secret-free summary of one explicit runner invocation."""

    invocation_id: UUID
    started_at: datetime
    finished_at: datetime
    operations_attempted: int
    completed: int
    already_completed: int
    not_claimable: int
    retry_scheduled: int
    manual_reconciliation_required: int
    stale_claim: int
    unexpected_failures: int
    failure_category: str | None
    stop_reason: RecoveryRunnerStopReason
    operation_limit_reached: bool
    time_budget_exhausted: bool
    time_budget_exceeded_after_operation: bool

    def __post_init__(self) -> None:
        if not isinstance(self.invocation_id, UUID):
            raise TypeError("invocation_id must be a UUID.")
        for name in ("started_at", "finished_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware.")
            object.__setattr__(self, name, value.astimezone(timezone.utc))
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at.")
        counters = (
            self.operations_attempted,
            self.completed,
            self.already_completed,
            self.not_claimable,
            self.retry_scheduled,
            self.manual_reconciliation_required,
            self.stale_claim,
            self.unexpected_failures,
        )
        if any(type(value) is not int or value < 0 for value in counters):
            raise ValueError("Run counters must be nonnegative integers.")
        outcomes = (
            self.completed
            + self.already_completed
            + self.not_claimable
            + self.retry_scheduled
            + self.manual_reconciliation_required
            + self.stale_claim
            + self.unexpected_failures
        )
        if outcomes != self.operations_attempted:
            raise ValueError("Outcome counters must equal operations_attempted.")
        if self.unexpected_failures not in {0, 1}:
            raise ValueError("The runner stops after its first unexpected failure.")
        if (self.failure_category is None) != (self.unexpected_failures == 0):
            raise ValueError("Failure category must match unexpected failure count.")
        if self.failure_category not in {
            None,
            "database_error",
            "configuration_error",
            "unexpected_error",
        }:
            raise ValueError("failure_category is not a supported sanitized category.")
        if not isinstance(self.stop_reason, RecoveryRunnerStopReason):
            raise TypeError("stop_reason must be a RecoveryRunnerStopReason.")
        for name in (
            "operation_limit_reached",
            "time_budget_exhausted",
            "time_budget_exceeded_after_operation",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean.")
        if self.time_budget_exhausted and self.time_budget_exceeded_after_operation:
            raise ValueError("Budget exhaustion and post-operation overrun are distinct.")


class AssetRecoveryRunner:
    """Run coordinator operations sequentially with finite work and time bounds."""

    def __init__(
        self,
        coordinator: RecoveryCoordinator,
        *,
        max_operations: int = DEFAULT_MAX_OPERATIONS,
        time_budget_seconds: float | None = DEFAULT_TIME_BUDGET_SECONDS,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        if not callable(getattr(coordinator, "run_once", None)):
            raise TypeError("An existing recovery coordinator is required.")
        if (
            type(max_operations) is not int
            or max_operations <= 0
            or max_operations > DEFAULT_MAX_OPERATIONS
        ):
            raise ValueError("max_operations must be between 1 and 10.")
        if time_budget_seconds is not None and (
            isinstance(time_budget_seconds, bool)
            or not isinstance(time_budget_seconds, (int, float))
            or not math.isfinite(time_budget_seconds)
            or time_budget_seconds <= 0
        ):
            raise ValueError("time_budget_seconds must be finite and positive, or None.")
        self._coordinator = coordinator
        self._max_operations = max_operations
        self._time_budget = (
            float(time_budget_seconds) if time_budget_seconds is not None else None
        )
        self._monotonic = monotonic_clock or monotonic
        self._run_lock = Lock()

    def run(self) -> RecoveryRunResult:
        """Run at most the configured calls; never sleeps or cancels in-flight work."""
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("A recovery runner invocation is already active.")
        try:
            return self._run_locked()
        finally:
            self._run_lock.release()

    def _run_locked(self) -> RecoveryRunResult:
        invocation_id = uuid4()
        started_at = datetime.now(timezone.utc)
        last_clock_value = self._read_monotonic()
        started_clock = last_clock_value

        def read_clock() -> float:
            nonlocal last_clock_value
            value = self._read_monotonic()
            if value < last_clock_value:
                raise RuntimeError("Monotonic clock moved backwards.")
            last_clock_value = value
            return value

        counters = {kind: 0 for kind in RecoveryOutcomeKind}
        attempted = 0
        unexpected_failures = 0
        failure_category: str | None = None
        operation_limit_reached = False
        time_budget_exhausted = False
        time_budget_exceeded_after_operation = False
        stop_reason: RecoveryRunnerStopReason | None = None

        while attempted < self._max_operations:
            if self._time_budget is not None:
                elapsed = read_clock() - started_clock
                if elapsed >= self._time_budget:
                    time_budget_exhausted = True
                    stop_reason = RecoveryRunnerStopReason.TIME_BUDGET_EXHAUSTED
                    break

            attempted += 1
            try:
                outcome = self._coordinator.run_once()
                if not isinstance(outcome, RecoveryOutcome):
                    raise TypeError("Coordinator returned an unsupported outcome.")
                counters[outcome.kind] += 1
            except Exception as exc:
                unexpected_failures += 1
                failure_category = _failure_category(exc)
                if self._time_budget is not None:
                    time_budget_exceeded_after_operation = (
                        read_clock() - started_clock >= self._time_budget
                    )
                stop_reason = RecoveryRunnerStopReason.UNEXPECTED_ERROR
                break

            elapsed_after = (
                read_clock() - started_clock
                if self._time_budget is not None
                else 0.0
            )
            if self._time_budget is not None and elapsed_after >= self._time_budget:
                time_budget_exceeded_after_operation = True
            if outcome.kind is RecoveryOutcomeKind.NOT_CLAIMABLE:
                stop_reason = RecoveryRunnerStopReason.NO_ELIGIBLE_WORK
                break
            if attempted >= self._max_operations:
                operation_limit_reached = True
                stop_reason = RecoveryRunnerStopReason.OPERATION_LIMIT_REACHED
                break
            if self._time_budget is not None and elapsed_after >= self._time_budget:
                stop_reason = RecoveryRunnerStopReason.TIME_BUDGET_EXCEEDED_AFTER_OPERATION
                break

        if stop_reason is None:
            stop_reason = RecoveryRunnerStopReason.OPERATION_LIMIT_REACHED
        operation_limit_reached = attempted >= self._max_operations

        finished_at = datetime.now(timezone.utc)
        return RecoveryRunResult(
            invocation_id=invocation_id,
            started_at=started_at,
            finished_at=finished_at,
            operations_attempted=attempted,
            completed=counters[RecoveryOutcomeKind.COMPLETED],
            already_completed=counters[RecoveryOutcomeKind.ALREADY_COMPLETED],
            not_claimable=counters[RecoveryOutcomeKind.NOT_CLAIMABLE],
            retry_scheduled=counters[RecoveryOutcomeKind.RETRY_SCHEDULED],
            manual_reconciliation_required=counters[
                RecoveryOutcomeKind.MANUAL_RECONCILIATION_REQUIRED
            ],
            stale_claim=counters[RecoveryOutcomeKind.STALE_CLAIM],
            unexpected_failures=unexpected_failures,
            failure_category=failure_category,
            stop_reason=stop_reason,
            operation_limit_reached=operation_limit_reached,
            time_budget_exhausted=time_budget_exhausted,
            time_budget_exceeded_after_operation=time_budget_exceeded_after_operation,
        )

    def _read_monotonic(self) -> float:
        value = self._monotonic()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise RuntimeError("Monotonic clock returned an invalid value.")
        return float(value)


def _failure_category(exc: Exception) -> str:
    if isinstance(exc, (DatabaseConfigurationError,)):
        return "configuration_error"
    if isinstance(exc, (DatabaseOperationError, SQLAlchemyError)):
        return "database_error"
    return "unexpected_error"
