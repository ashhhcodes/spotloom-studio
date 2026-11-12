"""Single-iteration, development-only local upload recovery orchestration.

This coordinator is deliberately not started at application import or startup.
Callers must explicitly construct it with a session factory, the existing
service configuration, and private local storage. It does no polling or sleep.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from time import monotonic
from typing import Callable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .asset_contract import PrivateObjectVersionReference
from .asset_recovery_repository import (
    AssetRecoveryConflict,
    AssetRecoveryRepository,
    RecoveryClaim,
    RecoveryFence,
)
from .asset_service import AssetService, AssetServiceConfig
from .asset_storage_provider import (
    AssetStorageError,
    FinalizedObject,
    PrivateAssetStorage,
    StorageIOFailure,
    StorageObjectMissing,
    StorageObjectIncomplete,
    StorageObjectConflict,
    StorageInvalidReference,
    TemporaryObjectReference,
)
from .database.models import Asset, AssetUploadIntent, AssetVersion, ProjectAssetUsage
from .local_asset_storage import LocalPrivateAssetStorage


LOCAL_STORAGE_PROVIDER = "local-private"


class RecoveryOutcomeKind(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    NOT_CLAIMABLE = "not_claimable"
    RETRY_SCHEDULED = "retry_scheduled"
    MANUAL_RECONCILIATION_REQUIRED = "manual_reconciliation_required"
    STALE_CLAIM = "stale_claim"


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    kind: RecoveryOutcomeKind
    intent_id: UUID | None = None
    next_retry_at: datetime | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class _Operation:
    claim: RecoveryClaim
    fence: RecoveryFence
    temporary: TemporaryObjectReference
    byte_size: int
    sha256: str
    storage_provider: str
    version_reference: PrivateObjectVersionReference | None


RepositoryFactory = Callable[[Session], AssetRecoveryRepository]
ServiceFactory = Callable[[Session, AssetServiceConfig, PrivateAssetStorage], AssetService]


class LocalUploadRecoveryCoordinator:
    """Run at most one claimed local upload recovery operation."""

    def __init__(
        self,
        session_factory: sessionmaker,
        service_config: AssetServiceConfig,
        storage: LocalPrivateAssetStorage,
        *,
        repository_factory: RepositoryFactory = AssetRecoveryRepository,
        service_factory: ServiceFactory | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("An explicit SQLAlchemy session factory is required.")
        if not isinstance(service_config, AssetServiceConfig):
            raise TypeError("Explicit asset service configuration is required.")
        if not isinstance(storage, LocalPrivateAssetStorage):
            raise TypeError("The local recovery coordinator requires private local storage.")
        self._session_factory = session_factory
        self._service_config = service_config
        self._storage = storage
        self._repository_factory = repository_factory
        self._monotonic = monotonic_clock or monotonic
        self._service_factory = service_factory or (
            lambda session, config, provider: AssetService(
                session, config, storage=provider
            )
        )

    def run_once(self) -> RecoveryOutcome:
        """Claim and reconcile at most one item; never hold DB locks for I/O."""
        with self._session_factory.begin() as session:
            claim = self._repository_factory(session).claim_next()
        if claim is None:
            return RecoveryOutcome(RecoveryOutcomeKind.NOT_CLAIMABLE)
        candidate_reference = self._storage.new_object_version_reference()
        with self._session_factory.begin() as session:
            operation = self._prepare_finalization(
                session, claim, candidate_reference
            )
        if operation is None:
            return RecoveryOutcome(
                RecoveryOutcomeKind.STALE_CLAIM, intent_id=claim.intent_id,
                reason_code="operation_not_eligible",
            )

        storage_started = self._monotonic()
        try:
            finalized = self._finalize_storage(operation)
        except (StorageObjectConflict, StorageObjectIncomplete, StorageInvalidReference):
            return self._mark_manual(operation, "permanent_failure")
        except (StorageObjectMissing, StorageIOFailure):
            return self._schedule_retry(operation)
        except AssetStorageError:
            # Unknown storage failures are not interpreted as safe evidence.
            return self._schedule_retry(operation)

        if self._monotonic() - storage_started >= 60.0:
            with self._session_factory.begin() as session:
                renewed = self._repository_factory(session).renew(
                    operation.claim.intent_id, operation.fence
                )
            if renewed is None:
                return RecoveryOutcome(
                    RecoveryOutcomeKind.STALE_CLAIM,
                    intent_id=operation.claim.intent_id,
                    reason_code="lease_renewal_rejected",
                )
            operation = replace(operation, claim=renewed, fence=renewed.fence)

        try:
            with self._session_factory.begin() as session:
                completion = self._service_factory(
                    session, self._service_config, self._storage
                ).complete_recovered_upload(
                    project_id=operation.claim.project_id,
                    asset_id=operation.claim.asset_id,
                    intent_id=operation.claim.intent_id,
                    storage_provider=operation.storage_provider,
                    finalized_object=finalized,
                    fence=operation.fence,
                )
                if completion is None:
                    return RecoveryOutcome(
                        RecoveryOutcomeKind.STALE_CLAIM,
                        intent_id=operation.claim.intent_id,
                        reason_code="completion_fence_rejected",
                    )
                created = completion.created
        except AssetRecoveryConflict:
            return RecoveryOutcome(
                RecoveryOutcomeKind.STALE_CLAIM,
                intent_id=operation.claim.intent_id,
                reason_code="completion_fence_rejected",
            )
        except SQLAlchemyError:
            # A connection can fail after PostgreSQL committed. Treat that as
            # success only after a fresh read proves the exact version,
            # operation, accounting conversion, and manifest all agree.
            if self._verify_committed_completion(operation, finalized):
                return RecoveryOutcome(
                    RecoveryOutcomeKind.ALREADY_COMPLETED,
                    intent_id=operation.claim.intent_id,
                )
            raise

        return RecoveryOutcome(
            RecoveryOutcomeKind.ALREADY_COMPLETED if not created
            else RecoveryOutcomeKind.COMPLETED,
            intent_id=operation.claim.intent_id,
        )

    def _verify_committed_completion(
        self, operation: _Operation, finalized: FinalizedObject
    ) -> bool:
        with self._session_factory() as session:
            rows = session.execute(
                select(AssetUploadIntent, AssetVersion, ProjectAssetUsage)
                .join(
                    AssetVersion,
                    AssetVersion.upload_intent_id == AssetUploadIntent.id,
                )
                .join(
                    ProjectAssetUsage,
                    ProjectAssetUsage.project_id == AssetUploadIntent.project_id,
                )
                .where(
                    AssetUploadIntent.id == operation.claim.intent_id,
                    AssetUploadIntent.project_id == operation.claim.project_id,
                    AssetUploadIntent.asset_id == operation.claim.asset_id,
                    AssetVersion.project_id == operation.claim.project_id,
                    AssetVersion.asset_id == operation.claim.asset_id,
                )
            ).first()
            if rows is None:
                return False
            intent, version, usage = rows
            expected_used = session.scalar(
                select(func.coalesce(func.sum(AssetVersion.byte_size), 0)).where(
                    AssetVersion.project_id == operation.claim.project_id,
                    AssetVersion.storage_state != "deleted",
                )
            )
            expected_reserved = session.scalar(
                select(func.coalesce(func.sum(AssetUploadIntent.reserved_bytes), 0)).where(
                    AssetUploadIntent.project_id == operation.claim.project_id,
                    AssetUploadIntent.state.in_(("open", "expired", "failed")),
                )
            )
            exact = (
                intent.state == "finalized"
                and intent.operation_state == "finalized"
                and intent.recovery_state == "completed"
                and intent.final_storage_provider == operation.storage_provider
                and intent.final_object_version_reference == finalized.object_version.value
                and intent.received_bytes == finalized.byte_size
                and intent.observed_sha256_hex == finalized.sha256
                and version.upload_intent_id == operation.claim.intent_id
                and version.storage_provider == operation.storage_provider
                and version.object_version_reference == finalized.object_version.value
                and version.byte_size == finalized.byte_size
                and version.validation_state == "quarantined"
                and usage.used_bytes == expected_used
                and usage.reserved_bytes == expected_reserved
            )
        if not exact:
            return False
        try:
            verified = self._storage.finalize_temporary_object_preserving_temporary(
                operation.temporary,
                finalized.object_version,
                expected_sha256=finalized.sha256,
                expected_byte_size=finalized.byte_size,
            )
        except AssetStorageError:
            return False
        return (
            verified.project_id == operation.claim.project_id
            and verified.operation_id == operation.claim.intent_id
            and verified.object_version.value == finalized.object_version.value
            and verified.byte_size == finalized.byte_size
            and verified.sha256 == finalized.sha256
        )

    def _prepare_finalization(
        self,
        session: Session,
        claim: RecoveryClaim,
        candidate_reference: PrivateObjectVersionReference,
    ) -> _Operation | None:
        intent = session.scalar(
            select(AssetUploadIntent).where(AssetUploadIntent.id == claim.intent_id)
        )
        asset = session.scalar(
            select(Asset).where(
                Asset.project_id == claim.project_id,
                Asset.id == claim.asset_id,
            )
        )
        db_now = session.scalar(select(func.clock_timestamp()))
        if intent is None or asset is None or not isinstance(db_now, datetime):
            return None
        if (
            intent.project_id != claim.project_id
            or intent.asset_id != claim.asset_id
            or intent.recovery_state != claim.fence.expected_state
            or intent.recovery_claim_token != claim.claim_token
            or intent.recovery_claim_generation != claim.claim_generation
            or intent.recovery_revision != claim.recovery_revision
            or intent.recovery_lease_expires_at is None
            or intent.recovery_lease_expires_at <= db_now
            or intent.recovery_deadline_at <= db_now
            or intent.recovery_attempt_count != claim.attempt_count
            or intent.operation_state not in {"uploaded", "finalizing"}
            or intent.state not in {"open", "expired"}
            or intent.received_bytes <= 0
            or intent.received_bytes > intent.reserved_bytes
            or intent.observed_sha256_hex is None
            or intent.transfer_completed_at is None
            or intent.transfer_completed_at > intent.expires_at
            or asset.deleted_at is not None
        ):
            return None

        reference = TemporaryObjectReference(
            intent.staging_reference, project_id=intent.project_id,
            operation_id=intent.id,
        )
        if intent.operation_state == "uploaded":
            version_ref = candidate_reference
            intent = self._repository_factory(session).begin_finalization(
                intent.id, claim.fence,
                storage_provider=LOCAL_STORAGE_PROVIDER,
                object_version_reference=version_ref,
            )
            if intent is None:
                return None
            provider = LOCAL_STORAGE_PROVIDER
        else:
            if (
                intent.final_storage_provider != LOCAL_STORAGE_PROVIDER
                or intent.final_object_version_reference is None
            ):
                return None
            version_ref = PrivateObjectVersionReference(
                value=intent.final_object_version_reference
            )
            provider = intent.final_storage_provider

        return _Operation(
            claim=claim, fence=claim.fence, temporary=reference,
            byte_size=intent.received_bytes,
            sha256=intent.observed_sha256_hex,
            storage_provider=provider,
            version_reference=version_ref,
        )

    def _finalize_storage(self, operation: _Operation) -> FinalizedObject:
        reference = operation.version_reference
        if reference is None:
            raise StorageObjectIncomplete()
        temporary_was_present = True
        try:
            temporary = self._storage.inspect_temporary_object(operation.temporary)
        except StorageObjectMissing:
            temporary_was_present = False
            temporary = None
        if temporary is not None and (
            not temporary.complete
            or temporary.byte_size != operation.byte_size
            or temporary.sha256 != operation.sha256
        ):
            raise StorageObjectIncomplete()

        # Reconcile an existing immutable object before attempting a create.
        # The manifest-aware finalizer below then proves project/operation/temp
        # provenance; this observation alone is never adopted as trusted.
        try:
            observed = self._storage.inspect_finalized_object(reference)
        except StorageObjectMissing:
            observed = None
        if observed is not None and (
            observed.byte_size != operation.byte_size
            or observed.sha256 != operation.sha256
        ):
            raise StorageObjectConflict()

        finalized = self._storage.finalize_temporary_object_preserving_temporary(
            operation.temporary,
            reference,
            expected_sha256=operation.sha256,
            expected_byte_size=operation.byte_size,
        )
        if (
            finalized.object_version.value != reference.value
            or finalized.byte_size != operation.byte_size
            or finalized.sha256 != operation.sha256
            or finalized.project_id != operation.claim.project_id
            or finalized.operation_id != operation.claim.intent_id
            or (temporary_was_present and not finalized.temporary_preserved)
        ):
            raise StorageObjectConflict()
        if temporary_was_present:
            retained = self._storage.inspect_temporary_object(operation.temporary)
            if (
                not retained.complete
                or retained.byte_size != operation.byte_size
                or retained.sha256 != operation.sha256
            ):
                raise StorageObjectConflict()
        return finalized

    def _schedule_retry(self, operation: _Operation) -> RecoveryOutcome:
        with self._session_factory.begin() as session:
            result = self._repository_factory(session).record_retryable_failure(
                operation.claim.intent_id, operation.fence
            )
            if result is None:
                return RecoveryOutcome(
                    RecoveryOutcomeKind.STALE_CLAIM,
                    intent_id=operation.claim.intent_id,
                    reason_code="retry_fence_rejected",
                )
            if result.next_retry_at is None:
                return RecoveryOutcome(
                    RecoveryOutcomeKind.MANUAL_RECONCILIATION_REQUIRED,
                    intent_id=operation.claim.intent_id,
                    reason_code=result.intent.recovery_outcome_code or "recovery_stopped",
                )
            return RecoveryOutcome(
                RecoveryOutcomeKind.RETRY_SCHEDULED,
                intent_id=operation.claim.intent_id,
                next_retry_at=result.next_retry_at,
            )

    def _mark_manual(self, operation: _Operation, reason: str) -> RecoveryOutcome:
        with self._session_factory.begin() as session:
            changed = self._repository_factory(session).mark_manual(
                operation.claim.intent_id, operation.fence,
                outcome_code=reason,
            )
        if changed is None:
            return RecoveryOutcome(
                RecoveryOutcomeKind.STALE_CLAIM,
                intent_id=operation.claim.intent_id,
                reason_code="manual_transition_fence_rejected",
            )
        return RecoveryOutcome(
            RecoveryOutcomeKind.MANUAL_RECONCILIATION_REQUIRED,
            intent_id=operation.claim.intent_id,
            reason_code=reason,
        )
