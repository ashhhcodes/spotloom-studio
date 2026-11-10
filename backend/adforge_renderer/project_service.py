"""Transactional identity mapping and owner-scoped project operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from adforge_renderer.database.models import (
    ExternalIdentity,
    Project,
    User,
    normalize_project_name,
)
from adforge_renderer.identity import VerifiedClerkPrincipal


class IdentityMappingError(RuntimeError):
    """Safe error when a verified identity cannot be resolved consistently."""


def find_internal_user_id(
    session: Session,
    principal: VerifiedClerkPrincipal,
) -> UUID | None:
    """Look up the exact verified issuer/subject pair without creating a user."""
    return session.scalar(
        select(ExternalIdentity.user_id).where(
            ExternalIdentity.issuer == principal.issuer,
            ExternalIdentity.subject == principal.subject,
        )
    )


def get_or_create_internal_user_id(
    session: Session,
    principal: VerifiedClerkPrincipal,
) -> UUID:
    """Resolve a verified identity, using the unique constraint for race safety.

    User and identity insertion occur inside a savepoint. If another transaction
    wins the unique `(issuer, subject)` insert, the savepoint removes this
    transaction's provisional user and a fresh read returns the winning user ID.
    The caller owns the enclosing transaction.
    """
    existing_user_id = find_internal_user_id(session, principal)
    if existing_user_id is not None:
        return existing_user_id

    provisional_user = User()
    try:
        with session.begin_nested():
            session.add(provisional_user)
            session.flush()
            session.add(
                ExternalIdentity(
                    issuer=principal.issuer,
                    subject=principal.subject,
                    user_id=provisional_user.id,
                )
            )
            session.flush()
    except IntegrityError:
        winning_user_id = find_internal_user_id(session, principal)
        if winning_user_id is not None:
            return winning_user_id
        raise IdentityMappingError("Verified identity mapping could not be completed.") from None

    if provisional_user.id is None:
        raise IdentityMappingError("Verified identity mapping could not be completed.")
    return provisional_user.id


def create_owned_project(
    session: Session,
    owner_user_id: UUID,
    name: str,
) -> Project:
    """Create a project using only the caller's server-resolved internal ID."""
    project = Project(owner_user_id=owner_user_id, name=normalize_project_name(name))
    session.add(project)
    session.flush()
    return project


def list_owned_projects(session: Session, owner_user_id: UUID) -> list[Project]:
    """Return projects for one internal owner only."""
    return list(
        session.scalars(
            select(Project)
            .where(Project.owner_user_id == owner_user_id)
            .order_by(Project.created_at, Project.id)
        )
    )


def get_owned_project(
    session: Session,
    project_id: UUID,
    owner_user_id: UUID,
) -> Project | None:
    """Resolve a project only when both its ID and owner match."""
    return session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.owner_user_id == owner_user_id,
        )
    )
