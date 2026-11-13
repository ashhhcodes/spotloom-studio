"""Persist exact cleanup claim receipts for quota accounting.

Revision ID: 20261113_0008_cleanup_receipt
Revises: 20261112_0007_asset_retry
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261113_0008_cleanup_receipt"
down_revision = "20261112_0007_asset_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_completed_claim_token", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_completed_claim_generation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "asset_upload_intents",
        sa.Column("cleanup_completed_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "asset_versions",
        sa.Column("cleanup_claim_token", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "asset_versions",
        sa.Column("cleanup_claim_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "asset_versions",
        sa.Column("cleanup_completed_claim_token", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "asset_versions",
        sa.Column("cleanup_completed_claim_generation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "asset_versions",
        sa.Column("cleanup_completed_revision", sa.Integer(), nullable=True),
    )

    op.create_check_constraint(
        "cleanup_completed_claim_state_consistent",
        "asset_upload_intents",
        "(cleanup_completed_claim_token IS NULL) = (cleanup_completed_claim_generation IS NULL) "
        "AND (cleanup_completed_claim_token IS NULL) = (cleanup_completed_revision IS NULL) "
        "AND (cleanup_completed_claim_generation IS NULL OR cleanup_completed_claim_generation > 0) "
        "AND (cleanup_completed_revision IS NULL OR cleanup_completed_revision >= 0)",
    )
    op.create_check_constraint(
        "cleanup_claim_generation_nonnegative",
        "asset_versions",
        "cleanup_claim_generation >= 0",
    )
    op.create_check_constraint(
        "cleanup_claim_generation_required",
        "asset_versions",
        "cleanup_claim_token IS NULL OR cleanup_claim_generation > 0",
    )
    op.create_check_constraint(
        "cleanup_claim_requires_pending_state",
        "asset_versions",
        "cleanup_claim_token IS NULL OR storage_state = 'deletion_pending'",
    )
    op.create_check_constraint(
        "cleanup_completed_claim_pair_consistent",
        "asset_versions",
        "(cleanup_completed_claim_token IS NULL) = (cleanup_completed_claim_generation IS NULL) "
        "AND (cleanup_completed_claim_token IS NULL) = (cleanup_completed_revision IS NULL) "
        "AND (cleanup_completed_claim_generation IS NULL OR cleanup_completed_claim_generation > 0) "
        "AND (cleanup_completed_revision IS NULL OR cleanup_completed_revision >= 0)",
    )
    op.create_check_constraint(
        "cleanup_completed_claim_requires_deleted_state",
        "asset_versions",
        "cleanup_completed_claim_token IS NULL OR storage_state = 'deleted'",
    )

    op.execute(
        """
        CREATE FUNCTION spotloom_asset_upload_cleanup_receipt_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.cleanup_completed_claim_token IS NOT NULL
                   OR NEW.cleanup_completed_claim_generation IS NOT NULL
                   OR NEW.cleanup_completed_revision IS NOT NULL THEN
                    RAISE EXCEPTION 'cleanup receipt is server generated' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(NEW.cleanup_completed_claim_token, NEW.cleanup_completed_claim_generation,
                   NEW.cleanup_completed_revision)
               IS DISTINCT FROM
               ROW(OLD.cleanup_completed_claim_token, OLD.cleanup_completed_claim_generation,
                   OLD.cleanup_completed_revision) THEN
                RAISE EXCEPTION 'cleanup receipt is immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.cleanup_state = 'claimed' AND NEW.cleanup_state = 'confirmed' THEN
                IF OLD.cleanup_claim_token IS NULL OR OLD.cleanup_claim_generation < 1 THEN
                    RAISE EXCEPTION 'confirmed cleanup requires an active claim' USING ERRCODE = '23514';
                END IF;
                NEW.cleanup_completed_claim_token := OLD.cleanup_claim_token;
                NEW.cleanup_completed_claim_generation := OLD.cleanup_claim_generation;
                NEW.cleanup_completed_revision := OLD.cleanup_revision;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_cleanup_receipt_guard "
        "BEFORE INSERT OR UPDATE ON asset_upload_intents "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_upload_cleanup_receipt_guard()"
    )

    op.execute(
        """
        CREATE FUNCTION spotloom_asset_version_cleanup_receipt_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.cleanup_claim_token IS NOT NULL
                   OR NEW.cleanup_claim_generation <> 0
                   OR NEW.cleanup_completed_claim_token IS NOT NULL
                   OR NEW.cleanup_completed_claim_generation IS NOT NULL
                   OR NEW.cleanup_completed_revision IS NOT NULL THEN
                    RAISE EXCEPTION 'version cleanup claim is server generated' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.cleanup_claim_generation < 0
               OR NEW.cleanup_claim_generation < OLD.cleanup_claim_generation THEN
                RAISE EXCEPTION 'cleanup generation cannot move backward' USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.cleanup_completed_claim_token, NEW.cleanup_completed_claim_generation,
                   NEW.cleanup_completed_revision)
               IS DISTINCT FROM
               ROW(OLD.cleanup_completed_claim_token, OLD.cleanup_completed_claim_generation,
                   OLD.cleanup_completed_revision)
               AND NOT (OLD.storage_state = 'deletion_pending' AND NEW.storage_state = 'deleted') THEN
                RAISE EXCEPTION 'completed cleanup receipt is server generated' USING ERRCODE = '23514';
            END IF;
            IF OLD.storage_state = 'present' AND NEW.storage_state = 'deletion_pending' THEN
                IF NEW.cleanup_claim_token IS NULL
                   OR NEW.cleanup_claim_generation <> OLD.cleanup_claim_generation + 1
                   OR NEW.state_revision <> OLD.state_revision + 1 THEN
                    RAISE EXCEPTION 'deletion claim must advance token, generation and revision' USING ERRCODE = '23514';
                END IF;
            ELSIF OLD.storage_state = 'deletion_pending' AND NEW.storage_state = 'deleted' THEN
                IF OLD.cleanup_claim_token IS NULL OR OLD.cleanup_claim_generation < 1
                   OR NEW.cleanup_claim_token IS NOT NULL
                   OR NEW.cleanup_claim_generation <> OLD.cleanup_claim_generation
                   OR NEW.state_revision <> OLD.state_revision + 1 THEN
                    RAISE EXCEPTION 'deleted version must complete its active cleanup claim' USING ERRCODE = '23514';
                END IF;
                NEW.cleanup_completed_claim_token := OLD.cleanup_claim_token;
                NEW.cleanup_completed_claim_generation := OLD.cleanup_claim_generation;
                NEW.cleanup_completed_revision := OLD.state_revision;
            ELSIF OLD.storage_state = 'deletion_pending'
                  AND NEW.cleanup_claim_token IS DISTINCT FROM OLD.cleanup_claim_token THEN
                RAISE EXCEPTION 'active cleanup claim cannot be replaced without a new state transition' USING ERRCODE = '23514';
            END IF;
            IF OLD.storage_state = 'deleted' AND NEW.storage_state <> 'deleted' THEN
                RAISE EXCEPTION 'deleted asset version is terminal' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_asset_version_cleanup_receipt_guard "
        "BEFORE INSERT OR UPDATE ON asset_versions "
        "FOR EACH ROW EXECUTE FUNCTION spotloom_asset_version_cleanup_receipt_guard()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        unsafe_intents = bind.exec_driver_sql(
            "SELECT EXISTS (SELECT 1 FROM asset_upload_intents "
            "WHERE cleanup_completed_claim_token IS NOT NULL)"
        ).scalar_one()
        unsafe_versions = bind.exec_driver_sql(
            "SELECT EXISTS (SELECT 1 FROM asset_versions WHERE cleanup_claim_token IS NOT NULL "
            "OR cleanup_claim_generation <> 0 OR cleanup_completed_claim_token IS NOT NULL "
            "OR cleanup_completed_claim_generation IS NOT NULL OR cleanup_completed_revision IS NOT NULL)"
        ).scalar_one()
        if unsafe_intents or unsafe_versions:
            raise RuntimeError(
                "Cannot downgrade cleanup claim receipts while durable cleanup claim data exists."
            )
    op.execute("DROP TRIGGER IF EXISTS trg_asset_version_cleanup_receipt_guard ON asset_versions")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_version_cleanup_receipt_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_cleanup_receipt_guard ON asset_upload_intents")
    op.execute("DROP FUNCTION IF EXISTS spotloom_asset_upload_cleanup_receipt_guard()")
    op.drop_constraint(
        "cleanup_completed_claim_requires_deleted_state", "asset_versions", type_="check"
    )
    op.drop_constraint(
        "cleanup_completed_claim_pair_consistent", "asset_versions", type_="check"
    )
    op.drop_constraint(
        "cleanup_claim_requires_pending_state", "asset_versions", type_="check"
    )
    op.drop_constraint(
        "cleanup_claim_generation_required", "asset_versions", type_="check"
    )
    op.drop_constraint(
        "cleanup_claim_generation_nonnegative", "asset_versions", type_="check"
    )
    op.drop_constraint(
        "cleanup_completed_claim_state_consistent", "asset_upload_intents", type_="check"
    )
    for column in (
        "cleanup_completed_revision", "cleanup_completed_claim_generation",
        "cleanup_completed_claim_token", "cleanup_claim_generation", "cleanup_claim_token",
    ):
        op.drop_column("asset_versions", column)
    for column in (
        "cleanup_completed_revision", "cleanup_completed_claim_generation",
        "cleanup_completed_claim_token",
    ):
        op.drop_column("asset_upload_intents", column)
