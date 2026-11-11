"""Owner-scoped database access for project assets.

The caller supplies an internal owner UUID obtained from the verified identity
mapping. This repository never accepts Clerk claims or client ownership data,
and it never commits the caller's transaction.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from adforge_renderer.database.models import Asset, Project


MAX_ASSET_PAGE_SIZE = 100


class AssetRepository:
    """Project-scoped asset queries; owner checks are part of each query."""

    @staticmethod
    def project_is_owned(session: Session, project_id: UUID, owner_user_id: UUID) -> bool:
        return session.scalar(
            select(Project.id).where(
                Project.id == project_id,
                Project.owner_user_id == owner_user_id,
            )
        ) is not None

    @staticmethod
    def create_asset(
        session: Session,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        kind: str,
        display_name: str | None,
    ) -> Asset | None:
        """Create a stable project asset ID only after checking project ownership."""
        if not AssetRepository.project_is_owned(session, project_id, owner_user_id):
            return None
        asset = Asset(project_id=project_id, kind=kind, display_name=display_name)
        session.add(asset)
        session.flush()
        return asset

    @staticmethod
    def get_active_asset(
        session: Session,
        *,
        project_id: UUID,
        asset_id: UUID,
        owner_user_id: UUID,
        for_update: bool = False,
    ) -> Asset | None:
        statement = (
            select(Asset)
            .join(Project, Project.id == Asset.project_id)
            .where(
                Asset.project_id == project_id,
                Asset.id == asset_id,
                Asset.deleted_at.is_(None),
                Project.owner_user_id == owner_user_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=Asset)
        return session.scalar(statement)

    @staticmethod
    def get_asset_for_owner(
        session: Session,
        *,
        project_id: UUID,
        asset_id: UUID,
        owner_user_id: UUID,
        for_update: bool = False,
    ) -> Asset | None:
        """Load an asset including its tombstone for authorized cleanup work."""
        statement = (
            select(Asset)
            .join(Project, Project.id == Asset.project_id)
            .where(
                Asset.project_id == project_id,
                Asset.id == asset_id,
                Project.owner_user_id == owner_user_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=Asset)
        return session.scalar(statement)

    @staticmethod
    def list_active_assets(
        session: Session,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        limit: int = 50,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[Asset] | None:
        """Return a bounded, keyset-paged list; None means project unavailable."""
        if type(limit) is not int or not 1 <= limit <= MAX_ASSET_PAGE_SIZE:
            raise ValueError(f"Asset page size must be between 1 and {MAX_ASSET_PAGE_SIZE}.")
        if not AssetRepository.project_is_owned(session, project_id, owner_user_id):
            return None

        statement = select(Asset).where(
            Asset.project_id == project_id,
            Asset.deleted_at.is_(None),
        )
        if after is not None:
            created_at, asset_id = after
            if not isinstance(created_at, datetime) or not isinstance(asset_id, UUID):
                raise ValueError("Asset cursor is invalid.")
            statement = statement.where(
                or_(
                    Asset.created_at > created_at,
                    and_(Asset.created_at == created_at, Asset.id > asset_id),
                )
            )
        return list(
            session.scalars(statement.order_by(Asset.created_at, Asset.id).limit(limit))
        )
