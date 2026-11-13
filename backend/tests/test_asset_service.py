from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, select
from sqlalchemy.orm import Session

from adforge_renderer.asset_repository import AssetRepository
from adforge_renderer.asset_service import (
    AssetCleanupNotConfirmed,
    AssetIntentConflict,
    AssetOperationConflict,
    AssetQuotaExceeded,
    AssetService,
    AssetServiceConfig,
    AssetServiceConfigurationError,
)
from adforge_renderer.asset_storage_provider import CleanupConfirmation, TemporaryObjectReference
from adforge_renderer.local_asset_storage import LocalAssetStorageConfig, LocalPrivateAssetStorage
from adforge_renderer.database.models import (
    Asset,
    AssetUploadIntent,
    AssetVersion,
    ExternalIdentity,
    Project,
    ProjectAssetUsage,
    User,
)


CLASSES = (User, ExternalIdentity, Project, ProjectAssetUsage, Asset, AssetUploadIntent, AssetVersion)


class _ReferenceAllocator:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []
        self.failure: Exception | None = None

    def allocate_temporary_reference(
        self, *, project_id: UUID, operation_id: UUID
    ) -> TemporaryObjectReference:
        if self.failure is not None:
            raise self.failure
        self.calls.append((project_id, operation_id))
        return TemporaryObjectReference(
            f"tmp_{operation_id.hex}", project_id, operation_id
        )


def _sqlite_session() -> Session:
    """Build a test-only SQLite schema without PostgreSQL-specific constraints."""
    metadata = MetaData()
    for model in CLASSES:
        source = model.__table__
        Table(
            source.name,
            metadata,
            *[
                Column(
                    column.name,
                    column.type,
                    primary_key=column.primary_key,
                    nullable=column.nullable,
                    default=column.default,
                    server_default=column.server_default,
                )
                for column in source.columns
            ],
        )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return Session(engine, autoflush=False, expire_on_commit=False)


def _seed(session: Session, *, quota: int = 1000):
    user = User()
    session.add(user)
    session.flush()
    project = Project(owner_user_id=user.id, name="Assets")
    session.add(project)
    session.flush()
    service = AssetService(
        session,
        AssetServiceConfig(quota, timedelta(hours=1)),
        clock=lambda: datetime(2026, 11, 11, tzinfo=timezone.utc),
        storage=_ReferenceAllocator(),
    )
    asset = service.create_asset(
        project_id=project.id, owner_user_id=user.id, kind="audio", display_name="  Track.wav  "
    )
    assert asset is not None
    return user, project, asset, service


def test_asset_repository_is_project_and_owner_scoped_and_hides_deleted_assets() -> None:
    session = _sqlite_session()
    user, project, asset, _ = _seed(session)
    other_user = User()
    session.add(other_user)
    session.flush()
    other_project = Project(owner_user_id=other_user.id, name="Other")
    session.add(other_project)
    session.flush()

    assert AssetRepository.get_active_asset(
        session, project_id=project.id, asset_id=asset.id, owner_user_id=user.id
    ) is asset
    assert AssetRepository.get_active_asset(
        session, project_id=other_project.id, asset_id=asset.id, owner_user_id=other_user.id
    ) is None
    assert AssetRepository.list_active_assets(
        session, project_id=other_project.id, owner_user_id=user.id
    ) is None
    assert len(AssetRepository.list_active_assets(
        session, project_id=project.id, owner_user_id=user.id, limit=1
    )) == 1

    asset.deleted_at = datetime.now(timezone.utc)
    session.flush()
    assert AssetRepository.get_active_asset(
        session, project_id=project.id, asset_id=asset.id, owner_user_id=user.id
    ) is None
    assert AssetRepository.get_asset_for_owner(
        session, project_id=project.id, asset_id=asset.id, owner_user_id=user.id
    ) is asset
    session.close()


def test_upload_intent_cross_owner_failure_does_not_create_quota_row() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    other = User()
    session.add(other)
    session.flush()
    result = service.create_upload_intent(
        project_id=project.id,
        asset_id=asset.id,
        owner_user_id=other.id,
        idempotency_key="unauthorized",
        reserved_bytes=25,
        lifetime=timedelta(minutes=5),
    )
    assert result is None
    assert session.get(ProjectAssetUsage, project.id).reserved_bytes == 0
    assert session.scalar(
        select(AssetUploadIntent).where(AssetUploadIntent.idempotency_key == "unauthorized")
    ) is None
    session.close()


def test_cross_owner_logical_delete_does_not_create_usage_or_mutate_asset() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    other = User()
    session.add(other)
    session.flush()
    other_project = Project(owner_user_id=other.id, name="Other")
    session.add(other_project)
    session.flush()

    assert service.mark_asset_deleted(
        project_id=other_project.id,
        asset_id=asset.id,
        owner_user_id=user.id,
    ) is None
    assert session.get(ProjectAssetUsage, other_project.id) is None
    assert asset.deleted_at is None
    session.close()


def test_upload_intent_is_idempotent_and_fingerprint_conflicts_are_rejected() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    first = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="attempt-1", reserved_bytes=400, lifetime=timedelta(minutes=30),
    )
    again = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="attempt-1", reserved_bytes=400, lifetime=timedelta(minutes=30),
    )
    assert first is not None and first.created
    assert again is not None and not again.created
    assert again.intent.id == first.intent.id
    assert first.intent.staging_reference == f"tmp_{first.intent.id.hex}"
    assert first.intent.staging_reference == again.intent.staging_reference
    assert service.storage.calls == [(project.id, first.intent.id)]
    assert first.intent.recovery_deadline_at == first.intent.expires_at + timedelta(hours=24)
    assert first.intent.recovery_state == "not_required"
    assert session.get(ProjectAssetUsage, project.id).reserved_bytes == 400
    with pytest.raises(AssetIntentConflict):
        service.create_upload_intent(
            project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
            idempotency_key="attempt-1", reserved_bytes=401, lifetime=timedelta(minutes=30),
        )
    with pytest.raises(AssetIntentConflict):
        service.create_upload_intent(
            project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
            idempotency_key="attempt-1", reserved_bytes=400, lifetime=timedelta(minutes=29),
        )
    session.close()


def test_upload_intent_persists_exact_local_storage_reference_without_materializing_bytes(
    tmp_path,
) -> None:
    session = _sqlite_session()
    user, project, asset, _ = _seed(session)
    storage = LocalPrivateAssetStorage(LocalAssetStorageConfig(tmp_path / "private-assets"))
    service = AssetService(
        session, AssetServiceConfig(1000, timedelta(hours=1)), storage=storage,
        clock=lambda: datetime(2026, 11, 11, tzinfo=timezone.utc),
    )
    result = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="local-reference", reserved_bytes=200,
        lifetime=timedelta(minutes=10),
    )
    reference = storage.allocate_temporary_reference(
        project_id=project.id, operation_id=result.intent.id
    )
    assert result.intent.staging_reference == reference.value
    assert not (tmp_path / "private-assets" / "temporary" / reference.value).exists()

    # The exact database reference is then reconstructed with the row's
    # project and intent IDs and materialized only when transfer starts.
    persisted_reference = TemporaryObjectReference(
        result.intent.staging_reference, project.id, result.intent.id
    )
    assert storage.create_temporary_object(persisted_reference) == reference
    assert storage.inspect_temporary_object(persisted_reference).complete is False
    usage = session.get(ProjectAssetUsage, project.id)
    assert (usage.used_bytes, usage.reserved_bytes) == (0, 200)
    session.close()


def test_storage_reference_allocation_failure_has_no_intent_or_reservation() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    service.storage.failure = RuntimeError("simulated allocation failure")
    with pytest.raises(RuntimeError, match="simulated allocation failure"):
        service.create_upload_intent(
            project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
            idempotency_key="allocation-fails", reserved_bytes=75,
            lifetime=timedelta(minutes=5),
        )
    assert session.get(ProjectAssetUsage, project.id).reserved_bytes == 0
    assert session.scalar(select(AssetUploadIntent).where(
        AssetUploadIntent.idempotency_key == "allocation-fails"
    )) is None
    session.close()


def test_persistence_failure_after_pure_allocation_has_no_storage_object_or_reservation() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    session.commit()
    allocator = service.storage
    original_add = session.add

    def fail_intent_insert(instance, *args, **kwargs):
        if isinstance(instance, AssetUploadIntent):
            raise RuntimeError("simulated persistence failure")
        return original_add(instance, *args, **kwargs)

    session.add = fail_intent_insert
    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        service.create_upload_intent(
            project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
            idempotency_key="persistence-fails", reserved_bytes=80,
            lifetime=timedelta(minutes=5),
        )
    session.add = original_add
    assert len(allocator.calls) == 1
    assert session.get(ProjectAssetUsage, project.id).reserved_bytes == 0
    assert session.scalar(select(AssetUploadIntent).where(
        AssetUploadIntent.idempotency_key == "persistence-fails"
    )) is None
    # Reference allocation is side-effect free; no object exists to clean up,
    # and an ambiguous persistence outcome must not trigger a storage delete.
    assert not hasattr(allocator, "delete_temporary_object")
    session.rollback()
    session.close()


def test_quota_arithmetic_rejects_oversubscription_and_checks_intent_bounds() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session, quota=500)
    service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="one", reserved_bytes=300, lifetime=timedelta(minutes=30),
    )
    with pytest.raises(AssetQuotaExceeded):
        service.create_upload_intent(
            project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
            idempotency_key="two", reserved_bytes=201, lifetime=timedelta(minutes=30),
        )
    with pytest.raises(ValueError, match="lifetime"):
        service.create_upload_intent(
            project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
            idempotency_key="three", reserved_bytes=1, lifetime=timedelta(hours=2),
        )
    with pytest.raises(ValueError, match="Reserved byte"):
        service.create_upload_intent(
            project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
            idempotency_key="four", reserved_bytes=1 << 63, lifetime=timedelta(minutes=1),
        )
    with pytest.raises(AssetServiceConfigurationError):
        AssetServiceConfig(1 << 63, timedelta(minutes=1))
    session.close()


def test_finalization_reconciliation_is_idempotent_and_uses_actual_bytes() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    result = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="finish", reserved_bytes=500, lifetime=timedelta(minutes=30),
    )
    intent = service.reconcile_finalized_upload(
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id, actual_bytes=375
    )
    assert intent.state == "finalized"
    assert intent.received_bytes == 375
    usage = session.get(ProjectAssetUsage, project.id)
    assert (usage.used_bytes, usage.reserved_bytes) == (375, 0)
    assert service.reconcile_finalized_upload(
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id, actual_bytes=375
    ) is intent
    with pytest.raises(AssetOperationConflict):
        service.reconcile_finalized_upload(
            project_id=project.id, asset_id=asset.id, intent_id=result.intent.id, actual_bytes=374
        )
    session.close()


def test_expiry_retains_quota_until_cleanup_confirms_removal(tmp_path) -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    storage = LocalPrivateAssetStorage(LocalAssetStorageConfig(tmp_path / "private-assets"))
    service.storage = storage
    result = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="expire", reserved_bytes=200, lifetime=timedelta(minutes=30),
    )
    # A later service clock simulates the expiry scanner.
    expired_service = AssetService(
        session, service.config,
        clock=lambda: datetime(2026, 11, 12, tzinfo=timezone.utc),
        storage=storage,
    )
    expired = expired_service.expire_upload_intent(
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id
    )
    assert expired.state == "expired"
    usage = session.get(ProjectAssetUsage, project.id)
    assert usage.reserved_bytes == 200
    with pytest.raises(AssetCleanupNotConfirmed):
        expired_service.release_reservation_after_cleanup(
            project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
            confirmation=True,  # type: ignore[arg-type]
        )
    temporary = storage.allocate_temporary_reference(project_id=project.id, operation_id=result.intent.id)
    result.intent.staging_reference = temporary.value
    storage.create_temporary_object(temporary)
    storage.write_temporary_object(temporary, [b"reserved upload"], max_bytes=128)
    claim_token = uuid4()
    result.intent.cleanup_state = "claimed"
    result.intent.cleanup_revision = 2
    result.intent.cleanup_claim_generation = 1
    result.intent.cleanup_claim_token = claim_token
    confirmation = storage.delete_temporary_object(
        temporary, project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
        claim_token=claim_token, cleanup_revision=result.intent.cleanup_revision,
        cleanup_generation=result.intent.cleanup_claim_generation,
    )
    result.intent.cleanup_state = "confirmed"
    result.intent.cleanup_revision += 1
    result.intent.cleanup_claim_token = None
    result.intent.cleanup_confirmed_at = datetime(2026, 11, 12, tzinfo=timezone.utc)
    result.intent.cleanup_completed_claim_token = claim_token
    result.intent.cleanup_completed_claim_generation = 1
    result.intent.cleanup_completed_revision = 2
    synthetic = CleanupConfirmation(
        reference=temporary, physically_absent=True,
        target_kind="temporary_upload", cleanup_operation="temporary_object_delete",
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
        operation_id=result.intent.id, claim_token=claim_token,
        cleanup_revision=2, cleanup_generation=1,
    )
    with pytest.raises(AssetCleanupNotConfirmed):
        expired_service.release_reservation_after_cleanup(
            project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
            confirmation=synthetic,
        )
    with pytest.raises(AssetCleanupNotConfirmed):
        expired_service.release_reservation_after_cleanup(
            project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
            confirmation=replace(confirmation, project_id=uuid4()),
        )
    assert usage.reserved_bytes == 200
    completed_token = result.intent.cleanup_completed_claim_token
    result.intent.cleanup_completed_claim_token = uuid4()
    with pytest.raises(AssetCleanupNotConfirmed):
        expired_service.release_reservation_after_cleanup(
            project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
            confirmation=confirmation,
        )
    result.intent.cleanup_completed_claim_token = completed_token
    released = expired_service.release_reservation_after_cleanup(
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
        confirmation=confirmation,
    )
    assert released.state == "cancelled"
    assert usage.reserved_bytes == 0
    assert expired_service.release_reservation_after_cleanup(
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
        confirmation=confirmation,
    ) is released
    session.close()


def test_logical_deletion_keeps_used_quota_until_version_removal_is_confirmed(tmp_path) -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    storage = LocalPrivateAssetStorage(LocalAssetStorageConfig(tmp_path / "private-assets"))
    service.storage = storage
    intent_result = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="stored", reserved_bytes=250, lifetime=timedelta(minutes=30),
    )
    intent = service.reconcile_finalized_upload(
        project_id=project.id, asset_id=asset.id,
        intent_id=intent_result.intent.id, actual_bytes=220,
    )
    temporary = storage.allocate_temporary_reference(project_id=project.id, operation_id=intent.id)
    storage.create_temporary_object(temporary)
    observation = storage.write_temporary_object(temporary, [b"x" * 220], max_bytes=256)
    object_version = storage.new_object_version_reference()
    storage.finalize_temporary_object_preserving_temporary(
        temporary, object_version, expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        upload_intent_id=intent.id,
        storage_provider="local-test",
        object_version_reference=object_version.value,
        byte_size=observation.byte_size,
        detected_media_type="audio/wav",
        validation_state="quarantined",
        storage_state="present",
        state_revision=0,
        finalized_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
    )
    session.add(version)
    session.flush()

    deleted_asset = service.mark_asset_deleted(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id
    )
    usage = session.get(ProjectAssetUsage, project.id)
    assert deleted_asset.deleted_at is not None
    assert usage.used_bytes == 220
    pending = service.mark_version_deletion_pending(
        project_id=project.id, asset_id=asset.id, version_id=version.id
    )
    assert pending.storage_state == "deletion_pending"
    with pytest.raises(AssetCleanupNotConfirmed):
        service.confirm_version_removed(
            project_id=project.id, asset_id=asset.id, version_id=version.id,
            confirmation=True,  # type: ignore[arg-type]
        )
    confirmation = storage.delete_finalized_object(
        object_version, project_id=project.id, asset_id=asset.id,
        intent_id=intent.id, claim_token=pending.cleanup_claim_token,
        cleanup_revision=pending.state_revision,
        cleanup_generation=pending.cleanup_claim_generation,
    )
    with pytest.raises(AssetCleanupNotConfirmed):
        service.confirm_version_removed(
            project_id=project.id, asset_id=asset.id, version_id=version.id,
            confirmation=replace(confirmation, cleanup_revision=pending.state_revision + 1),
        )
    assert usage.used_bytes == 220
    removed = service.confirm_version_removed(
        project_id=project.id, asset_id=asset.id, version_id=version.id,
        confirmation=confirmation,
    )
    assert removed.storage_state == "deleted"
    assert usage.used_bytes == 0
    assert service.confirm_version_removed(
        project_id=project.id, asset_id=asset.id, version_id=version.id,
        confirmation=confirmation,
    ) is removed
    session.close()
