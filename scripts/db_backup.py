#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "cyber_library.db"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"


def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _resolve(path_value):
    return Path(path_value).expanduser().resolve()


def _backup_temp_path(target: Path):
    return target.with_name(f".{target.name}.tmp")


def _integrity_check(db_path: Path):
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            results = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise SystemExit(f"integrity check failed: {db_path}: {exc}") from exc

    if results != ["ok"]:
        detail = "; ".join(str(item) for item in results[:10])
        raise SystemExit(f"integrity check failed: {db_path}: {detail}")

    return True


def _backup(db_path: Path, backup_dir: Path):
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{db_path.stem}.{_timestamp()}.db"
    counter = 1
    while target.exists():
        target = backup_dir / f"{db_path.stem}.{_timestamp()}.{counter}.db"
        counter += 1

    backup_verified = False
    temp_target = _backup_temp_path(target)
    try:
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(temp_target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

        _integrity_check(temp_target)
        temp_target.replace(target)
        backup_verified = True
    finally:
        if not backup_verified:
            try:
                temp_target.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"warning: failed to remove incomplete backup {temp_target}: {exc}", file=sys.stderr)

    print(target)
    return target


def _verify(db_path: Path):
    _integrity_check(db_path)
    print(f"{db_path}\tok")
    return True


def _list(backup_dir: Path):
    if not backup_dir.exists():
        return
    for item in sorted(backup_dir.glob("*.db"), key=lambda path: path.stat().st_mtime, reverse=True):
        size = item.stat().st_size
        print(f"{item}\t{size} bytes")


def _restore(db_path: Path, backup_path: Path, backup_dir: Path, yes: bool):
    if not yes:
        raise SystemExit("restore is destructive; rerun with --yes after verifying the backup path")
    if not backup_path.exists():
        raise SystemExit(f"backup not found: {backup_path}")

    _verify(backup_path)

    if db_path.exists():
        safety_backup = _backup(db_path, backup_dir)
        print(f"created pre-restore backup: {safety_backup}", file=sys.stderr)

    tmp_path = db_path.with_suffix(db_path.suffix + ".restore_tmp")
    restore_completed = False
    try:
        shutil.copy2(backup_path, tmp_path)
        tmp_path.replace(db_path)
        restore_completed = True
    finally:
        if not restore_completed:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"warning: failed to remove incomplete restore file {tmp_path}: {exc}", file=sys.stderr)
    print(db_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backup and restore the CyberStream SQLite database.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR), help="backup output directory")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup", help="create a timestamped SQLite backup")
    verify_parser = subparsers.add_parser("verify", help="run SQLite integrity_check on a database or backup")
    verify_parser.add_argument("target", nargs="?", help="database or backup .db file to verify; defaults to --db")
    subparsers.add_parser("list", help="list existing backups")
    restore_parser = subparsers.add_parser("restore", help="restore a database backup")
    restore_parser.add_argument("backup", help="backup .db file to restore")
    restore_parser.add_argument("--yes", action="store_true", help="confirm destructive restore")

    args = parser.parse_args(argv)
    db_path = _resolve(args.db)
    backup_dir = _resolve(args.backup_dir)

    if args.command == "backup":
        _backup(db_path, backup_dir)
    elif args.command == "verify":
        _verify(_resolve(args.target) if args.target else db_path)
    elif args.command == "list":
        _list(backup_dir)
    elif args.command == "restore":
        _restore(db_path, _resolve(args.backup), backup_dir, args.yes)


if __name__ == "__main__":
    main()
