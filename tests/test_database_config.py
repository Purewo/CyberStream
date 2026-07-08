from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class DatabaseConfigTests(unittest.TestCase):
    def _reload_config(self):
        import backend.config as config

        return importlib.reload(config)

    def tearDown(self):
        self._reload_config()

    def test_cyber_database_url_has_priority_over_database_url(self):
        with patch.dict(os.environ, {
            "CYBER_DATABASE_URL": "postgresql+psycopg://cyber:secret@127.0.0.1/cyber_hosted",
            "DATABASE_URL": "sqlite:////tmp/ignored.db",
        }, clear=False):
            config = self._reload_config()

        self.assertEqual(
            "postgresql+psycopg://cyber:secret@127.0.0.1/cyber_hosted",
            config.SQLALCHEMY_DATABASE_URI,
        )
        self.assertFalse(config.DATABASE_AUTO_CREATE_SCHEMA)
        self.assertEqual({"pool_pre_ping": True}, config.SQLALCHEMY_ENGINE_OPTIONS)

    def test_database_url_falls_back_to_sqlite_path_when_unset(self):
        with patch.dict(os.environ, {
            "CYBER_DATABASE_URL": "",
            "DATABASE_URL": "",
        }, clear=False):
            config = self._reload_config()

        self.assertTrue(config.SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"))
        self.assertTrue(config.DATABASE_AUTO_CREATE_SCHEMA)

    def test_fresh_sqlite_schema_uses_account_scoped_unique_constraints(self):
        from backend.app import create_app
        from backend.app.extensions import db

        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "USER_MANAGEMENT_ENABLED": False,
            "AUTH_ENABLED": False,
        })
        with app.app_context():
            constraints = {
                table_name: {
                    tuple(item["column_names"])
                    for item in inspect(db.engine).get_unique_constraints(table_name)
                }
                for table_name in (
                    "library_sources",
                    "library_movie_memberships",
                    "user_library_rules",
                    "user_preferences",
                    "user_homepage_settings",
                    "user_achievements",
                    "user_favorites",
                    "user_vault_secrets",
                    "resource_subtitles",
                    "resource_subtitle_settings",
                    "user_subtitle_settings",
                    "media_resources",
                )
            }

            self.assertIn(("account_id", "library_id", "source_id", "root_path"), constraints["library_sources"])
            self.assertIn(("account_id", "library_id", "movie_id"), constraints["library_movie_memberships"])
            self.assertIn(("account_id", "user_id", "library_id"), constraints["user_library_rules"])
            self.assertIn(("user_id",), constraints["user_preferences"])
            self.assertIn(("account_id", "user_id"), constraints["user_homepage_settings"])
            self.assertIn(("account_id", "scope_key", "achievement_id"), constraints["user_achievements"])
            self.assertIn(("account_id", "scope_key", "movie_id"), constraints["user_favorites"])
            self.assertIn(("account_id", "scope_key"), constraints["user_vault_secrets"])
            self.assertIn(("account_id", "resource_id", "candidate_id"), constraints["resource_subtitles"])
            self.assertIn(("account_id", "resource_id"), constraints["resource_subtitle_settings"])
            self.assertIn(("account_id", "user_id", "resource_id"), constraints["user_subtitle_settings"])
            self.assertIn(("account_id", "source_id", "path"), constraints["media_resources"])
            self.assertIn(("source_id", "path"), constraints["media_resources"])

    def test_sqlite_runtime_patch_replaces_global_movie_tmdb_unique_index(self):
        from backend.app.db.schema import ensure_sqlite_schema

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE movies ("
                "id VARCHAR(36) PRIMARY KEY, "
                "tmdb_id VARCHAR(50), "
                "title VARCHAR(255) NOT NULL)"
            ))
            connection.execute(text("CREATE UNIQUE INDEX ix_movies_tmdb_id ON movies (tmdb_id)"))
            connection.execute(text(
                "INSERT INTO movies (id, tmdb_id, title) VALUES ('movie-1', 'movie/1', 'Movie')"
            ))

        ensure_sqlite_schema(engine)

        indexes = {
            item["name"]: (item["column_names"], item["unique"])
            for item in inspect(engine).get_indexes("movies")
        }
        self.assertEqual((["tmdb_id"], 0), indexes["ix_movies_tmdb_id"])
        self.assertEqual((["account_id", "tmdb_id"], 1), indexes["uq_movies_account_tmdb"])


if __name__ == "__main__":
    unittest.main()
