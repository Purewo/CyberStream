from pathlib import Path

from flask import Blueprint, Response, current_app, url_for

from backend import config
from backend.app.utils.response import api_error, api_response


docs_bp = Blueprint("api_docs", __name__, url_prefix="/api/v1")


DOCUMENTS = {
    "release-notes": {
        "title": "OpenAPI Release Notes",
        "path": "release-notes",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "api-overview": {
        "title": "API Overview",
        "path": "docs/API_OVERVIEW.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-review-workbench": {
        "title": "Frontend Review Workbench Integration",
        "path": "docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-user-management": {
        "title": "Frontend User Management Integration",
        "path": "docs/FRONTEND_USER_MANAGEMENT_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-audio-transcode": {
        "title": "Frontend Audio Transcode Guide",
        "path": "docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "storage-config-flow": {
        "title": "Storage Config Flow",
        "path": "docs/STORAGE_CONFIG_FLOW.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "runbook": {
        "title": "Runbook",
        "path": "docs/RUNBOOK.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "test-checklist": {
        "title": "Test Checklist",
        "path": "docs/TEST_CHECKLIST.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
}


def _project_root():
    return Path(config.BASE_DIR).resolve()


def _openapi_version():
    explicit_version = str(current_app.config.get("OPENAPI_VERSION") or "").strip()
    if explicit_version:
        return explicit_version
    app_version = str(current_app.config.get("APP_VERSION") or config.APP_VERSION or "").strip()
    return f"{app_version}-beta" if app_version else "1.21.0-beta"


def _openapi_dir():
    return _project_root() / "backend" / "openapi" / f"openapi-{_openapi_version()}"


def _openapi_path():
    version = _openapi_version()
    primary = _openapi_dir() / f"openapi-{version}.json"
    if primary.is_file():
        return primary
    legacy = _openapi_dir() / "openapi.json"
    return legacy


def _release_notes_path():
    version = _openapi_version()
    return _openapi_dir() / f"release-notes-{version}.md"


def _document_path(entry):
    if entry["path"] == "release-notes":
        return _release_notes_path()
    return _project_root() / entry["path"]


def _send_static_contract_file(path, content_type):
    if not path.is_file():
        return api_error(code=40440, msg="Documentation file not found", http_status=404)
    return Response(
        path.read_bytes(),
        content_type=content_type,
        headers={"Cache-Control": "public, max-age=60"},
    )


@docs_bp.route("/docs", methods=["GET"])
def list_api_documentation():
    documents = []
    for key, entry in DOCUMENTS.items():
        path = _document_path(entry)
        documents.append({
            "key": key,
            "title": entry["title"],
            "format": entry["format"],
            "content_type": entry["content_type"],
            "url": url_for("api_docs.get_documentation_file", doc_key=key),
            "available": path.is_file(),
        })

    return api_response(data={
        "version": current_app.config.get("APP_VERSION", "unknown"),
        "openapi_version": _openapi_version(),
        "openapi": {
            "url": url_for("api_docs.get_openapi_json"),
            "docs_url": url_for("api_docs.get_docs_openapi_json"),
            "content_type": "application/json",
            "available": _openapi_path().is_file(),
        },
        "documents": documents,
    })


@docs_bp.route("/openapi.json", methods=["GET"])
def get_openapi_json():
    return _send_static_contract_file(
        _openapi_path(),
        "application/json",
    )


@docs_bp.route("/docs/openapi.json", methods=["GET"])
def get_docs_openapi_json():
    return get_openapi_json()


@docs_bp.route("/docs/<doc_key>", methods=["GET"])
def get_documentation_file(doc_key):
    entry = DOCUMENTS.get(doc_key)
    if not entry:
        return api_error(code=40441, msg="Documentation key not found", http_status=404)
    return _send_static_contract_file(
        _document_path(entry),
        entry["content_type"],
    )
