#!/usr/bin/env python3
"""Small DB maintenance helpers for CyberStream data-only cleanup."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


RESOURCE_DEP_TABLES = [
    "history",
    "resource_subtitle_settings",
    "resource_subtitles",
    "user_subtitle_settings",
]
MOVIE_DEP_TABLES = [
    "library_movie_memberships",
    "movie_metadata_locks",
    "movie_season_metadata",
]


def now_sqlite() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def require_yes(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Refusing to write without --yes")


def backup(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).resolve()
    backup_dir = Path(args.backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"{db_path.stem}.before_skill_maintenance_{datetime.utcnow():%Y%m%d_%H%M%S}{db_path.suffix}"
    shutil.copy2(db_path, dest)
    return {"backup": str(dest)}


def delete_resources(args: argparse.Namespace) -> dict[str, Any]:
    require_yes(args)
    resource_ids = list(dict.fromkeys(args.resource_id or []))
    if not resource_ids:
        raise SystemExit("Pass at least one --resource-id")

    con = connect(Path(args.db).resolve())
    try:
        with con:
            placeholders = ",".join("?" for _ in resource_ids)
            rows = [
                dict(row)
                for row in con.execute(
                    f"SELECT id, movie_id, filename, path, size FROM media_resources WHERE id IN ({placeholders})",
                    resource_ids,
                )
            ]
            source_movie_ids = sorted({row["movie_id"] for row in rows if row.get("movie_id")})

            deleted_deps: dict[str, int] = {}
            for table in RESOURCE_DEP_TABLES:
                cur = con.execute(f"DELETE FROM {table} WHERE resource_id IN ({placeholders})", resource_ids)
                deleted_deps[table] = cur.rowcount

            cur = con.execute(f"DELETE FROM media_resources WHERE id IN ({placeholders})", resource_ids)
            removed_movies: list[str] = []

            if args.delete_empty_movies:
                for movie_id in source_movie_ids:
                    remaining = con.execute(
                        "SELECT COUNT(*) FROM media_resources WHERE movie_id=?",
                        (movie_id,),
                    ).fetchone()[0]
                    if remaining:
                        continue
                    con.execute("UPDATE homepage_settings SET hero_movie_id=NULL WHERE hero_movie_id=?", (movie_id,))
                    for table in MOVIE_DEP_TABLES:
                        con.execute(f"DELETE FROM {table} WHERE movie_id=?", (movie_id,))
                    deleted = con.execute("DELETE FROM movies WHERE id=?", (movie_id,)).rowcount
                    if deleted:
                        removed_movies.append(movie_id)

            for movie_id in args.touch_movie_id or []:
                con.execute("UPDATE movies SET updated_at=? WHERE id=?", (now_sqlite(), movie_id))

            return {
                "matched_resources": rows,
                "deleted_resources": cur.rowcount,
                "deleted_dependencies": deleted_deps,
                "removed_empty_movies": removed_movies,
            }
    finally:
        con.close()


def parse_episode(filename: str) -> int | None:
    patterns = [
        r"\bS\d{1,2}E(\d{1,3})\b",
        r"\bE(\d{1,3})\b",
        r"第\s*(\d{1,3})\s*集",
        r"\[(\d{1,3})\](?=\[(?:HEVC|AVC|H264|H265|GB|\d{3,4}P)\])",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def normalize_tv_episodes(args: argparse.Namespace) -> dict[str, Any]:
    require_yes(args)
    con = connect(Path(args.db).resolve())
    try:
        with con:
            rows = [
                dict(row)
                for row in con.execute(
                    """
                    SELECT id, filename, season, episode
                    FROM media_resources
                    WHERE movie_id=?
                    ORDER BY filename, id
                    """,
                    (args.movie_id,),
                )
            ]
            if args.expected_count is not None and len(rows) != args.expected_count:
                raise SystemExit(f"Expected {args.expected_count} resources, found {len(rows)}")

            updated: list[dict[str, Any]] = []
            seen: set[int] = set()
            for row in rows:
                episode = parse_episode(row["filename"] or "")
                if episode is None:
                    if args.strict:
                        raise SystemExit(f"Cannot parse episode from {row['filename']!r}")
                    continue
                seen.add(episode)
                if row["season"] == args.season and row["episode"] == episode:
                    continue
                con.execute(
                    """
                    UPDATE media_resources
                    SET season=?, episode=?, metadata_edited_at=?
                    WHERE id=?
                    """,
                    (args.season, episode, now_sqlite(), row["id"]),
                )
                updated.append({"id": row["id"], "filename": row["filename"], "episode": episode})

            if args.expected_min is not None and args.expected_max is not None:
                expected = set(range(args.expected_min, args.expected_max + 1))
                if seen != expected:
                    raise SystemExit(f"Unexpected episode set: {sorted(seen)}; expected {sorted(expected)}")

            con.execute("UPDATE movies SET updated_at=? WHERE id=?", (now_sqlite(), args.movie_id))
            return {"updated": updated, "seen_episodes": sorted(seen)}
    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CyberStream DB maintenance helpers")
    parser.add_argument("--db", default="cyber_library.db", help="Path to cyber_library.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_backup = sub.add_parser("backup", help="Copy the DB to a timestamped backup")
    p_backup.add_argument("--backup-dir", default="backups")
    p_backup.set_defaults(func=backup)

    p_delete = sub.add_parser("delete-resources", help="Delete confirmed resource rows and dependencies")
    p_delete.add_argument("--resource-id", action="append", required=True)
    p_delete.add_argument("--delete-empty-movies", action="store_true")
    p_delete.add_argument("--touch-movie-id", action="append")
    p_delete.add_argument("--yes", action="store_true")
    p_delete.set_defaults(func=delete_resources)

    p_norm = sub.add_parser("normalize-tv-episodes", help="Fill season/episode from filenames")
    p_norm.add_argument("--movie-id", required=True)
    p_norm.add_argument("--season", type=int, default=1)
    p_norm.add_argument("--expected-count", type=int)
    p_norm.add_argument("--expected-min", type=int)
    p_norm.add_argument("--expected-max", type=int)
    p_norm.add_argument("--strict", action="store_true")
    p_norm.add_argument("--yes", action="store_true")
    p_norm.set_defaults(func=normalize_tv_episodes)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
