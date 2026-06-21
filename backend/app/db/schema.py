from sqlalchemy import inspect, text


SQLITE_COLUMN_PATCHES = {
    "storage_sources": {
        "account_id": "ALTER TABLE storage_sources ADD COLUMN account_id VARCHAR(36)",
    },
    "libraries": {
        "account_id": "ALTER TABLE libraries ADD COLUMN account_id VARCHAR(36)",
    },
    "media_resources": {
        "account_id": "ALTER TABLE media_resources ADD COLUMN account_id VARCHAR(36)",
        "title": "ALTER TABLE media_resources ADD COLUMN title VARCHAR(255)",
        "overview": "ALTER TABLE media_resources ADD COLUMN overview TEXT",
        "metadata_edited_at": "ALTER TABLE media_resources ADD COLUMN metadata_edited_at DATETIME",
    },
    "movie_season_metadata": {
        "account_id": "ALTER TABLE movie_season_metadata ADD COLUMN account_id VARCHAR(36)",
        "poster": "ALTER TABLE movie_season_metadata ADD COLUMN poster VARCHAR(500)",
        "episode_count": "ALTER TABLE movie_season_metadata ADD COLUMN episode_count INTEGER",
        "aired_episode_count": "ALTER TABLE movie_season_metadata ADD COLUMN aired_episode_count INTEGER",
    },
    "library_sources": {
        "account_id": "ALTER TABLE library_sources ADD COLUMN account_id VARCHAR(36)",
        "scraper_policy": "ALTER TABLE library_sources ADD COLUMN scraper_policy JSON",
    },
    "library_movie_memberships": {
        "account_id": "ALTER TABLE library_movie_memberships ADD COLUMN account_id VARCHAR(36)",
    },
    "movies": {
        "account_id": "ALTER TABLE movies ADD COLUMN account_id VARCHAR(36)",
        "catalog_visibility_status": "ALTER TABLE movies ADD COLUMN catalog_visibility_status VARCHAR(20) NOT NULL DEFAULT 'auto'",
        "catalog_visibility_note": "ALTER TABLE movies ADD COLUMN catalog_visibility_note TEXT",
        "catalog_visibility_updated_at": "ALTER TABLE movies ADD COLUMN catalog_visibility_updated_at DATETIME",
    },
    "history": {
        "account_id": "ALTER TABLE history ADD COLUMN account_id VARCHAR(36)",
        "user_id": "ALTER TABLE history ADD COLUMN user_id INTEGER",
    },
    "user_library_rules": {
        "account_id": "ALTER TABLE user_library_rules ADD COLUMN account_id VARCHAR(36)",
    },
    "audit_logs": {
        "account_id": "ALTER TABLE audit_logs ADD COLUMN account_id VARCHAR(36)",
    },
    "homepage_settings": {
        "account_id": "ALTER TABLE homepage_settings ADD COLUMN account_id VARCHAR(36)",
    },
    "user_achievements": {
        "account_id": "ALTER TABLE user_achievements ADD COLUMN account_id VARCHAR(36)",
    },
    "user_favorites": {
        "account_id": "ALTER TABLE user_favorites ADD COLUMN account_id VARCHAR(36)",
    },
    "user_vault_secrets": {
        "account_id": "ALTER TABLE user_vault_secrets ADD COLUMN account_id VARCHAR(36)",
    },
    "maintenance_jobs": {
        "account_id": "ALTER TABLE maintenance_jobs ADD COLUMN account_id VARCHAR(36)",
    },
    "movie_metadata_locks": {
        "account_id": "ALTER TABLE movie_metadata_locks ADD COLUMN account_id VARCHAR(36)",
    },
    "resource_subtitles": {
        "account_id": "ALTER TABLE resource_subtitles ADD COLUMN account_id VARCHAR(36)",
    },
    "resource_subtitle_settings": {
        "account_id": "ALTER TABLE resource_subtitle_settings ADD COLUMN account_id VARCHAR(36)",
    },
    "user_subtitle_settings": {
        "account_id": "ALTER TABLE user_subtitle_settings ADD COLUMN account_id VARCHAR(36)",
    },
    "users": {
        "password_changed_at": "ALTER TABLE users ADD COLUMN password_changed_at DATETIME",
        "session_version": "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1",
    },
}

SQLITE_DROP_COLUMNS = {
    "libraries": {
        "library_type",
    },
}

SQLITE_INDEX_PATCHES = {
    "movies": [
        {
            "name": "uq_movies_account_tmdb",
            "ddl": """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_movies_account_tmdb
                ON movies (account_id, tmdb_id)
                WHERE account_id IS NOT NULL AND tmdb_id IS NOT NULL
            """,
            "duplicate_check": """
                SELECT account_id, tmdb_id, COUNT(*) AS duplicate_count
                FROM movies
                WHERE account_id IS NOT NULL AND tmdb_id IS NOT NULL
                GROUP BY account_id, tmdb_id
                HAVING COUNT(*) > 1
                LIMIT 1
            """,
        },
        {
            "name": "ix_movies_tmdb_id",
            "ddl": "CREATE INDEX IF NOT EXISTS ix_movies_tmdb_id ON movies (tmdb_id)",
        },
    ],
    "media_resources": [
        {
            "name": "uq_media_resources_source_path",
            "ddl": """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_media_resources_source_path
                ON media_resources (source_id, path)
                WHERE source_id IS NOT NULL
            """,
            "duplicate_check": """
                SELECT source_id, path, COUNT(*) AS duplicate_count
                FROM media_resources
                WHERE source_id IS NOT NULL
                GROUP BY source_id, path
                HAVING COUNT(*) > 1
                LIMIT 1
            """,
        },
        {
            "name": "uq_media_resources_account_source_path",
            "ddl": """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_media_resources_account_source_path
                ON media_resources (account_id, source_id, path)
                WHERE account_id IS NOT NULL AND source_id IS NOT NULL
            """,
            "duplicate_check": """
                SELECT account_id, source_id, path, COUNT(*) AS duplicate_count
                FROM media_resources
                WHERE account_id IS NOT NULL AND source_id IS NOT NULL
                GROUP BY account_id, source_id, path
                HAVING COUNT(*) > 1
                LIMIT 1
            """,
        },
    ],
    "maintenance_jobs": [
        {
            "name": "ix_maintenance_jobs_type",
            "ddl": "CREATE INDEX IF NOT EXISTS ix_maintenance_jobs_type ON maintenance_jobs (type)",
        },
        {
            "name": "ix_maintenance_jobs_status",
            "ddl": "CREATE INDEX IF NOT EXISTS ix_maintenance_jobs_status ON maintenance_jobs (status)",
        },
    ],
    "audit_logs": [
        {
            "name": "ix_audit_logs_created_at",
            "ddl": "CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at)",
        },
        {
            "name": "ix_audit_logs_action",
            "ddl": "CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action)",
        },
        {
            "name": "ix_audit_logs_outcome",
            "ddl": "CREATE INDEX IF NOT EXISTS ix_audit_logs_outcome ON audit_logs (outcome)",
        },
    ],
}

for _account_table in (
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
):
    SQLITE_INDEX_PATCHES.setdefault(_account_table, []).append({
        "name": f"ix_{_account_table}_account_id",
        "ddl": f"CREATE INDEX IF NOT EXISTS ix_{_account_table}_account_id ON {_account_table} (account_id)",
    })

SQLITE_TABLE_PATCHES = {
    "library_movie_memberships": """
        CREATE TABLE library_movie_memberships (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            library_id INTEGER NOT NULL,
            movie_id VARCHAR(36) NOT NULL,
            mode VARCHAR(20) NOT NULL,
            sort_order INTEGER NOT NULL,
            created_at DATETIME,
            updated_at DATETIME,
            PRIMARY KEY (id),
            CONSTRAINT uq_library_movie_account_membership UNIQUE (account_id, library_id, movie_id),
            FOREIGN KEY(library_id) REFERENCES libraries (id),
            FOREIGN KEY(movie_id) REFERENCES movies (id)
        )
    """,
    "homepage_settings": """
        CREATE TABLE homepage_settings (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            hero_movie_id VARCHAR(36),
            sections JSON NOT NULL,
            created_at DATETIME,
            updated_at DATETIME,
            PRIMARY KEY (id),
            FOREIGN KEY(hero_movie_id) REFERENCES movies (id)
        )
    """,
    "movie_season_metadata": """
        CREATE TABLE movie_season_metadata (
            movie_id VARCHAR(36) NOT NULL,
            season INTEGER NOT NULL,
            account_id VARCHAR(36),
            title VARCHAR(255),
            overview TEXT,
            air_date VARCHAR(10),
            poster VARCHAR(500),
            episode_count INTEGER,
            aired_episode_count INTEGER,
            metadata_edited_at DATETIME,
            created_at DATETIME,
            updated_at DATETIME,
            PRIMARY KEY (movie_id, season),
            FOREIGN KEY(movie_id) REFERENCES movies (id)
        )
    """,
    "maintenance_jobs": """
        CREATE TABLE maintenance_jobs (
            id VARCHAR(36) NOT NULL,
            account_id VARCHAR(36),
            type VARCHAR(80) NOT NULL,
            title VARCHAR(255),
            status VARCHAR(30) NOT NULL,
            created_at DATETIME NOT NULL,
            started_at DATETIME,
            finished_at DATETIME,
            updated_at DATETIME NOT NULL,
            request JSON,
            progress JSON,
            result JSON,
            error JSON,
            PRIMARY KEY (id)
        )
    """,
    "resource_subtitle_settings": """
        CREATE TABLE resource_subtitle_settings (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            resource_id VARCHAR(36) NOT NULL,
            zh_size INTEGER NOT NULL,
            zh_color VARCHAR(16) NOT NULL,
            en_size INTEGER NOT NULL,
            en_color VARCHAR(16) NOT NULL,
            gap INTEGER NOT NULL,
            offset INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_resource_subtitle_settings_account_resource UNIQUE (account_id, resource_id),
            FOREIGN KEY(resource_id) REFERENCES media_resources (id)
        )
    """,
    "users": """
        CREATE TABLE users (
            id INTEGER NOT NULL,
            username VARCHAR(80) NOT NULL,
            display_name VARCHAR(120),
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL,
            is_enabled BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            last_login_at DATETIME,
            password_changed_at DATETIME,
            session_version INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (id),
            UNIQUE (username)
        )
    """,
    "audit_logs": """
        CREATE TABLE audit_logs (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            actor_user_id INTEGER,
            actor_username VARCHAR(80),
            actor_role VARCHAR(20),
            auth_via VARCHAR(40),
            action VARCHAR(80) NOT NULL,
            target_type VARCHAR(40),
            target_id VARCHAR(80),
            target_username VARCHAR(80),
            outcome VARCHAR(30) NOT NULL,
            ip_address VARCHAR(64),
            user_agent VARCHAR(255),
            details JSON,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(actor_user_id) REFERENCES users (id)
        )
    """,
    "user_library_rules": """
        CREATE TABLE user_library_rules (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            user_id INTEGER NOT NULL,
            library_id INTEGER NOT NULL,
            mode VARCHAR(20) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_user_library_rule_account UNIQUE (account_id, user_id, library_id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(library_id) REFERENCES libraries (id)
        )
    """,
    "user_subtitle_settings": """
        CREATE TABLE user_subtitle_settings (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            user_id INTEGER NOT NULL,
            resource_id VARCHAR(36) NOT NULL,
            zh_size INTEGER NOT NULL,
            zh_color VARCHAR(16) NOT NULL,
            en_size INTEGER NOT NULL,
            en_color VARCHAR(16) NOT NULL,
            gap INTEGER NOT NULL,
            offset INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_user_subtitle_settings_account_user_resource UNIQUE (account_id, user_id, resource_id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(resource_id) REFERENCES media_resources (id)
        )
    """,
    "user_achievements": """
        CREATE TABLE user_achievements (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            scope_key VARCHAR(80) NOT NULL,
            user_id INTEGER,
            achievement_id VARCHAR(80) NOT NULL,
            unlock_source VARCHAR(40),
            unlocked_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_user_achievement_account_scope_id UNIQUE (account_id, scope_key, achievement_id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """,
    "user_favorites": """
        CREATE TABLE user_favorites (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            scope_key VARCHAR(80) NOT NULL,
            user_id INTEGER,
            movie_id VARCHAR(36) NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_user_favorite_account_scope_movie UNIQUE (account_id, scope_key, movie_id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(movie_id) REFERENCES movies (id)
        )
    """,
    "user_vault_secrets": """
        CREATE TABLE user_vault_secrets (
            id INTEGER NOT NULL,
            account_id VARCHAR(36),
            scope_key VARCHAR(80) NOT NULL,
            user_id INTEGER,
            pin_hash VARCHAR(255) NOT NULL,
            pin_changed_at DATETIME,
            pin_change_window_started_at DATETIME,
            pin_change_count INTEGER NOT NULL,
            is_locked BOOLEAN NOT NULL,
            locked_until DATETIME,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_user_vault_secret_account_scope UNIQUE (account_id, scope_key),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """,
}


def ensure_sqlite_schema(engine):
    """Apply minimal additive schema patches for existing SQLite databases.

    This project currently has no migration framework. Keep patches strictly
    additive and idempotent so startup stays safe for existing deployments.
    """
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    def _create_table_if_not_exists(ddl):
        return ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)

    with engine.begin() as conn:
        for table_name, ddl in SQLITE_TABLE_PATCHES.items():
            if table_name in existing_tables:
                continue
            conn.execute(text(_create_table_if_not_exists(ddl)))
            existing_tables.add(table_name)

        if "user_vault_secrets" in existing_tables:
            vault_columns = {col["name"]: col for col in inspect(engine).get_columns("user_vault_secrets")}
            if not vault_columns["user_id"]["nullable"]:
                conn.execute(text("""
                    CREATE TABLE user_vault_secrets_nullable (
                        id INTEGER NOT NULL,
                        account_id VARCHAR(36),
                        scope_key VARCHAR(80) NOT NULL,
                        user_id INTEGER,
                        pin_hash VARCHAR(255) NOT NULL,
                        pin_changed_at DATETIME,
                        pin_change_window_started_at DATETIME,
                        pin_change_count INTEGER NOT NULL,
                        is_locked BOOLEAN NOT NULL,
                        locked_until DATETIME,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        PRIMARY KEY (id),
                        CONSTRAINT uq_user_vault_secret_account_scope UNIQUE (account_id, scope_key),
                        FOREIGN KEY(user_id) REFERENCES users (id)
                    )
                """))
                account_select = "account_id" if "account_id" in vault_columns else "NULL AS account_id"
                conn.execute(text("""
                    INSERT INTO user_vault_secrets_nullable (
                        id, account_id, scope_key, user_id, pin_hash, pin_changed_at,
                        pin_change_window_started_at, pin_change_count, is_locked,
                        locked_until, created_at, updated_at
                    )
                    SELECT
                        id, {account_select}, scope_key, user_id, pin_hash, pin_changed_at,
                        pin_change_window_started_at, pin_change_count, is_locked,
                        locked_until, created_at, updated_at
                    FROM user_vault_secrets
                """.format(account_select=account_select)))
                conn.execute(text("DROP TABLE user_vault_secrets"))
                conn.execute(text("ALTER TABLE user_vault_secrets_nullable RENAME TO user_vault_secrets"))

        for table_name, column_patches in SQLITE_COLUMN_PATCHES.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for column_name, ddl in column_patches.items():
                if column_name in existing_columns:
                    continue
                conn.execute(text(ddl))

        if "libraries" in existing_tables:
            library_sql = conn.execute(text("""
                SELECT sql FROM sqlite_master
                WHERE type = 'table' AND name = 'libraries'
            """)).scalar() or ""
            if "UNIQUE (name)" in library_sql or "UNIQUE (slug)" in library_sql:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                conn.execute(text("PRAGMA legacy_alter_table=ON"))
                conn.execute(text("ALTER TABLE libraries RENAME TO libraries_legacy_global_unique"))
                conn.execute(text("""
                    CREATE TABLE libraries (
                        id INTEGER NOT NULL,
                        account_id VARCHAR(36),
                        name VARCHAR(100) NOT NULL,
                        slug VARCHAR(100) NOT NULL,
                        description TEXT,
                        is_enabled BOOLEAN NOT NULL,
                        sort_order INTEGER NOT NULL,
                        settings JSON,
                        created_at DATETIME,
                        updated_at DATETIME,
                        PRIMARY KEY (id),
                        CONSTRAINT uq_libraries_account_name UNIQUE (account_id, name),
                        CONSTRAINT uq_libraries_account_slug UNIQUE (account_id, slug)
                    )
                """))
                legacy_columns = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(libraries_legacy_global_unique)")).all()
                }
                account_select = "account_id" if "account_id" in legacy_columns else "NULL AS account_id"
                conn.execute(text(f"""
                    INSERT INTO libraries (
                        id, account_id, name, slug, description, is_enabled,
                        sort_order, settings, created_at, updated_at
                    )
                    SELECT
                        id, {account_select}, name, slug, description, is_enabled,
                        sort_order, settings, created_at, updated_at
                    FROM libraries_legacy_global_unique
                """))
                conn.execute(text("DROP TABLE libraries_legacy_global_unique"))
                conn.execute(text("PRAGMA legacy_alter_table=OFF"))
                conn.execute(text("PRAGMA foreign_keys=ON"))

        if "movies" in existing_tables:
            for index in inspect(engine).get_indexes("movies"):
                if (
                    index.get("name") == "ix_movies_tmdb_id"
                    and index.get("unique")
                    and index.get("column_names") == ["tmdb_id"]
                ):
                    conn.execute(text("DROP INDEX ix_movies_tmdb_id"))
                    break

        for table_name, column_names in SQLITE_DROP_COLUMNS.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for column_name in column_names:
                if column_name not in existing_columns:
                    continue
                conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {column_name}"))

        for table_name, index_patches in SQLITE_INDEX_PATCHES.items():
            if table_name not in existing_tables:
                continue

            existing_indexes = {idx["name"] for idx in inspect(engine).get_indexes(table_name)}
            for index_patch in index_patches:
                index_name = index_patch["name"]
                if index_name in existing_indexes:
                    continue

                duplicate_check = index_patch.get("duplicate_check")
                if duplicate_check:
                    duplicate = conn.execute(text(duplicate_check)).first()
                    if duplicate:
                        details = ", ".join(
                            f"{key}={getattr(duplicate, key)!r}"
                            for key in duplicate._mapping.keys()
                        )
                        raise RuntimeError(
                            f"Cannot create unique index {index_name}: duplicate rows found ({details})"
                        )

                conn.execute(text(index_patch["ddl"]))
