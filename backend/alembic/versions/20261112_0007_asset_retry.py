"""Persist retry eligibility for fenced upload recovery.

Revision ID: 20261112_0007_asset_retry
Revises: 20261112_0006_asset_names
Create Date: 2026-11-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261112_0007_asset_retry"
down_revision = "20261112_0006_asset_names"
branch_labels = None
depends_on = None


def _recovery_guard_sql(*, retry_release: bool) -> str:
    """Return the complete recovery guard, preserving the 0005 transitions."""
    retry_column_insert = " OR NEW.next_retry_at IS NOT NULL" if retry_release else ""
    retry_field_in_row = ", NEW.next_retry_at" if retry_release else ""
    retry_field_in_claim_row = ", NEW.next_retry_at" if retry_release else ""
    retry_field_in_old_row = ", OLD.next_retry_at" if retry_release else ""
    retry_claim_check = " OR NEW.next_retry_at IS NOT NULL" if retry_release else ""
    retry_renew_check = " OR NEW.next_retry_at IS NOT NULL" if retry_release else ""
    retry_window_guard = (
        "IF NEW.next_retry_at IS NOT NULL\n"
        "       AND (NEW.recovery_state <> 'pending'\n"
        "            OR NEW.next_retry_at > now_value + INTERVAL '5 minutes'\n"
        "            OR NEW.next_retry_at >= NEW.recovery_deadline_at) THEN\n"
        "        RAISE EXCEPTION 'retry eligibility is outside the bounded recovery window' USING ERRCODE = '23514';\n"
        "    END IF;"
        if retry_release else ""
    )
    retry_rule = (
        "IF NEW.recovery_state = 'pending'\n"
        "                   AND OLD.recovery_lease_expires_at > now_value\n"
        "                   AND NEW.next_retry_at IS NULL THEN\n"
        "                    RAISE EXCEPTION 'active recovery lease cannot be released without a retry schedule' USING ERRCODE = '23514';\n"
        "                END IF;"
        if retry_release
        else "IF NEW.recovery_state = 'pending'\n"
        "                   AND OLD.recovery_lease_expires_at > now_value THEN\n"
        "                    RAISE EXCEPTION 'active recovery lease cannot be released for reclaim' USING ERRCODE = '23514';\n"
        "                END IF;"
    )
    return f"""
CREATE OR REPLACE FUNCTION spotloom_asset_upload_recovery_guard() RETURNS trigger
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
           OR NEW.recovery_outcome_code IS NOT NULL{retry_column_insert} THEN
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

    {retry_window_guard}

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
        NEW.recovery_finished_at, NEW.recovery_outcome_code{retry_field_in_row}
    ) IS DISTINCT FROM ROW(
        OLD.recovery_state, OLD.recovery_revision, OLD.recovery_claim_generation,
        OLD.recovery_claim_token, OLD.recovery_claimed_at, OLD.recovery_lease_issued_at,
        OLD.recovery_lease_expires_at, OLD.recovery_attempt_count,
        OLD.recovery_finished_at, OLD.recovery_outcome_code{retry_field_in_old_row}
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
           NEW.recovery_finished_at, NEW.recovery_outcome_code{retry_field_in_claim_row})
       IS NOT DISTINCT FROM
       ROW(OLD.recovery_state, OLD.recovery_claim_generation, OLD.recovery_claim_token,
           OLD.recovery_claimed_at, OLD.recovery_lease_issued_at,
           OLD.recovery_lease_expires_at, OLD.recovery_attempt_count,
           OLD.recovery_finished_at, OLD.recovery_outcome_code{retry_field_in_old_row}) THEN
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
           OR now_value >= NEW.recovery_deadline_at{retry_claim_check} THEN
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
           OR now_value >= NEW.recovery_deadline_at{retry_renew_check} THEN
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
        {retry_rule}
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
$$;
"""


def upgrade() -> None:
    op.add_column(
        "asset_upload_intents",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_asset_upload_intents_next_retry_pending_before_deadline"),
        "asset_upload_intents",
        "next_retry_at IS NULL OR "
        "(recovery_state = 'pending' AND next_retry_at < recovery_deadline_at)",
    )
    op.drop_index("ix_upload_intents_recovery_due", table_name="asset_upload_intents")
    op.create_index(
        "ix_upload_intents_recovery_due",
        "asset_upload_intents",
        ["recovery_state", "next_retry_at", "recovery_deadline_at"],
        postgresql_where=sa.text("recovery_state = 'pending'"),
    )
    op.execute(_recovery_guard_sql(retry_release=True))


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM asset_upload_intents WHERE next_retry_at IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot downgrade while a durable asset retry schedule is pending';
            END IF;
        END $$
        """
    )
    op.drop_index("ix_upload_intents_recovery_due", table_name="asset_upload_intents")
    op.create_index(
        "ix_upload_intents_recovery_due",
        "asset_upload_intents",
        ["recovery_state", "recovery_deadline_at"],
        postgresql_where=sa.text("recovery_state = 'pending'"),
    )
    op.execute(_recovery_guard_sql(retry_release=False))
    op.drop_constraint(
        op.f("ck_asset_upload_intents_next_retry_pending_before_deadline"),
        "asset_upload_intents",
        type_="check",
    )
    op.drop_column("asset_upload_intents", "next_retry_at")
