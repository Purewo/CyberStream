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
