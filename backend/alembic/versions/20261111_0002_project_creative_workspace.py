"""Add owner-scoped campaign and storyboard workspace storage.

Revision ID: 20261111_0002
Revises: 20261101_0001
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261111_0002"
down_revision = "20261101_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_creative_workspaces",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("creative_direction", sa.JSON(), nullable=False),
        sa.Column("storyboard", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 1", name="ck_project_creative_workspaces_revision_positive"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id", name="pk_project_creative_workspaces"),
    )


def downgrade() -> None:
    op.drop_table("project_creative_workspaces")
