from __future__ import annotations

import importlib
import json
import sys
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


migration = importlib.import_module(
    "migrations.versions.20260614_01_hosted_multitenant"
)
preferences_migration = importlib.import_module(
    "migrations.versions.20260624_01_user_preferences"
)


class HostedMultitenantMigrationTests(unittest.TestCase):
    def _legacy_engine(self, *, include_owner=True):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL, "
                "display_name VARCHAR(120))"
            ))
            if include_owner:
                connection.execute(
                    text(
                        "INSERT INTO users (id, username, display_name) "
                        "VALUES (1, 'pureworld', 'Pure World')"
                    )
                )
            connection.execute(text(
                "CREATE TABLE libraries ("
                "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, "
                "slug VARCHAR(100) NOT NULL UNIQUE, description TEXT, "
                "is_enabled BOOLEAN NOT NULL DEFAULT 1, "
                "sort_order INTEGER NOT NULL DEFAULT 0, settings JSON, "
                "created_at DATETIME, updated_at DATETIME)"
            ))
            connection.execute(text(
                "INSERT INTO libraries "
                "(id, name, slug, is_enabled, sort_order, settings) "
                "VALUES (1, 'Default', 'default', 1, 0, '{}')"
            ))
            connection.execute(text(
                "CREATE TABLE movies ("
                "id VARCHAR(36) PRIMARY KEY, tmdb_id VARCHAR(50) UNIQUE, "
                "title VARCHAR(255), original_title VARCHAR(255), cover VARCHAR(255))"
            ))
            connection.execute(text(
                "INSERT INTO movies "
                "(id, tmdb_id, title, original_title, cover) "
                "VALUES ('movie-1', 'movie/1', 'Movie', 'Movie', 'poster')"
            ))
            connection.execute(text(
                "CREATE TABLE storage_sources ("
                "id INTEGER PRIMARY KEY, name VARCHAR(50), type VARCHAR(20), config JSON)"
            ))
            connection.execute(text(
                "INSERT INTO storage_sources (id, name, type, config) "
                "VALUES (1, 'Local', 'local', '{}')"
            ))
            connection.execute(text(
                "CREATE TABLE media_resources ("
                "id VARCHAR(36) PRIMARY KEY, source_id INTEGER, movie_id VARCHAR(36), "
                "path VARCHAR(255), filename VARCHAR(255), UNIQUE(source_id, path))"
            ))
            connection.execute(text(
                "INSERT INTO media_resources "
                "(id, source_id, movie_id, path, filename) "
                "VALUES ('resource-1', 1, 'movie-1', 'a.mkv', 'a.mkv')"
            ))
        return engine

    def _upgrade(self, engine):
        self._run_migration(engine, migration)

    def _run_migration(self, engine, migration_module):
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            previous_op = migration_module.op
            migration_module.op = Operations(context)
            try:
                migration_module.upgrade()
            finally:
                migration_module.op = previous_op

    def test_upgrade_backfills_pureworld_and_account_unique_constraints(self):
        engine = self._legacy_engine()

        self._upgrade(engine)

        with engine.begin() as connection:
            account_id = connection.execute(
                text("SELECT id FROM accounts WHERE slug = 'pureworld'")
            ).scalar_one()
            membership = connection.execute(text(
                "SELECT role FROM account_memberships "
                "WHERE account_id = :account_id AND user_id = 1"
            ), {"account_id": account_id}).scalar_one()
            for table_name in ("libraries", "movies", "storage_sources", "media_resources"):
                self.assertEqual(
                    account_id,
                    connection.execute(
                        text(f"SELECT account_id FROM {table_name} LIMIT 1")
                    ).scalar_one(),
                )

            homepage_sections = json.loads(connection.execute(text(
                "SELECT sections FROM homepage_settings WHERE account_id = :account_id"
            ), {"account_id": account_id}).scalar_one())
            movie_unique_columns = {
                tuple(item["column_names"])
                for item in inspect(connection).get_unique_constraints("movies")
            }
            library_unique_columns = {
                tuple(item["column_names"])
                for item in inspect(connection).get_unique_constraints("libraries")
            }

            self.assertEqual("owner", membership)
            self.assertEqual(["sci_fi", "action", "drama", "animation"], [
                item["key"] for item in homepage_sections
            ])
            self.assertIn(("account_id", "tmdb_id"), movie_unique_columns)
            self.assertNotIn(("tmdb_id",), movie_unique_columns)
            self.assertIn(("account_id", "name"), library_unique_columns)
            self.assertIn(("account_id", "slug"), library_unique_columns)

            connection.execute(text(
                "INSERT INTO accounts "
                "(id, name, slug, status, settings, created_at, updated_at) "
                "VALUES ('account-2', 'Account 2', 'account-2', 'active', '{}', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO movies (id, account_id, tmdb_id, title) "
                "VALUES ('movie-2', 'account-2', 'movie/1', 'Movie')"
            ))

    def test_user_preferences_migration_is_idempotent_after_current_model_create_all(self):
        engine = self._legacy_engine()

        self._upgrade(engine)
        self._run_migration(engine, preferences_migration)

        with engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            unique_columns = {
                tuple(item["column_names"])
                for item in inspect(connection).get_unique_constraints("user_preferences")
            }

        self.assertIn("user_preferences", tables)
        self.assertIn(("user_id",), unique_columns)

    def test_upgrade_refuses_legacy_data_without_owner_user(self):
        engine = self._legacy_engine(include_owner=False)

        with self.assertRaisesRegex(RuntimeError, "pureworld"):
            self._upgrade(engine)


if __name__ == "__main__":
    unittest.main()
