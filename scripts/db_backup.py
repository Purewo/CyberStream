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


def _backup(db_path: Path, backup_dir: Path):
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{db_path.stem}.{_timestamp()}.db"
    counter = 1
    while target.exists():
        target = backup_dir / f"{db_path.stem}.{_timestamp()}.{counter}.db"
        counter += 1

    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    print(target)
    return target


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

    if db_path.exists():
        safety_backup = _backup(db_path, backup_dir)
        print(f"created pre-restore backup: {safety_backup}", file=sys.stderr)

    tmp_path = db_path.with_suffix(db_path.suffix + ".restore_tmp")
    shutil.copy2(backup_path, tmp_path)
    tmp_path.replace(db_path)
    print(db_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backup and restore the CyberStream SQLite database.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR), help="backup output directory")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup", help="create a timestamped SQLite backup")
    subparsers.add_parser("list", help="list existing backups")
    restore_parser = subparsers.add_parser("restore", help="restore a database backup")
    restore_parser.add_argument("backup", help="backup .db file to restore")
    restore_parser.add_argument("--yes", action="store_true", help="confirm destructive restore")

    args = parser.parse_args(argv)
    db_path = _resolve(args.db)
    backup_dir = _resolve(args.backup_dir)

    if args.command == "backup":
        _backup(db_path, backup_dir)
    elif args.command == "list":
        _list(backup_dir)
    elif args.command == "restore":
        _restore(db_path, _resolve(args.backup), backup_dir, args.yes)


if __name__ == "__main__":
    main()
