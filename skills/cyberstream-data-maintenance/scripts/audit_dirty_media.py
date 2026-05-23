#!/usr/bin/env python3
"""Read-only CyberStream dirty media audit."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


NON_ATTENTION_SOURCES = {
    "ANILIST",
    "BANGUMI",
    "TENCENT_VIDEO",
    "TMDB_STRICT",
    "NFO_TMDB",
    "TMDB",
    "LOCAL_MANUAL_MOVIE",
    "LOCAL_MANUAL_TV",
}
AD_PATTERNS = ["BTHDTV", "BBQDDQ", "HDBTHD", "DDHDTV", "BPHDTV"]


def row_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def open_readonly(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def audit(db_path: Path, ad_max_mb: float) -> dict[str, Any]:
    con = open_readonly(db_path)
    try:
        summary = {
            "movies": con.execute("SELECT COUNT(*) FROM movies").fetchone()[0],
            "media_resources": con.execute("SELECT COUNT(*) FROM media_resources").fetchone()[0],
        }

        local_or_fallback = row_dicts(
            con.execute(
                """
                SELECT
                  m.id,
                  m.title,
                  m.year,
                  m.tmdb_id,
                  m.scraper_source,
                  CASE WHEN m.cover IS NULL OR m.cover='' THEN 0 ELSE 1 END AS has_cover,
                  COUNT(r.id) AS resources,
                  GROUP_CONCAT(DISTINCT COALESCE(CAST(r.season AS TEXT), 'NULL')) AS seasons,
                  SUM(CASE WHEN r.episode IS NULL THEN 1 ELSE 0 END) AS episode_nulls,
                  MIN(r.path) AS sample_path
                FROM movies m
                LEFT JOIN media_resources r ON r.movie_id = m.id
                WHERE m.scraper_source='Local'
                   OR m.tmdb_id LIKE 'loc-%'
                   OR m.cover IS NULL
                   OR m.cover=''
                GROUP BY m.id
                ORDER BY resources DESC, m.title
                """
            )
        )

        placeholders = ",".join("?" for _ in NON_ATTENTION_SOURCES)
        other_video_like = row_dicts(
            con.execute(
                f"""
                SELECT
                  m.id AS movie_id,
                  m.title,
                  m.year,
                  m.tmdb_id,
                  m.scraper_source,
                  r.id AS resource_id,
                  r.filename,
                  r.path,
                  r.size,
                  ROUND(COALESCE(r.size, 0) / 1024.0 / 1024.0, 2) AS size_mb
                FROM media_resources r
                JOIN movies m ON m.id = r.movie_id
                WHERE r.season IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM media_resources rx
                    WHERE rx.movie_id = m.id AND rx.season IS NOT NULL
                  )
                  AND (
                    m.scraper_source IS NULL
                    OR m.scraper_source=''
                    OR UPPER(m.scraper_source) NOT IN ({placeholders})
                  )
                ORDER BY r.created_at DESC, r.id DESC
                """,
                tuple(NON_ATTENTION_SOURCES),
            )
        )

        tv_null_season = row_dicts(
            con.execute(
                """
                SELECT
                  m.id AS movie_id,
                  m.title,
                  m.tmdb_id,
                  COUNT(r.id) AS resources,
                  MIN(r.filename) AS sample_filename,
                  MAX(r.filename) AS sample_filename_2
                FROM movies m
                JOIN media_resources r ON r.movie_id = m.id
                WHERE m.tmdb_id LIKE 'tv/%' AND r.season IS NULL
                GROUP BY m.id
                ORDER BY resources DESC, m.title
                """
            )
        )

        ad_like: list[dict[str, Any]] = []
        ad_max_bytes = int(ad_max_mb * 1024 * 1024)
        for pattern in AD_PATTERNS:
            rows = row_dicts(
                con.execute(
                    """
                    SELECT
                      ? AS pattern,
                      m.id AS movie_id,
                      m.title,
                      r.id AS resource_id,
                      r.filename,
                      r.path,
                      r.size,
                      ROUND(COALESCE(r.size, 0) / 1024.0 / 1024.0, 2) AS size_mb
                    FROM media_resources r
                    JOIN movies m ON m.id = r.movie_id
                    WHERE r.filename LIKE ?
                      AND COALESCE(r.size, 0) <= ?
                    ORDER BY m.title, r.filename
                    """,
                    (pattern, f"%{pattern}%", ad_max_bytes),
                )
            )
            ad_like.extend(rows)

        return {
            "db": str(db_path),
            "summary": summary,
            "local_or_fallback": local_or_fallback,
            "other_video_like": other_video_like,
            "tv_null_season": tv_null_season,
            "ad_like_resources": ad_like,
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only CyberStream dirty media audit")
    parser.add_argument("--db", default="cyber_library.db", help="Path to cyber_library.db")
    parser.add_argument("--ad-max-mb", type=float, default=5.0, help="Max size for ad-stub candidates")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    data = audit(Path(args.db).resolve(), ad_max_mb=args.ad_max_mb)
    print(json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
