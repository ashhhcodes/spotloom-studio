"""Initial PostgreSQL model metadata for internal users and owned projects."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


PROJECT_NAME_MAX_LENGTH = 120  # Provisional engineering bound; not a numeric policy approval.


def normalize_project_name(value: str) -> str:
    """Trim and bound project names for future project-creation services."""
    if type(value) is not str:
        raise ValueError("Project name must be text.")
    normalized = value.strip()
    if not normalized or len(normalized) > PROJECT_NAME_MAX_LENGTH:
        raise ValueError(
            f"Project name must contain 1 to {PROJECT_NAME_MAX_LENGTH} characters after trimming."
        )
    return normalized


class Base(DeclarativeBase):
    """Shared declarative base for explicit metadata/migration use."""

    metadata = MetaData(
        naming_convention={
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_external_identities_issuer_subject"),
        Index("ix_external_identities_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            r"char_length(btrim(name, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')) > 0 "
            r"AND name = btrim(name, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')",
            name="name_nonblank",
        ),
        Index("ix_projects_owner_created_id", "owner_user_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        # This updates through SQLAlchemy ORM writes; direct SQL writers must set it.
        onupdate=func.now(),
    )
