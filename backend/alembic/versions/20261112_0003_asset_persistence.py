"""Add project-scoped asset persistence records.

Revision ID: 20261112_0003_asset_persistence
Revises: 20261111_0002
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261112_0003_asset_persistence"
down_revision = "20261111_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_asset_usage",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("quota_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("accounting_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("quota_limit_bytes > 0", name="ck_project_asset_usage_quota_limit_positive"),
        sa.CheckConstraint("used_bytes >= 0", name="ck_project_asset_usage_used_bytes_nonnegative"),
        sa.CheckConstraint("reserved_bytes >= 0", name="ck_project_asset_usage_reserved_bytes_nonnegative"),
        sa.CheckConstraint("accounting_revision >= 0", name="ck_project_asset_usage_revision_nonnegative"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_project_asset_usage_project_id_projects_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("project_id", name="pk_project_asset_usage"),
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("current_ready_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("state_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('audio', 'image')", name="ck_assets_kind_supported"),
        sa.CheckConstraint("state_revision >= 0", name="ck_assets_revision_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
        sa.UniqueConstraint("project_id", "id", name="uq_assets_project_id_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_assets_project_id_projects_id", ondelete="RESTRICT"),
    )
    op.create_index("ix_assets_project_created_id", "assets", ["project_id", "created_at", "id"])

    op.create_table(
        "asset_upload_intents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("staging_reference", sa.Text(), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("state", sa.String(16), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("reserved_bytes > 0", name="ck_asset_upload_intents_reserved_bytes_positive"),
        sa.CheckConstraint("received_bytes >= 0 AND received_bytes <= reserved_bytes", name="ck_asset_upload_intents_received_bytes_bounded"),
        sa.CheckConstraint("state IN ('open', 'finalized', 'cancelled', 'expired', 'failed')", name="ck_asset_upload_intents_state_supported"),
        sa.CheckConstraint("expires_at > created_at", name="ck_asset_upload_intents_expiry_after_creation"),
        sa.PrimaryKeyConstraint("id", name="pk_asset_upload_intents"),
        sa.UniqueConstraint("project_id", "asset_id", "id", name="uq_upload_intents_project_asset_id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_upload_intents_project_idempotency"),
        sa.ForeignKeyConstraint(["project_id", "asset_id"], ["assets.project_id", "assets.id"], name="fk_upload_intents_project_asset_assets", ondelete="RESTRICT"),
    )
    op.create_index("ix_upload_intents_project_state_expiry", "asset_upload_intents", ["project_id", "state", "expires_at"])

    op.create_table(
        "asset_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("upload_intent_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("storage_provider", sa.String(80), nullable=False),
        sa.Column("object_version_reference", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("detected_media_type", sa.String(80), nullable=False),
        sa.Column("validation_state", sa.String(16), server_default="quarantined", nullable=False),
        sa.Column("storage_state", sa.String(24), server_default="present", nullable=False),
        sa.Column("current_attempt_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("accepted_evidence_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("state_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("physically_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("byte_size > 0", name="ck_asset_versions_byte_size_positive"),
        sa.CheckConstraint("validation_state IN ('quarantined', 'validating', 'ready', 'rejected', 'failed', 'revoked')", name="ck_asset_versions_validation_state_supported"),
        sa.CheckConstraint("storage_state IN ('present', 'deletion_pending', 'deleted', 'missing')", name="ck_asset_versions_storage_state_supported"),
        sa.CheckConstraint("(storage_state = 'deleted') = (physically_deleted_at IS NOT NULL)", name="ck_asset_versions_physical_delete_timestamp_consistent"),
        sa.CheckConstraint("state_revision >= 0", name="ck_asset_versions_revision_nonnegative"),
        sa.CheckConstraint("(validation_state = 'ready') = (accepted_evidence_id IS NOT NULL)", name="ck_asset_versions_ready_requires_evidence"),
        sa.CheckConstraint("finalized_at IS NOT NULL", name="ck_asset_versions_version_finalized"),
        sa.PrimaryKeyConstraint("id", name="pk_asset_versions"),
        sa.UniqueConstraint("project_id", "asset_id", "id", name="uq_asset_versions_project_asset_id"),
        sa.UniqueConstraint("upload_intent_id", name="uq_asset_versions_upload_intent"),
        sa.UniqueConstraint("storage_provider", "object_version_reference", name="uq_asset_versions_storage_version"),
        sa.ForeignKeyConstraint(["project_id", "asset_id"], ["assets.project_id", "assets.id"], name="fk_asset_versions_project_asset_assets", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "upload_intent_id"], ["asset_upload_intents.project_id", "asset_upload_intents.asset_id", "asset_upload_intents.id"], name="fk_asset_versions_project_asset_intent", ondelete="RESTRICT"),
    )
    op.create_index("ix_asset_versions_asset_created", "asset_versions", ["project_id", "asset_id", "created_at"])

    op.create_table(
        "asset_validation_attempts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), server_default="queued", nullable=False),
        sa.Column("profile_id", sa.String(100), nullable=False),
        sa.Column("profile_version", sa.String(80), nullable=False),
        sa.Column("validator_identity", sa.String(160), nullable=False),
        sa.Column("validator_build", sa.String(160), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("attempt_number > 0", name="ck_asset_validation_attempts_attempt_number_positive"),
        sa.CheckConstraint("state IN ('queued', 'running', 'succeeded', 'rejected', 'failed', 'cancelled', 'superseded')", name="ck_asset_validation_attempts_state_supported"),
        sa.PrimaryKeyConstraint("id", name="pk_asset_validation_attempts"),
        sa.UniqueConstraint("project_id", "asset_id", "version_id", "id", name="uq_validation_attempts_version_identity"),
        sa.UniqueConstraint("version_id", "attempt_number", name="uq_validation_attempts_version_number"),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "version_id"], ["asset_versions.project_id", "asset_versions.asset_id", "asset_versions.id"], name="fk_validation_attempts_exact_version", ondelete="RESTRICT"),
    )
    op.create_index("ix_validation_attempts_version_created", "asset_validation_attempts", ["version_id", "created_at"])
    op.create_index(
        "uq_validation_attempts_one_active_per_version", "asset_validation_attempts", ["version_id"],
        unique=True, postgresql_where=sa.text("state IN ('queued', 'running')"),
    )

    op.create_table(
        "asset_validation_evidence",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("storage_provider", sa.String(80), nullable=False),
        sa.Column("object_version_reference", sa.Text(), nullable=False),
        sa.Column("sha256_hex", sa.String(64), nullable=False),
        sa.Column("observed_byte_count", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.String(100), nullable=False),
        sa.Column("profile_version", sa.String(80), nullable=False),
        sa.Column("validator_identity", sa.String(160), nullable=False),
        sa.Column("validator_build", sa.String(160), nullable=False),
        sa.Column("evidence_payload", sa.JSON(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(sha256_hex) = 64 AND sha256_hex ~ '^[0-9a-f]{64}$'", name="ck_asset_validation_evidence_sha256_lower_hex"),
        sa.CheckConstraint("observed_byte_count > 0", name="ck_asset_validation_evidence_observed_bytes_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_asset_validation_evidence"),
        sa.UniqueConstraint("project_id", "asset_id", "version_id", "id", name="uq_asset_evidence_version_identity"),
        sa.UniqueConstraint("version_id", "attempt_id", name="uq_asset_evidence_attempt"),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "version_id", "attempt_id"], ["asset_validation_attempts.project_id", "asset_validation_attempts.asset_id", "asset_validation_attempts.version_id", "asset_validation_attempts.id"], name="fk_asset_evidence_attempt_same_version", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "version_id"], ["asset_versions.project_id", "asset_versions.asset_id", "asset_versions.id"], name="fk_asset_evidence_exact_version", ondelete="RESTRICT"),
    )
    op.create_index("ix_asset_evidence_version_created", "asset_validation_evidence", ["version_id", "created_at"])

    op.create_table(
        "asset_evidence_revocations",
        sa.Column("evidence_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("revoked_by", sa.String(160), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.CheckConstraint("length(reason_code) > 0", name="ck_asset_evidence_revocations_reason_code_nonblank"),
        sa.PrimaryKeyConstraint("evidence_id", name="pk_asset_evidence_revocations"),
        sa.ForeignKeyConstraint(["evidence_id"], ["asset_validation_evidence.id"], name="fk_evidence_revocations_evidence", ondelete="RESTRICT"),
    )

    # Add cyclic same-version pointers after their target tables exist.
    op.create_foreign_key(
        "fk_assets_current_ready_version_same_asset", "assets", "asset_versions",
        ["project_id", "id", "current_ready_version_id"],
        ["project_id", "asset_id", "id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_asset_versions_current_attempt_same_version", "asset_versions", "asset_validation_attempts",
        ["project_id", "asset_id", "id", "current_attempt_id"],
        ["project_id", "asset_id", "version_id", "id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_asset_versions_accepted_evidence_same_version", "asset_versions", "asset_validation_evidence",
        ["project_id", "asset_id", "id", "accepted_evidence_id"],
        ["project_id", "asset_id", "version_id", "id"], ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE FUNCTION spotloom_asset_version_identity_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'asset version history is retained' USING ERRCODE = '23514';
            END IF;
            IF ROW(OLD.id, OLD.project_id, OLD.asset_id, OLD.upload_intent_id,
                   OLD.storage_provider, OLD.object_version_reference, OLD.byte_size,
                   OLD.detected_media_type, OLD.finalized_at)
               IS DISTINCT FROM
               ROW(NEW.id, NEW.project_id, NEW.asset_id, NEW.upload_intent_id,
                   NEW.storage_provider, NEW.object_version_reference, NEW.byte_size,
                   NEW.detected_media_type, NEW.finalized_at) THEN
                RAISE EXCEPTION 'asset version identity is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_versions_immutable_identity BEFORE UPDATE OR DELETE ON asset_versions "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_version_identity_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_asset_ready_pointer_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE target_state text;
                target_evidence uuid;
        BEGIN
            IF NEW.current_ready_version_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT validation_state, accepted_evidence_id INTO target_state, target_evidence
              FROM asset_versions
             WHERE project_id = NEW.project_id
               AND asset_id = NEW.id
               AND id = NEW.current_ready_version_id;
            IF target_state IS DISTINCT FROM 'ready' OR EXISTS (
                SELECT 1 FROM asset_evidence_revocations WHERE evidence_id = target_evidence
            ) THEN
                RAISE EXCEPTION 'current asset version must be ready' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_assets_current_version_must_be_ready_insert BEFORE INSERT ON assets "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_ready_pointer_guard()"
    )
    op.execute(
        "CREATE TRIGGER trg_assets_current_version_must_be_ready_update BEFORE UPDATE OF current_ready_version_id ON assets "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_ready_pointer_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_retain_current_ready_version() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.validation_state = 'ready'
               AND (NEW.validation_state <> 'ready'
                    OR NEW.accepted_evidence_id IS DISTINCT FROM OLD.accepted_evidence_id)
               AND EXISTS (
                   SELECT 1 FROM assets
                    WHERE project_id = OLD.project_id
                      AND id = OLD.asset_id
                      AND current_ready_version_id = OLD.id
               ) THEN
                RAISE EXCEPTION 'promote a validated replacement before changing the current ready version' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_versions_retain_current_ready BEFORE UPDATE OF validation_state, accepted_evidence_id ON asset_versions "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_retain_current_ready_version()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_asset_evidence_binding_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE stored_provider text;
                stored_reference text;
                stored_size bigint;
                attempt_state text;
        BEGIN
            SELECT v.storage_provider, v.object_version_reference, v.byte_size, a.state
              INTO stored_provider, stored_reference, stored_size, attempt_state
              FROM asset_versions v
              JOIN asset_validation_attempts a
                ON a.project_id = NEW.project_id
               AND a.asset_id = NEW.asset_id
               AND a.version_id = NEW.version_id
               AND a.id = NEW.attempt_id
             WHERE v.project_id = NEW.project_id
               AND v.asset_id = NEW.asset_id
               AND v.id = NEW.version_id;
            IF stored_provider IS DISTINCT FROM NEW.storage_provider
               OR stored_reference IS DISTINCT FROM NEW.object_version_reference
               OR stored_size IS DISTINCT FROM NEW.observed_byte_count
               OR attempt_state IS DISTINCT FROM 'succeeded' THEN
                RAISE EXCEPTION 'validation evidence does not match finalized version bytes' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_validation_evidence_exact_version BEFORE INSERT ON asset_validation_evidence "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_evidence_binding_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_asset_attempt_identity_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'asset validation history is retained' USING ERRCODE = '23514';
            END IF;
            IF ROW(OLD.id, OLD.project_id, OLD.asset_id, OLD.version_id,
                   OLD.attempt_number, OLD.profile_id, OLD.profile_version,
                   OLD.validator_identity, OLD.validator_build)
               IS DISTINCT FROM
               ROW(NEW.id, NEW.project_id, NEW.asset_id, NEW.version_id,
                   NEW.attempt_number, NEW.profile_id, NEW.profile_version,
                   NEW.validator_identity, NEW.validator_build) THEN
                RAISE EXCEPTION 'asset validation attempt identity is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_validation_attempts_immutable_identity BEFORE UPDATE OR DELETE ON asset_validation_attempts "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_attempt_identity_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_asset_evidence_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'asset validation evidence is immutable' USING ERRCODE = '23514';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_validation_evidence_immutable BEFORE UPDATE OR DELETE ON asset_validation_evidence "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_evidence_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_asset_evidence_revocation_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE evidence_project uuid;
                evidence_asset uuid;
                evidence_version uuid;
        BEGIN
            SELECT project_id, asset_id, version_id
              INTO evidence_project, evidence_asset, evidence_version
              FROM asset_validation_evidence
             WHERE id = NEW.evidence_id;
            UPDATE assets
               SET current_ready_version_id = NULL,
                   state_revision = state_revision + 1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE project_id = evidence_project
               AND id = evidence_asset
               AND current_ready_version_id = evidence_version;
            UPDATE asset_versions
               SET validation_state = 'revoked',
                   accepted_evidence_id = NULL,
                   state_revision = state_revision + 1
             WHERE project_id = evidence_project
               AND asset_id = evidence_asset
               AND id = evidence_version
               AND accepted_evidence_id = NEW.evidence_id;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_evidence_revocation_blocks_readiness AFTER INSERT ON asset_evidence_revocations "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_evidence_revocation_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_asset_validation_evidence_immutable ON asset_validation_evidence")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_validation_evidence_exact_version ON asset_validation_evidence")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_evidence_revocation_blocks_readiness ON asset_evidence_revocations")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_validation_attempts_immutable_identity ON asset_validation_attempts")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_attempt_identity_guard()")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_evidence_guard()")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_evidence_revocation_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_versions_retain_current_ready ON asset_versions")
    op.execute("DROP FUNCTION IF EXISTS spotloom_retain_current_ready_version()")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_evidence_binding_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_assets_current_version_must_be_ready_update ON assets")
    op.execute("DROP TRIGGER IF EXISTS trg_assets_current_version_must_be_ready_insert ON assets")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_ready_pointer_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_versions_immutable_identity ON asset_versions")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_version_identity_guard()")

    op.drop_constraint("fk_asset_versions_accepted_evidence_same_version", "asset_versions", type_="foreignkey")
    op.drop_constraint("fk_asset_versions_current_attempt_same_version", "asset_versions", type_="foreignkey")
    op.drop_constraint("fk_assets_current_ready_version_same_asset", "assets", type_="foreignkey")

    op.drop_table("asset_evidence_revocations")
    op.drop_index("ix_asset_evidence_version_created", table_name="asset_validation_evidence")
    op.drop_table("asset_validation_evidence")
    op.drop_index("uq_validation_attempts_one_active_per_version", table_name="asset_validation_attempts")
    op.drop_index("ix_validation_attempts_version_created", table_name="asset_validation_attempts")
    op.drop_table("asset_validation_attempts")
    op.drop_index("ix_asset_versions_asset_created", table_name="asset_versions")
    op.drop_table("asset_versions")
    op.drop_index("ix_upload_intents_project_state_expiry", table_name="asset_upload_intents")
    op.drop_table("asset_upload_intents")
    op.drop_index("ix_assets_project_created_id", table_name="assets")
    op.drop_table("assets")
    op.drop_table("project_asset_usage")
