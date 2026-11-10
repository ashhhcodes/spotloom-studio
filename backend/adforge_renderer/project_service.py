"""Transactional identity mapping and owner-scoped project operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from adforge_renderer.database.models import (
    ExternalIdentity,
    Project,
    ProjectCreativeWorkspace,
    User,
    normalize_project_name,
)
from adforge_renderer.identity import VerifiedClerkPrincipal


class IdentityMappingError(RuntimeError):
    """Safe error when a verified identity cannot be resolved consistently."""


class CreativeWorkspaceRevisionConflict(RuntimeError):
    """The project workspace changed since the caller last loaded it."""


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


def get_owned_creative_workspace(
    session: Session,
    project_id: UUID,
    owner_user_id: UUID,
) -> ProjectCreativeWorkspace | None:
    """Load a saved workspace only through its owner-scoped project."""
    return session.scalar(
        select(ProjectCreativeWorkspace)
        .join(Project, Project.id == ProjectCreativeWorkspace.project_id)
        .where(Project.id == project_id, Project.owner_user_id == owner_user_id)
    )


def save_owned_creative_workspace(
    session: Session,
    project_id: UUID,
    owner_user_id: UUID,
    *,
    expected_revision: int,
    brief: dict[str, object],
    creative_direction: dict[str, object],
    storyboard: list[dict[str, object]],
) -> ProjectCreativeWorkspace | None:
    """Create/update an owned planning document with optimistic concurrency.

    Revision zero represents an unsaved workspace. Inserts use a savepoint so
    concurrent first saves cannot poison the surrounding API transaction.
    Existing revisions are updated with a compare-and-swap predicate.
    """
    if get_owned_project(session, project_id, owner_user_id) is None:
        return None

    current = session.get(ProjectCreativeWorkspace, project_id)
    if expected_revision == 0:
        if current is not None:
            raise CreativeWorkspaceRevisionConflict
        row = ProjectCreativeWorkspace(
            project_id=project_id,
            revision=1,
            brief=brief,
            creative_direction=creative_direction,
            storyboard=storyboard,
        )
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            raise CreativeWorkspaceRevisionConflict from None
        session.refresh(row)
        return row

    if current is None or current.revision != expected_revision:
        raise CreativeWorkspaceRevisionConflict

    result = session.execute(
        update(ProjectCreativeWorkspace)
        .where(
            ProjectCreativeWorkspace.project_id == project_id,
            ProjectCreativeWorkspace.revision == expected_revision,
        )
        .values(
            brief=brief,
            creative_direction=creative_direction,
            storyboard=storyboard,
            revision=expected_revision + 1,
            updated_at=func.now(),
        )
    )
    if result.rowcount != 1:
        raise CreativeWorkspaceRevisionConflict
    session.refresh(current)
    return current
