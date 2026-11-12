"""Database-only, fenced transitions for durable asset upload recovery.

The caller owns the SQLAlchemy transaction. This module performs no storage
I/O, validation, quota accounting, commit, or rollback operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from adforge_renderer.database.models import (
    ASSET_RECOVERY_LEASE_RENEWAL_INTERVAL,
    ASSET_RECOVERY_MAX_LEASE,
    ASSET_RECOVERY_MAX_ATTEMPTS,
    Asset,
    AssetUploadIntent,
    ProjectAssetUsage,
)


_RENEWAL_CADENCE_SQL = text(
    f"INTERVAL '{int(ASSET_RECOVERY_LEASE_RENEWAL_INTERVAL.total_seconds())} seconds'"
)
_MAX_INTEGER = 2_147_483_647
_MANUAL_OUTCOMES = frozenset({"legacy_ambiguous", "permanent_failure"})


class AssetRecoveryConflict(RuntimeError):
    """A recovery transition was stale, ineligible, or no longer owned."""


@dataclass(frozen=True, slots=True)
class RecoveryFence:
    """The complete compare-and-set fence expected by recovery workers."""

    claim_token: UUID
    claim_generation: int
    recovery_revision: int
    expected_state: str = "claimed"

    def __post_init__(self) -> None:
        if not isinstance(self.claim_token, UUID):
            raise ValueError("A recovery claim token is required.")
        if type(self.claim_generation) is not int or self.claim_generation < 1:
            raise ValueError("A positive recovery claim generation is required.")
        if type(self.recovery_revision) is not int or self.recovery_revision < 1:
            raise ValueError("A positive recovery revision is required.")
        if self.expected_state not in {"pending", "claimed"}:
            raise ValueError("Recovery fence state must be pending or claimed.")


@dataclass(frozen=True, slots=True)
class RecoveryClaim:
    intent_id: UUID
    project_id: UUID
    asset_id: UUID
    claim_token: UUID
    claim_generation: int
    recovery_revision: int
    attempt_count: int
    lease_expires_at: datetime

    @classmethod
    def from_intent(cls, intent: AssetUploadIntent) -> RecoveryClaim:
        if (
            intent.recovery_claim_token is None
            or intent.recovery_lease_expires_at is None
        ):
            raise AssetRecoveryConflict("The database did not return a complete recovery claim.")
        return cls(
            intent_id=intent.id,
            project_id=intent.project_id,
            asset_id=intent.asset_id,
            claim_token=intent.recovery_claim_token,
            claim_generation=intent.recovery_claim_generation,
            recovery_revision=intent.recovery_revision,
            attempt_count=intent.recovery_attempt_count,
            lease_expires_at=intent.recovery_lease_expires_at,
        )

    @property
    def fence(self) -> RecoveryFence:
        return RecoveryFence(
            self.claim_token,
            self.claim_generation,
            self.recovery_revision,
        )


class AssetRecoveryRepository:
    """Atomic recovery claims and compare-and-set state transitions.

    Lock order is always project usage -> asset -> upload intent. Every method
    leaves transaction ownership with its caller. Recovery deadlines and lease
    decisions use PostgreSQL ``clock_timestamp()``; application clocks are not
    accepted for these security-sensitive comparisons.
    """

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("An active SQLAlchemy Session is required.")
        self.session = session

    def _require_postgresql(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Asset recovery transitions require PostgreSQL database time and row locks.")

    @staticmethod
    def _fence_predicates(intent_id: UUID, fence: RecoveryFence):
        """Return the mandatory token/generation/revision/state CAS predicates."""
        return (
            AssetUploadIntent.id == intent_id,
            AssetUploadIntent.recovery_claim_token == fence.claim_token,
            AssetUploadIntent.recovery_claim_generation == fence.claim_generation,
            AssetUploadIntent.recovery_revision == fence.recovery_revision,
            AssetUploadIntent.recovery_state == fence.expected_state,
        )

    @staticmethod
    def _snapshot_predicates(intent: AssetUploadIntent):
        token = intent.recovery_claim_token
        token_predicate = (
            AssetUploadIntent.recovery_claim_token.is_(None)
            if token is None
            else AssetUploadIntent.recovery_claim_token == token
        )
        return (
            AssetUploadIntent.id == intent.id,
            token_predicate,
            AssetUploadIntent.recovery_claim_generation == intent.recovery_claim_generation,
            AssetUploadIntent.recovery_revision == intent.recovery_revision,
            AssetUploadIntent.recovery_state == intent.recovery_state,
        )

    def _lock_intent(self, intent_id: UUID) -> AssetUploadIntent | None:
        """Lock the known project's rows using the global asset lock order."""
        locator = self.session.execute(
            select(AssetUploadIntent.project_id, AssetUploadIntent.asset_id)
            .where(AssetUploadIntent.id == intent_id)
            .execution_options(autoflush=False)
        ).first()
        if locator is None:
            return None
        project_id, asset_id = locator

        usage = self.session.scalar(
            select(ProjectAssetUsage)
            .where(ProjectAssetUsage.project_id == project_id)
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        )
        if usage is None:
            return None
        asset = self.session.scalar(
            select(Asset)
            .where(Asset.project_id == project_id, Asset.id == asset_id)
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        )
        if asset is None:
            return None
        return self.session.scalar(
            select(AssetUploadIntent)
            .where(
                AssetUploadIntent.id == intent_id,
                AssetUploadIntent.project_id == project_id,
                AssetUploadIntent.asset_id == asset_id,
            )
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        )

    def _update(self, statement) -> AssetUploadIntent | None:
        result = self.session.execute(
            statement.returning(AssetUploadIntent).execution_options(
                autoflush=False,
                populate_existing=True,
                synchronize_session=False,
            )
        )
        return result.scalar_one_or_none()

    def claim_next(
        self,
        *,
        scan_limit: int = 50,
        lease_duration: timedelta = ASSET_RECOVERY_MAX_LEASE,
    ) -> RecoveryClaim | None:
        """Claim one pending item or reclaim one whose prior lease expired.

        Candidate discovery takes no locks. Each candidate is then locked in
        usage -> asset -> intent order and revalidated with all four fencing
        fields in the atomic UPDATE. Concurrent callers therefore cannot steal
        a live lease or issue the same generation twice.
        """
        self._require_postgresql()
        if type(scan_limit) is not int or not 1 <= scan_limit <= 500:
            raise ValueError("Recovery scan limit must be between 1 and 500.")
        if (
            not isinstance(lease_duration, timedelta)
            or lease_duration <= timedelta(0)
            or lease_duration > ASSET_RECOVERY_MAX_LEASE
        ):
            raise ValueError("Recovery lease duration must be positive and at most five minutes.")
        lease_interval = text(
            f"INTERVAL '{lease_duration.total_seconds():.6f} seconds'"
        )
        db_now = func.clock_timestamp()
        eligible_claim_state = or_(
            AssetUploadIntent.recovery_state == "pending",
            and_(
                AssetUploadIntent.recovery_state == "claimed",
                AssetUploadIntent.recovery_lease_expires_at <= db_now,
            ),
        )
        candidate_ids = list(
            self.session.scalars(
                select(AssetUploadIntent.id)
                .where(
                    eligible_claim_state,
                    AssetUploadIntent.recovery_deadline_at > db_now,
                    AssetUploadIntent.recovery_attempt_count < ASSET_RECOVERY_MAX_ATTEMPTS,
                    AssetUploadIntent.recovery_claim_generation < _MAX_INTEGER,
                    AssetUploadIntent.operation_state.in_(("uploaded", "finalizing")),
                )
                .order_by(
                    AssetUploadIntent.recovery_deadline_at,
                    AssetUploadIntent.created_at,
                    AssetUploadIntent.id,
                )
                .limit(scan_limit)
                .execution_options(autoflush=False)
            )
        )

        for intent_id in candidate_ids:
            intent = self._lock_intent(intent_id)
            if intent is None or intent.recovery_state not in {"pending", "claimed"}:
                continue
            previous_token = intent.recovery_claim_token
            previous_state = intent.recovery_state
            previous_generation = intent.recovery_claim_generation
            previous_revision = intent.recovery_revision
            token_predicate = (
                AssetUploadIntent.recovery_claim_token.is_(None)
                if previous_token is None
                else AssetUploadIntent.recovery_claim_token == previous_token
            )
            state_predicate = (
                AssetUploadIntent.recovery_state == "pending"
                if previous_state == "pending"
                else and_(
                    AssetUploadIntent.recovery_state == "claimed",
                    AssetUploadIntent.recovery_lease_expires_at <= func.clock_timestamp(),
                )
            )
            token = uuid4()
            changed = self._update(
                update(AssetUploadIntent)
                .where(
                    AssetUploadIntent.id == intent.id,
                    token_predicate,
                    AssetUploadIntent.recovery_claim_generation == previous_generation,
                    AssetUploadIntent.recovery_revision == previous_revision,
                    state_predicate,
                    AssetUploadIntent.recovery_deadline_at > func.clock_timestamp(),
                    AssetUploadIntent.recovery_attempt_count < ASSET_RECOVERY_MAX_ATTEMPTS,
                    AssetUploadIntent.recovery_claim_generation < _MAX_INTEGER,
                    AssetUploadIntent.operation_state.in_(("uploaded", "finalizing")),
                )
                .values(
                    recovery_state="claimed",
                    recovery_revision=previous_revision + 1,
                    recovery_claim_generation=previous_generation + 1,
                    recovery_claim_token=token,
                    recovery_claimed_at=func.clock_timestamp(),
                    recovery_lease_issued_at=func.clock_timestamp(),
                    recovery_lease_expires_at=func.least(
                        func.clock_timestamp() + lease_interval,
                        AssetUploadIntent.recovery_deadline_at,
                    ),
                    recovery_attempt_count=AssetUploadIntent.recovery_attempt_count + 1,
                    recovery_outcome_code=None,
                )
            )
            if changed is not None:
                return RecoveryClaim.from_intent(changed)
        return None

    def renew(self, intent_id: UUID, fence: RecoveryFence) -> RecoveryClaim | None:
        """Renew a still-live claim after the 60-second application cadence."""
        self._require_postgresql()
        intent = self._lock_intent(intent_id)
        if intent is None:
            return None
        predicates = self._fence_predicates(intent_id, fence)
        db_now = func.clock_timestamp()
        changed = self._update(
            update(AssetUploadIntent)
            .where(
                *predicates,
                AssetUploadIntent.recovery_lease_expires_at > db_now,
                AssetUploadIntent.recovery_deadline_at > db_now,
                AssetUploadIntent.recovery_lease_issued_at
                <= db_now - _RENEWAL_CADENCE_SQL,
            )
            .values(
                recovery_revision=fence.recovery_revision + 1,
                recovery_lease_issued_at=db_now,
                recovery_lease_expires_at=func.least(
                    db_now + text(
                        f"INTERVAL '{ASSET_RECOVERY_MAX_LEASE.total_seconds():.6f} seconds'"
                    ),
                    AssetUploadIntent.recovery_deadline_at,
                ),
            )
        )
        return RecoveryClaim.from_intent(changed) if changed is not None else None

    def complete_finalization(self, intent_id: UUID, fence: RecoveryFence) -> AssetUploadIntent | None:
        """Complete an already-finalizing storage operation under its live fence.

        The caller must have finalized storage and assigned the immutable
        provider/reference in the prior finalizing transition. It must insert
        the exact ``AssetVersion`` in this same transaction after this method
        and before commit; the deferred database trigger rejects a commit that
        lacks that exact version. Quota reconciliation remains separate.
        """
        self._require_postgresql()
        intent = self._lock_intent(intent_id)
        if intent is None:
            return None
        db_now = func.clock_timestamp()
        return self._update(
            update(AssetUploadIntent)
            .where(
                *self._fence_predicates(intent_id, fence),
                AssetUploadIntent.operation_state == "finalizing",
                AssetUploadIntent.final_storage_provider.is_not(None),
                AssetUploadIntent.final_object_version_reference.is_not(None),
                AssetUploadIntent.finalization_started_at.is_not(None),
                AssetUploadIntent.storage_finalized_at.is_(None),
                AssetUploadIntent.recovery_lease_expires_at > db_now,
                AssetUploadIntent.recovery_deadline_at > db_now,
            )
            .values(
                operation_state="finalized",
                operation_revision=AssetUploadIntent.operation_revision + 1,
                storage_finalized_at=db_now,
                recovery_state="completed",
                recovery_revision=fence.recovery_revision + 1,
                recovery_claim_token=None,
                recovery_claimed_at=None,
                recovery_lease_issued_at=None,
                recovery_lease_expires_at=None,
                recovery_outcome_code=None,
            )
        )

    def requeue_expired_claim(self, intent_id: UUID, fence: RecoveryFence) -> AssetUploadIntent | None:
        """Return an expired claim to pending without extending its deadline."""
        self._require_postgresql()
        intent = self._lock_intent(intent_id)
        if intent is None:
            return None
        db_now = func.clock_timestamp()
        return self._update(
            update(AssetUploadIntent)
            .where(
                *self._fence_predicates(intent_id, fence),
                AssetUploadIntent.recovery_lease_expires_at <= db_now,
                AssetUploadIntent.recovery_deadline_at > db_now,
                AssetUploadIntent.recovery_attempt_count < ASSET_RECOVERY_MAX_ATTEMPTS,
            )
            .values(
                recovery_state="pending",
                recovery_revision=fence.recovery_revision + 1,
                recovery_claim_token=None,
                recovery_claimed_at=None,
                recovery_lease_issued_at=None,
                recovery_lease_expires_at=None,
                recovery_outcome_code=None,
            )
        )

    def mark_manual(self, intent_id: UUID, fence: RecoveryFence, *, outcome_code: str) -> AssetUploadIntent | None:
        """Move a live fenced claim to manual reconciliation for a safe reason."""
        self._require_postgresql()
        if outcome_code not in _MANUAL_OUTCOMES:
            raise ValueError("Manual outcome must be legacy_ambiguous or permanent_failure.")
        intent = self._lock_intent(intent_id)
        if intent is None:
            return None
        db_now = func.clock_timestamp()
        return self._update(
            update(AssetUploadIntent)
            .where(
                *self._fence_predicates(intent_id, fence),
                AssetUploadIntent.recovery_lease_expires_at > db_now,
                AssetUploadIntent.recovery_deadline_at > db_now,
            )
            .values(
                recovery_state="manual",
                recovery_revision=fence.recovery_revision + 1,
                recovery_claim_token=None,
                recovery_claimed_at=None,
                recovery_lease_issued_at=None,
                recovery_lease_expires_at=None,
                recovery_outcome_code=outcome_code,
            )
        )

    def mark_attempts_exhausted(self, intent_id: UUID, fence: RecoveryFence) -> AssetUploadIntent | None:
        """Terminalize the current live worker claim at the ten-attempt bound."""
        self._require_postgresql()
        intent = self._lock_intent(intent_id)
        if intent is None:
            return None
        db_now = func.clock_timestamp()
        return self._update(
            update(AssetUploadIntent)
            .where(
                *self._fence_predicates(intent_id, fence),
                AssetUploadIntent.recovery_lease_expires_at > db_now,
                AssetUploadIntent.recovery_attempt_count >= ASSET_RECOVERY_MAX_ATTEMPTS,
            )
            .values(
                recovery_state="exhausted",
                recovery_revision=fence.recovery_revision + 1,
                recovery_claim_token=None,
                recovery_claimed_at=None,
                recovery_lease_issued_at=None,
                recovery_lease_expires_at=None,
                recovery_outcome_code="attempts_exhausted",
            )
        )

    def mark_deadline_elapsed(self, intent_id: UUID) -> AssetUploadIntent | None:
        """Move due pending/expired claims to manual reconciliation using DB time."""
        self._require_postgresql()
        intent = self._lock_intent(intent_id)
        if intent is None or intent.recovery_state not in {"pending", "claimed"}:
            return None
        token_predicate = (
            AssetUploadIntent.recovery_claim_token.is_(None)
            if intent.recovery_claim_token is None
            else AssetUploadIntent.recovery_claim_token == intent.recovery_claim_token
        )
        db_now = func.clock_timestamp()
        lease_is_clear = (
            AssetUploadIntent.recovery_lease_expires_at.is_(None)
            if intent.recovery_state == "pending"
            else AssetUploadIntent.recovery_lease_expires_at <= db_now
        )
        return self._update(
            update(AssetUploadIntent)
            .where(
                AssetUploadIntent.id == intent_id,
                token_predicate,
                AssetUploadIntent.recovery_claim_generation == intent.recovery_claim_generation,
                AssetUploadIntent.recovery_revision == intent.recovery_revision,
                AssetUploadIntent.recovery_state == intent.recovery_state,
                AssetUploadIntent.recovery_deadline_at <= db_now,
                lease_is_clear,
            )
            .values(
                recovery_state="manual",
                recovery_revision=intent.recovery_revision + 1,
                recovery_claim_token=None,
                recovery_claimed_at=None,
                recovery_lease_issued_at=None,
                recovery_lease_expires_at=None,
                recovery_outcome_code="deadline_elapsed",
            )
        )

    def mark_expired_attempts_exhausted(self, intent_id: UUID) -> AssetUploadIntent | None:
        """Terminalize pending or expired claimed work after ten attempts."""
        self._require_postgresql()
        intent = self._lock_intent(intent_id)
        if intent is None or intent.recovery_state not in {"pending", "claimed"}:
            return None
        token_predicate = (
            AssetUploadIntent.recovery_claim_token.is_(None)
            if intent.recovery_claim_token is None
            else AssetUploadIntent.recovery_claim_token == intent.recovery_claim_token
        )
        db_now = func.clock_timestamp()
        lease_is_clear = (
            AssetUploadIntent.recovery_lease_expires_at.is_(None)
            if intent.recovery_state == "pending"
            else AssetUploadIntent.recovery_lease_expires_at <= db_now
        )
        return self._update(
            update(AssetUploadIntent)
            .where(
                AssetUploadIntent.id == intent_id,
                token_predicate,
                AssetUploadIntent.recovery_claim_generation == intent.recovery_claim_generation,
                AssetUploadIntent.recovery_revision == intent.recovery_revision,
                AssetUploadIntent.recovery_state == intent.recovery_state,
                AssetUploadIntent.recovery_attempt_count >= ASSET_RECOVERY_MAX_ATTEMPTS,
                AssetUploadIntent.recovery_deadline_at > db_now,
                lease_is_clear,
            )
            .values(
                recovery_state="exhausted",
                recovery_revision=intent.recovery_revision + 1,
                recovery_claim_token=None,
                recovery_claimed_at=None,
                recovery_lease_issued_at=None,
                recovery_lease_expires_at=None,
                recovery_outcome_code="attempts_exhausted",
            )
        )
