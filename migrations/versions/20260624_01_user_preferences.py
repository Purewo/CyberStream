"""Add opaque per-user frontend preferences.

Revision ID: 20260624_01
Revises: 20260614_01
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260624_01"
down_revision = "20260614_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "user_preferences" in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_preferences_user_id"),
    )
    op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"], unique=False)


def downgrade():
    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")
