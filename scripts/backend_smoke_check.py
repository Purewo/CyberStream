#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = os.environ.get("CYBER_BACKEND_SMOKE_BASE_URL", "http://127.0.0.1:5004")
DEFAULT_API_TOKEN = os.environ.get("CYBER_BACKEND_SMOKE_API_TOKEN") or os.environ.get("CYBER_API_TOKEN") or ""
DEFAULT_SYSTEMD_SERVICES = [
    "cyberstream-backend",
    "nginx",
    "cyberstream-alist",
    "cyberstream-openlist",
    "ddns-go",
]
EXPECTED_METADATA_PROVIDERS = ["nfo", "tmdb", "anilist", "bangumi", "tencent_video", "local"]
EXPECTED_METADATA_DEFAULT_ORDER = ["nfo", "tmdb", "local"]
EXPECTED_METADATA_SEARCH_PROVIDERS = ["tmdb", "anilist", "bangumi", "tencent_video"]
EXPECTED_METADATA_REVIEW_BUCKETS = [
    "metadata_review",
    "manual_content",
    "episode_review",
    "resource_governance",
    "catalog_visibility",
]
EXPECTED_METADATA_REVIEW_ACTIONS = [
    "batch_reidentify_plan",
    "match_metadata",
    "edit_episode_metadata",
    "resource_governance_plan",
    "resource_live_check",
    "manual_review",
    "create_manual_content",
    "catalog_publish",
]
EXPECTED_METADATA_QUALITY_ACTIONS = ["bulk_reidentify", "episode_review_queue"]
EXPECTED_METADATA_QUALITY_TOTALS = [
    "movie_count",
    "issue_movie_count",
    "bulk_reidentify_movie_count",
    "episode_review_movie_count",
]
EXPECTED_JOB_STATUSES = ["queued", "running", "succeeded", "failed"]
EXPECTED_OPENAPI_MODULES = [
    "docs",
    "auth-users",
    "catalog",
    "libraries",
    "metadata",
    "playback",
    "assets",
    "aggregator",
    "storage-system",
    "governance",
    "jobs",
]
EXPECTED_DOC_KEYS = [
    "release-notes",
    "api-overview",
    "terminology",
    "frontend-review-workbench",
    "frontend-user-management",
    "frontend-audio-transcode",
    "frontend-managed-guangyapan",
    "frontend-managed-tianyicloud",
    "experimental-tianyicloud-pc-qr",
    "frontend-managed-115cloud",
    "frontend-managed-aliyundrive",
    "frontend-managed-baidunetdisk",
    "frontend-managed-123pan",
    "frontend-managed-quark-uc",
    "storage-config-flow",
    "runbook",
    "test-checklist",
]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


@dataclass
class CheckSpec:
    name: str
    run: Callable[[], CheckResult]


class SmokeClient:
    def __init__(self, base_url: str, timeout: float = 30.0, api_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_token = (api_token or "").strip()

    def get_json(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {url}: {body[:300]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GET {url} failed: {exc}") from exc


def _response_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _response_list(payload: dict[str, Any]) -> list[Any]:
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _pagination_total(data: dict[str, Any]) -> int:
    pagination = data.get("pagination") if isinstance(data, dict) else None
    if isinstance(pagination, dict):
        return int(pagination.get("total_items") or 0)
    return 0


def _result(name: str, ok: bool, detail: str, data: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail, data=data)


def check_health(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/health")
    data = _response_data(payload)
    status = data.get("status")
    version = data.get("version")
    database = data.get("database") if isinstance(data.get("database"), dict) else {}
    database_status = database.get("status")
    ok = status == "up" and database_status == "ok"
    return _result(
        "health",
        ok,
        f"status={status} version={version} database={database_status}",
        {"status": status, "version": version, "database": database},
    )


def check_openapi_health_contract(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/openapi.json")
    paths = payload.get("paths") if isinstance(payload, dict) else {}
    operation = ((paths or {}).get("/api/v1/health") or {}).get("get") or {}
    operation_id = operation.get("operationId")
    ok = operation_id == "apiHealthCheck" and operation.get("security") == []
    return _result(
        "openapi_health_contract",
        ok,
        f"operationId={operation_id} public={operation.get('security') == []}",
        {"operation_id": operation_id, "security": operation.get("security")},
    )


def check_docs_index(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/docs")
    data = _response_data(payload)
    openapi = data.get("openapi") if isinstance(data, dict) else {}
    if not isinstance(openapi, dict):
        openapi = {}
    documents = data.get("documents") if isinstance(data, dict) else []
    doc_map = {
        item.get("key"): item
        for item in documents
        if isinstance(item, dict) and item.get("key")
    }

    missing = [key for key in EXPECTED_DOC_KEYS if key not in doc_map]
    unavailable = [
        key for key, item in doc_map.items()
        if key in EXPECTED_DOC_KEYS and item.get("available") is not True
    ]
    bad_urls = [
        key for key, item in doc_map.items()
        if key in EXPECTED_DOC_KEYS and _module_url_path(item.get("url")) != f"/api/v1/docs/{key}"
    ]
    non_markdown = [
        key for key, item in doc_map.items()
        if key in EXPECTED_DOC_KEYS and not str(item.get("content_type") or "").startswith("text/markdown")
    ]

    openapi_ok = (
        openapi.get("available") is True
        and _module_url_path(openapi.get("url")) == "/api/v1/openapi.json"
        and _module_url_path(openapi.get("docs_url")) == "/api/v1/docs/openapi.json"
        and _module_url_path(openapi.get("modules_url")) == "/api/v1/openapi/modules"
    )

    issues = []
    if not openapi_ok:
        issues.append("openapi_links_invalid")
    if missing:
        issues.append(f"missing={','.join(missing)}")
    if unavailable:
        issues.append(f"unavailable={','.join(unavailable)}")
    if bad_urls:
        issues.append(f"bad_urls={','.join(bad_urls)}")
    if non_markdown:
        issues.append(f"non_markdown={','.join(non_markdown)}")

    ok = not issues
    detail = f"documents={len(doc_map)} expected={len(EXPECTED_DOC_KEYS)} version={data.get('openapi_version')}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "docs_index",
        ok,
        detail,
        {
            "documents": sorted(doc_map),
            "expected": EXPECTED_DOC_KEYS,
            "missing": missing,
            "unavailable": unavailable,
            "bad_urls": bad_urls,
            "non_markdown": non_markdown,
            "openapi_ok": openapi_ok,
            "openapi_version": data.get("openapi_version"),
        },
    )


def _module_url_path(raw_url: Any) -> str:
    parsed = urllib.parse.urlparse(str(raw_url or ""))
    return parsed.path or str(raw_url or "")


def check_openapi_modules(client: SmokeClient, fetch_module_json: bool = False) -> CheckResult:
    payload = client.get_json("/api/v1/openapi/modules")
    data = _response_data(payload)
    modules = data.get("modules") if isinstance(data, dict) else []
    module_map = {
        item.get("key"): item
        for item in modules
        if isinstance(item, dict) and item.get("key")
    }

    missing = [key for key in EXPECTED_OPENAPI_MODULES if key not in module_map]
    unavailable = [
        key for key, item in module_map.items()
        if key in EXPECTED_OPENAPI_MODULES and item.get("available") is not True
    ]
    empty = [
        key for key, item in module_map.items()
        if key in EXPECTED_OPENAPI_MODULES and int(item.get("path_count") or 0) <= 0
    ]
    bad_urls = [
        key for key, item in module_map.items()
        if key in EXPECTED_OPENAPI_MODULES
        and _module_url_path(item.get("url")) != f"/api/v1/openapi/modules/{key}.json"
    ]
    fetched = []
    fetch_errors = []

    if fetch_module_json:
        for key in EXPECTED_OPENAPI_MODULES:
            item = module_map.get(key)
            if not item:
                continue
            path = _module_url_path(item.get("url"))
            try:
                module_payload = client.get_json(path)
            except Exception as exc:  # noqa: BLE001 - report all module fetch failures uniformly.
                fetch_errors.append(f"{key}:{exc}")
                continue
            paths = module_payload.get("paths") if isinstance(module_payload, dict) else {}
            if module_payload.get("openapi") != "3.0.0" or not isinstance(paths, dict) or not paths:
                fetch_errors.append(f"{key}:invalid_contract")
                continue
            fetched.append(key)

    issues = []
    if missing:
        issues.append(f"missing={','.join(missing)}")
    if unavailable:
        issues.append(f"unavailable={','.join(unavailable)}")
    if empty:
        issues.append(f"empty={','.join(empty)}")
    if bad_urls:
        issues.append(f"bad_urls={','.join(bad_urls)}")
    if fetch_errors:
        issues.append(f"fetch_errors={'; '.join(fetch_errors)}")

    ok = not issues
    keys = sorted(module_map)
    detail = f"modules={len(module_map)} expected={len(EXPECTED_OPENAPI_MODULES)} version={data.get('openapi_version')}"
    if fetch_module_json:
        detail = f"{detail} fetched={len(fetched)}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"

    return _result(
        "openapi_modules",
        ok,
        detail,
        {
            "modules": keys,
            "expected": EXPECTED_OPENAPI_MODULES,
            "missing": missing,
            "unavailable": unavailable,
            "empty": empty,
            "bad_urls": bad_urls,
            "fetched": fetched,
            "fetch_errors": fetch_errors,
            "openapi_version": data.get("openapi_version"),
        },
    )


def check_scan(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/scan")
    data = _response_data(payload)
    status = data.get("status")
    recent_errors = data.get("recent_errors") or []
    ok = len(recent_errors) == 0
    return _result("scan", ok, f"status={status} recent_errors={len(recent_errors)}", {
        "status": status,
        "recent_errors": recent_errors,
    })


def check_metadata_providers(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/metadata/providers")
    data = _response_data(payload)
    providers = data.get("providers") if isinstance(data, dict) else []
    provider_map = {
        item.get("key"): item
        for item in providers
        if isinstance(item, dict) and item.get("key")
    }
    keys = sorted(provider_map)
    default_order = data.get("default_order") if isinstance(data, dict) else []
    if not isinstance(default_order, list):
        default_order = []

    missing = [key for key in EXPECTED_METADATA_PROVIDERS if key not in provider_map]
    search_missing = [
        key for key in EXPECTED_METADATA_SEARCH_PROVIDERS
        if not provider_map.get(key, {}).get("supports_search")
    ]
    tencent = provider_map.get("tencent_video") or {}
    tencent_manual_only = tencent.get("manual_only") is True and tencent.get("supports_scrape") is False
    anilist = provider_map.get("anilist") or {}
    anilist_opt_in = anilist.get("default_enabled") is False
    default_order_ok = default_order == EXPECTED_METADATA_DEFAULT_ORDER

    issues = []
    if missing:
        issues.append(f"missing={','.join(missing)}")
    if search_missing:
        issues.append(f"search_missing={','.join(search_missing)}")
    if not default_order_ok:
        issues.append(f"default_order_expected={','.join(EXPECTED_METADATA_DEFAULT_ORDER)}")
    if not tencent_manual_only:
        issues.append("tencent_video_manual_only=false")
    if not anilist_opt_in:
        issues.append("anilist_default_enabled_not_false")

    ok = not issues
    detail = f"providers={','.join(keys)} default_order={'->'.join(str(item) for item in default_order)}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "metadata_providers",
        ok,
        detail,
        {
            "providers": keys,
            "default_order": default_order,
            "missing": missing,
            "search_missing": search_missing,
            "tencent_video_manual_only": tencent_manual_only,
            "anilist_opt_in": anilist_opt_in,
        },
    )


def check_tmdb_token(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/system/tmdb-config/check")
    data = _response_data(payload)
    ready = data.get("ready") is True
    status = data.get("status")
    token_set = data.get("token_set") is True
    token_valid = data.get("token_valid") is True
    proxy_enabled = data.get("proxy_enabled")
    proxy_configured = data.get("proxy_configured")
    elapsed_ms = data.get("elapsed_ms")
    return _result(
        "tmdb_token",
        ready,
        (
            f"ready={ready} status={status} token_set={token_set} token_valid={token_valid} "
            f"proxy_enabled={proxy_enabled} proxy_configured={proxy_configured} elapsed_ms={elapsed_ms}"
        ),
        {
            "ready": ready,
            "status": status,
            "token_set": token_set,
            "token_valid": token_valid,
            "proxy_enabled": proxy_enabled,
            "proxy_configured": proxy_configured,
            "elapsed_ms": elapsed_ms,
            "http_status": data.get("http_status"),
        },
    )


def _id_map(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        item.get("id"): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def check_metadata_review_workbench(client: SmokeClient) -> CheckResult:
    taxonomy_payload = client.get_json("/api/v1/metadata/review-taxonomy")
    taxonomy = _response_data(taxonomy_payload)
    buckets = _id_map(taxonomy.get("buckets"))
    taxonomy_actions = _id_map(taxonomy.get("actions"))

    quality_payload = client.get_json("/api/v1/metadata/quality-summary", {"sample_size": 1})
    quality = _response_data(quality_payload)
    totals = quality.get("totals") if isinstance(quality.get("totals"), dict) else {}
    quality_actions = _id_map(quality.get("actions"))

    missing_buckets = [bucket_id for bucket_id in EXPECTED_METADATA_REVIEW_BUCKETS if bucket_id not in buckets]
    missing_bucket_entrypoints = [
        bucket_id
        for bucket_id in EXPECTED_METADATA_REVIEW_BUCKETS
        if bucket_id in buckets and not buckets[bucket_id].get("entrypoints")
    ]
    missing_actions = [action_id for action_id in EXPECTED_METADATA_REVIEW_ACTIONS if action_id not in taxonomy_actions]
    missing_quality_actions = [
        action_id for action_id in EXPECTED_METADATA_QUALITY_ACTIONS if action_id not in quality_actions
    ]
    missing_quality_totals = [key for key in EXPECTED_METADATA_QUALITY_TOTALS if key not in totals]

    issues = []
    if missing_buckets:
        issues.append(f"missing_buckets={','.join(missing_buckets)}")
    if missing_bucket_entrypoints:
        issues.append(f"missing_bucket_entrypoints={','.join(missing_bucket_entrypoints)}")
    if missing_actions:
        issues.append(f"missing_actions={','.join(missing_actions)}")
    if missing_quality_actions:
        issues.append(f"missing_quality_actions={','.join(missing_quality_actions)}")
    if missing_quality_totals:
        issues.append(f"missing_quality_totals={','.join(missing_quality_totals)}")

    ok = not issues
    detail = (
        f"buckets={len(buckets)} actions={len(taxonomy_actions)} "
        f"quality_actions={len(quality_actions)} movie_count={totals.get('movie_count')} "
        f"issue_movies={totals.get('issue_movie_count')}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"

    return _result(
        "metadata_review_workbench",
        ok,
        detail,
        {
            "buckets": sorted(buckets),
            "actions": sorted(taxonomy_actions),
            "quality_actions": sorted(quality_actions),
            "missing_buckets": missing_buckets,
            "missing_bucket_entrypoints": missing_bucket_entrypoints,
            "missing_actions": missing_actions,
            "missing_quality_actions": missing_quality_actions,
            "missing_quality_totals": missing_quality_totals,
            "movie_count": totals.get("movie_count"),
            "issue_movie_count": totals.get("issue_movie_count"),
        },
    )


def check_background_jobs(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/jobs", {"limit": 1})
    data = _response_data(payload)
    items = data.get("items")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    issues = []

    if not isinstance(items, list):
        issues.append("items_not_list")
        items = []
    if not isinstance(data.get("summary"), dict):
        issues.append("summary_missing")

    if summary.get("limit") != 1:
        issues.append(f"limit={summary.get('limit')}")
    if summary.get("count") != len(items):
        issues.append(f"count_mismatch={summary.get('count')}/{len(items)}")
    if len(items) > 1:
        issues.append(f"too_many_items={len(items)}")

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"item_{index}_not_object")
            continue
        missing = [
            key for key in ("id", "type", "status", "created_at", "progress")
            if key not in item
        ]
        if missing:
            issues.append(f"item_{index}_missing={','.join(missing)}")
        status = item.get("status")
        if status not in EXPECTED_JOB_STATUSES:
            issues.append(f"item_{index}_status={status}")
        if "progress" in item and not isinstance(item.get("progress"), dict):
            issues.append(f"item_{index}_progress_not_object")
        if "persisted" in item and item.get("persisted") not in (True, False):
            issues.append(f"item_{index}_persisted_not_bool")

    ok = not issues
    latest = items[0] if items and isinstance(items[0], dict) else {}
    latest_detail = ""
    if latest:
        latest_detail = f" latest={latest.get('type')}:{latest.get('status')}"
    detail = f"items={len(items)} limit={summary.get('limit')} type={summary.get('type')}{latest_detail}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"

    return _result(
        "background_jobs",
        ok,
        detail,
        {
            "item_count": len(items),
            "summary": summary,
            "issues": issues,
            "latest": {
                "id": latest.get("id"),
                "type": latest.get("type"),
                "status": latest.get("status"),
                "persisted": latest.get("persisted"),
            } if latest else None,
        },
    )


def _source_label(source: dict[str, Any]) -> str:
    source_id = source.get("id", "?")
    source_type = source.get("type") or "unknown"
    name = source.get("name") or source.get("display_name") or "unnamed"
    return f"{source_id}:{name}({source_type})"


def _source_has_resources(source: dict[str, Any]) -> bool:
    usage = source.get("usage") if isinstance(source, dict) else {}
    if not isinstance(usage, dict):
        return False
    try:
        resource_count = int(usage.get("resource_count") or 0)
    except (TypeError, ValueError):
        resource_count = 0
    return bool(usage.get("has_resources")) or resource_count > 0


def _source_actions(source: dict[str, Any]) -> dict[str, Any]:
    actions = source.get("actions") if isinstance(source, dict) else {}
    return actions if isinstance(actions, dict) else {}


def check_storage_sources(client: SmokeClient, min_sources: int) -> CheckResult:
    payload = client.get_json("/api/v1/storage/sources")
    sources = [item for item in _response_list(payload) if isinstance(item, dict)]
    resource_backed = [source for source in sources if _source_has_resources(source)]
    issues = []

    if len(sources) < min_sources:
        issues.append(f"sources_below_min={len(sources)}/{min_sources}")

    ready_count = 0
    for source in sources:
        label = _source_label(source)
        if source.get("is_supported") is not True:
            issues.append(f"{label}:unsupported")
        if source.get("config_valid") is not True:
            issues.append(f"{label}:config_invalid")

        actions = _source_actions(source)
        resource_source = _source_has_resources(source)
        if resource_source:
            if actions.get("can_scan") is not True:
                issues.append(f"{label}:scan_disabled")
            if actions.get("can_stream") is not True:
                issues.append(f"{label}:stream_disabled")
            auth_state = (source.get("config") or {}).get("auth_state") if isinstance(source.get("config"), dict) else None
            if auth_state and str(auth_state).strip().lower() != "ready":
                issues.append(f"{label}:auth_state={auth_state}")

        if source.get("is_supported") is True and source.get("config_valid") is True:
            if not resource_source or (actions.get("can_scan") is True and actions.get("can_stream") is True):
                ready_count += 1

    ok = not issues
    detail = f"sources={len(sources)} ready={ready_count} resource_backed={len(resource_backed)}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "storage_sources",
        ok,
        detail,
        {
            "source_count": len(sources),
            "ready_count": ready_count,
            "resource_backed_count": len(resource_backed),
            "issues": issues,
            "sources": [
                {
                    "id": source.get("id"),
                    "name": source.get("name"),
                    "type": source.get("type"),
                    "config_valid": source.get("config_valid"),
                    "is_supported": source.get("is_supported"),
                    "has_resources": _source_has_resources(source),
                    "actions": _source_actions(source),
                }
                for source in sources
            ],
        },
    )


def check_storage_health(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/storage/sources")
    sources = [item for item in _response_list(payload) if isinstance(item, dict)]
    health_items = []
    issues = []

    for source in sources:
        if not _source_has_resources(source):
            continue
        capabilities = source.get("capabilities") if isinstance(source.get("capabilities"), dict) else {}
        if capabilities.get("health_check") is not True:
            continue
        source_id = source.get("id")
        if source_id is None:
            issues.append(f"{_source_label(source)}:missing_id")
            continue
        health_payload = client.get_json(f"/api/v1/storage/sources/{source_id}/health")
        health_source = _response_data(health_payload)
        health = health_source.get("health") if isinstance(health_source, dict) else {}
        if not isinstance(health, dict):
            health = {}
        status = health.get("status")
        reason = health.get("reason")
        health_items.append({
            "id": source_id,
            "name": source.get("name"),
            "type": source.get("type"),
            "status": status,
            "reason": reason,
        })
        if status != "online":
            issues.append(f"{_source_label(source)}:health={status or 'unknown'}:{reason or 'unknown'}")

    ok = not issues
    detail = f"checked={len(health_items)} online={sum(1 for item in health_items if item.get('status') == 'online')}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "storage_health",
        ok,
        detail,
        {
            "checked": len(health_items),
            "items": health_items,
            "issues": issues,
        },
    )


def check_work_items(client: SmokeClient, issue_code: str, max_items: int) -> CheckResult:
    payload = client.get_json(
        "/api/v1/metadata/work-items",
        {"metadata_issue_code": issue_code, "page_size": 20},
    )
    data = _response_data(payload)
    total = _pagination_total(data)
    titles = [item.get("title") for item in data.get("items") or [] if isinstance(item, dict)]
    ok = total <= max_items
    return _result(
        f"metadata_{issue_code}",
        ok,
        f"total={total} max={max_items}",
        {"total": total, "sample_titles": titles[:10]},
    )


def check_episode_review(client: SmokeClient, max_items: int) -> CheckResult:
    payload = client.get_json("/api/v1/metadata/episode-review-items", {"page_size": 20})
    data = _response_data(payload)
    total = _pagination_total(data)
    titles = [item.get("title") for item in data.get("items") or [] if isinstance(item, dict)]
    ok = total <= max_items
    return _result("episode_review", ok, f"total={total} max={max_items}", {
        "total": total,
        "sample_titles": titles[:10],
    })


def check_resource_governance(client: SmokeClient, live_check_limit: int, max_actionable: int) -> CheckResult:
    payload = client.get_json(
        "/api/v1/resources/governance-summary",
        {"live_check": "true", "live_check_limit": live_check_limit, "sample_size": 3},
    )
    data = _response_data(payload)
    totals = data.get("totals") or {}
    resource_count = int(totals.get("resource_count") or 0)
    live_checked = int(totals.get("live_path_checked_count") or 0)
    live_valid = int(totals.get("live_path_valid_count") or 0)
    actionable = int(totals.get("actionable_issue_count") or 0)
    ok = actionable <= max_actionable and live_checked == live_valid
    return _result(
        "resource_governance",
        ok,
        f"resources={resource_count} live={live_valid}/{live_checked} actionable={actionable}",
        {
            "resource_count": resource_count,
            "live_path_checked_count": live_checked,
            "live_path_valid_count": live_valid,
            "actionable_issue_count": actionable,
        },
    )


def check_systemd_services(services: list[str], timeout: float) -> CheckResult:
    if not services:
        return _result("systemd_services", True, "no services configured", {"services": {}})

    command = ["systemctl", "is-active", *services]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("systemctl not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"systemctl timed out after {timeout:g}s") from exc

    statuses = [line.strip() for line in completed.stdout.splitlines()]
    service_statuses = {
        service: statuses[index] if index < len(statuses) and statuses[index] else "unknown"
        for index, service in enumerate(services)
    }
    inactive = {
        service: status
        for service, status in service_statuses.items()
        if status != "active"
    }
    ok = completed.returncode == 0 and not inactive
    detail = ", ".join(f"{service}={status}" for service, status in service_statuses.items())
    return _result("systemd_services", ok, detail, {"services": service_statuses})


def run_checks(args) -> list[CheckResult]:
    client = SmokeClient(args.base_url, timeout=args.timeout, api_token=args.api_token)
    checks = [
        CheckSpec("health", lambda: check_health(client)),
        CheckSpec("openapi_health_contract", lambda: check_openapi_health_contract(client)),
        CheckSpec("docs_index", lambda: check_docs_index(client)),
        CheckSpec("openapi_modules", lambda: check_openapi_modules(client, args.openapi_module_json_check)),
        CheckSpec("scan", lambda: check_scan(client)),
        CheckSpec("metadata_providers", lambda: check_metadata_providers(client)),
        CheckSpec("metadata_review_workbench", lambda: check_metadata_review_workbench(client)),
        CheckSpec("background_jobs", lambda: check_background_jobs(client)),
        CheckSpec("storage_sources", lambda: check_storage_sources(client, args.min_storage_sources)),
        CheckSpec(
            "metadata_fallback_pipeline_match",
            lambda: check_work_items(client, "fallback_pipeline_match", args.max_fallback_items),
        ),
        CheckSpec("episode_review", lambda: check_episode_review(client, args.max_episode_review_items)),
        CheckSpec(
            "resource_governance",
            lambda: check_resource_governance(client, args.live_check_limit, args.max_resource_actionable),
        ),
    ]
    if args.systemd:
        systemd_services = args.systemd_service or list(DEFAULT_SYSTEMD_SERVICES)
        checks.insert(0, CheckSpec("systemd_services", lambda: check_systemd_services(systemd_services, args.timeout)))
    if getattr(args, "tmdb_token_check", False):
        checks.append(CheckSpec("tmdb_token", lambda: check_tmdb_token(client)))
    if getattr(args, "storage_health_check", False):
        checks.append(CheckSpec("storage_health", lambda: check_storage_health(client)))

    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(check.run())
        except Exception as exc:  # noqa: BLE001 - smoke checks should report all failures uniformly.
            results.append(_result(check.name, False, str(exc)))
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CyberStream backend smoke checks.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP and systemctl timeout in seconds")
    parser.add_argument(
        "--api-token",
        default=DEFAULT_API_TOKEN,
        help=(
            "Optional CyberStream API token for protected management endpoints. "
            "Defaults to CYBER_BACKEND_SMOKE_API_TOKEN or CYBER_API_TOKEN."
        ),
    )
    parser.add_argument("--live-check-limit", type=int, default=500, help="Resource live-check limit")
    parser.add_argument(
        "--openapi-module-json-check",
        action="store_true",
        help="Also fetch every indexed OpenAPI module JSON and validate it is a raw OpenAPI contract.",
    )
    parser.add_argument("--max-fallback-items", type=int, default=0, help="Maximum fallback metadata work items")
    parser.add_argument("--max-episode-review-items", type=int, default=0, help="Maximum episode review items")
    parser.add_argument("--max-resource-actionable", type=int, default=0, help="Maximum actionable resource issues")
    parser.add_argument("--min-storage-sources", type=int, default=0, help="Minimum configured storage sources")
    parser.add_argument(
        "--storage-health-check",
        action="store_true",
        help="Also run live health checks for resource-backed storage sources.",
    )
    parser.add_argument(
        "--tmdb-token-check",
        action="store_true",
        help="Also verify the configured TMDB token with the live TMDB API; use before scraping.",
    )
    parser.add_argument("--systemd", action="store_true", help="Also check local systemd service states")
    parser.add_argument(
        "--systemd-service",
        action="append",
        default=None,
        help="Systemd service to check when --systemd is set; may be repeated",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = run_checks(args)
    failed = [item for item in results if not item.ok]

    if args.json:
        print(json.dumps({
            "base_url": args.base_url,
            "ok": not failed,
            "checks": [item.__dict__ for item in results],
        }, ensure_ascii=False, indent=2))
    else:
        for item in results:
            prefix = "OK" if item.ok else "FAIL"
            print(f"{prefix}\t{item.name}\t{item.detail}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
