from sqlalchemy import inspect, text


SQLITE_COLUMN_PATCHES = {
    "media_resources": {
        "title": "ALTER TABLE media_resources ADD COLUMN title VARCHAR(255)",
        "overview": "ALTER TABLE media_resources ADD COLUMN overview TEXT",
        "metadata_edited_at": "ALTER TABLE media_resources ADD COLUMN metadata_edited_at DATETIME",
    },
    "movie_season_metadata": {
        "poster": "ALTER TABLE movie_season_metadata ADD COLUMN poster VARCHAR(500)",
        "episode_count": "ALTER TABLE movie_season_metadata ADD COLUMN episode_count INTEGER",
    },
    "library_sources": {
        "scraper_policy": "ALTER TABLE library_sources ADD COLUMN scraper_policy JSON",
    },
    "movies": {
        "catalog_visibility_status": "ALTER TABLE movies ADD COLUMN catalog_visibility_status VARCHAR(20) NOT NULL DEFAULT 'auto'",
        "catalog_visibility_note": "ALTER TABLE movies ADD COLUMN catalog_visibility_note TEXT",
        "catalog_visibility_updated_at": "ALTER TABLE movies ADD COLUMN catalog_visibility_updated_at DATETIME",
    },
    "history": {
        "user_id": "ALTER TABLE history ADD COLUMN user_id INTEGER",
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

SQLITE_TABLE_PATCHES = {
    "library_movie_memberships": """
        CREATE TABLE library_movie_memberships (
            id INTEGER NOT NULL,
            library_id INTEGER NOT NULL,
            movie_id VARCHAR(36) NOT NULL,
            mode VARCHAR(20) NOT NULL,
            sort_order INTEGER NOT NULL,
            created_at DATETIME,
            updated_at DATETIME,
            PRIMARY KEY (id),
            CONSTRAINT uq_library_movie_membership UNIQUE (library_id, movie_id),
            FOREIGN KEY(library_id) REFERENCES libraries (id),
            FOREIGN KEY(movie_id) REFERENCES movies (id)
        )
    """,
    "homepage_settings": """
        CREATE TABLE homepage_settings (
            id INTEGER NOT NULL,
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
            title VARCHAR(255),
            overview TEXT,
            air_date VARCHAR(10),
            poster VARCHAR(500),
            episode_count INTEGER,
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
            CONSTRAINT uq_resource_subtitle_settings_resource UNIQUE (resource_id),
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
            user_id INTEGER NOT NULL,
            library_id INTEGER NOT NULL,
            mode VARCHAR(20) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_user_library_rule UNIQUE (user_id, library_id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(library_id) REFERENCES libraries (id)
        )
    """,
    "user_subtitle_settings": """
        CREATE TABLE user_subtitle_settings (
            id INTEGER NOT NULL,
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
            CONSTRAINT uq_user_subtitle_settings_user_resource UNIQUE (user_id, resource_id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(resource_id) REFERENCES media_resources (id)
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

    with engine.begin() as conn:
        for table_name, ddl in SQLITE_TABLE_PATCHES.items():
            if table_name in existing_tables:
                continue
            conn.execute(text(ddl))
            existing_tables.add(table_name)

        for table_name, column_patches in SQLITE_COLUMN_PATCHES.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for column_name, ddl in column_patches.items():
                if column_name in existing_columns:
                    continue
                conn.execute(text(ddl))

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

            existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
            for index_patch in index_patches:
                index_name = index_patch["name"]
                if index_name in existing_indexes:
                    continue

                duplicate_check = index_patch.get("duplicate_check")
                if duplicate_check:
                    duplicate = conn.execute(text(duplicate_check)).first()
                    if duplicate:
                        raise RuntimeError(
                            f"Cannot create unique index {index_name}: duplicate media resource "
                            f"source_id={duplicate.source_id} path={duplicate.path!r} count={duplicate.duplicate_count}"
                        )

                conn.execute(text(index_patch["ddl"]))
