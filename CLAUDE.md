# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CyberStream is a personal media library system (movies, TV, anime) with three applications in one repo:

- **backend/** — Python Flask API server (SQLite, gunicorn)
- **frontend/** — React 19 + Vite 6 + TypeScript SPA (see `frontend/CLAUDE.md` for detailed frontend guidance)
- **pc/** — Tauri 2 desktop client (Rust + WebView2 + embedded libmpv)

The backend runs on a NAS/home server. The frontend is a pure SPA that talks to it via REST. The PC client wraps the same React frontend and adds native video playback.

## Commands

### Backend

```bash
# Install dependencies (use a virtualenv)
pip install -r requirements.txt

# Start dev server (port 5004)
python -m backend.run

# Health check
curl http://127.0.0.1:5004/

# Run tests
pytest tests/
```

### Frontend

```bash
cd frontend
npm install
npm run dev       # Vite dev server on port 3000
npm run build     # tsc + vite build → frontend/dist/
npm run lint      # tsc --noEmit (type errors are the only lint signal)
```

### PC Client

```bash
# Requires: Windows 11, Rust 1.77+, Node 22+, cargo-tauri ^2.0
# Plus libmpv binaries in pc/vendor/mpv/ (gitignored, fetched manually)
cd pc/src-tauri
cargo tauri dev     # Dev mode (uses Vite on port 3000)
cargo tauri build   # Produces MSI installer
```

## Architecture

### Backend (`backend/`)

Flask monolith with blueprint-based routing. Key layout:

- `app/api/` — Route blueprints (library, storage, player, auth, history, homepage, docs, system)
- `app/services/` — Business logic (scanner, metadata scraper, subtitles, playback, resource governance, audio transcode, jobs, CDN)
- `app/providers/` — Storage provider abstraction (local, webdav, smb, ftp, alist) with factory pattern
- `app/services/metadata_providers/` — Provider implementations (TMDB, AniList, Bangumi, Tencent Video, NFO, local fallback)
- `app/models.py` — All SQLAlchemy models (single large file)
- `config.py` — Single source of truth for version, env var loading (`_env()`, `_env_bool()`, `_env_int()`), and runtime defaults

Storage is SQLite (`cyber_library.db`). Environment config goes in `.env.local` (see `.env.local.example`).

### Frontend (`frontend/`)

See `frontend/CLAUDE.md` for complete frontend architecture. Key points:

- No react-router — hand-rolled navigation via `useAppRouting` hook
- `src/api/core.ts` is the seam between backend DTOs and UI types
- `src/components/Player.tsx` is the largest and most complex component
- Window event bus for cross-component communication
- No ESLint/Prettier — type errors are the lint signal

### PC Client (`pc/`)

Tauri 2 shell. The Rust side adds:

- `src/native_player/` — libmpv integration with egui OpenGL HUD, subtitle support, history heartbeat
- `src/external_player.rs` — PotPlayer/VLC native .exe spawning with subtitle pre-load
- Windows 11 only target; `pc/vendor/` (gitignored) holds libmpv runtime binaries

## Conventions

- **Language:** UI strings, toasts, and user-facing text are Chinese (Simplified). Code identifiers stay English.
- **Backend style:** 4-space indent, `snake_case` functions/variables, `UPPER_SNAKE_CASE` module constants. Extend existing modules before adding new top-level packages.
- **Frontend style:** Tailwind utility classes inline, CSS variable themes (`CYBER`, `ARASAKA`, `GOLDEN`). No CSS-in-JS. Optional chaining on all movie metadata fields — scraped data is unreliable.
- **Config:** Never hardcode secrets. All deployment-specific values go through env vars in `backend/config.py`. If you change `APP_VERSION`, also update references per `docs/VERSIONING.md`.
- **Testing:** Backend validation is integration-based — local startup + health check + curl smoke tests from `docs/TEST_CHECKLIST.md`. Frontend has no test runner.

## Key Integration Points

- **API contract:** OpenAPI specs live in `backend/openapi/`. The frontend typed API layer is in `frontend/src/api/` with UI types in `frontend/src/types/index.ts`.
- **Asset URLs:** Backend-relative URLs must go through `resolveAssetUrl()` on the frontend (in `src/api/core.ts`). Never concatenate `API_BASE` manually.
- **Auth model:** Single-token mode (`CYBER_API_TOKEN`) or multi-user sessions (`CYBER_USER_MANAGEMENT_ENABLED`). The token is a break-glass admin bypass in multi-user mode.
- **Storage providers:** Factory pattern in `backend/app/providers/`. Supports local filesystem, WebDAV, SMB, FTP, AList, and OpenList.
- **CDN layer:** Optional Super CDN for poster/image assets (configured via `CYBER_SUPERCDN_*` env vars). Video streaming always uses the storage provider directly.
