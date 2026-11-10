"""Create the initial internal identity and project tables.

Revision ID: 20261101_0001
Revises:
Create Date: 2026-11-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261101_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_external_identities_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_external_identities"),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identities_issuer_subject"),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"], unique=False)
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            r"char_length(btrim(name, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')) > 0 "
            r"AND name = btrim(name, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')",
            name="name_nonblank",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name="fk_projects_owner_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_index(
        "ix_projects_owner_created_id",
        "projects",
        ["owner_user_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_projects_owner_created_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_table("users")
