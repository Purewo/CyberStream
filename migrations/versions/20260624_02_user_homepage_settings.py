"""Add per-user homepage settings.

Revision ID: 20260624_02
Revises: 20260624_01
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260624_02"
down_revision = "20260624_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "user_homepage_settings" in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        "user_homepage_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("hero_movie_id", sa.String(length=36), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["hero_movie_id"], ["movies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "user_id", name="uq_user_homepage_settings_account_user"),
    )
    op.create_index("ix_user_homepage_settings_account_id", "user_homepage_settings", ["account_id"], unique=False)
    op.create_index("ix_user_homepage_settings_user_id", "user_homepage_settings", ["user_id"], unique=False)


def downgrade():
    op.drop_index("ix_user_homepage_settings_user_id", table_name="user_homepage_settings")
    op.drop_index("ix_user_homepage_settings_account_id", table_name="user_homepage_settings")
    op.drop_table("user_homepage_settings")
