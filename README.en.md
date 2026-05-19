<div align="center">

# CyberStream

**A cyberpunk-themed media center built for hardcore self-hosters**

Storage-agnostic · traceable metadata · real tech specs · first-class native player handoff

[中文](README.md) · [Architecture](docs/ARCHITECTURE.md) · [API Overview](docs/API_OVERVIEW.md) · [Runbook](docs/RUNBOOK.md) · [Test Checklist](docs/TEST_CHECKLIST.md)

</div>

---

## What this is

CyberStream is a self-hosted media library system: your storage, your metadata, your playback chain — all under your own control.

It is **not** another Plex / Emby / Jellyfin replacement. It does not aim to make things effortless. It aims to push the ceiling.

- Your library spans **local / WebDAV / SMB / FTP / AList / OpenList**? As long as the backend can reach it, the frontend can scan, manage and play it.
- You care whether a file is **UHD Blu-ray Remux + Dolby TrueHD 7.1 Atmos** or 1080p AAC 2.0? Tech specs are parsed, persisted and displayed field by field — not just a label glued onto a filename.
- You want **PotPlayer / IINA / VLC / nPlayer / Infuse / MX Player** to do the decoding, instead of getting humbled by browser H.265 limits? External player handoff is a first-class citizen here.
- You care about **where your metadata came from** — what TMDB / Bangumi / NFO / local-fallback contributed, why this candidate ranked first, and which fields you can lock so a future scan won't overwrite them? The review workbench and per-field locks have you covered.

If you're a "good enough" user, this system will feel over-engineered. If you treat your media library as a project to be engineered — welcome.

---

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/01-home.png" alt="Home · responsive backdrop and horizontal carousels" /></td>
    <td width="50%"><img src="docs/screenshots/02-movie-detail.png" alt="Movie detail · real tech-spec badges + seven external players" /></td>
  </tr>
  <tr>
    <td align="center"><sub>Home · backdrop follows the focused title, multi-section horizontal carousels in one viewport</sub></td>
    <td align="center"><sub>Movie detail · REMUX / 4K / HDR10 / Dolby Atmos badges + 7 one-click external player handoffs</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/03-governance.png" alt="Governance · episode review workbench" /></td>
    <td width="50%"><img src="docs/screenshots/04-subtitle-manager.png" alt="Subtitle manager · same-folder + online subtitles in one place" /></td>
  </tr>
  <tr>
    <td align="center"><sub>Governance · missing episodes / duplicate numbers / count drift diagnosed at a glance</sub></td>
    <td align="center"><sub>Subtitle manager · current subs + SubHD / Zimuku online search, candidates ranked srt &gt; unknown &gt; sup</sub></td>
  </tr>
</table>

---

## Core capabilities

### Storage & scanning

- Six storage protocols: `local` / `webdav` / `smb` / `ftp` / `alist` / `openlist`
- Storage capability matrix (`/api/v1/storage/capabilities`): the frontend dynamically queries which provider supports scan / preview / playback / Range / 302 redirects / health checks
- Directory preview & saved-source browsing: inspect the real directory tree before picking a root, no blind config
- Three scan entrypoints (full-library / single-source / single-library) sharing a unified scan lock — concurrent triggers return `429`
- Resource governance: orphan resources, empty-shell movies, duplicate copies, broken paths — each detected independently. The live-check job probes parent directories at scale without touching the DB. Cleanup always emits a dry-run first; deleted items keep a `restore_snapshot` for reversal.

### Metadata scraping

- Provider abstraction over `nfo` / `tmdb` / `bangumi` / `local`, ordered by `provider_order`
  - Anime libraries can explicitly configure `["nfo", "bangumi", "tmdb", "local"]` so anime identification goes through Bangumi instead of TMDB
  - Candidates return `match_explanation` and `rank` — you see why the match was made and why it ranked first
- Three-stage scraping pipeline: `strict` (canonical naming → direct match) → `fallback` (heuristic) → `ai` (reserved hook, not yet wired)
- **Per-field locks**: any field changed by manual PATCH gets locked by default, so subsequent scans won't overwrite hand-tuned values; explicit `metadata_unlocked_fields` opens specific fields back up
- **Two-step manual match**: `POST /v1/movies/{id}/metadata/match` is dry-run by default and returns a diff; the user reviews it in the UI, then re-submits with `apply: true` to actually write. Missing-poster cases return HTTP 409 to force a second confirmation.
- Metadata review workbench: failure classification, candidate explanations, batch re-scrape feedback, episode diagnostics (missing episodes, duplicate episode numbers, count drift between resources and season metadata) — all in one place
- Per-movie contextual recommendations: detail page falls back through same-collection → same-title-family → same-genre → same-section, and forces strict separation between anime and non-anime

### Playback experience

- **Web playback is not the whole story**: the HTML5 player is one entrypoint, not the only one
- **External player handoff is first-class**:
  - Resource objects inline `playback.web_player.url` / `playback.external_player.url` / `playback.stream_url` so a single request gives you everything
  - `GET /v1/resources/{id}/external-playback` returns a complete handoff manifest (absolute stream URL, default subtitle, player_profiles); `?format=m3u` returns an M3U playlist for VLC / mpv etc.
  - The detail page launches PotPlayer / IINA / VLC / nPlayer / MX Player / MX Player Pro / Infuse with one click
- **Real audio tracks & audio transcoding**: web playback uses parallel `audioRef + videoRef` to sync transcoded audio against the original video. The backend audio-transcode pipeline includes upstream Range caching, first-packet diagnostics, single-session replacement, and a history watchdog as backstop.
- **Source switching without unmount**: switching 1080p ↔ 4K REMUX does not rebuild the React tree; playback progress carries over
- **History heartbeats**: `progress / duration` reported every 10s, enabling cross-device resume
- **Same-folder subtitle discovery**: `srt / ass / ssa / vtt` files matching the video's name prefix are auto-mounted into the playback matrix; the web player gets dynamic SRT→WebVTT conversion; external players get the original format
- **Online subtitles**: integrated with `subhd` and `srtku`; candidates ranked `srt > unknown > sup` to prevent the web player from picking bitmap subs; user must `confirm: true` before any subtitle is bound and persisted

### Libraries & catalog publication

- Three-layer model: `StorageSource` (physical) / `Library` (logical) / `LibrarySource` (mount binding)
- Library content rule: `(auto-matched paths) ∪ (manual include) − (manual exclude)` — both whitelist and blacklist supported
- **Explicit catalog visibility**: each movie has `catalog_visibility_status` of `auto` / `published` / `hidden`, decoupling "is it in the public catalog" from "what scraper produced it" — your home-recorded videos, courses and crawled clips don't pollute the main catalog
- **Other-videos archive**: `/api/v1/other-videos` queues anything unfit for auto-scraping; `recommended_resolution` tells the frontend whether to route the user to "match metadata" or "create a manual movie shell"

### Security & access control

- Single-token API auth (`CYBER_API_TOKEN`): admin endpoints require `Bearer` or `X-Cyber-API-Token`; playback, images and health stay public
- **Optional user management** (off by default): admin / user roles, cookie-session login, last-admin protection, session-version invalidation on password / role / enable-state changes, login rate limiting, full audit log
- Library visibility allow / deny: once user management is enabled, every list, detail, playback, recommendation, subtitle and history endpoint enforces visibility
- Per-user subtitle styles & per-user watch history, fully isolated

### CDN & image assets

- Optional Super CDN for image caching: `cyberstream-cn-assets` bucket on the `china_all` route, serving posters / backdrops at edge speed inside China
- Image source tracking: every poster carries `source_info` exposing whether it came from TMDB / Bangumi / NFO / manual / external, whether the URL is locked, and when it was cached
- Batch warm-up / single-movie cleanup / CDN purge orchestrated through a single endpoint: `POST /v1/images/refresh`
- **Video streams stay off the CDN**: the main streaming chain keeps direct 302 / byte-range pass-through, avoiding CDN middleboxes that would choke 4K REMUX delivery

### Background jobs

- Persistent job registry (`maintenance_jobs`): jobs survive process restarts and remain queryable
- Primary async entrypoints: bulk re-scrape / governance cleanup / governance live-check / governance restore
- Jobs return `progress.{current, total, message}` and explainable `result.items`, so the frontend can render a real progress bar instead of a spinner
- **Scan progress is separate**: scan progress is polled via `GET /api/v1/scan`, never folded into `/jobs`

---

## Repository layout

```
CyberStream/
├── backend/         # Flask backend: app/ + config.py + run.py
├── frontend/        # React 19 + Vite 6 + TypeScript SPA
├── docs/            # Architecture / API / runbook / test / versioning docs
├── scripts/         # backend_service.sh, db_backup.py, ops scripts
├── tests/           # Backend integration tests
├── AGENTS.md        # Repository contributor guide
└── requirements.txt
```

The frontend lives in `frontend/` with its own `package.json` and is independently runnable via `npm run dev`. The backend contract is mirrored to the frontend through `frontend/openapi.json` and `frontend/openapi-1.21.0-beta/`.

---

## Quick start

### Backend

```bash
# At the repository root
cp .env.local.example .env.local
# Edit .env.local and fill in:
#   TMDB_TOKEN
#   CYBER_API_TOKEN
#   CYBER_BACKEND_PUBLIC_BASE_URL  (when behind a reverse proxy)
#   (optional) CYBER_USER_MANAGEMENT_ENABLED + CYBER_SESSION_SECRET + initial admin

./scripts/backend_service.sh start          # gunicorn-first, falls back to Flask built-in
./scripts/backend_service.sh status
./scripts/backend_service.sh restart
./scripts/backend_service.sh stop

# Foreground for dev
.venv/bin/python -m backend.run

# Health check
curl http://127.0.0.1:5004/
```

### Frontend

```bash
cd frontend
npm install
npm run dev          # Vite dev server on port 3000
npm run build        # tsc + Vite production build → dist/
npm run lint         # type-check only, no ESLint
```

The frontend `API_BASE` lives in `frontend/src/constants/index.ts` and points at the public backend by default. Set it to `http://127.0.0.1:5004/api` for local development against your own backend.

---

## Tech stack

| Layer | Stack |
|---|---|
| Backend framework | Python 3.10 + Flask + Flask-SQLAlchemy + SQLite |
| Backend serving | gunicorn (production) / Flask (development) |
| Metadata sources | TMDB / Bangumi / NFO / local fallback |
| Subtitles | Same-folder discovery / SubHD / Zimuku (srtku) / dynamic SRT→WebVTT |
| Frontend framework | React 19 + TypeScript + Vite 6 |
| Frontend styling | Tailwind CSS (utility-first) + theme CSS variables |
| Frontend motion | Motion (Framer Motion) |
| Frontend icons | Lucide React |
| Background jobs | In-house lightweight job registry + SQLite persistence |
| Static assets | Backend image cache + optional Super CDN |

---

## Documentation index

| Topic | Path |
|---|---|
| Project handover | [docs/PROJECT_HANDOVER.md](docs/PROJECT_HANDOVER.md) |
| Project progress | [docs/PROJECT_PROGRESS.md](docs/PROJECT_PROGRESS.md) |
| **PC client goal (v1)** | [docs/PC_CLIENT_GOAL.md](docs/PC_CLIENT_GOAL.md) |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| API overview | [docs/API_OVERVIEW.md](docs/API_OVERVIEW.md) |
| Metadata pipeline | [docs/METADATA_PIPELINE_V1.md](docs/METADATA_PIPELINE_V1.md) |
| Library design | [docs/LIBRARY_DESIGN_V1.md](docs/LIBRARY_DESIGN_V1.md) |
| Storage config flow | [docs/STORAGE_CONFIG_FLOW.md](docs/STORAGE_CONFIG_FLOW.md) |
| Audio transcode design | [docs/AUDIO_TRANSCODE_DESIGN_NOTES.md](docs/AUDIO_TRANSCODE_DESIGN_NOTES.md) |
| Frontend audio-transcode integration | [docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md](docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md) |
| Frontend review workbench integration | [docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md](docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md) |
| Frontend user management integration | [docs/FRONTEND_USER_MANAGEMENT_INTEGRATION.md](docs/FRONTEND_USER_MANAGEMENT_INTEGRATION.md) |
| Config reference | [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md) |
| Runbook | [docs/RUNBOOK.md](docs/RUNBOOK.md) |
| Test checklist | [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md) |
| Versioning | [docs/VERSIONING.md](docs/VERSIONING.md) |
| Maintenance todo | [docs/MAINTENANCE_TODO.md](docs/MAINTENANCE_TODO.md) |

Current OpenAPI baseline: `backend/openapi/openapi-1.21.0-beta/openapi-1.21.0-beta.json`

---

## Current version

`1.21.0` — single mainline; `main` always represents the latest release.

---

## Attribution requirements

**Any use, modification or redistribution of this project must explicitly credit the original author and project URL.**

Specifically:
- Author: `Purewo`
- Project: `https://github.com/Purewo/CyberStream`
- The credit must be visible in at least one of: product UI, about page, documentation, or source-code header
- You may not strip the existing copyright or attribution from the source

---

## Feedback

Issues: [https://github.com/Purewo/CyberStream/issues](https://github.com/Purewo/CyberStream/issues)
