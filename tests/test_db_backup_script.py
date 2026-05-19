from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from tests.path_cleaner_test_utils import PROJECT_ROOT


SCRIPT_PATH = PROJECT_ROOT / "scripts/db_backup.py"


def _load_backup_module():
    spec = importlib.util.spec_from_file_location("db_backup_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["db_backup_script"] = module
    spec.loader.exec_module(module)
    return module


class DbBackupScriptTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_backup_module()
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def _db_path(self):
        return self.module.Path(self.tempdir.name) / "cyber_library.db"

    def _backup_dir(self):
        return self.module.Path(self.tempdir.name) / "backups"

    def _write_value(self, value):
        conn = sqlite3.connect(self._db_path())
        try:
            conn.execute("create table if not exists items (value text)")
            conn.execute("delete from items")
            conn.execute("insert into items values (?)", (value,))
            conn.commit()
        finally:
            conn.close()

    def _read_value(self):
        conn = sqlite3.connect(self._db_path())
        try:
            return conn.execute("select value from items").fetchone()[0]
        finally:
            conn.close()

    def test_backup_creates_readable_sqlite_copy(self):
        self._write_value("before")

        with redirect_stdout(StringIO()):
            backup_path = self.module._backup(self._db_path(), self._backup_dir())

        conn = sqlite3.connect(backup_path)
        try:
            self.assertEqual("before", conn.execute("select value from items").fetchone()[0])
        finally:
            conn.close()

    def test_restore_requires_confirmation_and_keeps_pre_restore_backup(self):
        self._write_value("before")
        with redirect_stdout(StringIO()):
            backup_path = self.module._backup(self._db_path(), self._backup_dir())
        self._write_value("after")

        with self.assertRaises(SystemExit):
            self.module._restore(self._db_path(), backup_path, self._backup_dir(), yes=False)

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.module._restore(self._db_path(), backup_path, self._backup_dir(), yes=True)

        self.assertEqual("before", self._read_value())
        backups = list(self._backup_dir().glob("*.db"))
        self.assertGreaterEqual(len(backups), 2)


if __name__ == "__main__":
    unittest.main()
