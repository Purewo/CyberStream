# CyberStream Maintenance Reference

## Contents

- [Project Facts](#project-facts)
- [Current Operational Boundaries](#current-operational-boundaries)
- [Key Tables](#key-tables)
- [Common Classifications](#common-classifications)
- [API Recipes](#api-recipes)
- [Subtitle Maintenance](#subtitle-maintenance)
- [Vault And Favorites](#vault-and-favorites)
- [Verification Checklist](#verification-checklist)

## Project Facts

- Project root: `/home/pureworld/赛博影视`
- SQLite DB: `cyber_library.db`
- Backup directory: `backups/`
- Local backend API: `http://127.0.0.1:5004/api/v1`
- Public backend API: `https://pw.pioneer.fan:84/api/v1`
- Backend log: `backend_server.log`
- GitHub remote: `git@github.com:Purewo/CyberStream.git` as remote `github`

Keep this skill data-only by default. Do not trigger scans or scraping unless explicitly requested.

## Current Operational Boundaries

- Backend/data only. Do not edit frontend files.
- Do not trigger actual scraping or scanning during audit unless the user explicitly says to start.
- Use live docs before guessing: `GET /docs`, `GET /openapi.json`, `GET /openapi/modules`, `GET /openapi/modules/<module>.json`.
- Default metadata provider order is `nfo`, `tmdb`, `local`. `bangumi` and `anilist` can be explicit provider choices. `tencent_video` is manual-only and must not be used during whole-library auto scraping.
- `POST /movies/{id}/metadata/match` previews by default. Writes require `apply=true`; missing-poster candidates require `allow_missing_poster=true`.
- `POST /movies/{id}/resources/sync` is the preferred one-title refresh after new episodes/files arrive. It defaults `refresh=true` and refreshes AList/OpenList directories before scanning inferred roots.
- `POST /libraries/{id}/scan` defaults `refresh=true` and refreshes AList/OpenList binding `root_path` before scanning. Use `{"refresh": false}` only for deliberate cached scans.
- `POST /storage/sources/{id}/refresh` refreshes one AList/OpenList directory cache only. It does not scan or scrape.
- Favorites are the protected vault collection. `GET /libraries` intentionally does not include the virtual favorites library.
- Online subtitle search is read-only. Online subtitle download/bind, manual upload, delete, and set-default mutate backend cache/DB.
- Subtitle size is unlimited by default. Size limits exist only if positive env vars are configured:
  - `CYBER_ONLINE_SUBTITLE_EXTRACTED_MAX_BYTES`
  - `CYBER_ONLINE_SUBTITLE_NESTED_ARCHIVE_MAX_BYTES`
  - `CYBER_SUBTITLE_MANUAL_UPLOAD_MAX_BYTES`
  - `CYBER_SUBTITLE_WEBVTT_CONVERSION_MAX_BYTES`

## Key Tables

- `movies`: catalog metadata. Important fields: `id`, `tmdb_id`, `title`, `original_title`, `year`, `cover`, `scraper_source`, `catalog_visibility_status`, `added_at`, `updated_at`.
- `media_resources`: playable files. Important fields: `id`, `movie_id`, `source_id`, `path`, `filename`, `size`, `season`, `episode`, `title`, `overview`, `label`, `metadata_edited_at`.
- `movie_season_metadata`: season-level metadata for TV.
- `storage_sources`: configured local/WebDAV/SMB/FTP/AList/OpenList sources.
- `libraries` and `library_sources`: real resource libraries and their storage bindings.
- `user_favorites` and `user_vault_secrets`: protected vault/favorites state.
- Dependency tables for resource deletion: `history`, `resource_subtitle_settings`, `resource_subtitles`, `user_subtitle_settings`.
- Dependency tables for empty movie deletion: `homepage_settings`, `library_movie_memberships`, `movie_metadata_locks`, `movie_season_metadata`.

Datetime values should use SQLite/Python format like `YYYY-MM-DD HH:MM:SS.ffffff`, not an ISO `Z` suffix.

## Common Classifications

### Real Movie Or TV, Local Placeholder

Signals:
- `scraper_source='Local'`, `tmdb_id LIKE 'loc-%'`, no poster.
- File is large and has a recognizable title/year.
- `/metadata/search` returns a high-confidence TMDB/provider candidate with poster.

Action:
- Match in place with `POST /movies/{id}/metadata/match`.

### Real Resource Belongs To Existing Title

Signals:
- DB already has a correct TMDB title.
- Local/fallback resource path clearly belongs to that title, or a same-title placeholder exists separately.

Action:
- Attach resource with `POST /movies/{target_id}/resources/attach`.
- Use movie mode for films. Use TV mode with `preserve_episode_metadata=true` when season/episode values are already correct.

### TV Resources Need Episode Repair

Signals:
- `tmdb_id LIKE 'tv/%'`.
- Resources have null `season` or `episode`.
- Filename contains stable patterns such as `S01E01`, `E01`, or `第01集`.

Action:
- Use `scripts/db_maintenance.py normalize-tv-episodes` after backup.
- Verify `/movies/{id}/resources` summary and `/metadata/episode-review-items`.

### Confirmed Ad Stub

Signals:
- Filename is a download-site ad such as:
  - `BTHDTV`
  - `BBQDDQ`
  - `HDBTHD`
  - `DDHDTV`
  - `BPHDTV`
- File size is usually under 1 MB.
- No useful title/episode metadata.
- Do not classify a real feature file as an ad just because the parent folder path contains a release-site name. Judge the actual filename and size.

Action:
- Delete only DB resource rows and dependent DB rows.
- Delete empty movies only when all their resources were ad stubs.
- Do not delete physical files from the storage source unless explicitly asked.

## API Recipes

Set:

```bash
API=http://127.0.0.1:5004/api/v1
```

Search candidates:

```bash
curl -sS "$API/movies/<movie_id>/metadata/search?query=<query>&year=<year>&media_type_hint=movie&providers=tmdb"
```

Preview match:

```bash
curl -sS -X POST "$API/movies/<movie_id>/metadata/match" \
  -H 'Content-Type: application/json' \
  -d '{"candidate_id":"movie/123","provider":"tmdb","media_type_hint":"movie"}'
```

Apply match:

```bash
curl -sS -X POST "$API/movies/<movie_id>/metadata/match" \
  -H 'Content-Type: application/json' \
  -d '{"candidate_id":"movie/123","provider":"tmdb","media_type_hint":"movie","apply":true}'
```

Attach movie resource:

```bash
curl -sS -X POST "$API/movies/<target_movie_id>/resources/attach" \
  -H 'Content-Type: application/json' \
  -d '{"media_type":"movie","resource_ids":["<resource_id>"]}'
```

Attach TV resources with existing episode fields:

```bash
curl -sS -X POST "$API/movies/<target_movie_id>/resources/attach" \
  -H 'Content-Type: application/json' \
  -d '{"media_type":"tv","preserve_episode_metadata":true,"resource_ids":["<resource_id>"]}'
```

Sync one existing movie/series after files changed:

```bash
curl -sS -X POST "$API/movies/<movie_id>/resources/sync" \
  -H 'Content-Type: application/json' \
  -d '{"refresh":true}'
```

Refresh one storage directory without scanning:

```bash
curl -sS -X POST "$API/storage/sources/<source_id>/refresh" \
  -H 'Content-Type: application/json' \
  -d '{"path":"<relative/path>"}'
```

Trigger a full library scan only when asked:

```bash
curl -sS -X POST "$API/libraries/<library_id>/scan" \
  -H 'Content-Type: application/json' \
  -d '{"refresh":true}'
```

Read scan status:

```bash
curl -sS "$API/scan"
```

## Subtitle Maintenance

Search only:

```bash
curl -sS "$API/resources/<resource_id>/subtitles/online/search?query=<keyword>&providers=subhd&limit=5"
```

Search SubHD plus the slow备用源 SrtKu only when explicitly needed:

```bash
curl -sS "$API/resources/<resource_id>/subtitles/online/search?query=<keyword>&providers=subhd,srtku&limit=5&max_query_attempts=1"
```

Bind only after the user selects a candidate:

```bash
curl -sS -X POST "$API/resources/<resource_id>/subtitles/online/bind" \
  -H 'Content-Type: application/json' \
  -d '{"candidate_id":"subhd:<hash>","confirm":true}'
```

Manual upload uses multipart field `file` or `subtitle`:

```bash
curl -sS -X POST "$API/resources/<resource_id>/subtitles/upload" \
  -F "file=@/path/to/subtitle.ass" \
  -F "set_default=true"
```

Important subtitle behavior:

- Search candidates should expose stable display fields; bound subtitle display should preserve candidate title/language where available.
- `subhd` is the default source. `srtku` is an explicit slow fallback with a short timeout; timeout should appear in `providers.errors`, not as a backend failure.
- `srt/ass/ssa/vtt` are web-previewable. `sub/sup` are not browser `<track>` subtitles.
- Web player preview uses `web_player.url`, usually `/stream?subtitle_id=...&format=vtt`.
- Large subtitles should not return 413 by default.

## Vault And Favorites

- Favorites and the vault are the same protected collection for the current design.
- Default single-user mode temporarily treats the request as admin, but vault access still requires a six-digit vault PIN after setup.
- `GET /libraries` must not show the virtual favorites library. Frontend should use a fixed vault entry plus vault status.
- Dedicated vault/favorites endpoints:
  - `GET /user/vault/status`
  - `POST /user/vault/password`
  - `POST /user/vault/unlock`
  - `POST /user/vault/lock`
  - `GET/POST/DELETE /user/favorites`
  - `GET /libraries/favorites/movies`
- Do not read or dump favorites rows directly unless the user asks for vault maintenance.

## Verification Checklist

- `scripts/audit_dirty_media.py --db cyber_library.db` reports expected leftovers only.
- `GET /other-videos?page=1&page_size=500` contains only intentional manual/other videos.
- `GET /metadata/episode-review-items?page=1&page_size=100` did not gain new issues.
- For each touched item, `GET /movies/{id}/resources` has expected `total_items`, `season_count`, and `episode_diagnostics`.
- For movie sync or library scan, `GET /scan` should finish and `recent_errors` should not contain unexpected failures.
- For subtitles, search should return candidate items; bind/upload should update `playback.subtitles.items`.
- For docs, `GET /openapi.json` and `GET /openapi/modules` should remain valid JSON.
- `backend_server.log` has no new `ERROR`, `Traceback`, or HTTP 500 from the maintenance actions.
