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
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
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
    ok = status == "up"
    return _result("health", ok, f"status={status} version={version}", {"status": status, "version": version})


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
    client = SmokeClient(args.base_url, timeout=args.timeout)
    checks = [
        CheckSpec("health", lambda: check_health(client)),
        CheckSpec("openapi_health_contract", lambda: check_openapi_health_contract(client)),
        CheckSpec("scan", lambda: check_scan(client)),
        CheckSpec("metadata_providers", lambda: check_metadata_providers(client)),
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
    parser.add_argument("--live-check-limit", type=int, default=500, help="Resource live-check limit")
    parser.add_argument("--max-fallback-items", type=int, default=0, help="Maximum fallback metadata work items")
    parser.add_argument("--max-episode-review-items", type=int, default=0, help="Maximum episode review items")
    parser.add_argument("--max-resource-actionable", type=int, default=0, help="Maximum actionable resource issues")
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
