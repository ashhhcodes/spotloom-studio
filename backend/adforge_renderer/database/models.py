"""Initial PostgreSQL model metadata for internal users and owned projects."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    BigInteger,
    JSON,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
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


class ProjectCreativeWorkspace(Base):
    """Project-owned campaign and storyboard document, not trusted asset state."""

    __tablename__ = "project_creative_workspaces"
    __table_args__ = (CheckConstraint("revision >= 1", name="revision_positive"),)

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    brief: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    creative_direction: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    storyboard: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProjectAssetUsage(Base):
    """Transactional project quota accounting; limits are configured per project."""

    __tablename__ = "project_asset_usage"
    __table_args__ = (
        CheckConstraint("quota_limit_bytes > 0", name="quota_limit_positive"),
        CheckConstraint("used_bytes >= 0", name="used_bytes_nonnegative"),
        CheckConstraint("reserved_bytes >= 0", name="reserved_bytes_nonnegative"),
        CheckConstraint("accounting_revision >= 0", name="revision_nonnegative"),
    )

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True
    )
    quota_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    accounting_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Asset(Base):
    """Stable project-scoped asset identity, separate from immutable versions."""

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_assets_project_id_id"),
        CheckConstraint("kind IN ('audio', 'image')", name="kind_supported"),
        CheckConstraint("state_revision >= 0", name="revision_nonnegative"),
        Index("ix_assets_project_created_id", "project_id", "created_at", "id"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_assets_project_id_projects_id",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "id", "current_ready_version_id"],
            ["asset_versions.project_id", "asset_versions.asset_id", "asset_versions.id"],
            name="fk_assets_current_ready_version_same_asset", ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_ready_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssetUploadIntent(Base):
    """Project-scoped idempotent reservation; no client metadata is trusted."""

    __tablename__ = "asset_upload_intents"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "id", name="uq_upload_intents_project_asset_id"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_upload_intents_project_idempotency"),
        CheckConstraint("reserved_bytes > 0", name="reserved_bytes_positive"),
        CheckConstraint("received_bytes >= 0 AND received_bytes <= reserved_bytes", name="received_bytes_bounded"),
        CheckConstraint("state IN ('open', 'finalized', 'cancelled', 'expired', 'failed')", name="state_supported"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_upload_intents_project_state_expiry", "project_id", "state", "expires_at"),
        ForeignKeyConstraint(
            ["project_id", "asset_id"], ["assets.project_id", "assets.id"],
            name="fk_upload_intents_project_asset_assets", ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_reference: Mapped[str] = mapped_column(Text, nullable=False)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssetVersion(Base):
    """Finalized immutable byte identity with mutable validation/storage lifecycle."""

    __tablename__ = "asset_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "id", name="uq_asset_versions_project_asset_id"),
        UniqueConstraint("upload_intent_id", name="uq_asset_versions_upload_intent"),
        UniqueConstraint("storage_provider", "object_version_reference", name="uq_asset_versions_storage_version"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("validation_state IN ('quarantined', 'validating', 'ready', 'rejected', 'failed', 'revoked')", name="validation_state_supported"),
        CheckConstraint("storage_state IN ('present', 'deletion_pending', 'deleted', 'missing')", name="storage_state_supported"),
        CheckConstraint("(storage_state = 'deleted') = (physically_deleted_at IS NOT NULL)", name="physical_delete_timestamp_consistent"),
        CheckConstraint("state_revision >= 0", name="revision_nonnegative"),
        CheckConstraint("(validation_state = 'ready') = (accepted_evidence_id IS NOT NULL)", name="ready_requires_evidence"),
        CheckConstraint("finalized_at IS NOT NULL", name="version_finalized"),
        Index("ix_asset_versions_asset_created", "project_id", "asset_id", "created_at"),
        ForeignKeyConstraint(
            ["project_id", "asset_id"], ["assets.project_id", "assets.id"],
            name="fk_asset_versions_project_asset_assets", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "asset_id", "upload_intent_id"],
            ["asset_upload_intents.project_id", "asset_upload_intents.asset_id", "asset_upload_intents.id"],
            name="fk_asset_versions_project_asset_intent", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "asset_id", "id", "current_attempt_id"],
            ["asset_validation_attempts.project_id", "asset_validation_attempts.asset_id", "asset_validation_attempts.version_id", "asset_validation_attempts.id"],
            name="fk_asset_versions_current_attempt_same_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "asset_id", "id", "accepted_evidence_id"],
            ["asset_validation_evidence.project_id", "asset_validation_evidence.asset_id", "asset_validation_evidence.version_id", "asset_validation_evidence.id"],
            name="fk_asset_versions_accepted_evidence_same_version", ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    upload_intent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    object_version_reference: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    detected_media_type: Mapped[str] = mapped_column(String(80), nullable=False)
    validation_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="quarantined")
    storage_state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="present")
    current_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    accepted_evidence_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    physically_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssetValidationAttempt(Base):
    """Mutable attempt state with append-only historical identity."""

    __tablename__ = "asset_validation_attempts"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "version_id", "id", name="uq_validation_attempts_version_identity"),
        UniqueConstraint("version_id", "attempt_number", name="uq_validation_attempts_version_number"),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("state IN ('queued', 'running', 'succeeded', 'rejected', 'failed', 'cancelled', 'superseded')", name="state_supported"),
        Index("ix_validation_attempts_version_created", "version_id", "created_at"),
        Index(
            "uq_validation_attempts_one_active_per_version", "version_id", unique=True,
            postgresql_where=text("state IN ('queued', 'running')"),
            sqlite_where=text("state IN ('queued', 'running')"),
        ),
        ForeignKeyConstraint(
            ["project_id", "asset_id", "version_id"],
            ["asset_versions.project_id", "asset_versions.asset_id", "asset_versions.id"],
            name="fk_validation_attempts_exact_version", ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    validator_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    validator_build: Mapped[str] = mapped_column(String(160), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetValidationEvidence(Base):
    """Immutable trusted-service observation bound to exact finalized bytes."""

    __tablename__ = "asset_validation_evidence"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "version_id", "id", name="uq_asset_evidence_version_identity"),
        UniqueConstraint("version_id", "attempt_id", name="uq_asset_evidence_attempt"),
        CheckConstraint("length(sha256_hex) = 64 AND sha256_hex ~ '^[0-9a-f]{64}$'", name="sha256_lower_hex"),
        CheckConstraint("observed_byte_count > 0", name="observed_bytes_positive"),
        Index("ix_asset_evidence_version_created", "version_id", "created_at"),
        ForeignKeyConstraint(
            ["project_id", "asset_id", "version_id", "attempt_id"],
            ["asset_validation_attempts.project_id", "asset_validation_attempts.asset_id", "asset_validation_attempts.version_id", "asset_validation_attempts.id"],
            name="fk_asset_evidence_attempt_same_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "asset_id", "version_id"],
            ["asset_versions.project_id", "asset_versions.asset_id", "asset_versions.id"],
            name="fk_asset_evidence_exact_version", ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    object_version_reference: Mapped[str] = mapped_column(Text, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    validator_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    validator_build: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetEvidenceRevocation(Base):
    """Append-only revocation marker; evidence rows remain available for audit."""

    __tablename__ = "asset_evidence_revocations"
    __table_args__ = (
        CheckConstraint("length(reason_code) > 0", name="reason_code_nonblank"),
        ForeignKeyConstraint(
            ["evidence_id"], ["asset_validation_evidence.id"],
            name="fk_evidence_revocations_evidence", ondelete="RESTRICT",
        ),
    )

    evidence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_by: Mapped[str] = mapped_column(String(160), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
