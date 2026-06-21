"""Adopt the hosted multi-tenant account schema.

Revision ID: 20260614_01
Revises:
Create Date: 2026-06-14
"""

from __future__ import annotations

import json
import os
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260614_01"
down_revision = None
branch_labels = None
depends_on = None


ACCOUNT_SCOPED_TABLES = (
    "storage_sources",
    "libraries",
    "library_sources",
    "library_movie_memberships",
    "user_library_rules",
    "audit_logs",
    "homepage_settings",
    "movies",
    "history",
    "user_achievements",
    "user_favorites",
    "user_vault_secrets",
    "maintenance_jobs",
    "movie_metadata_locks",
    "movie_season_metadata",
    "resource_subtitles",
    "resource_subtitle_settings",
    "user_subtitle_settings",
    "media_resources",
)

DEFAULT_HOMEPAGE_SECTIONS = [
    {"key": "sci_fi", "title": "科幻", "genre": "科幻", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 0},
    {"key": "action", "title": "动作", "genre": "动作", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 1},
    {"key": "drama", "title": "剧情", "genre": "剧情", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 2},
    {"key": "animation", "title": "动画", "genre": "动画", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 3},
]


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name):
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _create_final_schema(bind):
    from backend.app.extensions import db
    import backend.app.models  # noqa: F401

    db.metadata.create_all(bind=bind)


def _ensure_account_tables(bind):
    tables = _table_names(bind)
    if "accounts" not in tables:
        op.create_table(
            "accounts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("slug", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("settings", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_accounts_slug", "accounts", ["slug"], unique=True)
        op.create_index("ix_accounts_status", "accounts", ["status"], unique=False)

    tables = _table_names(bind)
    if "account_memberships" not in tables:
        op.create_table(
            "account_memberships",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "user_id", name="uq_account_membership_user"),
        )
        op.create_index("ix_account_memberships_account_id", "account_memberships", ["account_id"])
        op.create_index("ix_account_memberships_user_id", "account_memberships", ["user_id"])
        op.create_index("ix_account_memberships_role", "account_memberships", ["role"])
        op.create_index("ix_account_memberships_status", "account_memberships", ["status"])


def _add_account_columns(bind):
    tables = _table_names(bind)
    for table_name in ACCOUNT_SCOPED_TABLES:
        if table_name not in tables:
            continue
        if "account_id" not in _column_names(bind, table_name):
            op.add_column(table_name, sa.Column("account_id", sa.String(length=36), nullable=True))
        index_name = f"ix_{table_name}_account_id"
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
        if index_name not in indexes:
            op.create_index(index_name, table_name, ["account_id"], unique=False)


def _unique_constraints(bind, table_name):
    if table_name not in _table_names(bind):
        return []
    return sa.inspect(bind).get_unique_constraints(table_name)


def _drop_unique_constraint_by_columns(bind, table_name, columns):
    expected = tuple(columns)
    for constraint in _unique_constraints(bind, table_name):
        if tuple(constraint.get("column_names") or ()) != expected:
            continue
        name = constraint.get("name")
        if not name:
            continue
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(name, type_="unique")


def _ensure_unique_constraint(bind, table_name, name, columns):
    expected = tuple(columns)
    for constraint in _unique_constraints(bind, table_name):
        if constraint.get("name") == name or tuple(constraint.get("column_names") or ()) == expected:
            return
    with op.batch_alter_table(table_name) as batch:
        batch.create_unique_constraint(name, columns)


def _adjust_account_unique_constraints(bind):
    tables = _table_names(bind)
    if "libraries" in tables:
        _drop_unique_constraint_by_columns(bind, "libraries", ["name"])
        _drop_unique_constraint_by_columns(bind, "libraries", ["slug"])
        _ensure_unique_constraint(bind, "libraries", "uq_libraries_account_name", ["account_id", "name"])
        _ensure_unique_constraint(bind, "libraries", "uq_libraries_account_slug", ["account_id", "slug"])
    if "movies" in tables:
        _drop_unique_constraint_by_columns(bind, "movies", ["tmdb_id"])
        _ensure_unique_constraint(bind, "movies", "uq_movies_account_tmdb", ["account_id", "tmdb_id"])

    account_unique_specs = {
        "library_sources": [
            (["library_id", "source_id", "root_path"], "uq_library_source_account_root", ["account_id", "library_id", "source_id", "root_path"]),
        ],
        "library_movie_memberships": [
            (["library_id", "movie_id"], "uq_library_movie_account_membership", ["account_id", "library_id", "movie_id"]),
        ],
        "user_library_rules": [
            (["user_id", "library_id"], "uq_user_library_rule_account", ["account_id", "user_id", "library_id"]),
        ],
        "user_achievements": [
            (["scope_key", "achievement_id"], "uq_user_achievement_account_scope_id", ["account_id", "scope_key", "achievement_id"]),
        ],
        "user_favorites": [
            (["scope_key", "movie_id"], "uq_user_favorite_account_scope_movie", ["account_id", "scope_key", "movie_id"]),
        ],
        "user_vault_secrets": [
            (["scope_key"], "uq_user_vault_secret_account_scope", ["account_id", "scope_key"]),
        ],
        "resource_subtitles": [
            (["resource_id", "candidate_id"], "uq_resource_subtitle_account_candidate", ["account_id", "resource_id", "candidate_id"]),
        ],
        "resource_subtitle_settings": [
            (["resource_id"], "uq_resource_subtitle_settings_account_resource", ["account_id", "resource_id"]),
        ],
        "user_subtitle_settings": [
            (["user_id", "resource_id"], "uq_user_subtitle_settings_account_user_resource", ["account_id", "user_id", "resource_id"]),
        ],
    }
    for table_name, specs in account_unique_specs.items():
        if table_name not in tables:
            continue
        for old_columns, new_name, new_columns in specs:
            _drop_unique_constraint_by_columns(bind, table_name, old_columns)
            _ensure_unique_constraint(bind, table_name, new_name, new_columns)


def _legacy_row_count(bind):
    tables = _table_names(bind)
    total = 0
    for table_name in ("storage_sources", "libraries", "movies", "media_resources"):
        if table_name in tables:
            total += int(bind.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)
    return total


def _backfill_pureworld(bind):
    bootstrap_username = (
        os.getenv("CYBER_BOOTSTRAP_ADMIN_USERNAME")
        or os.getenv("CYBER_LEGACY_ACCOUNT_USERNAME")
        or "pureworld"
    ).strip()
    user_row = bind.execute(
        sa.text("SELECT id, username, display_name FROM users WHERE username = :username"),
        {"username": bootstrap_username},
    ).mappings().first()
    if not user_row:
        if _legacy_row_count(bind):
            raise RuntimeError(
                f"Legacy data exists but owner user {bootstrap_username!r} was not found"
            )
        return

    existing_membership = bind.execute(
        sa.text("""
            SELECT am.account_id
            FROM account_memberships am
            WHERE am.user_id = :user_id AND am.status = 'active'
            ORDER BY am.id
            LIMIT 1
        """),
        {"user_id": user_row["id"]},
    ).scalar()
    if existing_membership:
        account_id = existing_membership
    else:
        account_id = str(uuid.uuid4())
        display_name = user_row["display_name"] or user_row["username"]
        slug = user_row["username"].lower()
        bind.execute(
            sa.text("""
                INSERT INTO accounts (
                    id, name, slug, status, settings, created_at, updated_at
                ) VALUES (
                    :id, :name, :slug, 'active', :settings, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """),
            {
                "id": account_id,
                "name": display_name,
                "slug": slug,
                "settings": json.dumps({}),
            },
        )
        bind.execute(
            sa.text("""
                INSERT INTO account_memberships (
                    account_id, user_id, role, status, created_at, updated_at
                ) VALUES (
                    :account_id, :user_id, 'owner', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """),
            {"account_id": account_id, "user_id": user_row["id"]},
        )

    for table_name in ACCOUNT_SCOPED_TABLES:
        if table_name not in _table_names(bind):
            continue
        bind.execute(
            sa.text(f"UPDATE {table_name} SET account_id = :account_id WHERE account_id IS NULL"),
            {"account_id": account_id},
        )

    default_library_id = bind.execute(
        sa.text("""
            SELECT id FROM libraries
            WHERE account_id = :account_id
            ORDER BY sort_order, id
            LIMIT 1
        """),
        {"account_id": account_id},
    ).scalar()
    if default_library_id is None:
        result = bind.execute(
            sa.text("""
                INSERT INTO libraries (
                    account_id, name, slug, description, is_enabled, sort_order,
                    settings, created_at, updated_at
                ) VALUES (
                    :account_id, :name, 'default', NULL, 1, 0, :settings,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """),
            {
                "account_id": account_id,
                "name": os.getenv("CYBER_DEFAULT_ACCOUNT_LIBRARY_NAME") or "默认片库",
                "settings": json.dumps({}),
            },
        )
        default_library_id = result.lastrowid

    homepage_exists = bind.execute(
        sa.text("SELECT id FROM homepage_settings WHERE account_id = :account_id LIMIT 1"),
        {"account_id": account_id},
    ).scalar()
    if homepage_exists is None:
        bind.execute(
            sa.text("""
                INSERT INTO homepage_settings (
                    account_id, hero_movie_id, sections, created_at, updated_at
                ) VALUES (
                    :account_id, NULL, :sections, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """),
            {"account_id": account_id, "sections": json.dumps(DEFAULT_HOMEPAGE_SECTIONS, ensure_ascii=False)},
        )

    bind.execute(
        sa.text("UPDATE accounts SET settings = :settings WHERE id = :account_id"),
        {
            "account_id": account_id,
            "settings": json.dumps({"default_library_id": default_library_id}),
        },
    )


def upgrade():
    bind = op.get_bind()
    if "users" not in _table_names(bind):
        _create_final_schema(bind)
        return

    _ensure_account_tables(bind)
    _create_final_schema(bind)
    _add_account_columns(bind)
    _backfill_pureworld(bind)
    _adjust_account_unique_constraints(bind)


def downgrade():
    raise RuntimeError("Hosted multi-tenant migration is intentionally irreversible")
