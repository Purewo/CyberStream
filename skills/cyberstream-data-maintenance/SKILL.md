---
name: cyberstream-data-maintenance
description: Maintain CyberStream/赛博影视 backend data and operations. Use when Codex needs to audit or repair dirty media metadata, Local/fallback placeholder entries, other-videos backlogs, split seasons, duplicate resources, ad stub video files, episode numbering, TMDB/Bangumi/AniList/Tencent/manual matches, subtitle search/bind/upload behavior, library scan/refresh contracts, favorites/vault data, OpenAPI docs, or database-only catalog cleanup for the CyberStream project.
---

# CyberStream Data Maintenance

## Overview

Use this skill to safely maintain CyberStream catalog data and backend operational contracts. Default posture is read-only: audit first, then make the smallest approved database/API change.

Default project root: `/home/pureworld/赛博影视`. Default database: `cyber_library.db`. Default local API: `http://127.0.0.1:5004/api/v1`.

## Hard Rules

- Do not scrape, scan, upload to CDN, purge CDN, or delete physical media files unless explicitly requested.
- Do not modify frontend code. This project boundary is backend/data maintenance.
- Do not modify backend code for data-only cleanup unless the user asks for a code fix or an API contract is clearly broken.
- Start with read-only audit. For destructive or write operations, explain the candidate set first unless the user already approved a concrete list.
- Back up `cyber_library.db` before any write.
- Prefer backend API contracts for metadata matching, resource attachment, movie sync, subtitles, and vault operations. Use direct DB writes only for deterministic cleanup such as deleting confirmed ad stubs or filling obvious episode numbers.
- Preserve user/manual content unless the user confirms it should be converted or removed.
- Treat subtitle search as read-only; subtitle download, bind, upload, delete, and default selection are write/mutation paths.
- Treat metadata match as preview-first unless the user explicitly approves applying. `POST /movies/{id}/metadata/match` is dry-run by default; writes require `apply=true`.
- Favorites are the protected vault collection. Do not expose or bypass vault data by raw DB reads unless the user explicitly asks for maintenance/audit.

## Workflow

1. Locate the project and service:
   - Verify `cyber_library.db`, `.env.local`, `backend_server.pid`, and `backend_server.log`.
   - Prefer local API `http://127.0.0.1:5004/api/v1` when the backend is running.
   - Use live docs before guessing contracts: `/api/v1/docs`, `/api/v1/openapi.json`, `/api/v1/openapi/modules`, and `/api/v1/openapi/modules/<module>.json`.
2. Audit without writes:
   - Run `scripts/audit_dirty_media.py --db /home/pureworld/赛博影视/cyber_library.db`.
   - Check `/api/v1/other-videos?page=1&page_size=500`.
   - Check `/api/v1/metadata/episode-review-items?page=1&page_size=100`.
   - Check `/api/v1/scan` before triggering or diagnosing scan work.
3. Classify each candidate:
   - **Match in place**: Local/fallback item is a real movie/series and should become a normal TMDB or provider-backed entry.
   - **Attach to existing**: Real resource belongs to an already-correct movie/TV entry.
   - **Episode repair**: TV resources are already under the right title but lack season/episode numbers.
   - **Ad stub**: tiny promotional files from download sites. Remove DB records, not physical files.
   - **Manual/other**: personal videos, courses, talks, or uncatalogued clips. Leave in other-videos unless instructed.
   - **Updated title**: Existing movie/series gained files. Prefer the single-movie sync API over whole-library scans when the user wants one title refreshed.
4. Execute carefully:
   - For metadata match:
     ```bash
     curl -sS -X POST "$API/movies/<movie_id>/metadata/match" \
       -H 'Content-Type: application/json' \
       -d '{"candidate_id":"movie/123","provider":"tmdb","media_type_hint":"movie","apply":true}'
     ```
   - For attaching resources:
     ```bash
     curl -sS -X POST "$API/movies/<target_movie_id>/resources/attach" \
       -H 'Content-Type: application/json' \
       -d '{"media_type":"movie","resource_ids":["<resource_id>"]}'
     ```
     Use `"media_type":"tv","preserve_episode_metadata":true` for TV resources that already have correct season/episode fields.
   - For refreshing one existing title after new episodes arrive:
     ```bash
     curl -sS -X POST "$API/movies/<movie_id>/resources/sync" \
       -H 'Content-Type: application/json' \
       -d '{"refresh":true}'
     ```
   - For DB-only operations, use `scripts/db_maintenance.py`; every write subcommand requires `--yes`.
5. Verify:
   - `other-videos` should shrink to only true manual/other items.
   - Local/fallback/no-poster report should contain only intentional manual leftovers.
   - Ad-pattern report should be empty unless the user chooses to keep those items.
   - Episode review should not gain new duplicate or missing-episode issues.
   - For subtitles, verify search first; only bind with `confirm=true` after the user chooses a candidate.
   - Tail `backend_server.log` for `ERROR`, `Traceback`, and `500`.

## References

- Read `references/cyberstream-maintenance.md` for schema notes, current backend API contracts, scan/refresh behavior, subtitle limits, vault/favorites semantics, known ad patterns, and cleanup recipes.
- Use `scripts/audit_dirty_media.py` for read-only DB reports.
- Use `scripts/db_maintenance.py` for backups, confirmed ad-resource deletion, and deterministic TV episode normalization.
