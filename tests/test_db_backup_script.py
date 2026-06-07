from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

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

    def test_backup_verifies_generated_copy_before_reporting_success(self):
        self._write_value("before")

        with patch.object(self.module, "_integrity_check", wraps=self.module._integrity_check) as integrity_check:
            output = StringIO()
            with redirect_stdout(output):
                backup_path = self.module._backup(self._db_path(), self._backup_dir())

        temp_backup_path = self.module._backup_temp_path(backup_path)
        integrity_check.assert_called_once_with(temp_backup_path)
        self.assertEqual(f"{backup_path}\n", output.getvalue())
        self.assertTrue(backup_path.exists())
        self.assertFalse(temp_backup_path.exists())

    def test_backup_rejects_generated_copy_when_integrity_check_fails(self):
        self._write_value("before")
        output = StringIO()

        with patch.object(self.module, "_integrity_check", side_effect=SystemExit("integrity check failed")):
            with self.assertRaises(SystemExit) as context:
                with redirect_stdout(output):
                    self.module._backup(self._db_path(), self._backup_dir())

        self.assertIn("integrity check failed", str(context.exception))
        self.assertEqual("", output.getvalue())
        self.assertEqual([], list(self._backup_dir().glob("*.db")))
        self.assertEqual([], list(self._backup_dir().glob("*.tmp")))

    def test_verify_accepts_current_database_and_backup_file(self):
        self._write_value("before")
        with redirect_stdout(StringIO()):
            backup_path = self.module._backup(self._db_path(), self._backup_dir())

        current_output = StringIO()
        with redirect_stdout(current_output):
            self.assertTrue(self.module._verify(self._db_path()))
        self.assertIn("\tok", current_output.getvalue())

        backup_output = StringIO()
        with redirect_stdout(backup_output):
            self.assertTrue(self.module._verify(backup_path))
        self.assertIn("\tok", backup_output.getvalue())

    def test_verify_rejects_missing_database_file(self):
        with self.assertRaises(SystemExit) as context:
            self.module._verify(self._db_path())

        self.assertIn("database not found", str(context.exception))

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

    def test_restore_rejects_corrupt_backup_before_replacing_database(self):
        self._write_value("before")
        self._backup_dir().mkdir(parents=True, exist_ok=True)
        corrupt_backup = self._backup_dir() / "corrupt.db"
        corrupt_backup.write_bytes(b"not sqlite")

        with self.assertRaises(SystemExit) as context:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.module._restore(self._db_path(), corrupt_backup, self._backup_dir(), yes=True)

        self.assertIn("integrity check failed", str(context.exception))
        self.assertEqual("before", self._read_value())


if __name__ == "__main__":
    unittest.main()
