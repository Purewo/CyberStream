import json
from copy import deepcopy
from pathlib import Path

from flask import Blueprint, Response, current_app, url_for

from backend import config
from backend.app.utils.response import api_error, api_response


docs_bp = Blueprint("api_docs", __name__, url_prefix="/api/v1")


OPENAPI_MODULES = {
    "docs": {
        "title": "Documentation",
        "description": "文档索引、完整 OpenAPI、模块化 OpenAPI 入口。",
    },
    "auth-users": {
        "title": "Auth & Users",
        "description": "登录态、用户资料、管理员用户管理和审计日志。",
    },
    "catalog": {
        "title": "Catalog",
        "description": "首页、筛选、推荐、影片列表、详情、资源列表和其他视频。",
    },
    "libraries": {
        "title": "Libraries",
        "description": "逻辑资源库、资源库绑定、按库浏览和按库扫描。",
    },
    "metadata": {
        "title": "Metadata",
        "description": "元数据搜索、匹配、刷新、重刮削、质量审查和剧集诊断。",
    },
    "playback": {
        "title": "Playback & Subtitles",
        "description": "播放直链、外部播放器、音频转码和字幕相关接口。",
    },
    "assets": {
        "title": "Images & Assets",
        "description": "海报、背景图、图片缓存、预热和刷新。",
    },
    "storage-system": {
        "title": "Storage & System",
        "description": "存储源、扫描、系统级能力和旧全库扫描入口。",
    },
    "governance": {
        "title": "Resource Governance",
        "description": "资源治理、可用性检查、恢复计划和治理任务。",
    },
    "jobs": {
        "title": "Jobs",
        "description": "后台任务查询和清理。",
    },
}


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
    "frontend-managed-guangyapan": {
        "title": "Frontend Managed GuangYaPan Integration",
        "path": "docs/FRONTEND_MANAGED_GUANGYAPAN_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-managed-tianyicloud": {
        "title": "Frontend Managed TianYiCloud Integration",
        "path": "docs/FRONTEND_MANAGED_TIANYICLOUD_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-managed-115cloud": {
        "title": "Frontend Managed 115 Cloud Integration",
        "path": "docs/FRONTEND_MANAGED_115CLOUD_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-managed-aliyundrive": {
        "title": "Frontend Managed Aliyundrive Integration",
        "path": "docs/FRONTEND_MANAGED_ALIYUNDRIVE_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-managed-baidunetdisk": {
        "title": "Frontend Managed Baidu Netdisk Integration",
        "path": "docs/FRONTEND_MANAGED_BAIDUNETDISK_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-managed-123pan": {
        "title": "Frontend Managed 123Pan Integration",
        "path": "docs/FRONTEND_MANAGED_123PAN_INTEGRATION.md",
        "format": "markdown",
        "content_type": "text/markdown; charset=utf-8",
    },
    "frontend-managed-quark-uc": {
        "title": "Frontend Managed QuarkTV / UCTV Integration",
        "path": "docs/FRONTEND_MANAGED_QUARK_UC_INTEGRATION.md",
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


def _load_openapi_contract():
    path = _openapi_path()
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def _classify_openapi_path(path):
    if path == "/" or path == "/api/v1/openapi.json" or path.startswith("/api/v1/docs") or path.startswith("/api/v1/openapi/modules"):
        return "docs"
    if path.startswith("/api/v1/auth") or path.startswith("/api/v1/user") or path.startswith("/api/v1/admin"):
        return "auth-users"
    if path.startswith("/api/v1/libraries"):
        return "libraries"
    if path.startswith("/api/v1/resources/governance"):
        return "governance"
    if path.startswith("/api/v1/jobs"):
        return "jobs"
    if path.startswith("/api/v1/storage") or path.startswith("/api/v1/system") or path == "/api/v1/scan":
        return "storage-system"
    if (
        path.startswith("/api/v1/metadata")
        or path == "/api/v1/reviews/resources"
        or "/metadata" in path
        or path.endswith("/episode-diagnostics")
    ):
        return "metadata"
    if path.startswith("/api/v1/images") or "/images/" in path:
        return "assets"
    if path.startswith("/api/v1/resources/"):
        return "playback"
    return "catalog"


def _component_refs(value):
    refs = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/"):
            parts = ref.split("/")
            if len(parts) >= 4:
                refs.add((parts[2], parts[3]))
        for item in value.values():
            refs.update(_component_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_component_refs(item))
    return refs


def _build_pruned_components(openapi, paths):
    components = openapi.get("components") or {}
    selected = {
        "securitySchemes": deepcopy(components.get("securitySchemes") or {}),
    }

    pending = set(_component_refs(paths))
    seen = set()
    while pending:
        section, name = pending.pop()
        if (section, name) in seen:
            continue
        seen.add((section, name))
        source = components.get(section) or {}
        value = source.get(name)
        if value is None:
            continue
        selected.setdefault(section, {})[name] = deepcopy(value)
        pending.update(_component_refs(value) - seen)

    return {section: values for section, values in selected.items() if values}


def _build_openapi_module_contract(openapi, module_key):
    selected_paths = {
        path: deepcopy(path_item)
        for path, path_item in (openapi.get("paths") or {}).items()
        if _classify_openapi_path(path) == module_key
    }
    if not selected_paths:
        return None

    module = OPENAPI_MODULES[module_key]
    info = deepcopy(openapi.get("info") or {})
    info["title"] = f"{info.get('title') or 'CyberStream API'} - {module['title']}"
    info["description"] = module["description"]

    contract = {
        "openapi": openapi.get("openapi", "3.0.0"),
        "info": info,
        "paths": selected_paths,
        "components": _build_pruned_components(openapi, selected_paths),
    }
    if openapi.get("servers"):
        contract["servers"] = deepcopy(openapi["servers"])
    if openapi.get("security"):
        contract["security"] = deepcopy(openapi["security"])
    return contract


def _module_meta(openapi, module_key):
    module = OPENAPI_MODULES[module_key]
    path_count = sum(
        1
        for path in (openapi.get("paths") or {})
        if _classify_openapi_path(path) == module_key
    )
    return {
        "key": module_key,
        "title": module["title"],
        "description": module["description"],
        "url": url_for("api_docs.get_openapi_module_json", module_key=module_key),
        "content_type": "application/json",
        "path_count": path_count,
        "available": path_count > 0,
    }


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
            "modules_url": url_for("api_docs.list_openapi_modules"),
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


@docs_bp.route("/openapi/modules", methods=["GET"])
def list_openapi_modules():
    openapi = _load_openapi_contract()
    if not openapi:
        return api_error(code=40440, msg="Documentation file not found", http_status=404)
    return api_response(data={
        "version": current_app.config.get("APP_VERSION", "unknown"),
        "openapi_version": _openapi_version(),
        "full_url": url_for("api_docs.get_openapi_json"),
        "modules": [_module_meta(openapi, key) for key in OPENAPI_MODULES],
    })


@docs_bp.route("/openapi/modules/<module_key>.json", methods=["GET"])
def get_openapi_module_json(module_key):
    if module_key not in OPENAPI_MODULES:
        return api_error(code=40442, msg="OpenAPI module not found", http_status=404)
    openapi = _load_openapi_contract()
    if not openapi:
        return api_error(code=40440, msg="Documentation file not found", http_status=404)
    module_contract = _build_openapi_module_contract(openapi, module_key)
    if not module_contract:
        return api_error(code=40442, msg="OpenAPI module not found", http_status=404)
    return Response(
        json.dumps(module_contract, ensure_ascii=False, separators=(",", ":")),
        content_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )


@docs_bp.route("/docs/<doc_key>", methods=["GET"])
def get_documentation_file(doc_key):
    entry = DOCUMENTS.get(doc_key)
    if not entry:
        return api_error(code=40441, msg="Documentation key not found", http_status=404)
    return _send_static_contract_file(
        _document_path(entry),
        entry["content_type"],
    )
