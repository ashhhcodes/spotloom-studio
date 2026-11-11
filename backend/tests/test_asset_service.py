from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

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


def test_expiry_retains_quota_until_cleanup_confirms_removal() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    result = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="expire", reserved_bytes=200, lifetime=timedelta(minutes=30),
    )
    # A later service clock simulates the expiry scanner.
    expired_service = AssetService(
        session, service.config,
        clock=lambda: datetime(2026, 11, 12, tzinfo=timezone.utc),
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
            cleanup_confirmed=False,
        )
    released = expired_service.release_reservation_after_cleanup(
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
        cleanup_confirmed=True,
    )
    assert released.state == "cancelled"
    assert usage.reserved_bytes == 0
    assert expired_service.release_reservation_after_cleanup(
        project_id=project.id, asset_id=asset.id, intent_id=result.intent.id,
        cleanup_confirmed=True,
    ) is released
    session.close()


def test_logical_deletion_keeps_used_quota_until_version_removal_is_confirmed() -> None:
    session = _sqlite_session()
    user, project, asset, service = _seed(session)
    intent_result = service.create_upload_intent(
        project_id=project.id, asset_id=asset.id, owner_user_id=user.id,
        idempotency_key="stored", reserved_bytes=250, lifetime=timedelta(minutes=30),
    )
    intent = service.reconcile_finalized_upload(
        project_id=project.id, asset_id=asset.id,
        intent_id=intent_result.intent.id, actual_bytes=220,
    )
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        upload_intent_id=intent.id,
        storage_provider="local-test",
        object_version_reference="opaque-version-1",
        byte_size=220,
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
            cleanup_confirmed=False,
        )
    removed = service.confirm_version_removed(
        project_id=project.id, asset_id=asset.id, version_id=version.id,
        cleanup_confirmed=True,
    )
    assert removed.storage_state == "deleted"
    assert usage.used_bytes == 0
    assert service.confirm_version_removed(
        project_id=project.id, asset_id=asset.id, version_id=version.id,
        cleanup_confirmed=True,
    ) is removed
    session.close()
