# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the Flask application. Core app setup lives in `backend/app/__init__.py`; API blueprints are under `backend/app/api/`; database and models are in `backend/app/db/`, `backend/app/extensions.py`, and `backend/app/models.py`; storage providers live in `backend/app/providers/`; scanning and TMDB integrations are in `backend/app/services/`. Runtime configuration is centralized in `backend/config.py`, and OpenAPI snapshots live in `backend/openapi/`. Operational and handover documentation is kept in `docs/`.

## Build, Test, and Development Commands
Create or reuse the local virtualenv, then install dependencies with `pip install -r requirements.txt`. Start the service with `python -m backend.run` from the repository root; `python backend/run.py` remains supported for compatibility. Use `curl http://127.0.0.1:5004/` for a health check and `ss -ltnp | grep ':5004 '` to verify the listener. For regression checks, follow the API smoke commands in `docs/TEST_CHECKLIST.md`.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, module-level constants in `UPPER_SNAKE_CASE`, functions and variables in `snake_case`, and concise route/helper names such as `storage_routes.py` or `library_helpers.py`. Keep comments brief and only where behavior is not obvious. Prefer extending existing modules before adding new top-level packages. Treat `backend/config.py` as the single source of truth for version and runtime defaults.

## Testing Guidelines
This snapshot does not include an automated test suite, so validation is primarily integration-based. After backend changes, run the local startup check, `/` health check, and the relevant `curl` cases from `docs/TEST_CHECKLIST.md` for scan, storage, listing, and streaming flows. When adding tests later, place them under a dedicated `tests/` package and name files `test_<feature>.py`.

## Commit & Pull Request Guidelines
Git history is not present in this workspace snapshot, so no repository-specific commit convention can be verified. Use short, imperative commit subjects such as `fix storage preview error` or `docs update runbook`. Pull requests should summarize behavior changes, list manual verification steps, note config or schema impacts, and include API examples or screenshots when response payloads or UI integrations change.

## Security & Configuration Tips
Do not hardcode new secrets in code or docs. Prefer environment variables for deployment-specific values such as `TMDB_TOKEN`, storage credentials, and path overrides. If you change `APP_VERSION`, also update the related references called out in `docs/VERSIONING.md`.
