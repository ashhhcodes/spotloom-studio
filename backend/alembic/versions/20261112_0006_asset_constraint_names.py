"""Align asset check-constraint names with SQLAlchemy metadata.

Revision ID: 20261112_0006_asset_names
Revises: 20261112_0005_asset_recovery
Create Date: 2026-11-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv


revision = "20261112_0006_asset_names"
down_revision = "20261112_0005_asset_recovery"
branch_labels = None
depends_on = None


# These are the metadata constraint names at revision 0005. Older migrations
# supplied the already-prefixed names to CheckConstraint while the shared
# naming convention adds ck_<table>_, producing a second physical prefix.
_CHECK_SUFFIXES = {
    "asset_evidence_revocations": ("reason_code_nonblank",),
    "asset_upload_intents": (
        "active_transfer_claim_required", "active_upload_cleanup_not_claimed",
        "active_upload_not_cleaned", "cleanup_claim_generation_nonnegative",
        "cleanup_claim_generation_required", "cleanup_claim_lease_consistent",
        "cleanup_claim_state_consistent", "cleanup_confirmation_consistent",
        "cleanup_lease_positive", "cleanup_revision_nonnegative", "cleanup_state_supported",
        "completed_transfer_observed", "expiry_after_creation", "final_reference_opaque_nonblank",
        "final_reference_pair_consistent", "finalization_after_transfer",
        "finalization_claim_has_reference", "operation_claim_generation_nonnegative",
        "operation_claim_generation_required", "operation_claim_lease_consistent",
        "operation_lease_bounded", "operation_revision_nonnegative", "operation_state_supported",
        "received_bytes_bounded", "recovery_attempt_count_bounded",
        "recovery_claim_generation_nonnegative", "recovery_claim_generation_required",
        "recovery_claim_lease_consistent", "recovery_claim_state_consistent",
        "recovery_deadline_after_expiry", "recovery_deadline_max_window",
        "recovery_finalized_consistent", "recovery_finished_state_consistent",
        "recovery_lease_bounded", "recovery_outcome_code_supported",
        "recovery_requires_completed_transfer", "recovery_revision_nonnegative",
        "recovery_state_supported", "reserved_bytes_positive", "state_supported",
        "storage_finalization_timestamp_consistent", "storage_finalized_after_start",
        "transfer_completed_before_expiry", "transfer_digest_hex", "transfer_digest_shape",
        "transfer_observation_consistent",
    ),
    "asset_validation_attempts": ("attempt_number_positive", "state_supported"),
    "asset_validation_evidence": ("observed_bytes_positive", "sha256_lower_hex"),
    "asset_versions": (
        "byte_size_positive", "physical_delete_timestamp_consistent", "ready_requires_evidence",
        "revision_nonnegative", "storage_state_supported", "validation_state_supported",
        "version_finalized",
    ),
    "assets": ("kind_supported", "revision_nonnegative"),
    "project_asset_usage": (
        "quota_limit_positive", "reserved_bytes_nonnegative", "revision_nonnegative",
        "used_bytes_nonnegative",
    ),
}


def _physical_name(name: str) -> str:
    preparer = op.get_bind().dialect.identifier_preparer
    return preparer.truncate_and_render_constraint_name(conv(name), _alembic_quote=False)


def _rename(*, to_canonical: bool) -> None:
    bind = op.get_bind()
    preparer = bind.dialect.identifier_preparer
    inspector = sa.inspect(bind)

    for table, suffixes in _CHECK_SUFFIXES.items():
        existing = {item["name"] for item in inspector.get_check_constraints(table)}
        for suffix in suffixes:
            canonical_logical = f"ck_{table}_{suffix}"
            legacy_logical = f"ck_{table}_{canonical_logical}"
            canonical = _physical_name(canonical_logical)
            legacy = _physical_name(legacy_logical)
            source, target = (legacy, canonical) if to_canonical else (canonical, legacy)

            if source not in existing and target in existing:
                continue
            if source in existing and target not in existing:
                op.execute(
                    sa.text(
                        f"ALTER TABLE {preparer.quote_identifier(table)} "
                        f"RENAME CONSTRAINT {preparer.quote_identifier(source)} "
                        f"TO {preparer.quote_identifier(target)}"
                    )
                )
                existing.remove(source)
                existing.add(target)
                continue
            raise RuntimeError(
                f"asset constraint naming migration found an unexpected state for {table}.{canonical}"
            )


def upgrade() -> None:
    _rename(to_canonical=True)


def downgrade() -> None:
    _rename(to_canonical=False)
