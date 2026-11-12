"""Transactional asset repository services for the pre-storage foundation.

All methods use the caller's SQLAlchemy transaction. They perform no storage I/O,
accept no client integrity metadata, and never commit or hold a transaction across
an upload or cleanup operation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from adforge_renderer.asset_repository import AssetRepository
from adforge_renderer.asset_storage_provider import (
    FinalizedObject,
    PrivateAssetStorage,
    TemporaryObjectReference,
)
from adforge_renderer.asset_recovery_repository import (
    AssetRecoveryConflict,
    AssetRecoveryRepository,
    RecoveryFence,
)
from adforge_renderer.database.models import (
    Asset,
    AssetUploadIntent,
    AssetVersion,
    ProjectAssetUsage,
)

MAX_DATABASE_BYTE_COUNT = (1 << 63) - 1


class AssetOperationConflict(RuntimeError):
    """The requested transition conflicts with the persisted lifecycle state."""


class AssetIntentConflict(AssetOperationConflict):
    """An idempotency key was reused for a different request."""


class AssetQuotaExceeded(RuntimeError):
    """The project's configured quota cannot accommodate the reservation."""


class AssetCleanupNotConfirmed(RuntimeError):
    """Quota cannot be released until trusted cleanup confirms byte removal."""


class AssetServiceConfigurationError(ValueError):
    """Required quota and upload lifetime configuration is invalid or absent."""


@dataclass(frozen=True, slots=True)
class AssetServiceConfig:
    """Per-project quota and upload bounds; no product limit is implicit here."""

    project_quota_limit_bytes: int
    maximum_upload_intent_lifetime: timedelta

    def __post_init__(self) -> None:
        if (
            type(self.project_quota_limit_bytes) is not int
            or not 0 < self.project_quota_limit_bytes <= MAX_DATABASE_BYTE_COUNT
        ):
            raise AssetServiceConfigurationError("A positive project quota configuration is required.")
        lifetime = self.maximum_upload_intent_lifetime
        if not isinstance(lifetime, timedelta) or lifetime <= timedelta(0):
            raise AssetServiceConfigurationError("A positive upload-intent lifetime is required.")


@dataclass(frozen=True, slots=True)
class UploadIntentResult:
    intent: AssetUploadIntent
    created: bool


@dataclass(frozen=True, slots=True)
class RecoveredUploadCompletion:
    """Atomic recovery completion outcome; never implies validation readiness."""

    intent: AssetUploadIntent
    version: AssetVersion
    created: bool


class AssetService:
    """Owner-scoped asset and quota operations inside a caller-owned transaction.

    Lock order is always project usage -> asset -> upload intent/version. Storage
    code must run before or after these short transactions, never inside them.
    """

    def __init__(
        self,
        session: Session,
        config: AssetServiceConfig,
        *,
        clock: Callable[[], datetime] | None = None,
        storage: PrivateAssetStorage | None = None,
    ) -> None:
        if not isinstance(config, AssetServiceConfig):
            raise AssetServiceConfigurationError("Explicit asset service configuration is required.")
        self.session = session
        self.config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.storage = storage

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("Asset service clock must return a timezone-aware datetime.")
        return value.astimezone(timezone.utc)

    def _lock_usage(self, project_id: UUID) -> ProjectAssetUsage:
        """Create usage row race-safely, then serialize project accounting."""
        values = {"project_id": project_id, "quota_limit_bytes": self.config.project_quota_limit_bytes}
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(ProjectAssetUsage).values(**values).on_conflict_do_nothing(
                index_elements=[ProjectAssetUsage.project_id]
            )
            self.session.execute(statement)
        elif dialect == "sqlite":
            statement = sqlite_insert(ProjectAssetUsage).values(**values).on_conflict_do_nothing(
                index_elements=[ProjectAssetUsage.project_id]
            )
            self.session.execute(statement)
        else:
            try:
                with self.session.begin_nested():
                    self.session.add(ProjectAssetUsage(**values))
                    self.session.flush()
            except IntegrityError:
                # Only treat the failed initialization as a race if a row now
                # exists. Otherwise preserve the database failure for the caller.
                existing = self.session.scalar(
                    select(ProjectAssetUsage).where(ProjectAssetUsage.project_id == project_id)
                )
                if existing is None:
                    raise
        row = self.session.scalar(
            select(ProjectAssetUsage)
            .where(ProjectAssetUsage.project_id == project_id)
            .with_for_update()
        )
        if row is None:
            raise AssetOperationConflict("Project quota accounting is unavailable.")
        return row

    @staticmethod
    def _adjust_usage(row: ProjectAssetUsage, *, used: int = 0, reserved: int = 0) -> None:
        next_used = row.used_bytes + used
        next_reserved = row.reserved_bytes + reserved
        if next_used < 0 or next_reserved < 0:
            raise AssetOperationConflict("Project quota accounting would become negative.")
        if next_used + next_reserved > row.quota_limit_bytes:
            raise AssetQuotaExceeded("The project's configured asset quota would be exceeded.")
        row.used_bytes = next_used
        row.reserved_bytes = next_reserved
        row.accounting_revision += 1

    def create_asset(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        kind: str,
        display_name: str | None = None,
    ) -> Asset | None:
        if kind not in {"audio", "image"}:
            raise ValueError("Asset kind must be audio or image.")
        if display_name is not None and (type(display_name) is not str or not display_name.strip() or len(display_name) > 255):
            raise ValueError("Asset display name must contain 1 to 255 characters.")
        if not AssetRepository.project_is_owned(self.session, project_id, owner_user_id):
            return None
        self._lock_usage(project_id)
        return AssetRepository.create_asset(
            self.session,
            project_id=project_id,
            owner_user_id=owner_user_id,
            kind=kind,
            display_name=display_name.strip() if display_name else None,
        )

    def list_assets(
        self,
        *, project_id: UUID, owner_user_id: UUID, limit: int = 50,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[Asset] | None:
        return AssetRepository.list_active_assets(
            self.session, project_id=project_id, owner_user_id=owner_user_id,
            limit=limit, after=after,
        )

    def get_asset(self, *, project_id: UUID, asset_id: UUID, owner_user_id: UUID) -> Asset | None:
        return AssetRepository.get_active_asset(
            self.session, project_id=project_id, asset_id=asset_id, owner_user_id=owner_user_id
        )

    def _request_fingerprint(
        self, *, asset_id: UUID, reserved_bytes: int, lifetime: timedelta
    ) -> str:
        payload = json.dumps(
            {
                "asset_id": str(asset_id),
                "reserved_bytes": reserved_bytes,
                "lifetime_microseconds": (lifetime.days * 86400 + lifetime.seconds) * 1_000_000
                + lifetime.microseconds,
            },
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def create_upload_intent(
        self,
        *, project_id: UUID,
        asset_id: UUID,
        owner_user_id: UUID,
        idempotency_key: str,
        reserved_bytes: int,
        lifetime: timedelta,
    ) -> UploadIntentResult | None:
        if type(idempotency_key) is not str or not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("A nonblank idempotency key of at most 200 characters is required.")
        if type(reserved_bytes) is not int or not 0 < reserved_bytes <= MAX_DATABASE_BYTE_COUNT:
            raise ValueError("Reserved byte count must be a positive integer.")
        if not isinstance(lifetime, timedelta) or lifetime <= timedelta(0) or lifetime > self.config.maximum_upload_intent_lifetime:
            raise ValueError("Upload-intent lifetime is outside the configured bound.")
        # Check ownership before creating even an empty quota row; unauthorized
        # requests must not cause project-scoped database mutations.
        if not AssetRepository.project_is_owned(self.session, project_id, owner_user_id):
            return None
        usage = self._lock_usage(project_id)
        asset = AssetRepository.get_active_asset(
            self.session, project_id=project_id, asset_id=asset_id,
            owner_user_id=owner_user_id, for_update=True,
        )
        if asset is None:
            return None
        key = idempotency_key
        fingerprint = self._request_fingerprint(
            asset_id=asset_id, reserved_bytes=reserved_bytes, lifetime=lifetime
        )
        existing = self.session.scalar(
            select(AssetUploadIntent).where(
                AssetUploadIntent.project_id == project_id,
                AssetUploadIntent.idempotency_key == key,
            ).with_for_update()
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise AssetIntentConflict("The idempotency key was already used for a different request.")
            return UploadIntentResult(existing, False)

        if self.storage is None:
            raise AssetServiceConfigurationError(
                "Private storage reference allocation is required for new upload intents."
            )
        intent_id = uuid4()
        temporary_reference = self.storage.allocate_temporary_reference(
            project_id=project_id, operation_id=intent_id
        )
        if (
            type(temporary_reference) is not TemporaryObjectReference
            or temporary_reference.project_id != project_id
            or temporary_reference.operation_id != intent_id
            or type(temporary_reference.value) is not str
            or not temporary_reference.value
        ):
            raise AssetServiceConfigurationError(
                "Private storage returned an invalid temporary reference."
            )

        now = self._now()
        intent = AssetUploadIntent(
            id=intent_id,
            project_id=project_id,
            asset_id=asset_id,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            staging_reference=temporary_reference.value,
            reserved_bytes=reserved_bytes,
            received_bytes=0,
            state="open",
            created_at=now,
            expires_at=now + lifetime,
        )
        try:
            with self.session.begin_nested():
                # Reservation and intent persistence share a savepoint so a
                # rejected/failed insert cannot leave quota partially held if
                # an internal caller elects to recover the outer transaction.
                self._adjust_usage(usage, reserved=reserved_bytes)
                self.session.add(intent)
                self.session.flush()
        except IntegrityError as exc:
            constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint_name != "uq_upload_intents_project_idempotency":
                raise
            # The unique project/key constraint is final authority. Re-read after
            # rolling back only this savepoint, leaving the outer txn usable.
            existing = self.session.scalar(
                select(AssetUploadIntent).where(
                    AssetUploadIntent.project_id == project_id,
                    AssetUploadIntent.idempotency_key == key,
                ).with_for_update()
            )
            if existing is None or existing.request_fingerprint != fingerprint:
                raise AssetIntentConflict("The idempotency key conflicted with another request.") from None
            return UploadIntentResult(existing, False)
        return UploadIntentResult(intent, True)

    def expire_upload_intent(self, *, project_id: UUID, asset_id: UUID, intent_id: UUID) -> AssetUploadIntent | None:
        usage = self._lock_usage(project_id)
        asset = self.session.scalar(
            select(Asset).where(Asset.project_id == project_id, Asset.id == asset_id).with_for_update()
        )
        if asset is None:
            return None
        intent = self.session.scalar(
            select(AssetUploadIntent).where(
                AssetUploadIntent.project_id == project_id,
                AssetUploadIntent.asset_id == asset_id,
                AssetUploadIntent.id == intent_id,
            ).with_for_update()
        )
        if intent is None:
            return None
        if intent.state == "open" and intent.expires_at <= self._now():
            intent.state = "expired"
            # Reservation is retained until cleanup confirms temporary bytes gone.
            usage.accounting_revision += 1
        return intent

    def mark_intent_failed_for_cleanup(self, *, project_id: UUID, asset_id: UUID, intent_id: UUID) -> AssetUploadIntent | None:
        usage = self._lock_usage(project_id)
        asset = self.session.scalar(
            select(Asset).where(Asset.project_id == project_id, Asset.id == asset_id).with_for_update()
        )
        if asset is None:
            return None
        intent = self.session.scalar(
            select(AssetUploadIntent).where(
                AssetUploadIntent.project_id == project_id,
                AssetUploadIntent.asset_id == asset_id,
                AssetUploadIntent.id == intent_id,
            ).with_for_update()
        )
        if intent is None:
            return None
        if intent.state == "open":
            intent.state = "failed"
            usage.accounting_revision += 1
        return intent

    def reconcile_finalized_upload(self, *, project_id: UUID, asset_id: UUID, intent_id: UUID, actual_bytes: int) -> AssetUploadIntent | None:
        """Reconcile after a future trusted finalizer verifies completed bytes."""
        if type(actual_bytes) is not int or not 0 < actual_bytes <= MAX_DATABASE_BYTE_COUNT:
            raise ValueError("Finalized byte count must be a positive integer.")
        usage = self._lock_usage(project_id)
        asset = self.session.scalar(
            select(Asset).where(Asset.project_id == project_id, Asset.id == asset_id).with_for_update()
        )
        if asset is None:
            return None
        intent = self.session.scalar(
            select(AssetUploadIntent).where(
                AssetUploadIntent.project_id == project_id,
                AssetUploadIntent.asset_id == asset_id,
                AssetUploadIntent.id == intent_id,
            ).with_for_update()
        )
        if intent is None:
            return None
        if intent.state == "finalized":
            if intent.received_bytes == actual_bytes:
                return intent
            raise AssetOperationConflict("Finalized intent cannot be rebound to different bytes.")
        if intent.state != "open" or intent.expires_at <= self._now():
            raise AssetOperationConflict("Only an unexpired open intent can be finalized.")
        if actual_bytes > intent.reserved_bytes:
            raise AssetQuotaExceeded("Finalized bytes exceed the upload reservation.")
        self._adjust_usage(usage, reserved=-intent.reserved_bytes, used=actual_bytes)
        intent.received_bytes = actual_bytes
        intent.state = "finalized"
        intent.finalized_at = self._now()
        return intent

    def complete_recovered_upload(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        intent_id: UUID,
        storage_provider: str,
        finalized_object: FinalizedObject,
        fence: RecoveryFence,
    ) -> RecoveredUploadCompletion | None:
        """Atomically persist a recovered immutable version and quota conversion.

        The caller obtains ``finalized_object`` from trusted storage inspection
        outside this transaction. This method only accepts the typed inspection
        result, then compares it to persisted transfer and operation facts. It
        performs no filesystem I/O and never commits the caller's transaction.
        """
        if type(finalized_object) is not FinalizedObject:
            raise AssetOperationConflict("A verified private-storage result is required.")
        if (
            finalized_object.project_id != project_id
            or finalized_object.operation_id != intent_id
            or type(storage_provider) is not str
            or not storage_provider.strip()
        ):
            raise AssetOperationConflict("Finalized storage provenance does not match the upload operation.")

        # Global lock order: usage -> asset -> intent/version.
        usage = self._lock_usage(project_id)
        asset = self.session.scalar(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.id == asset_id,
            ).with_for_update()
        )
        if asset is None:
            return None
        intent = self.session.scalar(
            select(AssetUploadIntent).where(
                AssetUploadIntent.project_id == project_id,
                AssetUploadIntent.asset_id == asset_id,
                AssetUploadIntent.id == intent_id,
            ).with_for_update()
        )
        if intent is None:
            return None

        version = self.session.scalar(
            select(AssetVersion)
            .where(AssetVersion.upload_intent_id == intent_id)
            .with_for_update()
        )
        if intent.operation_state == "finalized" and intent.state == "finalized":
            if (
                version is None
                or version.project_id != project_id
                or version.asset_id != asset_id
                or version.upload_intent_id != intent_id
                or version.storage_provider != storage_provider.strip()
                or version.object_version_reference != finalized_object.object_version.value
                or version.byte_size != finalized_object.byte_size
                or intent.final_storage_provider != storage_provider.strip()
                or intent.final_object_version_reference != finalized_object.object_version.value
                or intent.received_bytes != finalized_object.byte_size
                or intent.observed_sha256_hex != finalized_object.sha256
                or version.validation_state != "quarantined"
                or usage.used_bytes < version.byte_size
            ):
                raise AssetOperationConflict("Previously completed upload state does not match verified storage.")
            return RecoveredUploadCompletion(intent, version, False)

        if (
            intent.operation_state != "finalizing"
            or intent.state not in {"open", "expired"}
            or intent.final_storage_provider != storage_provider.strip()
            or intent.final_object_version_reference != finalized_object.object_version.value
            or intent.finalization_started_at is None
            or intent.received_bytes <= 0
            or intent.received_bytes > intent.reserved_bytes
            or intent.observed_sha256_hex is None
            or intent.transfer_completed_at is None
            or intent.transfer_completed_at > intent.expires_at
            or intent.received_bytes != finalized_object.byte_size
            or intent.observed_sha256_hex != finalized_object.sha256
            or finalized_object.byte_size <= 0
        ):
            raise AssetOperationConflict("Persisted transfer facts do not match the verified final object.")

        if version is not None:
            raise AssetOperationConflict("An uncompleted upload already has an immutable version record.")

        repository = AssetRecoveryRepository(self.session)
        # The savepoint contains the version, fenced state transition and quota
        # conversion together; callers retain control of the outer transaction.
        with self.session.begin_nested():
            completed = repository.complete_finalization(intent_id, fence)
            if completed is None:
                raise AssetRecoveryConflict("The recovery claim is stale or no longer eligible.")
            finalized_at = completed.storage_finalized_at
            if not isinstance(finalized_at, datetime) or finalized_at.tzinfo is None:
                raise AssetOperationConflict("Database finalization time is unavailable.")
            version = AssetVersion(
                project_id=project_id,
                asset_id=asset_id,
                upload_intent_id=intent_id,
                storage_provider=storage_provider.strip(),
                object_version_reference=finalized_object.object_version.value,
                byte_size=finalized_object.byte_size,
                detected_media_type=None,
                validation_state="quarantined",
                storage_state="present",
                finalized_at=finalized_at,
            )
            self.session.add(version)
            self.session.flush()
            self._adjust_usage(
                usage,
                reserved=-intent.reserved_bytes,
                used=intent.received_bytes,
            )
            completed.state = "finalized"
            completed.finalized_at = completed.storage_finalized_at
            self.session.flush()
        return RecoveredUploadCompletion(completed, version, True)

    def release_reservation_after_cleanup(
        self, *, project_id: UUID, asset_id: UUID, intent_id: UUID, cleanup_confirmed: bool,
    ) -> AssetUploadIntent | None:
        if cleanup_confirmed is not True:
            raise AssetCleanupNotConfirmed("Reservation remains until temporary bytes are confirmed removed.")
        usage = self._lock_usage(project_id)
        self.session.scalar(
            select(Asset).where(Asset.project_id == project_id, Asset.id == asset_id).with_for_update()
        )
        intent = self.session.scalar(
            select(AssetUploadIntent).where(
                AssetUploadIntent.project_id == project_id,
                AssetUploadIntent.asset_id == asset_id,
                AssetUploadIntent.id == intent_id,
            ).with_for_update()
        )
        if intent is None:
            return None
        if intent.state == "cancelled":
            return intent
        if intent.state not in {"expired", "failed"}:
            raise AssetOperationConflict("Only expired or failed intents can release a reservation.")
        self._adjust_usage(usage, reserved=-intent.reserved_bytes)
        intent.state = "cancelled"
        return intent

    def mark_asset_deleted(self, *, project_id: UUID, asset_id: UUID, owner_user_id: UUID) -> Asset | None:
        if not AssetRepository.project_is_owned(self.session, project_id, owner_user_id):
            return None
        usage = self._lock_usage(project_id)
        asset = AssetRepository.get_asset_for_owner(
            self.session, project_id=project_id, asset_id=asset_id,
            owner_user_id=owner_user_id, for_update=True,
        )
        if asset is None:
            return None
        if asset.deleted_at is None:
            asset.deleted_at = self._now()
            asset.current_ready_version_id = None
            asset.state_revision += 1
            asset.updated_at = self._now()
            usage.accounting_revision += 1
        return asset

    def mark_version_deletion_pending(self, *, project_id: UUID, asset_id: UUID, version_id: UUID) -> AssetVersion | None:
        """Internal cleanup claim; call only after trusted storage cleanup is scheduled."""
        self._lock_usage(project_id)
        asset = self.session.scalar(
            select(Asset).where(Asset.project_id == project_id, Asset.id == asset_id).with_for_update()
        )
        if asset is None or asset.deleted_at is None or asset.current_ready_version_id == version_id:
            raise AssetOperationConflict("Version is not eligible for physical cleanup.")
        version = self.session.scalar(
            select(AssetVersion).where(
                AssetVersion.project_id == project_id,
                AssetVersion.asset_id == asset_id,
                AssetVersion.id == version_id,
            ).with_for_update()
        )
        if version is None:
            return None
        if version.storage_state == "deleted":
            return version
        version.storage_state = "deletion_pending"
        version.state_revision += 1
        return version

    def confirm_version_removed(
        self, *, project_id: UUID, asset_id: UUID, version_id: UUID,
        cleanup_confirmed: bool,
    ) -> AssetVersion | None:
        """Internal accounting callback after trusted storage confirms deletion."""
        if cleanup_confirmed is not True:
            raise AssetCleanupNotConfirmed("Used quota remains until physical removal is confirmed.")
        usage = self._lock_usage(project_id)
        asset = self.session.scalar(
            select(Asset).where(Asset.project_id == project_id, Asset.id == asset_id).with_for_update()
        )
        if asset is None or asset.deleted_at is None or asset.current_ready_version_id == version_id:
            raise AssetOperationConflict("Version is not eligible for physical cleanup.")
        version = self.session.scalar(
            select(AssetVersion).where(
                AssetVersion.project_id == project_id,
                AssetVersion.asset_id == asset_id,
                AssetVersion.id == version_id,
            ).with_for_update()
        )
        if version is None:
            return None
        if version.storage_state == "deleted":
            return version
        if version.storage_state != "deletion_pending":
            raise AssetOperationConflict("Version cleanup must be claimed before removal is recorded.")
        if version.byte_size > usage.used_bytes:
            raise AssetOperationConflict("Project used-byte accounting is inconsistent.")
        version.storage_state = "deleted"
        version.physically_deleted_at = self._now()
        version.state_revision += 1
        self._adjust_usage(usage, used=-version.byte_size)
        return version
