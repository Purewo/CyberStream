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
