# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the Flask application. Core app setup lives in `backend/app/__init__.py`; API blueprints are under `backend/app/api/`; database and models are in `backend/app/db/`, `backend/app/extensions.py`, and `backend/app/models.py`; storage providers live in `backend/app/providers/`; scanning and TMDB integrations are in `backend/app/services/`. Runtime configuration is centralized in `backend/config.py`, and OpenAPI snapshots live in `backend/openapi/`. Operational and handover documentation is kept in `docs/`.

## Build, Test, and Development Commands
Create or reuse `.venv`, then install dependencies with `.venv/bin/python -m pip install -r requirements.txt`. Start the service with `./scripts/backend_service.sh start`; use `.venv/bin/python -m backend.run` for foreground development. Run `.venv/bin/python -m pytest -q` for the full backend suite and target individual files while iterating. Use `curl http://127.0.0.1:5004/` for a health check and `ss -ltnp | grep ':5004 '` to verify the listener. Follow the API smoke commands in `docs/TEST_CHECKLIST.md` when a change touches storage, scanning, playback, or deployment behavior.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, module-level constants in `UPPER_SNAKE_CASE`, functions and variables in `snake_case`, and concise route/helper names such as `storage_routes.py` or `library_helpers.py`. Keep comments brief and only where behavior is not obvious. Prefer extending existing modules before adding new top-level packages. Treat `backend/config.py` as the single source of truth for version and runtime defaults.

## Testing Guidelines
The backend has a broad pytest suite under `tests/`. Add focused regression coverage in `tests/test_<feature>.py`, run the directly affected tests while developing, and run `.venv/bin/python -m pytest -q` before handing off a backend change. Tests are necessary but not sufficient for storage, scanning, playback, and proxy behavior: also run the relevant startup and `curl` checks from `docs/TEST_CHECKLIST.md`. External-provider tests should mock network calls unless the test is explicitly an opt-in integration check.

## Commit & Pull Request Guidelines
Use short, imperative commit subjects consistent with the existing history, such as `fix storage preview error` or `docs: update runbook`. Pull requests should summarize behavior changes, list automated and manual verification, note config or schema impacts, and include API examples or screenshots when response payloads or UI integrations change.

## Security & Configuration Tips
Do not hardcode new secrets in code or docs. Prefer environment variables for deployment-specific values such as `TMDB_TOKEN`, storage credentials, and path overrides. If you change `APP_VERSION`, also update the related references called out in `docs/VERSIONING.md`.

## Project Runtime Memory
Keep CyberStream-specific operational facts in this repository, not in global agent memory, unless explicitly requested. Treat this file plus `docs/PROJECT_HANDOVER.md`, `docs/RUNBOOK.md`, and `docs/TEST_CHECKLIST.md` as the project-scoped memory entry points.

Current host notes:
- Use explicit proxy `127.0.0.1:7890` for GitHub/overseas access.
- Public backend HTTPS is `https://cyberstream.gameuniverse.top:40160/`.
- nginx terminates TLS on port `40160` and proxies to `127.0.0.1:5004`.
- IPv4 NAT public ports are limited to `40160-40169`; keep backend HTTPS on `40160` unless the user reallocates ports.
- Runtime services expected online for integration work: `cyberstream-backend`, `nginx`, `cyberstream-alist`, `cyberstream-openlist`, and `ddns-go`.
- AList is local-only at `127.0.0.1:5244`; OpenList is local-only at `127.0.0.1:5245`.
- Current app version is `1.21.0`; current OpenAPI version is `1.21.0-beta`; run smoke checks with `--expected-version 1.21.0 --expected-openapi-version 1.21.0-beta`.
- Full pytest baseline as of 2026-06-07 is `763 passed, 9 skipped, 16 subtests passed`.

Before scraping or frontend integration, run:

```bash
./scripts/backend_smoke_check.py --systemd --base-url http://127.0.0.1:5004 \
  --openapi-module-json-check \
  --expected-version 1.21.0 \
  --expected-openapi-version 1.21.0-beta \
  --min-storage-sources 1 \
  --storage-health-check \
  --min-storage-health-checks 1 \
  --tmdb-token-check
```

Do not print secrets from `/etc/cyberstream/`, `/var/lib/ddns-go/`, `/etc/mihomo/`, `/etc/nginx/`, or `.env.local`. Frontend work is owned separately; avoid touching `frontend/` unless the user explicitly redirects.

Fallback review status as of 2026-06-07: 30 manually checked `fallback_pipeline_match` items were published through `/api/v1/metadata/pending-review/publish`; 37 remain pending because they are local placeholders, missing posters, low confidence, episode/season diagnostics, or visible mismatches such as same-title wrong-year TMDB matches. Do not bulk-publish the remaining fallback queue without re-scrape/manual matching first.
