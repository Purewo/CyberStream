from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from sqlalchemy import inspect as sqlalchemy_inspect

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.db.schema import ensure_sqlite_schema
from backend.app.extensions import db


class _StaleTableInspector:
    def __init__(self, engine):
        self._delegate = sqlalchemy_inspect(engine)

    def get_table_names(self):
        return []

    def get_columns(self, table_name):
        return self._delegate.get_columns(table_name)

    def get_indexes(self, table_name):
        return self._delegate.get_indexes(table_name)


class SqliteSchemaMigrationTests(unittest.TestCase):
    def test_table_patches_tolerate_stale_table_snapshot(self):
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        with app.app_context():
            db.create_all()

            with patch("backend.app.db.schema.inspect", side_effect=lambda engine: _StaleTableInspector(engine)):
                ensure_sqlite_schema(db.engine)


if __name__ == "__main__":
    unittest.main()
