"""Persist bounded, independently fenced upload-recovery leases.

Revision ID: 20261112_0005_asset_recovery_leases
Revises: 20261112_0004_asset_upload_ops
Create Date: 2026-11-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261112_0005_asset_recovery"
down_revision = "20261112_0004_asset_upload_ops"
branch_labels = None
depends_on = None


_RECOVERY_WINDOW_SQL = "INTERVAL '24 hours'"
_MAX_ATTEMPTS = 10


def upgrade() -> None:
    # Do not migrate while a pre-recovery handler still owns an unexpired lease.
    # Operators must quiesce writers and retry after the bounded old lease ends.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM asset_upload_intents
                WHERE operation_state IN ('receiving', 'finalizing')
                  AND operation_claim_token IS NOT NULL
                  AND operation_lease_expires_at > clock_timestamp()
            ) THEN
                RAISE EXCEPTION 'asset recovery migration requires all legacy operation leases to expire';
            END IF;
        END $$
        """
    )

    columns = (
        sa.Column("recovery_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_state", sa.String(16), nullable=False, server_default="not_required"),
        sa.Column("recovery_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_claim_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_claim_token", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("recovery_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_lease_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_outcome_code", sa.String(40), nullable=True),
    )
    for column in columns:
        op.add_column("asset_upload_intents", column)

    # The deadline is deterministic for legacy rows. It is derived from the
    # immutable intent expiry; this is a data backfill, not a server default.
    op.execute(
        f"""
        UPDATE asset_upload_intents
        SET recovery_deadline_at = expires_at + {_RECOVERY_WINDOW_SQL}
        """
    )

    # Materialize old operation states without fabricating transfer evidence.
    # Existing finalizing claims become recovery claim generation/attempt one.
    op.drop_constraint(
        "ck_asset_upload_intents_active_operation_claim_required",
        "asset_upload_intents",
        type_="check",
    )
    op.execute(
        f"""
        UPDATE asset_upload_intents
        SET recovery_state = CASE
                WHEN operation_state = 'finalized' THEN 'completed'
                WHEN operation_state = 'uploaded'
                     AND recovery_deadline_at > clock_timestamp() THEN 'pending'
                WHEN operation_state = 'uploaded' THEN 'exhausted'
                WHEN operation_state = 'finalizing'
                     AND recovery_deadline_at > clock_timestamp() THEN 'claimed'
                WHEN operation_state = 'finalizing' THEN 'manual'
                WHEN operation_state = 'failed'
                     AND (transfer_completed_at IS NOT NULL OR finalization_started_at IS NOT NULL
                          OR final_object_version_reference IS NOT NULL) THEN 'manual'
                WHEN operation_state = 'failed' THEN 'exhausted'
                ELSE 'not_required'
            END,
            recovery_claim_generation = CASE
                WHEN operation_state = 'finalizing'
                     AND recovery_deadline_at > clock_timestamp()
                    THEN GREATEST(operation_claim_generation, 1)
                ELSE 0
            END,
            recovery_claim_token = CASE
                WHEN operation_state = 'finalizing'
                     AND recovery_deadline_at > clock_timestamp() THEN operation_claim_token
                ELSE NULL
            END,
            recovery_claimed_at = CASE
                WHEN operation_state = 'finalizing'
                     AND recovery_deadline_at > clock_timestamp() THEN operation_claimed_at
                ELSE NULL
            END,
            recovery_lease_issued_at = CASE
                WHEN operation_state = 'finalizing'
                     AND recovery_deadline_at > clock_timestamp() THEN operation_claimed_at
                ELSE NULL
            END,
            recovery_lease_expires_at = CASE
                WHEN operation_state = 'finalizing'
                     AND recovery_deadline_at > clock_timestamp() THEN operation_lease_expires_at
                ELSE NULL
            END,
            recovery_attempt_count = CASE WHEN operation_state = 'finalizing'
                     AND recovery_deadline_at > clock_timestamp() THEN 1 ELSE 0 END,
            recovery_finished_at = CASE
                WHEN operation_state = 'finalized' THEN COALESCE(storage_finalized_at, operation_updated_at)
                WHEN operation_state = 'uploaded' AND recovery_deadline_at <= clock_timestamp()
                    THEN recovery_deadline_at
                WHEN operation_state = 'finalizing' AND recovery_deadline_at <= clock_timestamp()
                    THEN COALESCE(operation_updated_at, recovery_deadline_at)
                WHEN operation_state = 'failed'
                    THEN COALESCE(operation_updated_at, created_at)
                ELSE NULL
            END,
            recovery_outcome_code = CASE
                WHEN operation_state = 'uploaded' AND recovery_deadline_at <= clock_timestamp()
                    THEN 'legacy_deadline_elapsed'
                WHEN operation_state = 'finalizing' AND recovery_deadline_at <= clock_timestamp()
                    THEN 'legacy_ambiguous'
                WHEN operation_state = 'failed'
                     AND (transfer_completed_at IS NOT NULL OR finalization_started_at IS NOT NULL
                          OR final_object_version_reference IS NOT NULL)
                    THEN 'legacy_ambiguous'
                WHEN operation_state = 'failed' THEN 'permanent_failure'
                ELSE NULL
            END,
            operation_claim_token = CASE WHEN operation_state = 'finalizing' THEN NULL ELSE operation_claim_token END,
            operation_claimed_at = CASE WHEN operation_state = 'finalizing' THEN NULL ELSE operation_claimed_at END,
            operation_lease_expires_at = CASE WHEN operation_state = 'finalizing' THEN NULL ELSE operation_lease_expires_at END,
            operation_revision = operation_revision + CASE WHEN operation_state = 'finalizing' THEN 1 ELSE 0 END
        """
    )
    op.alter_column("asset_upload_intents", "recovery_deadline_at", nullable=False)

    op.create_check_constraint(
        "ck_asset_upload_intents_active_transfer_claim_required",
        "asset_upload_intents",
        "(operation_state = 'receiving') = (operation_claim_token IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_revision_nonnegative",
        "asset_upload_intents", "recovery_revision >= 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_claim_generation_nonnegative",
        "asset_upload_intents", "recovery_claim_generation >= 0",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_attempt_count_bounded",
        "asset_upload_intents", f"recovery_attempt_count BETWEEN 0 AND {_MAX_ATTEMPTS}",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_state_supported",
        "asset_upload_intents",
        "recovery_state IN ('not_required', 'pending', 'claimed', 'completed', 'exhausted', 'manual')",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_deadline_after_expiry",
        "asset_upload_intents", "recovery_deadline_at > expires_at",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_deadline_max_window",
        "asset_upload_intents",
        f"recovery_deadline_at <= expires_at + {_RECOVERY_WINDOW_SQL}",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_claim_state_consistent",
        "asset_upload_intents",
        "(recovery_state = 'claimed') = (recovery_claim_token IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_claim_lease_consistent",
        "asset_upload_intents",
        "(recovery_claim_token IS NULL) = (recovery_claimed_at IS NULL) AND "
        "(recovery_claim_token IS NULL) = (recovery_lease_issued_at IS NULL) AND "
        "(recovery_claim_token IS NULL) = (recovery_lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_lease_bounded",
        "asset_upload_intents",
        "recovery_lease_expires_at IS NULL OR "
        "(recovery_lease_expires_at > recovery_lease_issued_at AND "
        "recovery_lease_expires_at <= recovery_deadline_at)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_claim_generation_required",
        "asset_upload_intents",
        "recovery_claim_token IS NULL OR "
        "(recovery_claim_generation > 0 AND recovery_attempt_count > 0)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_finished_state_consistent",
        "asset_upload_intents",
        "(recovery_state IN ('completed', 'exhausted', 'manual')) = "
        "(recovery_finished_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_outcome_code_supported",
        "asset_upload_intents",
        "recovery_outcome_code IS NULL OR "
        "(recovery_state IN ('exhausted', 'manual') AND recovery_outcome_code IN "
        "('deadline_elapsed', 'attempts_exhausted', 'legacy_deadline_elapsed', "
        "'legacy_ambiguous', 'permanent_failure'))",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_requires_completed_transfer",
        "asset_upload_intents",
        "recovery_state NOT IN ('pending', 'claimed') OR "
        "operation_state IN ('uploaded', 'finalizing')",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_recovery_finalized_consistent",
        "asset_upload_intents",
        "(operation_state = 'finalized') = (recovery_state = 'completed')",
    )
    op.create_check_constraint(
        "ck_asset_upload_intents_transfer_completed_before_expiry",
        "asset_upload_intents",
        "transfer_completed_at IS NULL OR transfer_completed_at <= expires_at",
    )

    op.create_index(
        "ix_upload_intents_recovery_due", "asset_upload_intents",
        ["recovery_state", "recovery_deadline_at"],
        postgresql_where=sa.text("recovery_state = 'pending'"),
    )
    op.create_index(
        "ix_upload_intents_expired_recovery_lease", "asset_upload_intents",
        ["recovery_state", "recovery_lease_expires_at"],
        postgresql_where=sa.text("recovery_state = 'claimed'"),
    )

    op.execute(
        """
        CREATE FUNCTION spotloom_asset_upload_recovery_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            now_value timestamptz;
            recovery_changed boolean;
            allowed boolean;
        BEGIN
            now_value := clock_timestamp();
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'upload recovery history is retained' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.recovery_state <> 'not_required'
                   OR NEW.recovery_revision <> 0
                   OR NEW.recovery_claim_generation <> 0
                   OR NEW.recovery_attempt_count <> 0
                   OR NEW.recovery_claim_token IS NOT NULL
                   OR NEW.recovery_claimed_at IS NOT NULL
                   OR NEW.recovery_lease_issued_at IS NOT NULL
                   OR NEW.recovery_lease_expires_at IS NOT NULL
                   OR NEW.recovery_finished_at IS NOT NULL
                   OR NEW.recovery_outcome_code IS NOT NULL THEN
                    RAISE EXCEPTION 'new upload recovery must begin unclaimed' USING ERRCODE = '23514';
                END IF;
                IF NEW.recovery_deadline_at <= now_value
                   OR NEW.recovery_deadline_at > NEW.expires_at + INTERVAL '24 hours' THEN
                    RAISE EXCEPTION 'upload recovery deadline is outside its allowed window' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR NEW.recovery_deadline_at IS DISTINCT FROM OLD.recovery_deadline_at THEN
                RAISE EXCEPTION 'upload expiry and recovery deadline are immutable' USING ERRCODE = '23514';
            END IF;

            IF OLD.operation_claim_token IS DISTINCT FROM NEW.operation_claim_token
               AND NEW.operation_claim_token IS NOT NULL
               AND (NEW.operation_state <> 'receiving'
                    OR now_value >= NEW.expires_at
                    OR NEW.operation_claimed_at > now_value
                    OR NEW.operation_lease_expires_at <= now_value) THEN
                RAISE EXCEPTION 'upload transfer claim is outside its intent expiry' USING ERRCODE = '23514';
            END IF;

            recovery_changed := ROW(
                NEW.recovery_state, NEW.recovery_revision, NEW.recovery_claim_generation,
                NEW.recovery_claim_token, NEW.recovery_claimed_at, NEW.recovery_lease_issued_at,
                NEW.recovery_lease_expires_at, NEW.recovery_attempt_count,
                NEW.recovery_finished_at, NEW.recovery_outcome_code
            ) IS DISTINCT FROM ROW(
                OLD.recovery_state, OLD.recovery_revision, OLD.recovery_claim_generation,
                OLD.recovery_claim_token, OLD.recovery_claimed_at, OLD.recovery_lease_issued_at,
                OLD.recovery_lease_expires_at, OLD.recovery_attempt_count,
                OLD.recovery_finished_at, OLD.recovery_outcome_code
            );
            IF NOT recovery_changed THEN
                RETURN NEW;
            END IF;
            IF OLD.recovery_state IN ('completed', 'exhausted', 'manual') THEN
                RAISE EXCEPTION 'terminal recovery state is immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.recovery_revision <> OLD.recovery_revision + 1 THEN
                RAISE EXCEPTION 'recovery revision must advance exactly once' USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.recovery_state, NEW.recovery_claim_generation, NEW.recovery_claim_token,
                   NEW.recovery_claimed_at, NEW.recovery_lease_issued_at,
                   NEW.recovery_lease_expires_at, NEW.recovery_attempt_count,
                   NEW.recovery_finished_at, NEW.recovery_outcome_code)
               IS NOT DISTINCT FROM
               ROW(OLD.recovery_state, OLD.recovery_claim_generation, OLD.recovery_claim_token,
                   OLD.recovery_claimed_at, OLD.recovery_lease_issued_at,
                   OLD.recovery_lease_expires_at, OLD.recovery_attempt_count,
                   OLD.recovery_finished_at, OLD.recovery_outcome_code) THEN
                RAISE EXCEPTION 'recovery revision cannot advance without a state change' USING ERRCODE = '23514';
            END IF;
            IF NEW.recovery_revision < OLD.recovery_revision
               OR NEW.recovery_claim_generation < OLD.recovery_claim_generation
               OR NEW.recovery_attempt_count < OLD.recovery_attempt_count THEN
                RAISE EXCEPTION 'recovery revisions, generations, and attempts cannot move backward' USING ERRCODE = '23514';
            END IF;

            IF OLD.recovery_state IS DISTINCT FROM NEW.recovery_state THEN
                allowed := CASE OLD.recovery_state
                    WHEN 'not_required' THEN NEW.recovery_state = 'pending'
                    WHEN 'pending' THEN NEW.recovery_state IN ('claimed', 'exhausted', 'manual')
                    WHEN 'claimed' THEN NEW.recovery_state IN ('claimed', 'pending', 'completed', 'exhausted', 'manual')
                    ELSE false
                END;
                IF NOT allowed THEN
                    RAISE EXCEPTION 'invalid upload recovery state transition' USING ERRCODE = '23514';
                END IF;
            END IF;

            IF OLD.recovery_claim_token IS DISTINCT FROM NEW.recovery_claim_token
               AND NEW.recovery_claim_token IS NOT NULL THEN
                IF NEW.recovery_state <> 'claimed'
                   OR OLD.recovery_state NOT IN ('pending', 'claimed')
                   OR (OLD.recovery_state = 'claimed' AND OLD.recovery_lease_expires_at > now_value)
                   OR OLD.recovery_claim_generation >= 2147483647
                   OR OLD.recovery_attempt_count >= 10
                   OR NEW.recovery_claim_generation <> OLD.recovery_claim_generation + 1
                   OR NEW.recovery_attempt_count <> OLD.recovery_attempt_count + 1
                   OR NEW.operation_state NOT IN ('uploaded', 'finalizing')
                   OR now_value >= NEW.recovery_deadline_at THEN
                    RAISE EXCEPTION 'recovery claim is stale, exhausted, or outside its deadline' USING ERRCODE = '23514';
                END IF;
                NEW.recovery_claimed_at := now_value;
                NEW.recovery_lease_issued_at := now_value;
                IF NEW.recovery_lease_expires_at <= now_value
                   OR NEW.recovery_lease_expires_at > now_value + INTERVAL '5 minutes'
                   OR NEW.recovery_lease_expires_at > NEW.recovery_deadline_at THEN
                    RAISE EXCEPTION 'recovery lease exceeds its allowed bound' USING ERRCODE = '23514';
                END IF;
            ELSIF OLD.recovery_claim_token IS NOT NULL
                  AND NEW.recovery_claim_token IS NOT DISTINCT FROM OLD.recovery_claim_token
                  AND NEW.recovery_lease_expires_at IS DISTINCT FROM OLD.recovery_lease_expires_at THEN
                IF OLD.recovery_state <> 'claimed'
                   OR OLD.recovery_lease_expires_at <= now_value
                   OR NEW.recovery_state <> 'claimed'
                   OR NEW.recovery_claim_generation <> OLD.recovery_claim_generation
                   OR NEW.recovery_attempt_count <> OLD.recovery_attempt_count
                   OR now_value >= NEW.recovery_deadline_at THEN
                    RAISE EXCEPTION 'expired or stale recovery lease cannot be renewed' USING ERRCODE = '23514';
                END IF;
                NEW.recovery_lease_issued_at := now_value;
                IF NEW.recovery_lease_expires_at <= now_value
                   OR NEW.recovery_lease_expires_at > now_value + INTERVAL '5 minutes'
                   OR NEW.recovery_lease_expires_at > NEW.recovery_deadline_at THEN
                    RAISE EXCEPTION 'recovery lease renewal exceeds its allowed bound' USING ERRCODE = '23514';
                END IF;
            ELSIF OLD.recovery_claim_token IS NOT NULL
                  AND NEW.recovery_claim_token IS NULL THEN
                IF NEW.recovery_state NOT IN ('pending', 'completed', 'exhausted', 'manual')
                   OR NEW.recovery_claim_generation <> OLD.recovery_claim_generation
                   OR NEW.recovery_attempt_count <> OLD.recovery_attempt_count THEN
                    RAISE EXCEPTION 'recovery claim release has inconsistent state' USING ERRCODE = '23514';
                END IF;
                IF NEW.recovery_state = 'pending'
                   AND OLD.recovery_lease_expires_at > now_value THEN
                    RAISE EXCEPTION 'active recovery lease cannot be released for reclaim' USING ERRCODE = '23514';
                END IF;
                NEW.recovery_claimed_at := NULL;
                NEW.recovery_lease_issued_at := NULL;
                NEW.recovery_lease_expires_at := NULL;
            ELSE
                IF OLD.recovery_claim_token IS NOT NULL
                   AND (NEW.recovery_claimed_at IS DISTINCT FROM OLD.recovery_claimed_at
                        OR NEW.recovery_lease_issued_at IS DISTINCT FROM OLD.recovery_lease_issued_at) THEN
                    RAISE EXCEPTION 'recovery claim timestamps change only on claim or renewal' USING ERRCODE = '23514';
                END IF;
                IF NEW.recovery_claim_generation <> OLD.recovery_claim_generation
                   OR NEW.recovery_attempt_count <> OLD.recovery_attempt_count THEN
                    RAISE EXCEPTION 'recovery generation and attempts change only on a new claim' USING ERRCODE = '23514';
                END IF;
            END IF;

            IF NEW.recovery_state IN ('completed', 'exhausted', 'manual')
               AND OLD.recovery_state NOT IN ('completed', 'exhausted', 'manual') THEN
                NEW.recovery_finished_at := now_value;
            ELSIF NEW.recovery_state IN ('pending', 'claimed', 'not_required') THEN
                NEW.recovery_finished_at := NULL;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_upload_recovery_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON asset_upload_intents "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_upload_recovery_guard()"
    )


def downgrade() -> None:
    # Old 0004 cannot represent a recovery claim/deadline or unresolved terminal
    # decision. Refuse rather than dropping information or reviving stale work.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM asset_upload_intents
                WHERE recovery_state IN ('pending', 'claimed', 'exhausted', 'manual')
                   OR operation_state = 'finalizing'
                   OR recovery_attempt_count > 0 AND recovery_state <> 'completed'
                   OR recovery_deadline_at <> expires_at + INTERVAL '24 hours'
            ) THEN
                RAISE EXCEPTION 'cannot downgrade while upload recovery state is not representable by revision 0004';
            END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_asset_upload_recovery_guard ON asset_upload_intents")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_upload_recovery_guard()")

    for name in (
        "ix_upload_intents_expired_recovery_lease",
        "ix_upload_intents_recovery_due",
    ):
        op.drop_index(name, table_name="asset_upload_intents")

    for name in (
        "ck_asset_upload_intents_transfer_completed_before_expiry",
        "ck_asset_upload_intents_recovery_finalized_consistent",
        "ck_asset_upload_intents_recovery_requires_completed_transfer",
        "ck_asset_upload_intents_recovery_outcome_code_supported",
        "ck_asset_upload_intents_recovery_finished_state_consistent",
        "ck_asset_upload_intents_recovery_claim_generation_required",
        "ck_asset_upload_intents_recovery_lease_bounded",
        "ck_asset_upload_intents_recovery_claim_lease_consistent",
        "ck_asset_upload_intents_recovery_claim_state_consistent",
        "ck_asset_upload_intents_recovery_deadline_max_window",
        "ck_asset_upload_intents_recovery_deadline_after_expiry",
        "ck_asset_upload_intents_recovery_state_supported",
        "ck_asset_upload_intents_recovery_attempt_count_bounded",
        "ck_asset_upload_intents_recovery_claim_generation_nonnegative",
        "ck_asset_upload_intents_recovery_revision_nonnegative",
        "ck_asset_upload_intents_active_transfer_claim_required",
    ):
        op.drop_constraint(name, "asset_upload_intents", type_="check")

    # Restore the exact 0004 active-claim contract before removing recovery data.
    op.create_check_constraint(
        "ck_asset_upload_intents_active_operation_claim_required",
        "asset_upload_intents",
        "(operation_state IN ('receiving', 'finalizing')) = (operation_claim_token IS NOT NULL)",
    )
    for name in (
        "recovery_outcome_code", "recovery_finished_at", "recovery_attempt_count",
        "recovery_lease_expires_at", "recovery_lease_issued_at", "recovery_claimed_at",
        "recovery_claim_token", "recovery_claim_generation", "recovery_revision",
        "recovery_state", "recovery_deadline_at",
    ):
        op.drop_column("asset_upload_intents", name)
