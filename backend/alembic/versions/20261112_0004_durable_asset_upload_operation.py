"""Persist fenced upload, finalization and cleanup operation state.

Revision ID: 20261112_0004_durable_asset_upload_operation
Revises: 20261112_0003_asset_persistence
Create Date: 2026-11-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261112_0004_asset_upload_ops"
down_revision = "20261112_0003_asset_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_upload_intents",
        sa.Column("operation_state", sa.String(16), server_default="open", nullable=False),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("operation_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("operation_updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("operation_claim_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("asset_upload_intents", sa.Column("operation_claim_token", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("asset_upload_intents", sa.Column("operation_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "asset_upload_intents",
        sa.Column("operation_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("asset_upload_intents", sa.Column("observed_sha256_hex", sa.String(64), nullable=True))
    op.add_column(
        "asset_upload_intents",
        sa.Column("transfer_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("asset_upload_intents", sa.Column("final_storage_provider", sa.String(80), nullable=True))
    op.add_column("asset_upload_intents", sa.Column("final_object_version_reference", sa.Text(), nullable=True))
    op.add_column(
        "asset_upload_intents",
        sa.Column("finalization_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("storage_finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_state", sa.String(16), server_default="not_required", nullable=False),
    )
    op.add_column("asset_upload_intents", sa.Column("cleanup_revision", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_claim_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("asset_upload_intents", sa.Column("cleanup_claim_token", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("asset_upload_intents", sa.Column("cleanup_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "ck_asset_upload_intents_operation_state_supported", "asset_upload_intents",
        "operation_state IN ('open', 'receiving', 'uploaded', 'finalizing', 'finalized', 'cancelled', 'expired', 'failed')",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_operation_revision_nonnegative", "asset_upload_intents",
        "operation_revision >= 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_operation_claim_generation_nonnegative", "asset_upload_intents",
        "operation_claim_generation >= 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_claim_generation_nonnegative", "asset_upload_intents",
        "cleanup_claim_generation >= 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_revision_nonnegative", "asset_upload_intents",
        "cleanup_revision >= 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_operation_claim_lease_consistent", "asset_upload_intents",
        "(operation_claim_token IS NULL) = (operation_lease_expires_at IS NULL) AND "
        "(operation_claim_token IS NULL) = (operation_claimed_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_operation_lease_bounded", "asset_upload_intents",
        "operation_lease_expires_at IS NULL OR "
        "(operation_lease_expires_at > operation_claimed_at AND operation_lease_expires_at <= expires_at)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_operation_claim_generation_required", "asset_upload_intents",
        "operation_claim_token IS NULL OR operation_claim_generation > 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_state_supported", "asset_upload_intents",
        "cleanup_state IN ('not_required', 'pending', 'claimed', 'confirmed')",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_claim_state_consistent", "asset_upload_intents",
        "(cleanup_state = 'claimed') = (cleanup_claim_token IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_claim_lease_consistent", "asset_upload_intents",
        "(cleanup_claim_token IS NULL) = (cleanup_lease_expires_at IS NULL) AND "
        "(cleanup_claim_token IS NULL) = (cleanup_claimed_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_lease_positive", "asset_upload_intents",
        "cleanup_lease_expires_at IS NULL OR cleanup_lease_expires_at > cleanup_claimed_at",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_claim_generation_required", "asset_upload_intents",
        "cleanup_claim_token IS NULL OR cleanup_claim_generation > 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_cleanup_confirmation_consistent", "asset_upload_intents",
        "(cleanup_state = 'confirmed') = (cleanup_confirmed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_active_operation_claim_required", "asset_upload_intents",
        "(operation_state IN ('receiving', 'finalizing')) = (operation_claim_token IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_transfer_observation_consistent", "asset_upload_intents",
        "(observed_sha256_hex IS NULL) = (transfer_completed_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_transfer_digest_shape", "asset_upload_intents",
        "observed_sha256_hex IS NULL OR (length(observed_sha256_hex) = 64 AND observed_sha256_hex = lower(observed_sha256_hex))",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_transfer_digest_hex", "asset_upload_intents",
        "observed_sha256_hex IS NULL OR observed_sha256_hex ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_completed_transfer_observed", "asset_upload_intents",
        "operation_state NOT IN ('uploaded', 'finalizing', 'finalized') OR "
        "(received_bytes > 0 AND observed_sha256_hex IS NOT NULL AND transfer_completed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_final_reference_pair_consistent", "asset_upload_intents",
        "(final_storage_provider IS NULL) = (final_object_version_reference IS NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_finalization_claim_has_reference", "asset_upload_intents",
        "operation_state NOT IN ('finalizing', 'finalized') OR "
        "(final_storage_provider IS NOT NULL AND finalization_started_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_final_reference_opaque_nonblank", "asset_upload_intents",
        "final_object_version_reference IS NULL OR "
        "(length(btrim(final_storage_provider)) > 0 AND "
        "length(btrim(final_object_version_reference)) > 0 AND "
        "lower(btrim(final_object_version_reference)) != 'latest')",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_finalization_after_transfer", "asset_upload_intents",
        "finalization_started_at IS NULL OR transfer_completed_at IS NOT NULL AND "
        "finalization_started_at >= transfer_completed_at",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_storage_finalization_timestamp_consistent", "asset_upload_intents",
        "(operation_state = 'finalized') = (storage_finalized_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_storage_finalized_after_start", "asset_upload_intents",
        "storage_finalized_at IS NULL OR storage_finalized_at >= finalization_started_at",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_active_upload_not_cleaned", "asset_upload_intents",
        "cleanup_state != 'confirmed' OR operation_state NOT IN ('receiving', 'uploaded', 'finalizing')",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_active_upload_cleanup_not_claimed", "asset_upload_intents",
        "cleanup_state != 'claimed' OR operation_state NOT IN ('receiving', 'uploaded', 'finalizing')",
    )

    op.create_index(
        "uq_upload_intents_final_storage_version", "asset_upload_intents",
        ["final_storage_provider", "final_object_version_reference"], unique=True,
        postgresql_where=sa.text("final_object_version_reference IS NOT NULL"),
    )
    op.create_index(
        "ix_upload_intents_expired_operation_lease", "asset_upload_intents",
        ["operation_state", "operation_lease_expires_at"],
        postgresql_where=sa.text("operation_lease_expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_upload_intents_pending_cleanup", "asset_upload_intents",
        ["cleanup_state", "cleanup_lease_expires_at"],
        postgresql_where=sa.text("cleanup_state IN ('pending', 'claimed')"),
    )

    # A detected type is unavailable during transfer. It may be populated once,
    # together with an accepted exact-version evidence reference, by the later
    # trusted validation boundary. Transfer facts alone never set this field.
    op.alter_column("asset_versions", "detected_media_type", existing_type=sa.String(80), nullable=True)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION spotloom_asset_version_identity_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'asset version history is retained' USING ERRCODE = '23514';
            END IF;
            IF ROW(OLD.id, OLD.project_id, OLD.asset_id, OLD.upload_intent_id,
                   OLD.storage_provider, OLD.object_version_reference, OLD.byte_size,
                   OLD.finalized_at)
               IS DISTINCT FROM
               ROW(NEW.id, NEW.project_id, NEW.asset_id, NEW.upload_intent_id,
                   NEW.storage_provider, NEW.object_version_reference, NEW.byte_size,
                   NEW.finalized_at) THEN
                RAISE EXCEPTION 'asset version identity is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_asset_detected_media_type_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.detected_media_type IS NOT NULL
               AND NEW.detected_media_type IS DISTINCT FROM OLD.detected_media_type THEN
                RAISE EXCEPTION 'detected media type is immutable once established' USING ERRCODE = '23514';
            END IF;
            IF OLD.detected_media_type IS NULL AND NEW.detected_media_type IS NOT NULL
               AND (NEW.accepted_evidence_id IS NULL OR NOT EXISTS (
                   SELECT 1 FROM asset_validation_evidence evidence
                   WHERE evidence.id = NEW.accepted_evidence_id
                     AND evidence.project_id = NEW.project_id
                     AND evidence.asset_id = NEW.asset_id
                     AND evidence.version_id = NEW.id
               )) THEN
                RAISE EXCEPTION 'detected media type requires accepted exact-version evidence' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_versions_detected_media_type_guard "
        "BEFORE UPDATE OF detected_media_type ON asset_versions "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_detected_media_type_guard()"
    )

    op.execute(
        """
        CREATE FUNCTION spotloom_asset_upload_operation_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE allowed boolean;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.operation_state <> 'open'
                   OR NEW.operation_revision <> 0
                   OR NEW.operation_claim_generation <> 0
                   OR NEW.operation_claim_token IS NOT NULL
                   OR NEW.operation_claimed_at IS NOT NULL
                   OR NEW.operation_lease_expires_at IS NOT NULL
                   OR NEW.observed_sha256_hex IS NOT NULL
                   OR NEW.transfer_completed_at IS NOT NULL
                   OR NEW.final_storage_provider IS NOT NULL
                   OR NEW.final_object_version_reference IS NOT NULL
                   OR NEW.finalization_started_at IS NOT NULL
                   OR NEW.storage_finalized_at IS NOT NULL
                   OR NEW.cleanup_state <> 'not_required'
                   OR NEW.cleanup_revision <> 0
                   OR NEW.cleanup_claim_generation <> 0
                   OR NEW.cleanup_claim_token IS NOT NULL
                   OR NEW.cleanup_claimed_at IS NOT NULL
                   OR NEW.cleanup_lease_expires_at IS NOT NULL
                   OR NEW.cleanup_confirmed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'upload operation must begin in the open state' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'upload operation history is retained' USING ERRCODE = '23514';
            END IF;
            IF OLD.operation_state IS DISTINCT FROM NEW.operation_state THEN
                allowed := CASE OLD.operation_state
                    WHEN 'open' THEN NEW.operation_state IN ('receiving', 'cancelled', 'expired', 'failed')
                    WHEN 'receiving' THEN NEW.operation_state IN ('uploaded', 'cancelled', 'expired', 'failed')
                    WHEN 'uploaded' THEN NEW.operation_state IN ('finalizing', 'cancelled', 'expired', 'failed')
                    WHEN 'finalizing' THEN NEW.operation_state IN ('finalized', 'failed')
                    ELSE false
                END;
                IF NOT allowed THEN
                    RAISE EXCEPTION 'invalid upload operation state transition' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF ROW(NEW.operation_state, NEW.operation_claim_token, NEW.operation_claimed_at,
                   NEW.operation_lease_expires_at, NEW.observed_sha256_hex,
                   NEW.transfer_completed_at, NEW.final_storage_provider,
                   NEW.final_object_version_reference, NEW.finalization_started_at,
                   NEW.storage_finalized_at)
               IS DISTINCT FROM
               ROW(OLD.operation_state, OLD.operation_claim_token, OLD.operation_claimed_at,
                   OLD.operation_lease_expires_at, OLD.observed_sha256_hex,
                   OLD.transfer_completed_at, OLD.final_storage_provider,
                   OLD.final_object_version_reference, OLD.finalization_started_at,
                   OLD.storage_finalized_at)
               AND NEW.operation_revision <> OLD.operation_revision + 1 THEN
                RAISE EXCEPTION 'upload operation revision must advance exactly once' USING ERRCODE = '23514';
            END IF;
            IF (OLD.observed_sha256_hex IS NOT NULL OR NEW.observed_sha256_hex IS NOT NULL)
               AND OLD.received_bytes IS DISTINCT FROM NEW.received_bytes
               AND NEW.operation_revision <> OLD.operation_revision + 1 THEN
                RAISE EXCEPTION 'observed byte count change must advance operation revision' USING ERRCODE = '23514';
            END IF;
            IF OLD.operation_claim_token IS DISTINCT FROM NEW.operation_claim_token
               AND NEW.operation_claim_token IS NOT NULL
               AND NEW.operation_claim_generation <> OLD.operation_claim_generation + 1 THEN
                RAISE EXCEPTION 'new upload claim must advance its fencing generation' USING ERRCODE = '23514';
            END IF;
            IF NEW.operation_revision < OLD.operation_revision
               OR NEW.operation_claim_generation < OLD.operation_claim_generation
               OR (OLD.operation_claim_token IS NOT DISTINCT FROM NEW.operation_claim_token
                   AND NEW.operation_claim_generation <> OLD.operation_claim_generation) THEN
                RAISE EXCEPTION 'upload operation revisions and fencing generations cannot move backward' USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.cleanup_state, NEW.cleanup_claim_token, NEW.cleanup_claimed_at,
                   NEW.cleanup_lease_expires_at, NEW.cleanup_confirmed_at)
               IS DISTINCT FROM
               ROW(OLD.cleanup_state, OLD.cleanup_claim_token, OLD.cleanup_claimed_at,
                   OLD.cleanup_lease_expires_at, OLD.cleanup_confirmed_at)
               AND NEW.cleanup_revision <> OLD.cleanup_revision + 1 THEN
                RAISE EXCEPTION 'cleanup revision must advance exactly once' USING ERRCODE = '23514';
            END IF;
            IF OLD.cleanup_claim_token IS DISTINCT FROM NEW.cleanup_claim_token
               AND NEW.cleanup_claim_token IS NOT NULL
               AND NEW.cleanup_claim_generation <> OLD.cleanup_claim_generation + 1 THEN
                RAISE EXCEPTION 'new cleanup claim must advance its fencing generation' USING ERRCODE = '23514';
            END IF;
            IF NEW.cleanup_revision < OLD.cleanup_revision
               OR NEW.cleanup_claim_generation < OLD.cleanup_claim_generation
               OR (OLD.cleanup_claim_token IS NOT DISTINCT FROM NEW.cleanup_claim_token
                   AND NEW.cleanup_claim_generation <> OLD.cleanup_claim_generation) THEN
                RAISE EXCEPTION 'cleanup revisions and fencing generations cannot move backward' USING ERRCODE = '23514';
            END IF;
            IF NEW.operation_revision IS DISTINCT FROM OLD.operation_revision THEN
                NEW.operation_updated_at := clock_timestamp();
            ELSE
                NEW.operation_updated_at := OLD.operation_updated_at;
            END IF;
            IF NEW.cleanup_revision IS DISTINCT FROM OLD.cleanup_revision THEN
                NEW.cleanup_updated_at := clock_timestamp();
            ELSE
                NEW.cleanup_updated_at := OLD.cleanup_updated_at;
            END IF;
            IF OLD.final_storage_provider IS NOT NULL
               AND ROW(NEW.final_storage_provider, NEW.final_object_version_reference)
                   IS DISTINCT FROM ROW(OLD.final_storage_provider, OLD.final_object_version_reference) THEN
                RAISE EXCEPTION 'final object reference is immutable once assigned' USING ERRCODE = '23514';
            END IF;
            IF (OLD.final_storage_provider IS NULL AND NEW.final_storage_provider IS NOT NULL
                AND NEW.operation_state NOT IN ('finalizing', 'finalized')) THEN
                RAISE EXCEPTION 'final object reference can only be assigned during finalization' USING ERRCODE = '23514';
            END IF;
            IF (OLD.finalization_started_at IS NOT NULL
                AND NEW.finalization_started_at IS DISTINCT FROM OLD.finalization_started_at)
               OR (OLD.storage_finalized_at IS NOT NULL
                   AND NEW.storage_finalized_at IS DISTINCT FROM OLD.storage_finalized_at) THEN
                RAISE EXCEPTION 'finalization timestamps are immutable once established' USING ERRCODE = '23514';
            END IF;
            IF OLD.observed_sha256_hex IS NOT NULL
               AND ROW(NEW.observed_sha256_hex, NEW.received_bytes, NEW.transfer_completed_at)
                   IS DISTINCT FROM ROW(OLD.observed_sha256_hex, OLD.received_bytes, OLD.transfer_completed_at) THEN
                RAISE EXCEPTION 'completed transfer observation is immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.cleanup_state IS DISTINCT FROM NEW.cleanup_state THEN
                allowed := CASE OLD.cleanup_state
                    WHEN 'not_required' THEN NEW.cleanup_state = 'pending'
                    WHEN 'pending' THEN NEW.cleanup_state IN ('claimed', 'confirmed')
                    WHEN 'claimed' THEN NEW.cleanup_state IN ('pending', 'confirmed')
                    ELSE false
                END;
                IF NOT allowed THEN
                    RAISE EXCEPTION 'invalid upload cleanup state transition' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_upload_operation_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON asset_upload_intents "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_upload_operation_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_asset_version_upload_binding_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE intent asset_upload_intents%ROWTYPE;
        BEGIN
            SELECT * INTO intent FROM asset_upload_intents
            WHERE id = NEW.upload_intent_id
              AND project_id = NEW.project_id
              AND asset_id = NEW.asset_id;
            IF NOT FOUND
               OR intent.operation_state <> 'finalized'
               OR intent.final_storage_provider IS DISTINCT FROM NEW.storage_provider
               OR intent.final_object_version_reference IS DISTINCT FROM NEW.object_version_reference
               OR intent.received_bytes IS DISTINCT FROM NEW.byte_size
               OR intent.observed_sha256_hex IS NULL
               OR intent.storage_finalized_at IS DISTINCT FROM NEW.finalized_at
               OR NEW.validation_state <> 'quarantined'
               OR NEW.current_attempt_id IS NOT NULL
               OR NEW.accepted_evidence_id IS NOT NULL THEN
                RAISE EXCEPTION 'asset version does not match finalized upload operation' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_versions_upload_binding_guard "
        "BEFORE INSERT ON asset_versions "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_version_upload_binding_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION spotloom_finalized_upload_has_version_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.operation_state = 'finalized' AND NOT EXISTS (
                SELECT 1 FROM asset_versions version
                WHERE version.upload_intent_id = NEW.id
                  AND version.project_id = NEW.project_id
                  AND version.asset_id = NEW.asset_id
                  AND version.storage_provider = NEW.final_storage_provider
                  AND version.object_version_reference = NEW.final_object_version_reference
                  AND version.byte_size = NEW.received_bytes
                  AND version.finalized_at = NEW.storage_finalized_at
            ) THEN
                RAISE EXCEPTION 'finalized upload operation requires its exact asset version' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_finalized_upload_has_version "
        "AFTER INSERT OR UPDATE ON asset_upload_intents "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION spotloom_finalized_upload_has_version_guard()"
    )


def downgrade() -> None:
    # Refuse to restore the old NOT NULL contract if any newly-created version
    # has not yet received a trusted detected media type. No placeholder data is
    # fabricated during rollback.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM asset_versions WHERE detected_media_type IS NULL) THEN
                RAISE EXCEPTION 'cannot downgrade while versions lack detected media type';
            END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_finalized_upload_has_version ON asset_upload_intents")
    op.execute("DROP FUNCTION IF EXISTS spotloom_finalized_upload_has_version_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_versions_upload_binding_guard ON asset_versions")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_version_upload_binding_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_upload_operation_guard ON asset_upload_intents")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_upload_operation_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_versions_detected_media_type_guard ON asset_versions")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_detected_media_type_guard()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION spotloom_asset_version_identity_guard() RETURNS trigger
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
    op.alter_column("asset_versions", "detected_media_type", existing_type=sa.String(80), nullable=False)

    for name in (
        "ix_upload_intents_pending_cleanup",
        "ix_upload_intents_expired_operation_lease",
        "uq_upload_intents_final_storage_version",
    ):
        op.drop_index(name, table_name="asset_upload_intents")

    for name in (
        "ck_asset_upload_intents_active_upload_not_cleaned",
        "ck_asset_upload_intents_active_upload_cleanup_not_claimed",
        "ck_asset_upload_intents_final_reference_opaque_nonblank",
        "ck_asset_upload_intents_storage_finalization_timestamp_consistent",
        "ck_asset_upload_intents_storage_finalized_after_start",
        "ck_asset_upload_intents_finalization_after_transfer",
        "ck_asset_upload_intents_finalization_claim_has_reference",
        "ck_asset_upload_intents_final_reference_pair_consistent",
        "ck_asset_upload_intents_completed_transfer_observed",
        "ck_asset_upload_intents_transfer_digest_hex",
        "ck_asset_upload_intents_transfer_digest_shape",
        "ck_asset_upload_intents_transfer_observation_consistent",
        "ck_asset_upload_intents_active_operation_claim_required",
        "ck_asset_upload_intents_cleanup_confirmation_consistent",
        "ck_asset_upload_intents_cleanup_claim_generation_required",
        "ck_asset_upload_intents_cleanup_claim_lease_consistent",
        "ck_asset_upload_intents_cleanup_lease_positive",
        "ck_asset_upload_intents_cleanup_claim_state_consistent",
        "ck_asset_upload_intents_cleanup_state_supported",
        "ck_asset_upload_intents_operation_claim_generation_required",
        "ck_asset_upload_intents_operation_claim_lease_consistent",
        "ck_asset_upload_intents_operation_lease_bounded",
        "ck_asset_upload_intents_cleanup_claim_generation_nonnegative",
        "ck_asset_upload_intents_cleanup_revision_nonnegative",
        "ck_asset_upload_intents_operation_claim_generation_nonnegative",
        "ck_asset_upload_intents_operation_revision_nonnegative",
        "ck_asset_upload_intents_operation_state_supported",
    ):
        op.drop_constraint(name, "asset_upload_intents", type_="check")

    for name in (
        "cleanup_confirmed_at",
        "cleanup_lease_expires_at",
        "cleanup_claimed_at",
        "cleanup_claim_token",
        "cleanup_claim_generation",
        "cleanup_revision",
        "cleanup_state",
        "cleanup_updated_at",
        "storage_finalized_at",
        "finalization_started_at",
        "final_object_version_reference",
        "final_storage_provider",
        "transfer_completed_at",
        "observed_sha256_hex",
        "operation_lease_expires_at",
        "operation_claimed_at",
        "operation_claim_token",
        "operation_claim_generation",
        "operation_revision",
        "operation_updated_at",
        "operation_state",
    ):
        op.drop_column("asset_upload_intents", name)
