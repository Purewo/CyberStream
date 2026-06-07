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
DEFAULT_EXPECTED_VERSION = os.environ.get("CYBER_BACKEND_EXPECTED_VERSION", "")
DEFAULT_EXPECTED_OPENAPI_VERSION = os.environ.get("CYBER_BACKEND_EXPECTED_OPENAPI_VERSION", "")
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
EXPECTED_TMDB_CONFIG_KEYS = [
    "token_set",
    "proxy_enabled",
    "proxy_url",
    "proxy_url_redacted",
]
EXPECTED_METADATA_OVERVIEW_KEYS = [
    "totals",
    "source_groups",
    "review_priorities",
    "recommended_actions",
    "issues",
]
EXPECTED_METADATA_OVERVIEW_TOTALS = [
    "movie_count",
    "needs_attention_count",
    "placeholder_count",
    "local_only_count",
    "external_match_count",
    "low_confidence_resource_count",
    "fallback_resource_count",
    "locked_movie_count",
    "nfo_candidate_movie_count",
]
EXPECTED_METADATA_OVERVIEW_COUNTER_KEYS = [
    "key",
    "count",
]
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
EXPECTED_METADATA_QUALITY_ACTION_KEYS = [
    "id",
    "endpoint",
    "method",
    "enabled",
]
EXPECTED_METADATA_QUALITY_ISSUE_KEYS = [
    "code",
    "label",
    "movie_count",
    "affected_count",
    "samples",
]
EXPECTED_METADATA_QUALITY_SAMPLE_KEYS = [
    "movie_id",
    "title",
    "scraper_source",
    "metadata_state",
    "metadata_actions",
    "matching_issue",
]
EXPECTED_METADATA_REIDENTIFY_ISSUE_CODES = [
    "fallback_pipeline_match",
    "poster_missing",
    "low_confidence_resources",
]
EXPECTED_METADATA_REIDENTIFY_PLAN_KEYS = [
    "dry_run",
    "plan_mode",
    "provider_search",
    "selection",
    "apply_method",
    "apply_endpoint",
    "sync_apply_endpoint",
    "progress_endpoint_template",
    "apply_payload",
    "items",
    "summary",
]
EXPECTED_METADATA_REIDENTIFY_SUMMARY_KEYS = [
    "total",
    "planned",
    "failed",
    "apply_item_count",
    "status_counts",
    "issue_code_counts",
    "failed_movie_ids",
]
EXPECTED_METADATA_REIDENTIFY_ITEM_KEYS = [
    "movie_id",
    "title",
    "status",
    "dry_run",
    "plan_mode",
    "matched_issue_codes",
    "metadata_state",
    "metadata_actions",
    "search_query",
    "search_title",
    "search_year",
    "preview",
    "diff",
    "resolution",
    "explanation",
    "apply_item",
]
EXPECTED_RESOURCE_GOVERNANCE_ISSUE_CODES = [
    "duplicate_playback_resource",
    "detached_source_resource",
]
EXPECTED_RESOURCE_GOVERNANCE_PLAN_KEYS = [
    "generated_at",
    "dry_run",
    "apply_method",
    "apply_endpoint",
    "selection",
    "items",
    "summary",
    "returned_summary",
    "pagination",
    "apply_payload",
]
EXPECTED_RESOURCE_GOVERNANCE_SUMMARY_KEYS = [
    "total",
    "planned",
    "skipped",
    "manual_review",
    "planned_resource_ids",
    "issue_code_counts",
    "skip_reason_counts",
]
EXPECTED_RESOURCE_GOVERNANCE_ITEM_KEYS = [
    "issue_code",
    "status",
    "action",
    "resource",
    "apply_item",
    "restore_snapshot_available",
]
EXPECTED_EPISODE_REVIEW_SUMMARY_KEYS = [
    "total_items",
    "issue_code_counts",
    "auto_update_count",
    "manual_suggestion_count",
    "warning_count",
]
EXPECTED_EPISODE_REVIEW_ITEM_KEYS = [
    "movie_id",
    "title",
    "playable",
    "primary_resource_id",
    "scraper_source",
    "metadata_state",
    "metadata_actions",
    "metadata_issues",
    "episode_diagnostics",
    "season_count",
    "seasons_needing_attention",
    "auto_update_count",
    "manual_suggestion_count",
    "warning_count",
    "diagnostics_endpoint",
    "apply_method",
    "apply_endpoint",
    "apply_payload",
]
EXPECTED_METADATA_WORK_ITEM_KEYS = [
    "id",
    "title",
    "scraper_source",
    "metadata_state",
    "metadata_actions",
    "metadata_diagnostics",
    "metadata_issues",
    "catalog_visibility",
    "manual_content",
]
EXPECTED_CATALOG_MOVIE_ITEM_KEYS = [
    "id",
    "title",
    "poster_url",
    "poster_asset_url",
    "poster_asset_urls",
    "poster_asset_fallback_urls",
    "poster_source_info",
    "rating",
    "year",
    "country",
    "quality_badge",
    "scraper_source",
    "metadata_state",
    "catalog_visibility",
    "manual_content",
    "date_added",
    "updated_at",
    "tags",
    "source_ids",
    "season_cards",
    "season_count",
    "has_multi_season_content",
    "user_data",
]
EXPECTED_MOVIE_DETAIL_KEYS = [
    "original_title",
    "overview",
    "backdrop_url",
    "backdrop_asset_url",
    "backdrop_asset_urls",
    "backdrop_asset_fallback_urls",
    "backdrop_source_info",
    "director",
    "actors",
    "metadata_locked_fields",
    "metadata_actions",
    "metadata_diagnostics",
    "metadata_issues",
]
EXPECTED_MOVIE_IMAGE_STATUS_KEYS = [
    "movie_id",
    "title",
    "items",
    "summary",
]
EXPECTED_MOVIE_IMAGE_STATUS_ITEM_KEYS = [
    "kind",
    "asset_url",
    "asset_urls",
    "fallback_urls",
    "source_url",
    "source_info",
    "has_source",
    "source_valid",
    "source_error",
    "cached",
    "cache_state",
    "source_changed",
    "cache",
    "cdn",
]
EXPECTED_MOVIE_IMAGE_ASSET_URLS_KEYS = [
    "kind",
    "strategy",
    "primary_url",
    "url",
    "cdn_url",
    "local_url",
    "original_url",
    "fallback_urls",
    "source",
]
EXPECTED_MOVIE_IMAGE_SOURCE_INFO_KEYS = [
    "kind",
    "field",
    "public_field",
    "source_url",
    "has_source",
    "source_type",
    "provider",
    "provider_label",
    "scraper_source",
    "metadata_source_group",
    "metadata_source_label",
    "locked",
    "confidence",
    "evidence",
]
EXPECTED_MOVIE_IMAGE_STATUS_SUMMARY_KEYS = [
    "total",
    "cached",
    "missing",
    "missing_source",
    "invalid_source",
    "stale_source",
]
EXPECTED_MOVIE_IMAGE_KINDS = {"poster", "backdrop"}
EXPECTED_MOVIE_IMAGE_CACHE_STATES = {
    "cached",
    "missing",
    "missing_source",
    "invalid_source",
    "stale_source",
}
EXPECTED_MOVIE_RESOURCES_KEYS = [
    "items",
    "groups",
    "summary",
]
EXPECTED_MOVIE_SEASONS_KEYS = [
    "items",
    "summary",
]
EXPECTED_MOVIE_RESOURCES_GROUP_KEYS = [
    "standalone",
    "seasons",
    "playback_sources",
]
EXPECTED_MOVIE_RESOURCES_SUMMARY_KEYS = [
    "total_items",
    "hydrated_item_count",
    "selected_season",
    "playback_source_count",
    "hydrated_playback_source_count",
    "duplicate_group_count",
    "alternate_resource_count",
    "season_count",
    "standalone_count",
    "edited_items_count",
    "season_metadata_count",
    "episode_diagnostics",
    "metadata_source_group",
    "has_placeholder_metadata",
    "is_local_only_metadata",
    "needs_attention",
    "review_priority",
]
EXPECTED_MOVIE_EPISODE_DIAGNOSTICS_KEYS = [
    "movie_id",
    "title",
    "dry_run",
    "apply_method",
    "apply_endpoint",
    "apply_payload",
    "summary",
    "seasons",
    "suggested_updates",
    "warnings",
]
EXPECTED_MOVIE_EPISODE_DIAGNOSTICS_SUMMARY_KEYS = [
    "status",
    "coverage_status",
    "issue_count",
    "issue_code_counts",
    "season_count",
    "seasons_needing_attention",
]
EXPECTED_MOVIE_EPISODE_DIAGNOSTICS_SEASON_KEYS = [
    "season",
    "title",
    "display_title",
    "diagnostics",
    "affected_resource_ids",
    "affected_resources",
    "suggestions",
]
EXPECTED_MOVIE_SEASON_ITEM_KEYS = [
    "season",
    "title",
    "display_title",
    "overview",
    "air_date",
    "poster_url",
    "poster_source",
    "resource_ids",
    "primary_resource_ids",
    "playback_source_count",
    "alternate_resource_count",
    "edited_items_count",
    "episode_count",
    "tmdb_episode_count",
    "expected_episode_count",
    "aired_episode_count",
    "has_distinct_poster",
    "has_manual_metadata",
    "has_metadata",
    "metadata_edited_at",
    "episode_diagnostics",
    "sort",
    "user_data",
]
EXPECTED_SEASON_EPISODE_DIAGNOSTICS_KEYS = [
    "status",
    "coverage_status",
    "issue_codes",
    "available_episode_count",
    "available_episode_numbers",
    "missing_episode_numbers",
    "duplicate_episode_numbers",
    "duplicate_episode_resources",
    "alternate_episode_numbers",
    "alternate_episode_resources",
    "unnumbered_resource_ids",
    "completion_ratio",
    "expected_episode_count",
    "expected_source",
    "first_episode",
    "last_episode",
]
EXPECTED_MOVIE_RESOURCE_ITEM_KEYS = [
    "id",
    "resource_info",
    "playback",
    "metadata",
    "user_data",
]
EXPECTED_MOVIE_RESOURCE_INFO_KEYS = [
    "file",
    "display",
    "technical",
]
EXPECTED_MOVIE_RESOURCE_PLAYBACK_KEYS = [
    "stream_url",
    "web_player",
    "external_player",
    "subtitles",
    "cloud_transcode",
]
EXPECTED_MOVIE_RESOURCE_CLOUD_TRANSCODE_KEYS = [
    "supported",
    "provider",
    "provider_name",
    "mode",
    "qualities_endpoint",
    "stream_endpoint",
    "resolution_param",
    "available_resolutions",
    "recommended_for",
    "quality_semantics",
    "reason",
]
EXPECTED_MOVIE_PLAYBACK_SOURCE_KEYS = [
    "id",
    "primary_resource_id",
    "resource_ids",
    "alternate_resource_ids",
    "count",
    "is_duplicate_group",
    "duplicate_key",
    "match",
    "display",
    "file",
    "source_summary",
    "user_data",
]
EXPECTED_EXTERNAL_PLAYBACK_KEYS = [
    "resource_id",
    "movie_id",
    "title",
    "filename",
    "resource_info",
    "stream",
    "subtitles",
    "handoff",
    "player_profiles",
    "warnings",
]
EXPECTED_EXTERNAL_PLAYBACK_STREAM_KEYS = [
    "url",
    "mime_type",
    "storage_type",
    "default_mode",
    "playback_modes",
    "range_supported",
    "url_type",
    "requires_local_backend",
    "requires_user_agent_rewrite",
    "reason",
]
EXPECTED_EXTERNAL_PLAYBACK_SUBTITLES_KEYS = [
    "supported",
    "default_subtitle_id",
    "default_url",
    "items",
]
EXPECTED_EXTERNAL_PLAYBACK_HANDOFF_KEYS = [
    "supported",
    "method",
    "manifest_url",
    "playlist_url",
    "playlist_format",
    "playlist_mime_type",
    "reason",
]
EXPECTED_EXTERNAL_PLAYER_PROFILE_KEYS = [
    "key",
    "name",
    "platforms",
    "handoff_methods",
    "recommended",
]
EXPECTED_SUBTITLE_SETTINGS_KEYS = [
    "resource_id",
    "settings",
    "customized",
    "source",
    "updated_at",
]
EXPECTED_SUBTITLE_DISPLAY_SETTING_KEYS = [
    "zhSize",
    "zhColor",
    "enSize",
    "enColor",
    "gap",
    "offset",
]
SUBTITLE_NUMERIC_RANGES = {
    "zhSize": (8, 96),
    "enSize": (8, 96),
    "gap": (0, 120),
    "offset": (-500, 500),
}
EXPECTED_AUDIO_TRANSCODE_DIAGNOSTICS_KEYS = [
    "resource_id",
    "session_id",
    "active_count",
    "items",
]
EXPECTED_STORAGE_CAPABILITIES_KEYS = [
    "supported_types",
    "items",
]
EXPECTED_STORAGE_CAPABILITY_ITEM_KEYS = [
    "type",
    "display_name",
    "label",
    "browse",
    "validate_path",
    "range_stream",
    "library_root_path",
    "config_root_key",
    "preview",
    "scan",
    "stream",
]
EXPECTED_STORAGE_CAPABILITY_TYPES = {
    "local",
    "alist",
    "openlist",
    "guangyapan",
}
EXPECTED_STORAGE_PROVIDER_TYPE_KEYS = [
    "type",
    "display_name",
    "status",
    "capabilities",
    "config_fields",
]
EXPECTED_STORAGE_PROVIDER_CONFIG_FIELD_KEYS = [
    "name",
    "type",
    "required",
]
EXPECTED_STORAGE_PROVIDER_REQUIRED_FIELDS = {
    "local": {"root_path"},
    "alist": {"base_url", "host", "root"},
    "openlist": {"base_url", "host", "root"},
    "guangyapan": {"alist_storage_id", "mount_path", "auth_state", "cloud_root_path"},
}
EXPECTED_CATALOG_FILTER_KEYS = [
    "genres",
    "years",
    "countries",
]
EXPECTED_LIBRARY_KEYS = [
    "id",
    "name",
    "slug",
    "description",
    "is_enabled",
    "sort_order",
    "settings",
    "created_at",
    "updated_at",
]
EXPECTED_SYSTEM_UPDATE_KEYS = [
    "product",
    "channel",
    "platform",
    "arch",
    "variant",
    "current",
    "latest",
    "update_available",
    "downloads",
    "selected_download",
    "cdn",
    "source",
    "warnings",
    "checked_at",
]
EXPECTED_SYSTEM_UPDATE_CURRENT_KEYS = [
    "version",
    "release",
    "backend_version",
]
EXPECTED_SYSTEM_UPDATE_LATEST_KEYS = [
    "version",
    "release",
    "title",
    "mandatory",
]
EXPECTED_SYSTEM_UPDATE_CDN_KEYS = [
    "required",
    "validated",
]
EXPECTED_SYSTEM_UPDATE_DOWNLOAD_KEYS = [
    "platform",
    "arch",
    "url",
    "cdn",
]
EXPECTED_OTHER_VIDEOS_KEYS = [
    "items",
    "pagination",
    "summary",
    "actions",
]
EXPECTED_OTHER_VIDEOS_SUMMARY_KEYS = [
    "total_items",
    "manual_movie_count",
]
EXPECTED_OTHER_VIDEO_ITEM_KEYS = [
    "resource_id",
    "movie_id",
    "movie_title",
    "movie_original_title",
    "movie_year",
    "movie_manual_content",
    "resource_info",
    "playback",
    "metadata",
    "catalog_visibility",
    "metadata_state",
    "metadata_issues",
    "metadata_actions",
    "metadata_match_context",
    "recommended_resolution",
    "actions",
]
EXPECTED_OTHER_VIDEO_MATCH_CONTEXT_KEYS = [
    "suggested_query",
    "suggested_year",
    "suggested_media_type_hint",
    "source_media_type_hint",
    "media_type_options",
    "title_hint_source",
]
EXPECTED_HOMEPAGE_KEYS = [
    "hero",
    "sections",
]
EXPECTED_HOMEPAGE_HERO_KEYS = [
    "mode",
    "movie",
]
EXPECTED_HOMEPAGE_SECTION_KEYS = [
    "key",
    "title",
    "genre",
    "mode",
    "limit",
    "items",
]
EXPECTED_HOMEPAGE_CONFIG_KEYS = [
    "hero_movie_id",
    "sections",
    "created_at",
    "updated_at",
]
EXPECTED_HOMEPAGE_CONFIG_SECTION_KEYS = [
    "key",
    "title",
    "genre",
    "mode",
    "limit",
    "movie_ids",
    "enabled",
    "sort_order",
]
EXPECTED_RECOMMENDATION_KEYS = [
    "primary_reason",
    "rank",
    "reason_text",
    "reasons",
    "score",
    "signals",
    "strategy",
]
EXPECTED_RECOMMENDATION_REASON_KEYS = [
    "code",
    "label",
    "weight",
]
EXPECTED_RECOMMENDATION_SIGNAL_KEYS = [
    "progress_ratio",
    "quality_badge",
    "resource_count",
]
EXPECTED_USER_HISTORY_KEYS = [
    "id",
    "resource_id",
    "last_played_at",
    "progress",
    "duration",
    "position_sec",
    "duration_sec",
    "progress_ratio",
    "progress_percent",
    "last_watched",
    "view_count",
    "device_id",
    "device_name",
    "movie",
    "filename",
]
EXPECTED_USER_FAVORITES_KEYS = [
    "items",
    "movie_ids",
    "total",
    "library",
]
EXPECTED_USER_FAVORITE_ITEM_KEYS = [
    "id",
    "movie_id",
    "created_at",
]
EXPECTED_USER_FAVORITE_STATE_KEYS = [
    "movie_id",
    "is_favorite",
    "created_at",
]
EXPECTED_FAVORITES_LIBRARY_KEYS = [
    *EXPECTED_LIBRARY_KEYS,
    "is_virtual",
    "kind",
    "movie_count",
    "actions",
]
EXPECTED_VAULT_ACCESS_ERROR_CODES = {40340, 40341, 40342, 42340}
EXPECTED_VAULT_STATUS_KEYS = [
    "configured",
    "unlocked",
    "locked",
    "locked_until",
    "pin_change_limit_per_day",
    "pin_changes_used_today",
    "pin_changes_remaining_today",
]
EXPECTED_METADATA_STATE_KEYS = [
    "source_group",
    "source_code",
    "source_label",
    "issue_codes",
    "needs_attention",
    "review_priority",
    "recommended_action",
]
EXPECTED_METADATA_ACTION_KEYS = [
    "can_manual_match",
    "can_refresh",
    "can_re_scrape",
    "primary_action",
]
EXPECTED_CATALOG_VISIBILITY_KEYS = [
    "effective_status",
    "status",
    "is_visible",
    "can_publish",
]
EXPECTED_STORAGE_BROWSE_KEYS = [
    "source",
    "current_path",
    "parent_path",
    "items",
]
EXPECTED_STORAGE_BROWSE_ITEM_KEYS = [
    "name",
    "path",
    "type",
    "size",
]
EXPECTED_JOB_STATUSES = ["queued", "running", "succeeded", "failed"]
EXPECTED_JOB_PRUNE_KEYS = [
    "dry_run",
    "retention_days",
    "cutoff",
    "type",
    "matched",
    "matched_ids",
    "removed",
    "removed_ids",
    "type_counts",
    "status_counts",
]
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
EXPECTED_AUTH_ME_KEYS = [
    "user_management_enabled",
    "authenticated",
    "role",
    "auth_via",
    "user",
    "permissions",
]
EXPECTED_AUTH_PERMISSION_KEYS = [
    "admin",
    "read_catalog",
    "manage_catalog",
    "manage_users",
    "personal_history",
    "personal_subtitle_settings",
]
EXPECTED_AUTH_ROLES = {"admin", "user"}


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
        return self._request_json("GET", url)

    def get_json_allow_error(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        return self._request_json("GET", url, allow_http_error=True)

    def post_json(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body or {}).encode("utf-8")
        return self._request_json("POST", url, data=data)

    def _request_json(
        self,
        method: str,
        url: str,
        data: bytes | None = None,
        allow_http_error: bool = False,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload)
                if isinstance(data, dict) and allow_http_error:
                    data["_http_status"] = response.status
                return data
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if allow_http_error:
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {"code": exc.code, "msg": body[:300]}
                if isinstance(data, dict):
                    data["_http_status"] = exc.code
                    return data
            raise RuntimeError(f"HTTP {exc.code} {url}: {body[:300]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc


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


def _json_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _result(name: str, ok: bool, detail: str, data: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail, data=data)


def check_health(client: SmokeClient, expected_version: str = "") -> CheckResult:
    root_payload = client.get_json("/")
    api_payload = client.get_json("/api/v1/health")
    root_data = _response_data(root_payload)
    api_data = _response_data(api_payload)
    root_database = root_data.get("database") if isinstance(root_data.get("database"), dict) else {}
    api_database = api_data.get("database") if isinstance(api_data.get("database"), dict) else {}
    root_status = root_data.get("status")
    api_status = api_data.get("status")
    root_version = root_data.get("version")
    api_version = api_data.get("version")
    expected_version = str(expected_version or "").strip()
    root_database_status = root_database.get("status")
    api_database_status = api_database.get("status")

    issues = []
    if api_status != "up":
        issues.append(f"api_status={api_status}")
    if api_database_status != "ok":
        issues.append(f"api_database={api_database_status}")
    if root_status != api_status:
        issues.append(f"root_status={root_status}")
    if root_version != api_version:
        issues.append(f"version_mismatch={root_version}/{api_version}")
    if expected_version and api_version != expected_version:
        issues.append(f"version_expected={expected_version} actual={api_version}")
    if root_database_status != api_database_status:
        issues.append(f"database_mismatch={root_database_status}/{api_database_status}")

    ok = not issues
    detail = (
        f"status={api_status} version={api_version} database={api_database_status} "
        f"root_status={root_status} root_database={root_database_status}"
    )
    if expected_version:
        detail = f"{detail} expected_version={expected_version}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "health",
        ok,
        detail,
        {
            "status": api_status,
            "version": api_version,
            "expected_version": expected_version or None,
            "database": api_database,
            "root_status": root_status,
            "root_version": root_version,
            "root_database": root_database,
            "issues": issues,
        },
    )


def check_auth_me(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/auth/me")
    data = _response_data(payload)
    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_AUTH_ME_KEYS, "auth_me"))

    authenticated = data.get("authenticated") if isinstance(data, dict) else None
    user_management_enabled = data.get("user_management_enabled") if isinstance(data, dict) else None
    role = data.get("role") if isinstance(data, dict) else None
    auth_via = data.get("auth_via") if isinstance(data, dict) else None
    user = data.get("user") if isinstance(data, dict) else None

    if authenticated not in (True, False):
        issues.append("auth_me_authenticated_not_bool")
    if user_management_enabled not in (True, False):
        issues.append("auth_me_user_management_enabled_not_bool")
    if role is not None and not isinstance(role, str):
        issues.append("auth_me_role_not_str_or_null")
    if isinstance(role, str) and role not in EXPECTED_AUTH_ROLES:
        issues.append(f"auth_me_role={role}")
    if auth_via is not None and not isinstance(auth_via, str):
        issues.append("auth_me_auth_via_not_str_or_null")
    if user is not None and not isinstance(user, dict):
        issues.append("auth_me_user_not_object_or_null")

    permissions = data.get("permissions") if isinstance(data, dict) else None
    issues.extend(_dict_missing_keys(permissions, EXPECTED_AUTH_PERMISSION_KEYS, "auth_permissions"))
    if isinstance(permissions, dict):
        for key in EXPECTED_AUTH_PERMISSION_KEYS:
            if key in permissions and permissions.get(key) not in (True, False):
                issues.append(f"auth_permission_{key}_not_bool")

        if authenticated is False:
            enabled_permissions = [key for key in EXPECTED_AUTH_PERMISSION_KEYS if permissions.get(key) is True]
            if enabled_permissions:
                issues.append(f"unauth_permissions_enabled={','.join(enabled_permissions)}")

    if authenticated is False:
        if role is not None:
            issues.append(f"unauth_role={role}")
        if auth_via is not None:
            issues.append(f"unauth_auth_via={auth_via}")
        if user is not None:
            issues.append("unauth_user_present")
    elif authenticated is True:
        if not isinstance(role, str) or role not in EXPECTED_AUTH_ROLES:
            issues.append(f"authenticated_role={role}")
        if user_management_enabled is True and not isinstance(user, dict):
            issues.append("authenticated_user_missing")

    ok = not issues
    detail = (
        f"authenticated={authenticated} role={role} auth_via={auth_via} "
        f"user_management_enabled={user_management_enabled}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "auth_me",
        ok,
        detail,
        {
            "authenticated": authenticated,
            "role": role,
            "auth_via": auth_via,
            "user_management_enabled": user_management_enabled,
            "issues": issues,
        },
    )


def check_openapi_health_contract(client: SmokeClient, expected_openapi_version: str = "") -> CheckResult:
    payload = client.get_json("/api/v1/openapi.json")
    info = payload.get("info") if isinstance(payload, dict) else {}
    if not isinstance(info, dict):
        info = {}
    openapi_version = info.get("version")
    expected_openapi_version = str(expected_openapi_version or "").strip()
    paths = payload.get("paths") if isinstance(payload, dict) else {}
    components = payload.get("components") if isinstance(payload, dict) else {}
    operation = ((paths or {}).get("/api/v1/health") or {}).get("get") or {}
    operation_id = operation.get("operationId")
    public = operation.get("security") == []
    issues = []
    if payload.get("openapi") != "3.0.0":
        issues.append(f"openapi={payload.get('openapi')}")
    if not isinstance(paths, dict) or not paths:
        issues.append("paths_invalid")
    if not isinstance(components, dict):
        issues.append("components_invalid")
    if operation_id != "apiHealthCheck":
        issues.append(f"operationId={operation_id}")
    if not public:
        issues.append("public=false")
    if expected_openapi_version and openapi_version != expected_openapi_version:
        issues.append(f"openapi_version_expected={expected_openapi_version} actual={openapi_version}")
    ok = not issues
    detail = f"operationId={operation_id} public={public} version={openapi_version}"
    if expected_openapi_version:
        detail = f"{detail} expected_openapi_version={expected_openapi_version}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "openapi_health_contract",
        ok,
        detail,
        {
            "operation_id": operation_id,
            "security": operation.get("security"),
            "openapi": payload.get("openapi"),
            "openapi_version": openapi_version,
            "expected_openapi_version": expected_openapi_version or None,
            "path_count": len(paths) if isinstance(paths, dict) else 0,
            "components_present": isinstance(components, dict),
            "issues": issues,
        },
    )


def check_docs_index(
    client: SmokeClient,
    expected_version: str = "",
    expected_openapi_version: str = "",
) -> CheckResult:
    payload = client.get_json("/api/v1/docs")
    data = _response_data(payload)
    app_version = data.get("version")
    expected_version = str(expected_version or "").strip()
    openapi_version = data.get("openapi_version")
    expected_openapi_version = str(expected_openapi_version or "").strip()
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
    if expected_version and app_version != expected_version:
        issues.append(f"version_expected={expected_version} actual={app_version}")
    if expected_openapi_version and openapi_version != expected_openapi_version:
        issues.append(f"openapi_version_expected={expected_openapi_version} actual={openapi_version}")

    ok = not issues
    detail = (
        f"documents={len(doc_map)} expected={len(EXPECTED_DOC_KEYS)} "
        f"app_version={app_version} openapi_version={openapi_version}"
    )
    if expected_version:
        detail = f"{detail} expected_version={expected_version}"
    if expected_openapi_version:
        detail = f"{detail} expected_openapi_version={expected_openapi_version}"
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
            "version": app_version,
            "expected_version": expected_version or None,
            "openapi_version": openapi_version,
            "expected_openapi_version": expected_openapi_version or None,
        },
    )


def check_update_check(client: SmokeClient, expected_version: str = "") -> CheckResult:
    current_version = expected_version or "1.21.0"
    current_release = f"{current_version}-pc.0"
    payload = client.get_json(
        "/api/v1/system/update-check",
        {
            "current_version": current_version,
            "current_release": current_release,
            "platform": "windows",
            "arch": "x64",
        },
    )
    data = _response_data(payload)
    issues = _system_update_check_issues(data, expected_backend_version=expected_version)

    downloads = data.get("downloads") if isinstance(data, dict) and isinstance(data.get("downloads"), list) else []
    latest = data.get("latest") if isinstance(data, dict) and isinstance(data.get("latest"), dict) else {}
    current = data.get("current") if isinstance(data, dict) and isinstance(data.get("current"), dict) else {}
    cdn = data.get("cdn") if isinstance(data, dict) and isinstance(data.get("cdn"), dict) else {}
    warnings = data.get("warnings") if isinstance(data, dict) and isinstance(data.get("warnings"), list) else []

    ok = not issues
    detail = (
        f"source={data.get('source') if isinstance(data, dict) else None} "
        f"current={current.get('version')} latest={latest.get('release')} "
        f"update_available={data.get('update_available') if isinstance(data, dict) else None} "
        f"downloads={len(downloads)} cdn_validated={cdn.get('validated')} warnings={len(warnings)}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "update_check",
        ok,
        detail,
        {
            "source": data.get("source") if isinstance(data, dict) else None,
            "current_version": current.get("version"),
            "latest_release": latest.get("release"),
            "download_count": len(downloads),
            "warning_count": len(warnings),
            "issues": issues,
        },
    )


def _module_url_path(raw_url: Any) -> str:
    parsed = urllib.parse.urlparse(str(raw_url or ""))
    return parsed.path or str(raw_url or "")


def check_openapi_modules(
    client: SmokeClient,
    fetch_module_json: bool = False,
    expected_openapi_version: str = "",
) -> CheckResult:
    payload = client.get_json("/api/v1/openapi/modules")
    data = _response_data(payload)
    openapi_version = data.get("openapi_version")
    expected_openapi_version = str(expected_openapi_version or "").strip()
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
    non_json = [
        key for key, item in module_map.items()
        if key in EXPECTED_OPENAPI_MODULES and not str(item.get("content_type") or "").startswith("application/json")
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
            info = module_payload.get("info") if isinstance(module_payload, dict) else {}
            if not isinstance(info, dict):
                info = {}
            module_version = info.get("version")
            paths = module_payload.get("paths") if isinstance(module_payload, dict) else {}
            components = module_payload.get("components") if isinstance(module_payload, dict) else {}
            contract_errors = []
            if module_payload.get("openapi") != "3.0.0":
                contract_errors.append(f"openapi={module_payload.get('openapi')}")
            if not isinstance(paths, dict) or not paths:
                contract_errors.append("paths_invalid")
            if not isinstance(components, dict):
                contract_errors.append("components_invalid")
            if contract_errors:
                fetch_errors.append(f"{key}:invalid_contract:{','.join(contract_errors)}")
                continue
            if expected_openapi_version and module_version != expected_openapi_version:
                fetch_errors.append(
                    f"{key}:version_expected={expected_openapi_version} actual={module_version}"
                )
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
    if non_json:
        issues.append(f"non_json={','.join(non_json)}")
    if _module_url_path(data.get("full_url")) != "/api/v1/openapi.json":
        issues.append("full_url_invalid")
    if fetch_errors:
        issues.append(f"fetch_errors={'; '.join(fetch_errors)}")
    if expected_openapi_version and openapi_version != expected_openapi_version:
        issues.append(f"openapi_version_expected={expected_openapi_version} actual={openapi_version}")

    ok = not issues
    keys = sorted(module_map)
    detail = f"modules={len(module_map)} expected={len(EXPECTED_OPENAPI_MODULES)} version={openapi_version}"
    if expected_openapi_version:
        detail = f"{detail} expected_openapi_version={expected_openapi_version}"
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
            "non_json": non_json,
            "full_url": data.get("full_url"),
            "fetched": fetched,
            "fetch_errors": fetch_errors,
            "openapi_version": openapi_version,
            "expected_openapi_version": expected_openapi_version or None,
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


def _tmdb_config_payload_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["tmdb_config_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_TMDB_CONFIG_KEYS, "tmdb_config"))
    for key in ("token_set", "proxy_enabled", "proxy_url_redacted"):
        if key in data and data.get(key) not in (True, False):
            issues.append(f"tmdb_config_{key}_not_bool")
    proxy_url = data.get("proxy_url")
    if "proxy_url" in data and proxy_url is not None and not isinstance(proxy_url, str):
        issues.append("tmdb_config_proxy_url_not_str")
    if isinstance(proxy_url, str):
        if any(secret_hint in proxy_url.lower() for secret_hint in ("tmdb_token", "bearer ", "authorization")):
            issues.append("tmdb_config_proxy_url_secret_hint")
        if "@" in proxy_url and data.get("proxy_url_redacted") is not True:
            issues.append("tmdb_config_proxy_url_unredacted_credentials")
    return issues


def check_tmdb_config(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/system/tmdb-config")
    data = _response_data(payload)
    issues = _tmdb_config_payload_issues(data)
    token_set = data.get("token_set") if isinstance(data, dict) else None
    proxy_enabled = data.get("proxy_enabled") if isinstance(data, dict) else None
    proxy_url = data.get("proxy_url") if isinstance(data, dict) else None
    proxy_url_redacted = data.get("proxy_url_redacted") if isinstance(data, dict) else None

    ok = not issues
    detail = (
        f"token_set={token_set} proxy_enabled={proxy_enabled} "
        f"proxy_configured={bool(proxy_url)} redacted={proxy_url_redacted}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "tmdb_config",
        ok,
        detail,
        {
            "token_set": token_set,
            "proxy_enabled": proxy_enabled,
            "proxy_configured": bool(proxy_url),
            "proxy_url_redacted": proxy_url_redacted,
            "issues": issues,
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


def _metadata_counter_item_issues(item: Any, index: int, section: str) -> list[str]:
    prefix = f"{section}_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_METADATA_OVERVIEW_COUNTER_KEYS, prefix))
    if "key" in item and not isinstance(item.get("key"), str):
        issues.append(f"{prefix}_key_not_str")
    if "count" in item and not _json_int(item.get("count")):
        issues.append(f"{prefix}_count_not_int")
    return issues


def _metadata_overview_payload_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["metadata_overview_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_METADATA_OVERVIEW_KEYS, "metadata_overview"))

    totals = data.get("totals")
    issues.extend(_dict_missing_keys(totals, EXPECTED_METADATA_OVERVIEW_TOTALS, "metadata_overview_totals"))
    if isinstance(totals, dict):
        for key in EXPECTED_METADATA_OVERVIEW_TOTALS:
            if key in totals and not _json_int(totals.get(key)):
                issues.append(f"metadata_overview_totals_{key}_not_int")

    for section in ("source_groups", "review_priorities", "recommended_actions", "issues"):
        items = data.get(section)
        if not isinstance(items, list):
            issues.append(f"metadata_overview_{section}_not_list")
            continue
        if section != "issues" and not items:
            issues.append(f"metadata_overview_{section}_empty")
        for index, item in enumerate(items[:10]):
            issues.extend(_metadata_counter_item_issues(item, index, f"metadata_overview_{section}"))
    return issues


def check_metadata_overview(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/metadata/overview")
    data = _response_data(payload)
    issues = _metadata_overview_payload_issues(data)
    totals = data.get("totals") if isinstance(data, dict) and isinstance(data.get("totals"), dict) else {}
    source_groups = data.get("source_groups") if isinstance(data, dict) and isinstance(data.get("source_groups"), list) else []
    review_priorities = (
        data.get("review_priorities")
        if isinstance(data, dict) and isinstance(data.get("review_priorities"), list)
        else []
    )
    recommended_actions = (
        data.get("recommended_actions")
        if isinstance(data, dict) and isinstance(data.get("recommended_actions"), list)
        else []
    )

    ok = not issues
    detail = (
        f"movies={totals.get('movie_count')} needs_attention={totals.get('needs_attention_count')} "
        f"source_groups={len(source_groups)} review_priorities={len(review_priorities)} "
        f"actions={len(recommended_actions)}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "metadata_overview",
        ok,
        detail,
        {
            "movie_count": totals.get("movie_count"),
            "needs_attention_count": totals.get("needs_attention_count"),
            "source_group_count": len(source_groups),
            "review_priority_count": len(review_priorities),
            "recommended_action_count": len(recommended_actions),
            "issues": issues,
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
    quality_contract_issues = _quality_summary_contract_issues(quality)

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
    issues.extend(quality_contract_issues)

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
            "quality_contract_issues": quality_contract_issues,
            "movie_count": totals.get("movie_count"),
            "issue_movie_count": totals.get("issue_movie_count"),
        },
    )


def _pagination_contract_issues(pagination: Any, expected_page_size: int | None = None) -> list[str]:
    if not isinstance(pagination, dict):
        return ["pagination_missing"]

    issues = []
    for key in ("current_page", "page_size", "total_items", "total_pages"):
        if not _json_int(pagination.get(key)):
            issues.append(f"pagination_{key}_not_int")
    if expected_page_size is not None and pagination.get("page_size") != expected_page_size:
        issues.append(f"pagination_page_size={pagination.get('page_size')}")
    return issues


def _dict_missing_keys(value: Any, keys: list[str], prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix}_not_object"]
    missing = [key for key in keys if key not in value]
    return [f"{prefix}_missing={','.join(missing)}"] if missing else []


def _work_item_contract_issues(item: Any, index: int) -> list[str]:
    prefix = f"item_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    missing = [key for key in EXPECTED_METADATA_WORK_ITEM_KEYS if key not in item]
    if missing:
        issues.append(f"{prefix}_missing={','.join(missing)}")

    if "id" in item and not isinstance(item.get("id"), str):
        issues.append(f"{prefix}_id_not_str")
    if "title" in item and not isinstance(item.get("title"), str):
        issues.append(f"{prefix}_title_not_str")
    if "metadata_issues" in item and not isinstance(item.get("metadata_issues"), list):
        issues.append(f"{prefix}_metadata_issues_not_list")

    metadata_state = item.get("metadata_state")
    issues.extend(
        _dict_missing_keys(metadata_state, EXPECTED_METADATA_STATE_KEYS, f"{prefix}_metadata_state")
    )
    if isinstance(metadata_state, dict):
        if "issue_codes" in metadata_state and not isinstance(metadata_state.get("issue_codes"), list):
            issues.append(f"{prefix}_metadata_state_issue_codes_not_list")
        if "needs_attention" in metadata_state and metadata_state.get("needs_attention") not in (True, False):
            issues.append(f"{prefix}_metadata_state_needs_attention_not_bool")

    metadata_actions = item.get("metadata_actions")
    issues.extend(
        _dict_missing_keys(metadata_actions, EXPECTED_METADATA_ACTION_KEYS, f"{prefix}_metadata_actions")
    )

    catalog_visibility = item.get("catalog_visibility")
    issues.extend(
        _dict_missing_keys(
            catalog_visibility,
            EXPECTED_CATALOG_VISIBILITY_KEYS,
            f"{prefix}_catalog_visibility",
        )
    )

    if "metadata_diagnostics" in item and not isinstance(item.get("metadata_diagnostics"), dict):
        issues.append(f"{prefix}_metadata_diagnostics_not_object")
    if "manual_content" in item and not isinstance(item.get("manual_content"), dict):
        issues.append(f"{prefix}_manual_content_not_object")
    return issues


def _catalog_movie_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"item_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    missing = [key for key in EXPECTED_CATALOG_MOVIE_ITEM_KEYS if key not in item]
    if missing:
        issues.append(f"{prefix}_missing={','.join(missing)}")

    if "id" in item and not isinstance(item.get("id"), str):
        issues.append(f"{prefix}_id_not_str")
    if "title" in item and not isinstance(item.get("title"), str):
        issues.append(f"{prefix}_title_not_str")
    for nullable_str_key in (
        "poster_url",
        "poster_asset_url",
        "country",
        "quality_badge",
        "scraper_source",
    ):
        if nullable_str_key in item and item.get(nullable_str_key) is not None:
            if not isinstance(item.get(nullable_str_key), str):
                issues.append(f"{prefix}_{nullable_str_key}_not_str")
    if "rating" in item and item.get("rating") is not None:
        if not isinstance(item.get("rating"), (int, float)) or isinstance(item.get("rating"), bool):
            issues.append(f"{prefix}_rating_not_number")
    if "year" in item and item.get("year") is not None and not _json_int(item.get("year")):
        issues.append(f"{prefix}_year_not_int")
    for list_key in ("poster_asset_fallback_urls", "tags", "source_ids", "season_cards"):
        if list_key in item and not isinstance(item.get(list_key), list):
            issues.append(f"{prefix}_{list_key}_not_list")
    if "source_ids" in item and isinstance(item.get("source_ids"), list):
        invalid_source_ids = [value for value in item["source_ids"] if not _json_int(value)]
        if invalid_source_ids:
            issues.append(f"{prefix}_source_ids_not_int")
    if "season_count" in item and not _json_int(item.get("season_count")):
        issues.append(f"{prefix}_season_count_not_int")
    if (
        "has_multi_season_content" in item
        and item.get("has_multi_season_content") not in (True, False)
    ):
        issues.append(f"{prefix}_has_multi_season_content_not_bool")

    for dict_key in ("poster_asset_urls", "poster_source_info", "manual_content"):
        if dict_key in item and not isinstance(item.get(dict_key), dict):
            issues.append(f"{prefix}_{dict_key}_not_object")
    if (
        "user_data" in item
        and item.get("user_data") is not None
        and not isinstance(item.get("user_data"), dict)
    ):
        issues.append(f"{prefix}_user_data_not_object")

    issues.extend(
        _dict_missing_keys(
            item.get("metadata_state"),
            EXPECTED_METADATA_STATE_KEYS,
            f"{prefix}_metadata_state",
        )
    )
    metadata_state = item.get("metadata_state")
    if isinstance(metadata_state, dict):
        if "issue_codes" in metadata_state and not isinstance(metadata_state.get("issue_codes"), list):
            issues.append(f"{prefix}_metadata_state_issue_codes_not_list")
        if "needs_attention" in metadata_state and metadata_state.get("needs_attention") not in (True, False):
            issues.append(f"{prefix}_metadata_state_needs_attention_not_bool")

    issues.extend(
        _dict_missing_keys(
            item.get("catalog_visibility"),
            EXPECTED_CATALOG_VISIBILITY_KEYS,
            f"{prefix}_catalog_visibility",
        )
    )
    return issues


def _movie_detail_issues(item: Any, expected_id: str) -> list[str]:
    if not isinstance(item, dict):
        return ["detail_not_object"]

    issues = _catalog_movie_item_issues(item, 0)
    missing = [key for key in EXPECTED_MOVIE_DETAIL_KEYS if key not in item]
    if missing:
        issues.append(f"detail_missing={','.join(missing)}")

    if item.get("id") != expected_id:
        issues.append(f"id_mismatch={item.get('id')}/{expected_id}")
    if "resources" in item:
        issues.append("resources_embedded")

    for nullable_str_key in (
        "original_title",
        "overview",
        "backdrop_url",
        "backdrop_asset_url",
        "director",
    ):
        if nullable_str_key in item and item.get(nullable_str_key) is not None:
            if not isinstance(item.get(nullable_str_key), str):
                issues.append(f"detail_{nullable_str_key}_not_str")

    for list_key in (
        "actors",
        "backdrop_asset_fallback_urls",
        "metadata_locked_fields",
        "metadata_issues",
    ):
        if list_key in item and not isinstance(item.get(list_key), list):
            issues.append(f"detail_{list_key}_not_list")

    for dict_key in (
        "backdrop_asset_urls",
        "backdrop_source_info",
        "metadata_actions",
        "metadata_diagnostics",
    ):
        if dict_key in item and not isinstance(item.get(dict_key), dict):
            issues.append(f"detail_{dict_key}_not_object")

    if isinstance(item.get("actors"), list):
        for index, actor in enumerate(item["actors"][:1]):
            prefix = f"actor_{index}"
            issues.extend(_dict_missing_keys(actor, ["name", "role", "avatar"], prefix))
            if isinstance(actor, dict):
                for key in ("name", "role", "avatar"):
                    if key in actor and not isinstance(actor.get(key), str):
                        issues.append(f"{prefix}_{key}_not_str")

    issues.extend(
        _dict_missing_keys(
            item.get("metadata_actions"),
            EXPECTED_METADATA_ACTION_KEYS,
            "detail_metadata_actions",
        )
    )
    return issues


def _movie_image_asset_urls_issues(data: Any, prefix: str, expected_kind: str = "") -> list[str]:
    if not isinstance(data, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_MOVIE_IMAGE_ASSET_URLS_KEYS, prefix))
    if expected_kind and data.get("kind") != expected_kind:
        issues.append(f"{prefix}_kind={data.get('kind')}")
    for key in ("kind", "strategy", "source"):
        if key in data and not isinstance(data.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in ("primary_url", "url", "cdn_url", "local_url", "original_url"):
        if key in data and data.get(key) is not None and not isinstance(data.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "fallback_urls" in data:
        fallback_urls = data.get("fallback_urls")
        if not isinstance(fallback_urls, list):
            issues.append(f"{prefix}_fallback_urls_not_list")
        elif not all(isinstance(url, str) for url in fallback_urls):
            issues.append(f"{prefix}_fallback_urls_not_str")
    return issues


def _movie_image_source_info_issues(data: Any, prefix: str, expected_kind: str = "") -> list[str]:
    if not isinstance(data, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_MOVIE_IMAGE_SOURCE_INFO_KEYS, prefix))
    if expected_kind and data.get("kind") != expected_kind:
        issues.append(f"{prefix}_kind={data.get('kind')}")
    for key in (
        "kind",
        "field",
        "public_field",
        "source_url",
        "source_type",
        "provider",
        "provider_label",
        "scraper_source",
        "metadata_source_group",
        "metadata_source_label",
        "confidence",
    ):
        if key in data and data.get(key) is not None and not isinstance(data.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in ("has_source", "locked"):
        if key in data and data.get(key) not in (True, False):
            issues.append(f"{prefix}_{key}_not_bool")
    if "evidence" in data:
        evidence = data.get("evidence")
        if not isinstance(evidence, list):
            issues.append(f"{prefix}_evidence_not_list")
        elif not all(isinstance(item, str) for item in evidence):
            issues.append(f"{prefix}_evidence_not_str")
    return issues


def _movie_image_status_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"image_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_MOVIE_IMAGE_STATUS_ITEM_KEYS, prefix))
    kind = item.get("kind")
    if "kind" in item and kind not in EXPECTED_MOVIE_IMAGE_KINDS:
        issues.append(f"{prefix}_kind={kind}")
    for key in ("asset_url", "source_url", "cache_state"):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in ("has_source", "source_valid", "cached", "source_changed"):
        if key in item and item.get(key) not in (True, False):
            issues.append(f"{prefix}_{key}_not_bool")
    if isinstance(item.get("cache_state"), str) and item.get("cache_state") not in EXPECTED_MOVIE_IMAGE_CACHE_STATES:
        issues.append(f"{prefix}_cache_state={item.get('cache_state')}")
    if "fallback_urls" in item:
        fallback_urls = item.get("fallback_urls")
        if not isinstance(fallback_urls, list):
            issues.append(f"{prefix}_fallback_urls_not_list")
        elif not all(isinstance(url, str) for url in fallback_urls):
            issues.append(f"{prefix}_fallback_urls_not_str")
    for nullable_dict_key in ("source_error", "cache", "cdn"):
        if (
            nullable_dict_key in item
            and item.get(nullable_dict_key) is not None
            and not isinstance(item.get(nullable_dict_key), dict)
        ):
            issues.append(f"{prefix}_{nullable_dict_key}_not_object")
    issues.extend(_movie_image_asset_urls_issues(
        item.get("asset_urls"),
        f"{prefix}_asset_urls",
        kind if isinstance(kind, str) else "",
    ))
    issues.extend(_movie_image_source_info_issues(
        item.get("source_info"),
        f"{prefix}_source_info",
        kind if isinstance(kind, str) else "",
    ))
    return issues


def _movie_images_status_payload_issues(data: Any, expected_movie_id: str) -> list[str]:
    if not isinstance(data, dict):
        return ["movie_images_status_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_MOVIE_IMAGE_STATUS_KEYS, "movie_images_status"))
    if data.get("movie_id") != expected_movie_id:
        issues.append(f"movie_images_status_movie_id={data.get('movie_id')}")
    if "title" in data and data.get("title") is not None and not isinstance(data.get("title"), str):
        issues.append("movie_images_status_title_not_str")

    items = data.get("items")
    if not isinstance(items, list):
        issues.append("movie_images_status_items_not_list")
        items = []
    item_kinds = {
        item.get("kind")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    missing_kinds = sorted(EXPECTED_MOVIE_IMAGE_KINDS - item_kinds)
    if missing_kinds:
        issues.append(f"movie_images_status_missing_kinds={','.join(missing_kinds)}")
    for index, item in enumerate(items):
        issues.extend(_movie_image_status_item_issues(item, index))

    summary = data.get("summary")
    issues.extend(_dict_missing_keys(summary, EXPECTED_MOVIE_IMAGE_STATUS_SUMMARY_KEYS, "image_summary"))
    if isinstance(summary, dict):
        for key in EXPECTED_MOVIE_IMAGE_STATUS_SUMMARY_KEYS:
            if key in summary and not _json_int(summary.get(key)):
                issues.append(f"image_summary_{key}_not_int")
        if summary.get("total") != len(items):
            issues.append(f"image_summary_total_mismatch={summary.get('total')}/{len(items)}")
    return issues


def check_movie_images_status(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "movie_images_status",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "movie_images_status",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/images/status")
    data = _response_data(payload)
    issues = _movie_images_status_payload_issues(data, movie_id)
    items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []
    summary = data.get("summary") if isinstance(data, dict) and isinstance(data.get("summary"), dict) else {}
    kinds = sorted({
        item.get("kind")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    })

    ok = not issues
    detail = (
        f"id={movie_id} kinds={','.join(kinds)} total={summary.get('total')} "
        f"cached={summary.get('cached')} missing={summary.get('missing')}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "movie_images_status",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "kinds": kinds,
            "summary": summary,
            "issues": issues,
        },
    )


def _movie_resource_cloud_transcode_issues(data: Any, prefix: str, resource_id: str | None = None) -> list[str]:
    if not isinstance(data, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_MOVIE_RESOURCE_CLOUD_TRANSCODE_KEYS, prefix))
    if "supported" in data and data.get("supported") not in (True, False):
        issues.append(f"{prefix}_supported_not_bool")
    for key in (
        "provider",
        "provider_name",
        "mode",
        "qualities_endpoint",
        "stream_endpoint",
        "resolution_param",
        "quality_semantics",
        "reason",
    ):
        if key in data and data.get(key) is not None and not isinstance(data.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "available_resolutions" in data:
        resolutions = data.get("available_resolutions")
        if not isinstance(resolutions, list):
            issues.append(f"{prefix}_available_resolutions_not_list")
        elif not all(isinstance(value, str) for value in resolutions):
            issues.append(f"{prefix}_available_resolutions_not_str")
    if "recommended_for" in data:
        recommended_for = data.get("recommended_for")
        if not isinstance(recommended_for, list):
            issues.append(f"{prefix}_recommended_for_not_list")
        elif not all(isinstance(value, str) for value in recommended_for):
            issues.append(f"{prefix}_recommended_for_not_str")
    if data.get("resolution_param") != "resolution":
        issues.append(f"{prefix}_resolution_param={data.get('resolution_param')}")

    supported = data.get("supported")
    qualities_endpoint = data.get("qualities_endpoint")
    stream_endpoint = data.get("stream_endpoint")
    reason = data.get("reason")
    if supported is True:
        if not isinstance(qualities_endpoint, str) or "/streaming-qualities" not in qualities_endpoint:
            issues.append(f"{prefix}_qualities_endpoint_invalid")
        if not isinstance(stream_endpoint, str) or "/stream-transcoded" not in stream_endpoint:
            issues.append(f"{prefix}_stream_endpoint_invalid")
        if resource_id:
            expected_qualities_path = f"/api/v1/resources/{resource_id}/streaming-qualities"
            expected_stream_path = f"/api/v1/resources/{resource_id}/stream-transcoded"
            if isinstance(qualities_endpoint, str) and expected_qualities_path not in qualities_endpoint:
                issues.append(f"{prefix}_qualities_endpoint_resource_mismatch")
            if isinstance(stream_endpoint, str) and expected_stream_path not in stream_endpoint:
                issues.append(f"{prefix}_stream_endpoint_resource_mismatch")
    elif supported is False:
        if not isinstance(reason, str) or not reason:
            issues.append(f"{prefix}_unsupported_reason_missing")
    return issues


def _movie_resource_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"resource_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_MOVIE_RESOURCE_ITEM_KEYS, prefix))
    resource_id = item.get("id")
    if "id" in item and not isinstance(resource_id, str):
        issues.append(f"{prefix}_id_not_str")

    resource_info = item.get("resource_info")
    issues.extend(_dict_missing_keys(resource_info, EXPECTED_MOVIE_RESOURCE_INFO_KEYS, f"{prefix}_resource_info"))
    if isinstance(resource_info, dict):
        for key in EXPECTED_MOVIE_RESOURCE_INFO_KEYS:
            if key in resource_info and not isinstance(resource_info.get(key), dict):
                issues.append(f"{prefix}_resource_info_{key}_not_object")
        file_info = resource_info.get("file") if isinstance(resource_info.get("file"), dict) else {}
        if "filename" in file_info and not isinstance(file_info.get("filename"), str):
            issues.append(f"{prefix}_file_filename_not_str")
        if "size_bytes" in file_info and file_info.get("size_bytes") is not None:
            if not _json_int(file_info.get("size_bytes")):
                issues.append(f"{prefix}_file_size_bytes_not_int")
        storage_source = file_info.get("storage_source")
        if "storage_source" in file_info and not isinstance(storage_source, dict):
            issues.append(f"{prefix}_file_storage_source_not_object")

    playback = item.get("playback")
    issues.extend(_dict_missing_keys(playback, EXPECTED_MOVIE_RESOURCE_PLAYBACK_KEYS, f"{prefix}_playback"))
    if isinstance(playback, dict):
        stream_url = playback.get("stream_url")
        if "stream_url" in playback and not isinstance(stream_url, str):
            issues.append(f"{prefix}_playback_stream_url_not_str")
        elif isinstance(resource_id, str) and isinstance(stream_url, str):
            expected_stream_path = f"/api/v1/resources/{resource_id}/stream"
            if expected_stream_path not in stream_url:
                issues.append(f"{prefix}_playback_stream_url_invalid")

        if "playback_modes" in playback and not isinstance(playback.get("playback_modes"), list):
            issues.append(f"{prefix}_playback_modes_not_list")
        if "range_supported" in playback and playback.get("range_supported") not in (True, False):
            issues.append(f"{prefix}_range_supported_not_bool")
        for dict_key in ("web_player", "external_player", "subtitles", "cloud_transcode"):
            if dict_key in playback and not isinstance(playback.get(dict_key), dict):
                issues.append(f"{prefix}_playback_{dict_key}_not_object")
        for bool_parent in ("web_player", "external_player"):
            parent = playback.get(bool_parent)
            if isinstance(parent, dict) and "supported" in parent and parent.get("supported") not in (True, False):
                issues.append(f"{prefix}_playback_{bool_parent}_supported_not_bool")
        if "cloud_transcode" in playback:
            issues.extend(_movie_resource_cloud_transcode_issues(
                playback.get("cloud_transcode"),
                f"{prefix}_playback_cloud_transcode",
                resource_id if isinstance(resource_id, str) else None,
            ))

    metadata = item.get("metadata")
    if "metadata" in item and not isinstance(metadata, dict):
        issues.append(f"{prefix}_metadata_not_object")
    elif isinstance(metadata, dict):
        for key in ("trace", "analysis", "edit_context"):
            if key in metadata and not isinstance(metadata.get(key), dict):
                issues.append(f"{prefix}_metadata_{key}_not_object")

    if "user_data" in item and item.get("user_data") is not None and not isinstance(item.get("user_data"), dict):
        issues.append(f"{prefix}_user_data_not_object")
    return issues


def _movie_playback_source_issues(
    item: Any,
    index: int,
    known_resource_ids: set[str],
) -> list[str]:
    prefix = f"playback_source_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_MOVIE_PLAYBACK_SOURCE_KEYS, prefix))
    if "id" in item and not isinstance(item.get("id"), str):
        issues.append(f"{prefix}_id_not_str")
    primary_resource_id = item.get("primary_resource_id")
    if "primary_resource_id" in item and not isinstance(primary_resource_id, str):
        issues.append(f"{prefix}_primary_resource_id_not_str")

    resource_ids = item.get("resource_ids")
    if not isinstance(resource_ids, list):
        issues.append(f"{prefix}_resource_ids_not_list")
        resource_ids = []
    elif not all(isinstance(resource_id, str) for resource_id in resource_ids):
        issues.append(f"{prefix}_resource_ids_not_str")

    alternate_resource_ids = item.get("alternate_resource_ids")
    if not isinstance(alternate_resource_ids, list):
        issues.append(f"{prefix}_alternate_resource_ids_not_list")
        alternate_resource_ids = []
    elif not all(isinstance(resource_id, str) for resource_id in alternate_resource_ids):
        issues.append(f"{prefix}_alternate_resource_ids_not_str")

    if "count" in item and not _json_int(item.get("count")):
        issues.append(f"{prefix}_count_not_int")
    elif item.get("count") != len(resource_ids):
        issues.append(f"{prefix}_count_mismatch={item.get('count')}/{len(resource_ids)}")
    if "is_duplicate_group" in item and item.get("is_duplicate_group") not in (True, False):
        issues.append(f"{prefix}_is_duplicate_group_not_bool")

    if isinstance(primary_resource_id, str) and primary_resource_id not in resource_ids:
        issues.append(f"{prefix}_primary_not_in_resource_ids")
    if known_resource_ids:
        unknown_ids = [resource_id for resource_id in resource_ids if resource_id not in known_resource_ids]
        if unknown_ids:
            issues.append(f"{prefix}_unknown_resource_ids={','.join(unknown_ids[:3])}")

    for dict_key in ("duplicate_key", "match", "display", "file"):
        if dict_key in item and not isinstance(item.get(dict_key), dict):
            issues.append(f"{prefix}_{dict_key}_not_object")
    source_summary = item.get("source_summary")
    if "source_summary" in item and not isinstance(source_summary, list):
        issues.append(f"{prefix}_source_summary_not_list")
    elif isinstance(source_summary, list):
        for source_index, source in enumerate(source_summary[:1]):
            source_prefix = f"{prefix}_source_{source_index}"
            if not isinstance(source, dict):
                issues.append(f"{source_prefix}_not_object")
            elif "id" in source and source.get("id") is not None and not _json_int(source.get("id")):
                issues.append(f"{source_prefix}_id_not_int")
    if "user_data" in item and item.get("user_data") is not None and not isinstance(item.get("user_data"), dict):
        issues.append(f"{prefix}_user_data_not_object")
    return issues


def _movie_resources_payload_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["resources_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_MOVIE_RESOURCES_KEYS, "resources"))

    items = data.get("items")
    if not isinstance(items, list):
        issues.append("items_not_list")
        items = []
    for index, item in enumerate(items[:1]):
        issues.extend(_movie_resource_item_issues(item, index))
    known_resource_ids = {
        item.get("id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    groups = data.get("groups")
    issues.extend(_dict_missing_keys(groups, EXPECTED_MOVIE_RESOURCES_GROUP_KEYS, "groups"))
    playback_sources = []
    if isinstance(groups, dict):
        standalone = groups.get("standalone")
        if not isinstance(standalone, dict):
            issues.append("groups_standalone_not_object")
        else:
            for key in ("resource_ids", "primary_resource_ids"):
                if key in standalone and not isinstance(standalone.get(key), list):
                    issues.append(f"groups_standalone_{key}_not_list")
            for key in ("count", "playback_source_count", "alternate_resource_count"):
                if key in standalone and not _json_int(standalone.get(key)):
                    issues.append(f"groups_standalone_{key}_not_int")
        if not isinstance(groups.get("seasons"), list):
            issues.append("groups_seasons_not_list")
        playback_sources = groups.get("playback_sources")
        if not isinstance(playback_sources, list):
            issues.append("groups_playback_sources_not_list")
            playback_sources = []
        for index, playback_source in enumerate(playback_sources[:1]):
            issues.extend(_movie_playback_source_issues(playback_source, index, known_resource_ids))

    summary = data.get("summary")
    issues.extend(_dict_missing_keys(summary, EXPECTED_MOVIE_RESOURCES_SUMMARY_KEYS, "summary"))
    if isinstance(summary, dict):
        for key in (
            "total_items",
            "hydrated_item_count",
            "playback_source_count",
            "hydrated_playback_source_count",
            "duplicate_group_count",
            "alternate_resource_count",
            "season_count",
            "standalone_count",
            "edited_items_count",
            "season_metadata_count",
        ):
            if key in summary and not _json_int(summary.get(key)):
                issues.append(f"summary_{key}_not_int")
        for key in ("has_placeholder_metadata", "is_local_only_metadata", "needs_attention"):
            if key in summary and summary.get(key) not in (True, False):
                issues.append(f"summary_{key}_not_bool")
        if "episode_diagnostics" in summary and not isinstance(summary.get("episode_diagnostics"), dict):
            issues.append("summary_episode_diagnostics_not_object")
        if "hydrated_item_count" in summary and summary.get("hydrated_item_count") != len(items):
            issues.append(f"summary_hydrated_item_count_mismatch={summary.get('hydrated_item_count')}/{len(items)}")
        if "total_items" in summary and _json_int(summary.get("total_items")) and summary["total_items"] > 0 and not items:
            issues.append("items_empty_with_total")
        if "hydrated_playback_source_count" in summary and summary.get("hydrated_playback_source_count") != len(playback_sources):
            issues.append(
                "summary_hydrated_playback_source_count_mismatch="
                f"{summary.get('hydrated_playback_source_count')}/{len(playback_sources)}"
            )
    return issues


def _season_episode_diagnostics_issues(data: Any, prefix: str) -> list[str]:
    if not isinstance(data, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_SEASON_EPISODE_DIAGNOSTICS_KEYS, prefix))
    for key in ("status", "coverage_status", "expected_source"):
        if key in data and data.get(key) is not None and not isinstance(data.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in ("available_episode_count", "expected_episode_count", "first_episode", "last_episode"):
        if key in data and data.get(key) is not None and not _json_int(data.get(key)):
            issues.append(f"{prefix}_{key}_not_int")
    if "completion_ratio" in data and data.get("completion_ratio") is not None:
        if not isinstance(data.get("completion_ratio"), (int, float)) or isinstance(data.get("completion_ratio"), bool):
            issues.append(f"{prefix}_completion_ratio_not_number")
    for key in (
        "issue_codes",
        "available_episode_numbers",
        "missing_episode_numbers",
        "duplicate_episode_numbers",
        "duplicate_episode_resources",
        "alternate_episode_numbers",
        "alternate_episode_resources",
        "unnumbered_resource_ids",
    ):
        if key in data and not isinstance(data.get(key), list):
            issues.append(f"{prefix}_{key}_not_list")
    return issues


def _movie_season_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"season_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_MOVIE_SEASON_ITEM_KEYS, prefix))
    if "season" in item and not _json_int(item.get("season")):
        issues.append(f"{prefix}_season_not_int")
    for key in ("title", "display_title", "overview", "air_date", "poster_url", "poster_source", "metadata_edited_at"):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in ("resource_ids", "primary_resource_ids"):
        values = item.get(key)
        if key in item and not isinstance(values, list):
            issues.append(f"{prefix}_{key}_not_list")
        elif isinstance(values, list) and not all(isinstance(value, str) for value in values):
            issues.append(f"{prefix}_{key}_not_str")
    resource_ids = item.get("resource_ids") if isinstance(item.get("resource_ids"), list) else []
    primary_resource_ids = item.get("primary_resource_ids") if isinstance(item.get("primary_resource_ids"), list) else []
    unknown_primary_ids = [
        resource_id
        for resource_id in primary_resource_ids
        if isinstance(resource_id, str) and resource_id not in resource_ids
    ]
    if unknown_primary_ids:
        issues.append(f"{prefix}_primary_resource_ids_unknown={','.join(unknown_primary_ids[:3])}")
    for key in ("playback_source_count", "alternate_resource_count", "edited_items_count", "episode_count"):
        if key in item and not _json_int(item.get(key)):
            issues.append(f"{prefix}_{key}_not_int")
    for key in ("tmdb_episode_count", "expected_episode_count", "aired_episode_count"):
        if key in item and item.get(key) is not None and not _json_int(item.get(key)):
            issues.append(f"{prefix}_{key}_not_int")
    for key in ("has_distinct_poster", "has_manual_metadata", "has_metadata"):
        if key in item and item.get(key) not in (True, False):
            issues.append(f"{prefix}_{key}_not_bool")
    if "playback_source_count" in item and _json_int(item.get("playback_source_count")):
        if item.get("playback_source_count") != len(primary_resource_ids):
            issues.append(f"{prefix}_playback_source_count_mismatch={item.get('playback_source_count')}/{len(primary_resource_ids)}")
    sort = item.get("sort")
    if "sort" in item:
        if not isinstance(sort, dict):
            issues.append(f"{prefix}_sort_not_object")
        else:
            if "season" in sort and not _json_int(sort.get("season")):
                issues.append(f"{prefix}_sort_season_not_int")
            if "first_episode" in sort and sort.get("first_episode") is not None and not _json_int(sort.get("first_episode")):
                issues.append(f"{prefix}_sort_first_episode_not_int")
    issues.extend(_season_episode_diagnostics_issues(item.get("episode_diagnostics"), f"{prefix}_episode_diagnostics"))
    if "user_data" in item and item.get("user_data") is not None and not isinstance(item.get("user_data"), dict):
        issues.append(f"{prefix}_user_data_not_object")
    return issues


def _movie_seasons_payload_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["movie_seasons_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_MOVIE_SEASONS_KEYS, "movie_seasons"))
    items = data.get("items")
    if not isinstance(items, list):
        issues.append("movie_seasons_items_not_list")
        items = []
    for index, item in enumerate(items[:1]):
        issues.extend(_movie_season_item_issues(item, index))

    summary = data.get("summary")
    issues.extend(_dict_missing_keys(summary, EXPECTED_MOVIE_RESOURCES_SUMMARY_KEYS, "season_summary"))
    if isinstance(summary, dict):
        for key in (
            "total_items",
            "hydrated_item_count",
            "playback_source_count",
            "hydrated_playback_source_count",
            "duplicate_group_count",
            "alternate_resource_count",
            "season_count",
            "standalone_count",
            "edited_items_count",
            "season_metadata_count",
        ):
            if key in summary and not _json_int(summary.get(key)):
                issues.append(f"season_summary_{key}_not_int")
        for key in ("has_placeholder_metadata", "is_local_only_metadata", "needs_attention"):
            if key in summary and summary.get(key) not in (True, False):
                issues.append(f"season_summary_{key}_not_bool")
        if "episode_diagnostics" in summary and not isinstance(summary.get("episode_diagnostics"), dict):
            issues.append("season_summary_episode_diagnostics_not_object")
        if "season_count" in summary and summary.get("season_count") != len(items):
            issues.append(f"season_summary_season_count_mismatch={summary.get('season_count')}/{len(items)}")
    return issues


def _movie_episode_diagnostics_season_issues(item: Any, index: int) -> list[str]:
    prefix = f"episode_diagnostics_season_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_MOVIE_EPISODE_DIAGNOSTICS_SEASON_KEYS, prefix))
    if "season" in item and not _json_int(item.get("season")):
        issues.append(f"{prefix}_season_not_int")
    for key in ("title", "display_title"):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "diagnostics" in item and not isinstance(item.get("diagnostics"), dict):
        issues.append(f"{prefix}_diagnostics_not_object")
    for key in ("affected_resource_ids", "affected_resources", "suggestions"):
        if key in item and not isinstance(item.get(key), list):
            issues.append(f"{prefix}_{key}_not_list")
    affected_ids = item.get("affected_resource_ids")
    if isinstance(affected_ids, list) and not all(isinstance(resource_id, str) for resource_id in affected_ids):
        issues.append(f"{prefix}_affected_resource_ids_not_str")
    return issues


def _movie_episode_diagnostics_payload_issues(data: Any, expected_movie_id: str) -> list[str]:
    if not isinstance(data, dict):
        return ["movie_episode_diagnostics_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_MOVIE_EPISODE_DIAGNOSTICS_KEYS, "movie_episode_diagnostics"))

    movie_id = data.get("movie_id")
    if "movie_id" in data and not isinstance(movie_id, str):
        issues.append("movie_episode_diagnostics_movie_id_not_str")
    elif expected_movie_id and movie_id != expected_movie_id:
        issues.append(f"movie_episode_diagnostics_movie_id={movie_id}")
    if "title" in data and not isinstance(data.get("title"), str):
        issues.append("movie_episode_diagnostics_title_not_str")
    if "dry_run" in data and data.get("dry_run") is not True:
        issues.append(f"movie_episode_diagnostics_dry_run={data.get('dry_run')}")
    if "apply_method" in data and data.get("apply_method") != "PATCH":
        issues.append(f"movie_episode_diagnostics_apply_method={data.get('apply_method')}")
    apply_endpoint = data.get("apply_endpoint")
    if "apply_endpoint" in data:
        expected_endpoint = f"/api/v1/movies/{expected_movie_id}/resources/metadata"
        if not isinstance(apply_endpoint, str):
            issues.append("movie_episode_diagnostics_apply_endpoint_not_str")
        elif expected_movie_id and apply_endpoint != expected_endpoint:
            issues.append(f"movie_episode_diagnostics_apply_endpoint={apply_endpoint}")

    apply_payload = data.get("apply_payload")
    if "apply_payload" in data:
        if not isinstance(apply_payload, dict):
            issues.append("movie_episode_diagnostics_apply_payload_not_object")
        elif not isinstance(apply_payload.get("items"), list):
            issues.append("movie_episode_diagnostics_apply_payload_items_not_list")

    summary = data.get("summary")
    issues.extend(_dict_missing_keys(summary, EXPECTED_MOVIE_EPISODE_DIAGNOSTICS_SUMMARY_KEYS, "episode_summary"))
    if isinstance(summary, dict):
        for key in ("status", "coverage_status"):
            if key in summary and not isinstance(summary.get(key), str):
                issues.append(f"episode_summary_{key}_not_str")
        for key in ("issue_count", "season_count"):
            if key in summary and not _json_int(summary.get(key)):
                issues.append(f"episode_summary_{key}_not_int")
        if "issue_code_counts" in summary and not isinstance(summary.get("issue_code_counts"), dict):
            issues.append("episode_summary_issue_code_counts_not_object")
        if "seasons_needing_attention" in summary and not isinstance(summary.get("seasons_needing_attention"), list):
            issues.append("episode_summary_seasons_needing_attention_not_list")

    seasons = data.get("seasons")
    if not isinstance(seasons, list):
        issues.append("movie_episode_diagnostics_seasons_not_list")
        seasons = []
    for index, item in enumerate(seasons[:1]):
        issues.extend(_movie_episode_diagnostics_season_issues(item, index))

    for key in ("suggested_updates", "warnings"):
        if key in data and not isinstance(data.get(key), list):
            issues.append(f"movie_episode_diagnostics_{key}_not_list")
    return issues


def _external_player_profile_issues(item: Any, index: int) -> list[str]:
    prefix = f"player_profile_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_EXTERNAL_PLAYER_PROFILE_KEYS, prefix))
    for key in ("key", "name"):
        if key in item and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in ("platforms", "handoff_methods"):
        if key in item and not isinstance(item.get(key), list):
            issues.append(f"{prefix}_{key}_not_list")
        elif isinstance(item.get(key), list) and not all(isinstance(value, str) for value in item.get(key)):
            issues.append(f"{prefix}_{key}_not_str")
    if "recommended" in item and item.get("recommended") not in (True, False):
        issues.append(f"{prefix}_recommended_not_bool")
    return issues


def _external_playback_manifest_issues(data: Any, expected_resource_id: str = "") -> list[str]:
    if not isinstance(data, dict):
        return ["external_playback_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_EXTERNAL_PLAYBACK_KEYS, "external_playback"))
    resource_id = data.get("resource_id")
    if "resource_id" in data and not isinstance(resource_id, str):
        issues.append("external_playback_resource_id_not_str")
    elif expected_resource_id and resource_id != expected_resource_id:
        issues.append(f"external_playback_resource_id={resource_id}")
    for key in ("movie_id", "title", "filename"):
        if key in data and data.get(key) is not None and not isinstance(data.get(key), str):
            issues.append(f"external_playback_{key}_not_str")

    resource_info = data.get("resource_info")
    issues.extend(_dict_missing_keys(resource_info, EXPECTED_MOVIE_RESOURCE_INFO_KEYS, "external_resource_info"))
    if isinstance(resource_info, dict):
        for key in EXPECTED_MOVIE_RESOURCE_INFO_KEYS:
            if key in resource_info and not isinstance(resource_info.get(key), dict):
                issues.append(f"external_resource_info_{key}_not_object")

    stream = data.get("stream")
    issues.extend(_dict_missing_keys(stream, EXPECTED_EXTERNAL_PLAYBACK_STREAM_KEYS, "external_stream"))
    if isinstance(stream, dict):
        for key in ("url", "mime_type", "storage_type", "default_mode", "url_type", "reason"):
            if key in stream and stream.get(key) is not None and not isinstance(stream.get(key), str):
                issues.append(f"external_stream_{key}_not_str")
        for key in ("range_supported", "requires_local_backend", "requires_user_agent_rewrite"):
            if key in stream and stream.get(key) not in (True, False):
                issues.append(f"external_stream_{key}_not_bool")
        if "playback_modes" in stream and not isinstance(stream.get("playback_modes"), list):
            issues.append("external_stream_playback_modes_not_list")
        elif isinstance(stream.get("playback_modes"), list) and not all(
            isinstance(mode, str) for mode in stream.get("playback_modes")
        ):
            issues.append("external_stream_playback_modes_not_str")
        stream_url = stream.get("url")
        if resource_id and isinstance(stream_url, str) and f"/api/v1/resources/{resource_id}/stream" not in stream_url:
            issues.append("external_stream_url_invalid")

    subtitles = data.get("subtitles")
    issues.extend(_dict_missing_keys(subtitles, EXPECTED_EXTERNAL_PLAYBACK_SUBTITLES_KEYS, "external_subtitles"))
    if isinstance(subtitles, dict):
        if "supported" in subtitles and subtitles.get("supported") not in (True, False):
            issues.append("external_subtitles_supported_not_bool")
        for key in ("default_subtitle_id", "default_url"):
            if key in subtitles and subtitles.get(key) is not None and not isinstance(subtitles.get(key), str):
                issues.append(f"external_subtitles_{key}_not_str")
        if "items" in subtitles and not isinstance(subtitles.get("items"), list):
            issues.append("external_subtitles_items_not_list")

    handoff = data.get("handoff")
    issues.extend(_dict_missing_keys(handoff, EXPECTED_EXTERNAL_PLAYBACK_HANDOFF_KEYS, "external_handoff"))
    if isinstance(handoff, dict):
        if "supported" in handoff and handoff.get("supported") not in (True, False):
            issues.append("external_handoff_supported_not_bool")
        for key in ("method", "manifest_url", "playlist_url", "playlist_format", "playlist_mime_type", "reason"):
            if key in handoff and handoff.get(key) is not None and not isinstance(handoff.get(key), str):
                issues.append(f"external_handoff_{key}_not_str")
        if handoff.get("method") != "http_stream":
            issues.append(f"external_handoff_method={handoff.get('method')}")
        if handoff.get("playlist_format") != "m3u":
            issues.append(f"external_handoff_playlist_format={handoff.get('playlist_format')}")
        if handoff.get("playlist_mime_type") != "audio/x-mpegurl":
            issues.append(f"external_handoff_playlist_mime_type={handoff.get('playlist_mime_type')}")
        manifest_url = handoff.get("manifest_url")
        playlist_url = handoff.get("playlist_url")
        if resource_id and isinstance(manifest_url, str) and f"/api/v1/resources/{resource_id}/external-playback" not in manifest_url:
            issues.append("external_handoff_manifest_url_invalid")
        if resource_id and isinstance(playlist_url, str):
            expected_path = f"/api/v1/resources/{resource_id}/external-playback"
            if expected_path not in playlist_url or "format=m3u" not in playlist_url:
                issues.append("external_handoff_playlist_url_invalid")
        if handoff.get("supported") is True and isinstance(stream, dict) and not stream.get("url"):
            issues.append("external_handoff_supported_without_stream_url")
        if handoff.get("supported") is False and not handoff.get("reason"):
            issues.append("external_handoff_unsupported_without_reason")

    profiles = data.get("player_profiles")
    if not isinstance(profiles, list):
        issues.append("external_player_profiles_not_list")
        profiles = []
    elif not profiles:
        issues.append("external_player_profiles_empty")
    else:
        for index, item in enumerate(profiles[:4]):
            issues.extend(_external_player_profile_issues(item, index))
        profile_keys = {item.get("key") for item in profiles if isinstance(item, dict)}
        if "vlc" not in profile_keys:
            issues.append("external_player_profiles_missing_vlc")

    warnings = data.get("warnings")
    if "warnings" in data and not isinstance(warnings, list):
        issues.append("external_warnings_not_list")
    return issues


def _subtitle_settings_payload_issues(data: Any, expected_resource_id: str = "") -> list[str]:
    if not isinstance(data, dict):
        return ["subtitle_settings_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_SUBTITLE_SETTINGS_KEYS, "subtitle_settings"))
    resource_id = data.get("resource_id")
    if "resource_id" in data and not isinstance(resource_id, str):
        issues.append("subtitle_settings_resource_id_not_str")
    elif expected_resource_id and resource_id != expected_resource_id:
        issues.append(f"subtitle_settings_resource_id={resource_id}")

    if "customized" in data and data.get("customized") not in (True, False):
        issues.append("subtitle_settings_customized_not_bool")
    if "source" in data and data.get("source") not in {"default", "resource", "user"}:
        issues.append(f"subtitle_settings_source={data.get('source')}")
    if "updated_at" in data and data.get("updated_at") is not None and not isinstance(data.get("updated_at"), str):
        issues.append("subtitle_settings_updated_at_not_str")
    if data.get("customized") is False and data.get("source") != "default":
        issues.append(f"subtitle_settings_default_source={data.get('source')}")
    if data.get("customized") is True and data.get("source") == "default":
        issues.append("subtitle_settings_customized_default_source")

    settings = data.get("settings")
    issues.extend(_dict_missing_keys(settings, EXPECTED_SUBTITLE_DISPLAY_SETTING_KEYS, "subtitle_display"))
    if isinstance(settings, dict):
        for key, (minimum, maximum) in SUBTITLE_NUMERIC_RANGES.items():
            value = settings.get(key)
            if key in settings and not _json_int(value):
                issues.append(f"subtitle_display_{key}_not_int")
            elif key in settings and (value < minimum or value > maximum):
                issues.append(f"subtitle_display_{key}_out_of_range={value}")
        for key in ("zhColor", "enColor"):
            value = settings.get(key)
            if key in settings and not isinstance(value, str):
                issues.append(f"subtitle_display_{key}_not_str")
            elif key in settings:
                raw = value.strip()
                hex_digits = raw[1:] if raw.startswith("#") else ""
                if len(hex_digits) not in {3, 6, 8} or not all(
                    char in "0123456789abcdefABCDEF" for char in hex_digits
                ):
                    issues.append(f"subtitle_display_{key}_invalid")
    return issues


def _audio_transcode_diagnostic_item_issues(item: Any, index: int, expected_resource_id: str = "") -> list[str]:
    prefix = f"audio_diagnostic_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    for key in ("diagnostic_id", "resource_id", "session_id", "status", "started_at", "finished_at", "close_reason"):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if expected_resource_id and item.get("resource_id") != expected_resource_id:
        issues.append(f"{prefix}_resource_id={item.get('resource_id')}")
    if "active" in item and item.get("active") not in (True, False):
        issues.append(f"{prefix}_active_not_bool")
    for key in ("input", "options", "counters", "timings"):
        if key in item and not isinstance(item.get(key), dict):
            issues.append(f"{prefix}_{key}_not_object")
    events = item.get("events")
    if "events" in item and not isinstance(events, list):
        issues.append(f"{prefix}_events_not_list")
    elif isinstance(events, list):
        for event_index, event in enumerate(events[:1]):
            if not isinstance(event, dict):
                issues.append(f"{prefix}_event_{event_index}_not_object")
            elif "type" in event and not isinstance(event.get("type"), str):
                issues.append(f"{prefix}_event_{event_index}_type_not_str")
    return issues


def _audio_transcode_diagnostics_payload_issues(data: Any, expected_resource_id: str = "") -> list[str]:
    if not isinstance(data, dict):
        return ["audio_diagnostics_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_AUDIO_TRANSCODE_DIAGNOSTICS_KEYS, "audio_diagnostics"))
    resource_id = data.get("resource_id")
    if "resource_id" in data and not isinstance(resource_id, str):
        issues.append("audio_diagnostics_resource_id_not_str")
    elif expected_resource_id and resource_id != expected_resource_id:
        issues.append(f"audio_diagnostics_resource_id={resource_id}")
    if "session_id" in data and data.get("session_id") is not None and not isinstance(data.get("session_id"), str):
        issues.append("audio_diagnostics_session_id_not_str")
    active_count = data.get("active_count")
    if "active_count" in data and not _json_int(active_count):
        issues.append("audio_diagnostics_active_count_not_int")
    elif _json_int(active_count) and active_count < 0:
        issues.append("audio_diagnostics_active_count_negative")

    items = data.get("items")
    if not isinstance(items, list):
        issues.append("audio_diagnostics_items_not_list")
        items = []
    else:
        for index, item in enumerate(items[:2]):
            issues.extend(_audio_transcode_diagnostic_item_issues(item, index, expected_resource_id))
    if _json_int(active_count):
        actual_active = sum(1 for item in items if isinstance(item, dict) and item.get("active") is True)
        if active_count != actual_active:
            issues.append(f"audio_diagnostics_active_count_mismatch={active_count}/{actual_active}")
    return issues


def _catalog_filter_option_issues(item: Any, index: int, kind: str) -> list[str]:
    prefix = f"{kind}_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    if kind == "years":
        expected_keys = ["year", "count"]
    elif kind == "countries":
        expected_keys = ["name", "code", "count"]
    else:
        expected_keys = ["name", "slug", "count"]

    issues = _dict_missing_keys(item, expected_keys, prefix)
    if kind == "years":
        if "year" in item and not _json_int(item.get("year")):
            issues.append(f"{prefix}_year_not_int")
    else:
        for key in ("name", "slug" if kind == "genres" else "code"):
            if key in item and not isinstance(item.get(key), str):
                issues.append(f"{prefix}_{key}_not_str")
    if "count" in item:
        count = item.get("count")
        if not _json_int(count):
            issues.append(f"{prefix}_count_not_int")
        elif count < 0:
            issues.append(f"{prefix}_count_negative")
    return issues


def _catalog_filters_payload_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["filters_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_CATALOG_FILTER_KEYS, "filters"))
    for key in EXPECTED_CATALOG_FILTER_KEYS:
        items = data.get(key)
        if not isinstance(items, list):
            issues.append(f"{key}_not_list")
            continue
        for index, item in enumerate(items[:3]):
            issues.extend(_catalog_filter_option_issues(item, index, key))
    return issues


def _library_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"library_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_LIBRARY_KEYS, prefix))
    library_id = item.get("id")
    if "id" in item and not _json_int(library_id):
        issues.append(f"{prefix}_id_not_int")
    for key in ("name", "slug", "description", "created_at", "updated_at"):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "slug" in item and item.get("slug") == "favorites":
        issues.append(f"{prefix}_virtual_favorites_in_list")
    if "id" in item and item.get("id") == "favorites":
        issues.append(f"{prefix}_virtual_favorites_id_in_list")
    if "is_virtual" in item and item.get("is_virtual") is True:
        issues.append(f"{prefix}_virtual_in_list")
    if "kind" in item and item.get("kind") == "favorites":
        issues.append(f"{prefix}_favorites_kind_in_list")
    if "is_enabled" in item and item.get("is_enabled") not in (True, False):
        issues.append(f"{prefix}_is_enabled_not_bool")
    if "sort_order" in item and not _json_int(item.get("sort_order")):
        issues.append(f"{prefix}_sort_order_not_int")
    if "settings" in item and not isinstance(item.get("settings"), dict):
        issues.append(f"{prefix}_settings_not_object")
    return issues


def _system_update_download_issues(download: Any, prefix: str) -> list[str]:
    if not isinstance(download, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(download, EXPECTED_SYSTEM_UPDATE_DOWNLOAD_KEYS, prefix))
    for key in ("platform", "arch", "url", "variant", "name", "sha256", "content_type", "label", "notes"):
        if key in download and download.get(key) is not None and not isinstance(download.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "variant" in download and download.get("variant") is not None and download.get("variant") not in {"lite", "full"}:
        issues.append(f"{prefix}_variant={download.get('variant')}")
    if "cdn" in download and download.get("cdn") is not True:
        issues.append(f"{prefix}_cdn_not_true")
    if "url" in download and isinstance(download.get("url"), str):
        if not download["url"].startswith(("https://", "http://")):
            issues.append(f"{prefix}_url_not_http")
    if "size" in download and download.get("size") is not None:
        if not _json_int(download.get("size")):
            issues.append(f"{prefix}_size_not_int")
        elif download.get("size") < 0:
            issues.append(f"{prefix}_size_negative")
    return issues


def _system_update_check_issues(data: Any, expected_backend_version: str = "") -> list[str]:
    if not isinstance(data, dict):
        return ["update_check_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_SYSTEM_UPDATE_KEYS, "update_check"))
    for key in ("product", "channel", "platform", "arch", "source", "checked_at", "variant"):
        if key in data and data.get(key) is not None and not isinstance(data.get(key), str):
            issues.append(f"update_check_{key}_not_str")
    if "variant" in data and data.get("variant") is not None and data.get("variant") not in {"lite", "full"}:
        issues.append(f"update_check_variant={data.get('variant')}")
    if "source" in data and data.get("source") not in {"manifest", "source_tree"}:
        issues.append(f"update_check_source={data.get('source')}")
    if "update_available" in data and data.get("update_available") not in (True, False):
        issues.append("update_check_update_available_not_bool")

    current = data.get("current")
    issues.extend(_dict_missing_keys(current, EXPECTED_SYSTEM_UPDATE_CURRENT_KEYS, "update_current"))
    if isinstance(current, dict):
        for key in EXPECTED_SYSTEM_UPDATE_CURRENT_KEYS:
            if key in current and current.get(key) is not None and not isinstance(current.get(key), str):
                issues.append(f"update_current_{key}_not_str")
        if expected_backend_version and current.get("backend_version") != expected_backend_version:
            issues.append(f"update_current_backend_version={current.get('backend_version')}")

    latest = data.get("latest")
    issues.extend(_dict_missing_keys(latest, EXPECTED_SYSTEM_UPDATE_LATEST_KEYS, "update_latest"))
    if isinstance(latest, dict):
        for key in (
            "version",
            "release",
            "tag",
            "title",
            "released_at",
            "notes",
            "notes_url",
            "release_page_url",
            "minimum_supported_version",
        ):
            if key in latest and latest.get(key) is not None and not isinstance(latest.get(key), str):
                issues.append(f"update_latest_{key}_not_str")
        if "mandatory" in latest and latest.get("mandatory") not in (True, False):
            issues.append("update_latest_mandatory_not_bool")

    cdn = data.get("cdn")
    issues.extend(_dict_missing_keys(cdn, EXPECTED_SYSTEM_UPDATE_CDN_KEYS, "update_cdn"))
    if isinstance(cdn, dict):
        for key in EXPECTED_SYSTEM_UPDATE_CDN_KEYS:
            if key in cdn and cdn.get(key) not in (True, False):
                issues.append(f"update_cdn_{key}_not_bool")

    downloads = data.get("downloads")
    if not isinstance(downloads, list):
        issues.append("update_downloads_not_list")
        downloads = []
    else:
        for index, download in enumerate(downloads[:3]):
            issues.extend(_system_update_download_issues(download, f"update_download_{index}"))

    selected_download = data.get("selected_download")
    if selected_download is not None:
        issues.extend(_system_update_download_issues(selected_download, "update_selected_download"))
        selected_url = selected_download.get("url") if isinstance(selected_download, dict) else None
        download_urls = {
            item.get("url")
            for item in downloads
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        }
        if selected_url not in download_urls:
            issues.append("update_selected_download_not_in_downloads")

    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        issues.append("update_warnings_not_list")
    else:
        invalid_warnings = [warning for warning in warnings if not isinstance(warning, str)]
        if invalid_warnings:
            issues.append("update_warnings_not_str")
    return issues


def _endpoint_action_issues(action: Any, prefix: str, method: str, endpoint: str | None = None) -> list[str]:
    if not isinstance(action, dict):
        return [f"{prefix}_not_object"]

    issues = []
    if action.get("method") != method:
        issues.append(f"{prefix}_method={action.get('method')}")
    if "endpoint" not in action:
        issues.append(f"{prefix}_missing=endpoint")
    elif not isinstance(action.get("endpoint"), str):
        issues.append(f"{prefix}_endpoint_not_str")
    elif endpoint is not None and action.get("endpoint") != endpoint:
        issues.append(f"{prefix}_endpoint={action.get('endpoint')}")
    return issues


def _other_video_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"other_video_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_OTHER_VIDEO_ITEM_KEYS, prefix))

    if "resource_id" in item and not isinstance(item.get("resource_id"), str):
        issues.append(f"{prefix}_resource_id_not_str")
    if "movie_id" in item and item.get("movie_id") is not None and not isinstance(item.get("movie_id"), str):
        issues.append(f"{prefix}_movie_id_not_str")
    for key in ("movie_title", "movie_original_title", "recommended_resolution"):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "movie_year" in item and item.get("movie_year") is not None and not _json_int(item.get("movie_year")):
        issues.append(f"{prefix}_movie_year_not_int")

    for dict_key in (
        "movie_manual_content",
        "resource_info",
        "playback",
        "metadata",
        "catalog_visibility",
        "metadata_state",
        "metadata_actions",
        "metadata_match_context",
        "actions",
    ):
        if dict_key in item and item.get(dict_key) is not None and not isinstance(item.get(dict_key), dict):
            issues.append(f"{prefix}_{dict_key}_not_object")
    if "metadata_issues" in item and not isinstance(item.get("metadata_issues"), list):
        issues.append(f"{prefix}_metadata_issues_not_list")

    resource_info = item.get("resource_info")
    issues.extend(_dict_missing_keys(resource_info, EXPECTED_MOVIE_RESOURCE_INFO_KEYS, f"{prefix}_resource_info"))
    if isinstance(resource_info, dict):
        for key in EXPECTED_MOVIE_RESOURCE_INFO_KEYS:
            if key in resource_info and not isinstance(resource_info.get(key), dict):
                issues.append(f"{prefix}_resource_info_{key}_not_object")

    playback = item.get("playback")
    issues.extend(_dict_missing_keys(playback, EXPECTED_MOVIE_RESOURCE_PLAYBACK_KEYS, f"{prefix}_playback"))
    if isinstance(playback, dict):
        for key in ("web_player", "external_player", "subtitles", "cloud_transcode"):
            if key in playback and not isinstance(playback.get(key), dict):
                issues.append(f"{prefix}_playback_{key}_not_object")
        if "cloud_transcode" in playback:
            issues.extend(_movie_resource_cloud_transcode_issues(
                playback.get("cloud_transcode"),
                f"{prefix}_playback_cloud_transcode",
                item.get("resource_id") if isinstance(item.get("resource_id"), str) else None,
            ))

    match_context = item.get("metadata_match_context")
    issues.extend(_dict_missing_keys(match_context, EXPECTED_OTHER_VIDEO_MATCH_CONTEXT_KEYS, f"{prefix}_match_context"))
    if isinstance(match_context, dict):
        for key in ("suggested_query", "suggested_media_type_hint", "source_media_type_hint", "title_hint_source"):
            if key in match_context and match_context.get(key) is not None and not isinstance(match_context.get(key), str):
                issues.append(f"{prefix}_match_context_{key}_not_str")
        if "suggested_year" in match_context and match_context.get("suggested_year") is not None:
            if not _json_int(match_context.get("suggested_year")):
                issues.append(f"{prefix}_match_context_suggested_year_not_int")
        media_type_options = match_context.get("media_type_options")
        if not isinstance(media_type_options, list):
            issues.append(f"{prefix}_match_context_media_type_options_not_list")
        elif not all(isinstance(option, str) for option in media_type_options):
            issues.append(f"{prefix}_match_context_media_type_options_not_str")
        elif not {"movie", "tv"}.issubset(set(media_type_options)):
            issues.append(f"{prefix}_match_context_media_type_options={media_type_options}")

    actions = item.get("actions")
    if isinstance(actions, dict):
        create_action = actions.get("create_manual_movie")
        issues.extend(_endpoint_action_issues(
            create_action,
            f"{prefix}_action_create_manual_movie",
            "POST",
            "/api/v1/movies/manual",
        ))
        create_body = create_action.get("body") if isinstance(create_action, dict) else None
        if not isinstance(create_body, dict):
            issues.append(f"{prefix}_action_create_manual_movie_body_not_object")
        elif "resource_ids" not in create_body:
            issues.append(f"{prefix}_action_create_manual_movie_body_missing=resource_ids")
        elif not isinstance(create_body.get("resource_ids"), list):
            issues.append(f"{prefix}_action_create_manual_movie_resource_ids_not_list")
        elif item.get("resource_id") not in create_body.get("resource_ids"):
            issues.append(f"{prefix}_action_create_manual_movie_resource_id_missing")

        match_actions = actions.get("match_metadata")
        if item.get("movie_id") is not None:
            if not isinstance(match_actions, dict):
                issues.append(f"{prefix}_action_match_metadata_not_object")
            else:
                movie_endpoint_prefix = f"/api/v1/movies/{item.get('movie_id')}/metadata"
                issues.extend(_endpoint_action_issues(
                    match_actions.get("search"),
                    f"{prefix}_action_match_metadata_search",
                    "GET",
                    f"{movie_endpoint_prefix}/search",
                ))
                for action_key in ("preview", "apply"):
                    action = match_actions.get(action_key)
                    issues.extend(_endpoint_action_issues(
                        action,
                        f"{prefix}_action_match_metadata_{action_key}",
                        "POST",
                        f"{movie_endpoint_prefix}/match",
                    ))
                    body_template = action.get("body_template") if isinstance(action, dict) else None
                    if not isinstance(body_template, dict):
                        issues.append(f"{prefix}_action_match_metadata_{action_key}_body_template_not_object")
                apply_template = match_actions.get("apply", {}).get("body_template") if isinstance(match_actions.get("apply"), dict) else {}
                if isinstance(apply_template, dict) and apply_template.get("apply") is not True:
                    issues.append(f"{prefix}_action_match_metadata_apply_missing_apply_true")
    return issues


def _other_videos_payload_issues(data: Any, expected_page_size: int = 1) -> list[str]:
    if not isinstance(data, dict):
        return ["other_videos_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_OTHER_VIDEOS_KEYS, "other_videos"))

    items = data.get("items")
    if not isinstance(items, list):
        issues.append("other_videos_items_not_list")
        items = []
    for index, item in enumerate(items[:1]):
        issues.extend(_other_video_item_issues(item, index))

    pagination = data.get("pagination")
    issues.extend(_pagination_contract_issues(pagination, expected_page_size=expected_page_size))
    if isinstance(pagination, dict):
        total_items = pagination.get("total_items")
        if _json_int(total_items) and total_items > 0 and not items:
            issues.append("other_videos_items_empty_with_total")
        if _json_int(total_items) and "summary" in data and isinstance(data.get("summary"), dict):
            if data["summary"].get("total_items") != total_items:
                issues.append(f"other_videos_summary_total_mismatch={data['summary'].get('total_items')}/{total_items}")

    summary = data.get("summary")
    issues.extend(_dict_missing_keys(summary, EXPECTED_OTHER_VIDEOS_SUMMARY_KEYS, "other_videos_summary"))
    if isinstance(summary, dict):
        for key in EXPECTED_OTHER_VIDEOS_SUMMARY_KEYS:
            if key in summary and not _json_int(summary.get(key)):
                issues.append(f"other_videos_summary_{key}_not_int")
        if _json_int(summary.get("manual_movie_count")) and summary.get("manual_movie_count") < 0:
            issues.append("other_videos_summary_manual_movie_count_negative")

    actions = data.get("actions")
    if not isinstance(actions, dict):
        issues.append("other_videos_actions_not_object")
    else:
        issues.extend(_endpoint_action_issues(
            actions.get("create_manual_movie"),
            "other_videos_action_create_manual_movie",
            "POST",
            "/api/v1/movies/manual",
        ))
        issues.extend(_endpoint_action_issues(
            actions.get("attach_resources"),
            "other_videos_action_attach_resources",
            "POST",
            "/api/v1/movies/{movie_id}/resources/attach",
        ))
    return issues


def _homepage_config_section_issues(section: Any, index: int) -> list[str]:
    prefix = f"config_section_{index}"
    if not isinstance(section, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(section, EXPECTED_HOMEPAGE_CONFIG_SECTION_KEYS, prefix))
    for key in ("key", "title", "genre", "mode"):
        if key in section and not isinstance(section.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "mode" in section and section.get("mode") not in {"custom", "latest"}:
        issues.append(f"{prefix}_mode={section.get('mode')}")
    if "limit" in section:
        limit = section.get("limit")
        if not _json_int(limit):
            issues.append(f"{prefix}_limit_not_int")
        elif limit < 1 or limit > 20:
            issues.append(f"{prefix}_limit_out_of_range={limit}")
    movie_ids = section.get("movie_ids")
    if "movie_ids" in section and not isinstance(movie_ids, list):
        issues.append(f"{prefix}_movie_ids_not_list")
    elif isinstance(movie_ids, list):
        invalid_movie_ids = [value for value in movie_ids if not isinstance(value, str) or not value]
        if invalid_movie_ids:
            issues.append(f"{prefix}_movie_ids_invalid")
    if "enabled" in section and section.get("enabled") not in (True, False):
        issues.append(f"{prefix}_enabled_not_bool")
    if "sort_order" in section and not _json_int(section.get("sort_order")):
        issues.append(f"{prefix}_sort_order_not_int")
    return issues


def _homepage_config_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["homepage_config_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_HOMEPAGE_CONFIG_KEYS, "homepage_config"))
    hero_movie_id = data.get("hero_movie_id")
    if "hero_movie_id" in data and hero_movie_id is not None and not isinstance(hero_movie_id, str):
        issues.append("homepage_config_hero_movie_id_not_str")
    for key in ("created_at", "updated_at"):
        if key in data and data.get(key) is not None and not isinstance(data.get(key), str):
            issues.append(f"homepage_config_{key}_not_str")

    sections = data.get("sections")
    if not isinstance(sections, list):
        issues.append("homepage_config_sections_not_list")
    else:
        for index, section in enumerate(sections[:10]):
            issues.extend(_homepage_config_section_issues(section, index))
    return issues


def _homepage_section_issues(
    section: Any,
    index: int,
    seen_movie_ids: set[str],
) -> list[str]:
    prefix = f"section_{index}"
    if not isinstance(section, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(section, EXPECTED_HOMEPAGE_SECTION_KEYS, prefix))
    for key in ("key", "title", "genre", "mode"):
        if key in section and not isinstance(section.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if section.get("mode") not in {"custom", "latest"}:
        issues.append(f"{prefix}_mode={section.get('mode')}")
    limit = section.get("limit")
    if "limit" in section and not _json_int(limit):
        issues.append(f"{prefix}_limit_not_int")

    items = section.get("items")
    if not isinstance(items, list):
        issues.append(f"{prefix}_items_not_list")
        return issues
    if _json_int(limit) and len(items) > limit:
        issues.append(f"{prefix}_items_above_limit={len(items)}/{limit}")

    for item_index, item in enumerate(items[:1]):
        issues.extend(_catalog_movie_item_issues(item, item_index))
        if isinstance(item, dict):
            movie_id = item.get("id")
            if isinstance(movie_id, str):
                if movie_id in seen_movie_ids:
                    issues.append(f"{prefix}_duplicate_movie_id={movie_id}")
                seen_movie_ids.add(movie_id)
            if item.get("season_cards") not in (None, []):
                issues.append(f"{prefix}_item_{item_index}_season_cards_not_empty")
    for item in items[1:]:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            movie_id = item["id"]
            if movie_id in seen_movie_ids:
                issues.append(f"{prefix}_duplicate_movie_id={movie_id}")
            seen_movie_ids.add(movie_id)
    return issues


def _homepage_payload_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["homepage_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_HOMEPAGE_KEYS, "homepage"))
    seen_movie_ids = set()

    hero = data.get("hero")
    issues.extend(_dict_missing_keys(hero, EXPECTED_HOMEPAGE_HERO_KEYS, "hero"))
    if isinstance(hero, dict):
        mode = hero.get("mode")
        if mode is not None and mode not in {"custom", "latest"}:
            issues.append(f"hero_mode={mode}")
        movie = hero.get("movie")
        if movie is not None:
            if not isinstance(movie, dict):
                issues.append("hero_movie_not_object")
            else:
                movie_id = movie.get("id")
                if isinstance(movie_id, str):
                    seen_movie_ids.add(movie_id)
                    issues.extend(_movie_detail_issues(movie, movie_id))
                else:
                    issues.append(f"hero_movie_id_invalid={movie_id}")

    sections = data.get("sections")
    if not isinstance(sections, list):
        issues.append("sections_not_list")
    else:
        for index, section in enumerate(sections[:5]):
            issues.extend(_homepage_section_issues(section, index, seen_movie_ids))
    return issues


def _recommendation_reason_issues(reason: Any, prefix: str) -> list[str]:
    if not isinstance(reason, dict):
        return [f"{prefix}_not_object"]

    issues = _dict_missing_keys(reason, EXPECTED_RECOMMENDATION_REASON_KEYS, prefix)
    for key in ("code", "label", "detail"):
        if key in reason and reason.get(key) is not None and not isinstance(reason.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "weight" in reason:
        weight = reason.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            issues.append(f"{prefix}_weight_not_number")
    return issues


def _recommendation_issues(value: Any, index: int, expected_strategy: str) -> list[str]:
    prefix = f"item_{index}_recommendation"
    if not isinstance(value, dict):
        return [f"{prefix}_not_object"]

    issues = _dict_missing_keys(value, EXPECTED_RECOMMENDATION_KEYS, prefix)
    if "strategy" in value and value.get("strategy") != expected_strategy:
        issues.append(f"{prefix}_strategy={value.get('strategy')}")
    if "rank" in value and not _json_int(value.get("rank")):
        issues.append(f"{prefix}_rank_not_int")
    if "rank" in value and _json_int(value.get("rank")) and value.get("rank") < 1:
        issues.append(f"{prefix}_rank_below_one")
    if "score" in value:
        score = value.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            issues.append(f"{prefix}_score_not_number")
    if "reason_text" in value and not isinstance(value.get("reason_text"), str):
        issues.append(f"{prefix}_reason_text_not_str")

    issues.extend(_recommendation_reason_issues(value.get("primary_reason"), f"{prefix}_primary_reason"))

    reasons = value.get("reasons")
    if not isinstance(reasons, list):
        issues.append(f"{prefix}_reasons_not_list")
    elif not reasons:
        issues.append(f"{prefix}_reasons_empty")
    else:
        for reason_index, reason in enumerate(reasons[:1]):
            issues.extend(_recommendation_reason_issues(reason, f"{prefix}_reason_{reason_index}"))

    signals = value.get("signals")
    issues.extend(_dict_missing_keys(signals, EXPECTED_RECOMMENDATION_SIGNAL_KEYS, f"{prefix}_signals"))
    if isinstance(signals, dict):
        progress_ratio = signals.get("progress_ratio")
        if "progress_ratio" in signals and (
            not isinstance(progress_ratio, (int, float)) or isinstance(progress_ratio, bool)
        ):
            issues.append(f"{prefix}_signals_progress_ratio_not_number")
        if "quality_badge" in signals and signals.get("quality_badge") is not None:
            if not isinstance(signals.get("quality_badge"), str):
                issues.append(f"{prefix}_signals_quality_badge_not_str")
        if "resource_count" in signals and not _json_int(signals.get("resource_count")):
            issues.append(f"{prefix}_signals_resource_count_not_int")
    return issues


def _recommendation_item_issues(item: Any, index: int, expected_strategy: str) -> list[str]:
    issues = _catalog_movie_item_issues(item, index)
    if not isinstance(item, dict):
        return issues
    if "recommendation" not in item:
        issues.append(f"item_{index}_missing=recommendation")
    else:
        issues.extend(_recommendation_issues(item.get("recommendation"), index, expected_strategy))
    return issues


def _user_history_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"history_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_USER_HISTORY_KEYS, prefix))
    if "is_played" in item:
        issues.append(f"{prefix}_has_is_played")
    for key in ("id", "progress", "duration", "position_sec", "duration_sec", "view_count"):
        if key in item and not _json_int(item.get(key)):
            issues.append(f"{prefix}_{key}_not_int")
    for key in (
        "resource_id",
        "last_played_at",
        "last_watched",
        "device_id",
        "device_name",
        "filename",
        "label",
        "episode_label",
        "poster_url",
        "poster_source",
        "season_poster_url",
        "series_poster_url",
        "season_title",
        "season_display_title",
    ):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in ("season", "episode"):
        if key in item and item.get(key) is not None and not _json_int(item.get(key)):
            issues.append(f"{prefix}_{key}_not_int")
    for key in ("progress_ratio", "progress_percent"):
        if key in item and item.get(key) is not None:
            value = item.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                issues.append(f"{prefix}_{key}_not_number")
    if (
        _json_int(item.get("progress"))
        and _json_int(item.get("position_sec"))
        and item.get("progress") != item.get("position_sec")
    ):
        issues.append(f"{prefix}_progress_position_mismatch={item.get('progress')}/{item.get('position_sec')}")
    if (
        _json_int(item.get("duration"))
        and _json_int(item.get("duration_sec"))
        and item.get("duration") != item.get("duration_sec")
    ):
        issues.append(f"{prefix}_duration_mismatch={item.get('duration')}/{item.get('duration_sec')}")
    progress_ratio = item.get("progress_ratio")
    if isinstance(progress_ratio, (int, float)) and not isinstance(progress_ratio, bool):
        if progress_ratio < 0 or progress_ratio > 1:
            issues.append(f"{prefix}_progress_ratio_out_of_range={progress_ratio}")

    movie = item.get("movie")
    if not isinstance(movie, dict):
        issues.append(f"{prefix}_movie_not_object")
    else:
        if "is_played" in movie:
            issues.append(f"{prefix}_movie_has_is_played")
        issues.extend(f"{prefix}_movie_{issue}" for issue in _catalog_movie_item_issues(movie, index))
    return issues


def _expected_vault_access_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status = payload.get("_http_status")
    return (
        payload.get("code") in EXPECTED_VAULT_ACCESS_ERROR_CODES
        and status in (None, 400, 403, 423)
    )


def _user_favorite_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"favorite_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_USER_FAVORITE_ITEM_KEYS, prefix))
    if "id" in item and not _json_int(item.get("id")):
        issues.append(f"{prefix}_id_not_int")
    for key in ("movie_id", "created_at"):
        if key in item and item.get(key) is not None and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "movie" in item:
        movie = item.get("movie")
        if movie is not None and not isinstance(movie, dict):
            issues.append(f"{prefix}_movie_not_object")
        elif isinstance(movie, dict):
            movie_id = movie.get("id")
            if isinstance(movie_id, str):
                issues.extend(f"{prefix}_movie_{issue}" for issue in _catalog_movie_item_issues(movie, index))
            else:
                issues.append(f"{prefix}_movie_id_invalid={movie_id}")
    return issues


def _user_favorites_payload_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["favorites_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_USER_FAVORITES_KEYS, "favorites"))
    items = data.get("items")
    if not isinstance(items, list):
        issues.append("favorites_items_not_list")
        items = []
    for index, item in enumerate(items[:1]):
        issues.extend(_user_favorite_item_issues(item, index))

    movie_ids = data.get("movie_ids")
    if not isinstance(movie_ids, list):
        issues.append("favorites_movie_ids_not_list")
        movie_ids = []
    elif not all(isinstance(movie_id, str) for movie_id in movie_ids):
        issues.append("favorites_movie_ids_not_str")
    if "total" in data and not _json_int(data.get("total")):
        issues.append("favorites_total_not_int")
    elif _json_int(data.get("total")) and data.get("total") != len(items):
        issues.append(f"favorites_total_mismatch={data.get('total')}/{len(items)}")
    if isinstance(movie_ids, list) and len(movie_ids) != len(items):
        issues.append(f"favorites_movie_ids_count_mismatch={len(movie_ids)}/{len(items)}")

    item_movie_ids = [
        item.get("movie_id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("movie_id"), str)
    ]
    if isinstance(movie_ids, list) and item_movie_ids and movie_ids != item_movie_ids:
        issues.append("favorites_movie_ids_order_mismatch")

    library = data.get("library")
    if "library" in data and library is not None:
        issues.extend(_dict_missing_keys(library, EXPECTED_FAVORITES_LIBRARY_KEYS, "favorites_library"))
        if isinstance(library, dict):
            for key in ("id", "name", "slug", "description", "kind", "created_at", "updated_at"):
                if key in library and library.get(key) is not None and not isinstance(library.get(key), str):
                    issues.append(f"favorites_library_{key}_not_str")
            if library.get("id") != "favorites":
                issues.append(f"favorites_library_id={library.get('id')}")
            if library.get("slug") != "favorites":
                issues.append(f"favorites_library_slug={library.get('slug')}")
            if library.get("is_virtual") is not True:
                issues.append(f"favorites_library_is_virtual={library.get('is_virtual')}")
            if library.get("kind") != "favorites":
                issues.append(f"favorites_library_kind={library.get('kind')}")
            if "is_enabled" in library and library.get("is_enabled") not in (True, False):
                issues.append("favorites_library_is_enabled_not_bool")
            if "sort_order" in library and not _json_int(library.get("sort_order")):
                issues.append("favorites_library_sort_order_not_int")
            if "settings" in library and not isinstance(library.get("settings"), dict):
                issues.append("favorites_library_settings_not_object")
            if "actions" in library and not isinstance(library.get("actions"), dict):
                issues.append("favorites_library_actions_not_object")
            if "movie_count" in library and not _json_int(library.get("movie_count")):
                issues.append("favorites_library_movie_count_not_int")
            if "movie_count" in library and library.get("movie_count") != len(items):
                issues.append(f"favorites_library_movie_count_mismatch={library.get('movie_count')}/{len(items)}")
    if not items and library is not None:
        issues.append("favorites_empty_with_library")
    return issues


def _user_favorite_state_issues(data: Any, expected_movie_id: str) -> list[str]:
    if not isinstance(data, dict):
        return ["favorite_state_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_USER_FAVORITE_STATE_KEYS, "favorite_state"))
    if "movie_id" in data and data.get("movie_id") != expected_movie_id:
        issues.append(f"favorite_state_movie_id={data.get('movie_id')}")
    if "is_favorite" in data and data.get("is_favorite") not in (True, False):
        issues.append("favorite_state_is_favorite_not_bool")
    if "created_at" in data and data.get("created_at") is not None and not isinstance(data.get("created_at"), str):
        issues.append("favorite_state_created_at_not_str")
    return issues


def _vault_status_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["vault_status_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_VAULT_STATUS_KEYS, "vault_status"))
    for key in ("configured", "unlocked", "locked"):
        if key in data and data.get(key) not in (True, False):
            issues.append(f"vault_status_{key}_not_bool")
    if "locked_until" in data and data.get("locked_until") is not None:
        if not isinstance(data.get("locked_until"), str):
            issues.append("vault_status_locked_until_not_str")
    for key in ("pin_change_limit_per_day", "pin_changes_used_today", "pin_changes_remaining_today"):
        if key in data and not _json_int(data.get(key)):
            issues.append(f"vault_status_{key}_not_int")
    if data.get("locked") is True and not data.get("locked_until"):
        issues.append("vault_status_locked_without_locked_until")
    if data.get("locked") is False and data.get("locked_until") is not None:
        issues.append("vault_status_unlocked_has_locked_until")
    if data.get("locked") is True and data.get("unlocked") is True:
        issues.append("vault_status_locked_and_unlocked")
    if data.get("configured") is False and data.get("unlocked") is True:
        issues.append("vault_status_unconfigured_unlocked")
    limit = data.get("pin_change_limit_per_day")
    used = data.get("pin_changes_used_today")
    remaining = data.get("pin_changes_remaining_today")
    if _json_int(limit) and limit < 1:
        issues.append(f"vault_status_pin_change_limit_invalid={limit}")
    if _json_int(used) and used < 0:
        issues.append(f"vault_status_pin_changes_used_negative={used}")
    if _json_int(remaining) and remaining < 0:
        issues.append(f"vault_status_pin_changes_remaining_negative={remaining}")
    if _json_int(limit) and _json_int(used) and _json_int(remaining) and used + remaining != limit:
        issues.append(f"vault_status_pin_change_window_mismatch={used}+{remaining}/{limit}")
    return issues


def _quality_summary_contract_issues(quality: Any) -> list[str]:
    if not isinstance(quality, dict):
        return ["quality_not_object"]

    issues = []
    actions = quality.get("actions")
    if not isinstance(actions, list):
        issues.append("quality_actions_not_list")
    else:
        for index, action in enumerate(actions):
            prefix = f"quality_action_{index}"
            issues.extend(
                _dict_missing_keys(action, EXPECTED_METADATA_QUALITY_ACTION_KEYS, prefix)
            )
            if not isinstance(action, dict):
                continue
            if "enabled" in action and action.get("enabled") not in (True, False):
                issues.append(f"{prefix}_enabled_not_bool")
            if "method" in action and not isinstance(action.get("method"), str):
                issues.append(f"{prefix}_method_not_str")
            if "endpoint" in action and not isinstance(action.get("endpoint"), str):
                issues.append(f"{prefix}_endpoint_not_str")

    issue_items = quality.get("issues")
    if not isinstance(issue_items, list):
        issues.append("quality_issues_not_list")
    else:
        for index, issue in enumerate(issue_items):
            prefix = f"quality_issue_{index}"
            issues.extend(_dict_missing_keys(issue, EXPECTED_METADATA_QUALITY_ISSUE_KEYS, prefix))
            if not isinstance(issue, dict):
                continue
            for key in ("movie_count", "affected_count"):
                if key in issue and not _json_int(issue.get(key)):
                    issues.append(f"{prefix}_{key}_not_int")

            samples = issue.get("samples")
            if not isinstance(samples, list):
                if "samples" in issue:
                    issues.append(f"{prefix}_samples_not_list")
                continue
            for sample_index, sample in enumerate(samples[:1]):
                sample_prefix = f"{prefix}_sample_{sample_index}"
                issues.extend(
                    _dict_missing_keys(sample, EXPECTED_METADATA_QUALITY_SAMPLE_KEYS, sample_prefix)
                )
                if not isinstance(sample, dict):
                    continue
                issues.extend(
                    _dict_missing_keys(
                        sample.get("metadata_state"),
                        EXPECTED_METADATA_STATE_KEYS,
                        f"{sample_prefix}_metadata_state",
                    )
                )
                issues.extend(
                    _dict_missing_keys(
                        sample.get("metadata_actions"),
                        EXPECTED_METADATA_ACTION_KEYS,
                        f"{sample_prefix}_metadata_actions",
                    )
                )
                matching_issue = sample.get("matching_issue")
                if not isinstance(matching_issue, dict):
                    issues.append(f"{sample_prefix}_matching_issue_not_object")
                elif "code" not in matching_issue:
                    issues.append(f"{sample_prefix}_matching_issue_missing=code")
    return issues


def _metadata_reidentify_plan_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"item_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_METADATA_REIDENTIFY_ITEM_KEYS, prefix))
    if item.get("dry_run") is not True:
        issues.append(f"{prefix}_dry_run_not_true")
    if item.get("plan_mode") != "keyword_preview":
        issues.append(f"{prefix}_plan_mode={item.get('plan_mode')}")
    if "matched_issue_codes" in item and not isinstance(item.get("matched_issue_codes"), list):
        issues.append(f"{prefix}_matched_issue_codes_not_list")
    for null_field in ("preview", "diff", "resolution", "explanation"):
        if null_field in item and item.get(null_field) is not None:
            issues.append(f"{prefix}_{null_field}_not_null")

    issues.extend(
        _dict_missing_keys(
            item.get("metadata_state"),
            EXPECTED_METADATA_STATE_KEYS,
            f"{prefix}_metadata_state",
        )
    )
    issues.extend(
        _dict_missing_keys(
            item.get("metadata_actions"),
            EXPECTED_METADATA_ACTION_KEYS,
            f"{prefix}_metadata_actions",
        )
    )

    apply_item = item.get("apply_item")
    if item.get("status") == "planned":
        if not isinstance(apply_item, dict):
            issues.append(f"{prefix}_apply_item_not_object")
        elif apply_item.get("id") != item.get("movie_id"):
            issues.append(f"{prefix}_apply_item_id_mismatch")
    return issues


def check_metadata_reidentify_plan(client: SmokeClient) -> CheckResult:
    payload = client.post_json(
        "/api/v1/metadata/re-scrape/plan",
        {
            "issue_codes": EXPECTED_METADATA_REIDENTIFY_ISSUE_CODES,
            "limit": 1,
        },
    )
    data = _response_data(payload)
    issues = []

    issues.extend(_dict_missing_keys(data, EXPECTED_METADATA_REIDENTIFY_PLAN_KEYS, "plan"))
    if data.get("dry_run") is not True:
        issues.append("dry_run_not_true")
    if data.get("plan_mode") != "keyword_preview":
        issues.append(f"plan_mode={data.get('plan_mode')}")
    if data.get("provider_search") is not False:
        issues.append(f"provider_search={data.get('provider_search')}")
    if data.get("apply_method") != "POST":
        issues.append(f"apply_method={data.get('apply_method')}")
    if data.get("apply_endpoint") != "/api/v1/metadata/re-scrape/jobs":
        issues.append(f"apply_endpoint={data.get('apply_endpoint')}")
    if data.get("sync_apply_endpoint") != "/api/v1/metadata/re-scrape":
        issues.append(f"sync_apply_endpoint={data.get('sync_apply_endpoint')}")
    if data.get("progress_endpoint_template") != "/api/v1/jobs/{job_id}":
        issues.append(f"progress_endpoint_template={data.get('progress_endpoint_template')}")

    selection = data.get("selection") if isinstance(data.get("selection"), dict) else {}
    selected_issue_codes = selection.get("issue_codes") if isinstance(selection, dict) else None
    if selected_issue_codes != EXPECTED_METADATA_REIDENTIFY_ISSUE_CODES:
        issues.append(f"selection_issue_codes={selected_issue_codes}")
    if selection.get("limit") != 1:
        issues.append(f"selection_limit={selection.get('limit')}")

    apply_payload = data.get("apply_payload")
    apply_items = []
    if not isinstance(apply_payload, dict):
        issues.append("apply_payload_not_object")
    else:
        apply_items = apply_payload.get("items")
        if not isinstance(apply_items, list):
            issues.append("apply_payload_items_not_list")
            apply_items = []

    plan_items = data.get("items")
    if not isinstance(plan_items, list):
        issues.append("items_not_list")
        plan_items = []
    if len(plan_items) > 1:
        issues.append(f"too_many_items={len(plan_items)}")
    for index, item in enumerate(plan_items[:1]):
        issues.extend(_metadata_reidentify_plan_item_issues(item, index))

    summary = data.get("summary")
    issues.extend(_dict_missing_keys(summary, EXPECTED_METADATA_REIDENTIFY_SUMMARY_KEYS, "summary"))
    if isinstance(summary, dict):
        for key in ("total", "planned", "failed", "apply_item_count"):
            if key in summary and not _json_int(summary.get(key)):
                issues.append(f"summary_{key}_not_int")
        if summary.get("total") != len(plan_items):
            issues.append(f"summary_total_mismatch={summary.get('total')}/{len(plan_items)}")
        if summary.get("apply_item_count") != len(apply_items):
            issues.append(
                f"summary_apply_item_count_mismatch={summary.get('apply_item_count')}/{len(apply_items)}"
            )
        if "failed_movie_ids" in summary and not isinstance(summary.get("failed_movie_ids"), list):
            issues.append("summary_failed_movie_ids_not_list")
        if "status_counts" in summary and not isinstance(summary.get("status_counts"), dict):
            issues.append("summary_status_counts_not_object")
        if "issue_code_counts" in summary and not isinstance(summary.get("issue_code_counts"), dict):
            issues.append("summary_issue_code_counts_not_object")

    ok = not issues
    detail = (
        f"dry_run={data.get('dry_run')} mode={data.get('plan_mode')} "
        f"items={len(plan_items)} apply_items={len(apply_items)} "
        f"total={summary.get('total') if isinstance(summary, dict) else None}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "metadata_reidentify_plan",
        ok,
        detail,
        {
            "dry_run": data.get("dry_run"),
            "plan_mode": data.get("plan_mode"),
            "provider_search": data.get("provider_search"),
            "item_count": len(plan_items),
            "apply_item_count": len(apply_items),
            "summary": summary if isinstance(summary, dict) else None,
            "issues": issues,
        },
    )


def check_libraries(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/libraries")
    items = _response_list(payload)
    issues = []

    for index, item in enumerate(items[:3]):
        issues.extend(_library_item_issues(item, index))

    ok = not issues
    sample = items[0] if items and isinstance(items[0], dict) else None
    sample_name = sample.get("name") if sample else None
    detail = f"items={len(items)}"
    if sample_name:
        detail = f"{detail} sample={sample_name}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "libraries",
        ok,
        detail,
        {
            "item_count": len(items),
            "sample_name": sample_name,
            "issues": issues,
        },
    )


def check_other_videos(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/other-videos", {"page": 1, "page_size": 1})
    data = _response_data(payload)
    issues = _other_videos_payload_issues(data, expected_page_size=1)

    items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []
    summary = data.get("summary") if isinstance(data, dict) and isinstance(data.get("summary"), dict) else {}
    total_items = summary.get("total_items") if isinstance(summary, dict) else None
    sample = items[0] if items and isinstance(items[0], dict) else None
    sample_title = sample.get("movie_title") if sample else None
    sample_resource_id = sample.get("resource_id") if sample else None

    ok = not issues
    detail = (
        f"total={total_items} items={len(items)} "
        f"manual={summary.get('manual_movie_count') if isinstance(summary, dict) else None}"
    )
    if sample_title or sample_resource_id:
        detail = f"{detail} sample={sample_title or sample_resource_id}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "other_videos",
        ok,
        detail,
        {
            "total": total_items,
            "item_count": len(items),
            "manual_movie_count": summary.get("manual_movie_count") if isinstance(summary, dict) else None,
            "sample_resource_id": sample_resource_id,
            "issues": issues,
        },
    )


def check_catalog_filters(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/filters", {"include": "genres,years,countries"})
    data = _response_data(payload)
    issues = _catalog_filters_payload_issues(data)

    counts = {
        key: len(data.get(key) or []) if isinstance(data, dict) and isinstance(data.get(key), list) else 0
        for key in EXPECTED_CATALOG_FILTER_KEYS
    }
    ok = not issues
    detail = (
        f"genres={counts['genres']} years={counts['years']} "
        f"countries={counts['countries']}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "catalog_filters",
        ok,
        detail,
        {
            "counts": counts,
            "issues": issues,
        },
    )


def check_catalog_movies(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    data = _response_data(payload)
    issues = []

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        issues.append("items_not_list")
        items = []
    if len(items) > 1:
        issues.append(f"too_many_items={len(items)}")

    pagination = data.get("pagination") if isinstance(data, dict) else None
    issues.extend(_pagination_contract_issues(pagination, expected_page_size=1))
    total = pagination.get("total_items") if isinstance(pagination, dict) else None
    page_size = pagination.get("page_size") if isinstance(pagination, dict) else None
    if _json_int(total) and total > 0 and not items:
        issues.append("items_empty_with_total")

    sample = items[0] if items else None
    if sample is not None:
        issues.extend(_catalog_movie_item_issues(sample, 0))

    ok = not issues
    sample_title = sample.get("title") if isinstance(sample, dict) else None
    detail = f"items={len(items)} total={total} page_size={page_size}"
    if sample_title:
        detail = f"{detail} sample={sample_title}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "catalog_movies",
        ok,
        detail,
        {
            "item_count": len(items),
            "total": total,
            "sample_title": sample_title,
            "issues": issues,
        },
    )


def check_movie_detail(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "movie_detail",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "movie_detail",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}")
    data = _response_data(payload)
    issues = _movie_detail_issues(data, movie_id)

    ok = not issues
    title = data.get("title") if isinstance(data, dict) else None
    actor_count = len(data.get("actors") or []) if isinstance(data.get("actors"), list) else 0
    detail = f"id={movie_id} title={title} actors={actor_count}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "movie_detail",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "title": title,
            "actor_count": actor_count,
            "issues": issues,
        },
    )


def check_movie_resources(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "movie_resources",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "movie_resources",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/resources")
    data = _response_data(payload)
    issues = _movie_resources_payload_issues(data)
    summary = data.get("summary") if isinstance(data, dict) and isinstance(data.get("summary"), dict) else {}
    groups = data.get("groups") if isinstance(data, dict) and isinstance(data.get("groups"), dict) else {}
    playback_sources = groups.get("playback_sources") if isinstance(groups.get("playback_sources"), list) else []
    items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []

    ok = not issues
    detail = (
        f"id={movie_id} items={len(items)} total={summary.get('total_items')} "
        f"playback_sources={len(playback_sources)}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "movie_resources",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "item_count": len(items),
            "total": summary.get("total_items"),
            "playback_source_count": len(playback_sources),
            "issues": issues,
        },
    )


def check_movie_seasons(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "movie_seasons",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "movie_seasons",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/seasons")
    data = _response_data(payload)
    issues = _movie_seasons_payload_issues(data)
    items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []
    summary = data.get("summary") if isinstance(data, dict) and isinstance(data.get("summary"), dict) else {}
    episode_diagnostics = (
        summary.get("episode_diagnostics")
        if isinstance(summary.get("episode_diagnostics"), dict)
        else {}
    )

    ok = not issues
    detail = (
        f"id={movie_id} seasons={len(items)} summary_seasons={summary.get('season_count')} "
        f"episode_status={episode_diagnostics.get('status')}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "movie_seasons",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "season_count": len(items),
            "summary_season_count": summary.get("season_count"),
            "episode_status": episode_diagnostics.get("status"),
            "issues": issues,
        },
    )


def check_movie_episode_diagnostics(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "movie_episode_diagnostics",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "movie_episode_diagnostics",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/episode-diagnostics")
    data = _response_data(payload)
    issues = _movie_episode_diagnostics_payload_issues(data, movie_id)
    summary = data.get("summary") if isinstance(data, dict) and isinstance(data.get("summary"), dict) else {}
    seasons = data.get("seasons") if isinstance(data, dict) and isinstance(data.get("seasons"), list) else []
    apply_payload = data.get("apply_payload") if isinstance(data, dict) and isinstance(data.get("apply_payload"), dict) else {}
    apply_items = apply_payload.get("items") if isinstance(apply_payload.get("items"), list) else []
    warnings = data.get("warnings") if isinstance(data, dict) and isinstance(data.get("warnings"), list) else []

    ok = not issues
    detail = (
        f"id={movie_id} status={summary.get('status')} coverage={summary.get('coverage_status')} "
        f"seasons={len(seasons)} apply_items={len(apply_items)} warnings={len(warnings)}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "movie_episode_diagnostics",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "status": summary.get("status"),
            "coverage_status": summary.get("coverage_status"),
            "season_count": len(seasons),
            "apply_item_count": len(apply_items),
            "warning_count": len(warnings),
            "issues": issues,
        },
    )


def check_external_playback(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "external_playback",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "external_playback",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    resources_payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/resources")
    resources_data = _response_data(resources_payload)
    resource_items = (
        resources_data.get("items")
        if isinstance(resources_data, dict) and isinstance(resources_data.get("items"), list)
        else []
    )
    if not resource_items:
        return _result(
            "external_playback",
            True,
            f"skipped no resources movie_id={movie_id}",
            {"skipped": True, "movie_id": movie_id},
        )

    sample_resource = resource_items[0] if isinstance(resource_items[0], dict) else {}
    resource_id = sample_resource.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        return _result(
            "external_playback",
            False,
            f"resource_id_invalid={resource_id}",
            {"movie_id": movie_id, "resource_id": resource_id},
        )

    payload = client.get_json(f"/api/v1/resources/{urllib.parse.quote(resource_id, safe='')}/external-playback")
    data = _response_data(payload)
    issues = _external_playback_manifest_issues(data, expected_resource_id=resource_id)

    handoff = data.get("handoff") if isinstance(data, dict) and isinstance(data.get("handoff"), dict) else {}
    stream = data.get("stream") if isinstance(data, dict) and isinstance(data.get("stream"), dict) else {}
    subtitles = data.get("subtitles") if isinstance(data, dict) and isinstance(data.get("subtitles"), dict) else {}
    profiles = data.get("player_profiles") if isinstance(data, dict) and isinstance(data.get("player_profiles"), list) else []

    ok = not issues
    detail = (
        f"resource={resource_id} supported={handoff.get('supported')} "
        f"stream={bool(stream.get('url'))} subtitles={len(subtitles.get('items') or [])} "
        f"profiles={len(profiles)}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "external_playback",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "resource_id": resource_id,
            "supported": handoff.get("supported"),
            "profile_count": len(profiles),
            "issues": issues,
        },
    )


def check_subtitle_settings(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "subtitle_settings",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "subtitle_settings",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    resources_payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/resources")
    resources_data = _response_data(resources_payload)
    resource_items = (
        resources_data.get("items")
        if isinstance(resources_data, dict) and isinstance(resources_data.get("items"), list)
        else []
    )
    if not resource_items:
        return _result(
            "subtitle_settings",
            True,
            f"skipped no resources movie_id={movie_id}",
            {"skipped": True, "movie_id": movie_id},
        )

    sample_resource = resource_items[0] if isinstance(resource_items[0], dict) else {}
    resource_id = sample_resource.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        return _result(
            "subtitle_settings",
            False,
            f"resource_id_invalid={resource_id}",
            {"movie_id": movie_id, "resource_id": resource_id},
        )

    payload = client.get_json(f"/api/v1/resources/{urllib.parse.quote(resource_id, safe='')}/subtitle-settings")
    data = _response_data(payload)
    issues = _subtitle_settings_payload_issues(data, expected_resource_id=resource_id)
    settings = data.get("settings") if isinstance(data, dict) and isinstance(data.get("settings"), dict) else {}

    ok = not issues
    detail = (
        f"resource={resource_id} source={data.get('source') if isinstance(data, dict) else None} "
        f"customized={data.get('customized') if isinstance(data, dict) else None} "
        f"zhSize={settings.get('zhSize')} enSize={settings.get('enSize')} "
        f"offset={settings.get('offset')}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "subtitle_settings",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "resource_id": resource_id,
            "source": data.get("source") if isinstance(data, dict) else None,
            "customized": data.get("customized") if isinstance(data, dict) else None,
            "issues": issues,
        },
    )


def check_audio_transcode_diagnostics(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "audio_transcode_diagnostics",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "audio_transcode_diagnostics",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    resources_payload = client.get_json(f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/resources")
    resources_data = _response_data(resources_payload)
    resource_items = (
        resources_data.get("items")
        if isinstance(resources_data, dict) and isinstance(resources_data.get("items"), list)
        else []
    )
    if not resource_items:
        return _result(
            "audio_transcode_diagnostics",
            True,
            f"skipped no resources movie_id={movie_id}",
            {"skipped": True, "movie_id": movie_id},
        )

    sample_resource = resource_items[0] if isinstance(resource_items[0], dict) else {}
    resource_id = sample_resource.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        return _result(
            "audio_transcode_diagnostics",
            False,
            f"resource_id_invalid={resource_id}",
            {"movie_id": movie_id, "resource_id": resource_id},
        )

    payload = client.get_json(f"/api/v1/resources/{urllib.parse.quote(resource_id, safe='')}/audio-transcode/diagnostics")
    data = _response_data(payload)
    issues = _audio_transcode_diagnostics_payload_issues(data, expected_resource_id=resource_id)
    items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []

    ok = not issues
    detail = (
        f"resource={resource_id} active={data.get('active_count') if isinstance(data, dict) else None} "
        f"items={len(items)} session={data.get('session_id') if isinstance(data, dict) else None}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "audio_transcode_diagnostics",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "resource_id": resource_id,
            "active_count": data.get("active_count") if isinstance(data, dict) else None,
            "item_count": len(items),
            "issues": issues,
        },
    )


def check_featured(client: SmokeClient) -> CheckResult:
    expected_limit = 5
    payload = client.get_json("/api/v1/featured")
    items = _response_list(payload)
    issues = []

    if len(items) > expected_limit:
        issues.append(f"too_many_items={len(items)}/{expected_limit}")
    for index, item in enumerate(items[:1]):
        if not isinstance(item, dict):
            issues.append(f"item_{index}_not_object")
            continue
        movie_id = item.get("id")
        expected_id = movie_id if isinstance(movie_id, str) else ""
        issues.extend(_movie_detail_issues(item, expected_id))

    ok = not issues
    sample = items[0] if items and isinstance(items[0], dict) else None
    sample_title = sample.get("title") if sample else None
    detail = f"items={len(items)} expected_limit={expected_limit}"
    if sample_title:
        detail = f"{detail} sample={sample_title}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "featured",
        ok,
        detail,
        {
            "item_count": len(items),
            "expected_limit": expected_limit,
            "sample_title": sample_title,
            "issues": issues,
        },
    )


def check_homepage(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/homepage")
    data = _response_data(payload)
    issues = _homepage_payload_issues(data)

    hero = data.get("hero") if isinstance(data, dict) and isinstance(data.get("hero"), dict) else {}
    hero_movie = hero.get("movie") if isinstance(hero.get("movie"), dict) else None
    sections = data.get("sections") if isinstance(data, dict) and isinstance(data.get("sections"), list) else []
    section_item_count = sum(
        len(section.get("items") or [])
        for section in sections
        if isinstance(section, dict) and isinstance(section.get("items"), list)
    )

    ok = not issues
    hero_title = hero_movie.get("title") if isinstance(hero_movie, dict) else None
    detail = f"hero_mode={hero.get('mode')} sections={len(sections)} items={section_item_count}"
    if hero_title:
        detail = f"{detail} hero={hero_title}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "homepage",
        ok,
        detail,
        {
            "hero_mode": hero.get("mode"),
            "hero_title": hero_title,
            "section_count": len(sections),
            "section_item_count": section_item_count,
            "issues": issues,
        },
    )


def check_homepage_config(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/homepage/config")
    data = _response_data(payload)
    issues = _homepage_config_issues(data)

    sections = data.get("sections") if isinstance(data, dict) and isinstance(data.get("sections"), list) else []
    enabled_count = sum(
        1
        for section in sections
        if isinstance(section, dict) and section.get("enabled") is True
    )
    hero_movie_id = data.get("hero_movie_id") if isinstance(data, dict) else None

    ok = not issues
    detail = f"sections={len(sections)} enabled={enabled_count} hero_movie_id={hero_movie_id}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "homepage_config",
        ok,
        detail,
        {
            "section_count": len(sections),
            "enabled_count": enabled_count,
            "hero_movie_id": hero_movie_id,
            "issues": issues,
        },
    )


def check_recommendations(client: SmokeClient) -> CheckResult:
    strategy = "default"
    limit = 3
    payload = client.get_json("/api/v1/recommendations", {"strategy": strategy, "limit": limit})
    items = _response_list(payload)
    issues = []

    if len(items) > limit:
        issues.append(f"too_many_items={len(items)}/{limit}")
    for index, item in enumerate(items[:1]):
        issues.extend(_recommendation_item_issues(item, index, strategy))

    ok = not issues
    sample = items[0] if items and isinstance(items[0], dict) else None
    sample_title = sample.get("title") if sample else None
    recommendation = sample.get("recommendation") if sample and isinstance(sample.get("recommendation"), dict) else {}
    primary_reason = recommendation.get("primary_reason") if isinstance(recommendation.get("primary_reason"), dict) else {}
    primary_reason_code = primary_reason.get("code")
    detail = f"items={len(items)} strategy={strategy}"
    if sample_title:
        detail = f"{detail} sample={sample_title} primary_reason={primary_reason_code}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "recommendations",
        ok,
        detail,
        {
            "item_count": len(items),
            "strategy": strategy,
            "sample_title": sample_title,
            "sample_primary_reason": primary_reason_code,
            "issues": issues,
        },
    )


def check_movie_context_recommendations(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    if not isinstance(catalog_items, list) or not catalog_items:
        return _result(
            "movie_context_recommendations",
            True,
            "skipped no catalog movies",
            {"skipped": True, "catalog_item_count": 0},
        )

    catalog_sample = catalog_items[0]
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if not isinstance(movie_id, str) or not movie_id:
        return _result(
            "movie_context_recommendations",
            False,
            f"catalog_sample_id_invalid={movie_id}",
            {"catalog_item_count": len(catalog_items), "movie_id": movie_id},
        )

    strategy = "context"
    limit = 3
    payload = client.get_json(
        f"/api/v1/movies/{urllib.parse.quote(movie_id, safe='')}/recommendations",
        {"limit": limit},
    )
    items = _response_list(payload)
    issues = []

    if len(items) > limit:
        issues.append(f"too_many_items={len(items)}/{limit}")
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == movie_id:
            issues.append(f"item_{index}_is_anchor={movie_id}")
    for index, item in enumerate(items[:1]):
        issues.extend(_recommendation_item_issues(item, index, strategy))

    ok = not issues
    sample = items[0] if items and isinstance(items[0], dict) else None
    sample_title = sample.get("title") if sample else None
    recommendation = sample.get("recommendation") if sample and isinstance(sample.get("recommendation"), dict) else {}
    primary_reason = recommendation.get("primary_reason") if isinstance(recommendation.get("primary_reason"), dict) else {}
    primary_reason_code = primary_reason.get("code")
    anchor_title = catalog_sample.get("title") if isinstance(catalog_sample, dict) else None
    detail = f"anchor={movie_id} items={len(items)} strategy={strategy}"
    if anchor_title:
        detail = f"{detail} anchor_title={anchor_title}"
    if sample_title:
        detail = f"{detail} sample={sample_title} primary_reason={primary_reason_code}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "movie_context_recommendations",
        ok,
        detail,
        {
            "movie_id": movie_id,
            "anchor_title": anchor_title,
            "item_count": len(items),
            "strategy": strategy,
            "sample_title": sample_title,
            "sample_primary_reason": primary_reason_code,
            "issues": issues,
        },
    )


def check_user_history(client: SmokeClient) -> CheckResult:
    page_size = 1
    payload = client.get_json("/api/v1/user/history", {"page": 1, "page_size": page_size})
    data = _response_data(payload)
    issues = []

    if not isinstance(data, dict):
        issues.append("history_not_object")
        items = []
        pagination = None
    else:
        items = data.get("items")
        pagination = data.get("pagination")
        if not isinstance(items, list):
            issues.append("history_items_not_list")
            items = []
        issues.extend(_pagination_contract_issues(pagination, expected_page_size=page_size))

    total = pagination.get("total_items") if isinstance(pagination, dict) else None
    page_size_value = pagination.get("page_size") if isinstance(pagination, dict) else None
    if _json_int(total) and total > 0 and not items:
        issues.append("history_items_empty_with_total")
    for index, item in enumerate(items[:1]):
        issues.extend(_user_history_item_issues(item, index))

    ok = not issues
    sample = items[0] if items and isinstance(items[0], dict) else None
    movie = sample.get("movie") if sample and isinstance(sample.get("movie"), dict) else None
    sample_title = movie.get("title") if movie else None
    detail = f"items={len(items)} total={total} page_size={page_size_value}"
    if sample_title:
        detail = f"{detail} sample={sample_title}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "user_history",
        ok,
        detail,
        {
            "item_count": len(items),
            "total": total,
            "page_size": page_size_value,
            "sample_title": sample_title,
            "issues": issues,
        },
    )


def check_user_favorites(client: SmokeClient) -> CheckResult:
    catalog_payload = client.get_json("/api/v1/movies", {"page": 1, "page_size": 1})
    catalog_data = _response_data(catalog_payload)
    catalog_items = catalog_data.get("items") if isinstance(catalog_data, dict) else None
    catalog_sample = catalog_items[0] if isinstance(catalog_items, list) and catalog_items else {}
    movie_id = catalog_sample.get("id") if isinstance(catalog_sample, dict) else None
    if movie_id is not None and not isinstance(movie_id, str):
        movie_id = None

    payload = client.get_json_allow_error("/api/v1/user/favorites", {"include_movies": "true"})
    list_status = payload.get("_http_status") if isinstance(payload, dict) else None
    list_code = payload.get("code") if isinstance(payload, dict) else None
    issues = []

    if _expected_vault_access_error(payload):
        state_code = None
        if movie_id:
            state_payload = client.get_json_allow_error(
                f"/api/v1/user/favorites/{urllib.parse.quote(movie_id, safe='')}"
            )
            state_code = state_payload.get("code") if isinstance(state_payload, dict) else None
            if not _expected_vault_access_error(state_payload):
                issues.append(f"favorite_state_expected_vault_error={state_code}")
        ok = not issues
        detail = f"vault_required list_code={list_code}"
        if movie_id:
            detail = f"{detail} state_code={state_code}"
        if issues:
            detail = f"{detail} issues={'; '.join(issues)}"
        return _result(
            "user_favorites",
            ok,
            detail,
            {
                "vault_required": True,
                "list_code": list_code,
                "state_code": state_code,
                "movie_id": movie_id,
                "issues": issues,
            },
        )

    if list_status not in (None, 200):
        issues.append(f"favorites_http_status={list_status}")
    if list_code not in (None, 200):
        issues.append(f"favorites_code={list_code}")

    data = _response_data(payload)
    issues.extend(_user_favorites_payload_issues(data))
    items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []
    movie_ids = data.get("movie_ids") if isinstance(data, dict) and isinstance(data.get("movie_ids"), list) else []
    library = data.get("library") if isinstance(data, dict) else None
    total = data.get("total") if isinstance(data, dict) else None

    favorite_state = None
    if movie_id:
        state_payload = client.get_json_allow_error(
            f"/api/v1/user/favorites/{urllib.parse.quote(movie_id, safe='')}"
        )
        state_status = state_payload.get("_http_status") if isinstance(state_payload, dict) else None
        state_code = state_payload.get("code") if isinstance(state_payload, dict) else None
        if _expected_vault_access_error(state_payload):
            issues.append(f"favorite_state_vault_error={state_code}")
        elif state_status not in (None, 200):
            issues.append(f"favorite_state_http_status={state_status}")
        elif state_code not in (None, 200):
            issues.append(f"favorite_state_code={state_code}")
        else:
            favorite_state = _response_data(state_payload)
            issues.extend(_user_favorite_state_issues(favorite_state, movie_id))

    ok = not issues
    state_value = favorite_state.get("is_favorite") if isinstance(favorite_state, dict) else None
    detail = (
        f"items={len(items)} total={total} movie_ids={len(movie_ids)} "
        f"library={bool(library)} state={state_value}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "user_favorites",
        ok,
        detail,
        {
            "item_count": len(items),
            "total": total,
            "movie_id_count": len(movie_ids),
            "has_library": bool(library),
            "movie_id": movie_id,
            "is_favorite": state_value,
            "issues": issues,
        },
    )


def check_vault_status(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/user/vault/status")
    data = _response_data(payload)
    issues = _vault_status_issues(data)

    ok = not issues
    configured = data.get("configured") if isinstance(data, dict) else None
    unlocked = data.get("unlocked") if isinstance(data, dict) else None
    locked = data.get("locked") if isinstance(data, dict) else None
    remaining = data.get("pin_changes_remaining_today") if isinstance(data, dict) else None
    detail = (
        f"configured={configured} unlocked={unlocked} locked={locked} "
        f"pin_changes_remaining_today={remaining}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "vault_status",
        ok,
        detail,
        {
            "configured": configured,
            "unlocked": unlocked,
            "locked": locked,
            "pin_changes_remaining_today": remaining,
            "issues": issues,
        },
    )


def check_metadata_work_items_contract(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/metadata/work-items", {"page_size": 1})
    data = _response_data(payload)
    issues = []

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        issues.append("items_not_list")
        items = []
    if len(items) > 1:
        issues.append(f"too_many_items={len(items)}")

    pagination = data.get("pagination") if isinstance(data, dict) else None
    issues.extend(_pagination_contract_issues(pagination, expected_page_size=1))
    total = pagination.get("total_items") if isinstance(pagination, dict) else None
    page_size = pagination.get("page_size") if isinstance(pagination, dict) else None
    if _json_int(total) and total > 0 and not items:
        issues.append("items_empty_with_total")

    sample = items[0] if items else None
    if sample is not None:
        issues.extend(_work_item_contract_issues(sample, 0))

    ok = not issues
    sample_title = sample.get("title") if isinstance(sample, dict) else None
    detail = f"items={len(items)} total={total} page_size={page_size}"
    if sample_title:
        detail = f"{detail} sample={sample_title}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "metadata_work_items_contract",
        ok,
        detail,
        {
            "item_count": len(items),
            "total": total,
            "sample_title": sample_title,
            "issues": issues,
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


def check_background_jobs_prune(client: SmokeClient) -> CheckResult:
    payload = client.post_json(
        "/api/v1/jobs/prune",
        {
            "retention_days": 30,
            "dry_run": True,
        },
    )
    data = _response_data(payload)
    issues = []

    issues.extend(_dict_missing_keys(data, EXPECTED_JOB_PRUNE_KEYS, "prune"))
    if data.get("dry_run") is not True:
        issues.append("dry_run_not_true")
    if data.get("retention_days") != 30:
        issues.append(f"retention_days={data.get('retention_days')}")
    if data.get("removed") != 0:
        issues.append(f"removed={data.get('removed')}")
    if data.get("removed_ids") != []:
        issues.append(f"removed_ids={data.get('removed_ids')}")
    for key in ("matched", "removed"):
        if key in data and not _json_int(data.get(key)):
            issues.append(f"{key}_not_int")
    for key in ("matched_ids", "removed_ids"):
        if key in data and not isinstance(data.get(key), list):
            issues.append(f"{key}_not_list")
    for key in ("type_counts", "status_counts"):
        if key in data and not isinstance(data.get(key), dict):
            issues.append(f"{key}_not_object")
    if data.get("type") is not None:
        issues.append(f"type={data.get('type')}")

    ok = not issues
    detail = (
        f"dry_run={data.get('dry_run')} retention_days={data.get('retention_days')} "
        f"matched={data.get('matched')} removed={data.get('removed')}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "background_jobs_prune",
        ok,
        detail,
        {
            "dry_run": data.get("dry_run"),
            "retention_days": data.get("retention_days"),
            "matched": data.get("matched"),
            "removed": data.get("removed"),
            "issues": issues,
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


def _storage_provider_config_field_issues(field: Any, index: int, provider_label: str) -> list[str]:
    prefix = f"{provider_label}_field_{index}"
    if not isinstance(field, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(field, EXPECTED_STORAGE_PROVIDER_CONFIG_FIELD_KEYS, prefix))
    for key in ("name", "type"):
        if key in field and not isinstance(field.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    if "required" in field and field.get("required") not in (True, False):
        issues.append(f"{prefix}_required_not_bool")
    if "description" in field and not isinstance(field.get("description"), str):
        issues.append(f"{prefix}_description_not_str")
    return issues


def _storage_provider_type_issues(provider: Any, index: int) -> list[str]:
    prefix = f"provider_{index}"
    if not isinstance(provider, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(provider, EXPECTED_STORAGE_PROVIDER_TYPE_KEYS, prefix))
    provider_type = provider.get("type")
    provider_type_key = provider_type if isinstance(provider_type, str) else ""
    provider_label = provider_type_key if provider_type_key else prefix

    for key in ("type", "display_name", "status"):
        if key in provider and not isinstance(provider.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")

    capabilities = provider.get("capabilities")
    if not isinstance(capabilities, dict):
        issues.append(f"{provider_label}_capabilities_not_object")
    else:
        for key, value in capabilities.items():
            if not isinstance(key, str):
                issues.append(f"{provider_label}_capability_key_not_str")
            if value not in (True, False):
                issues.append(f"{provider_label}_capability_{key}_not_bool")

    config_fields = provider.get("config_fields")
    if not isinstance(config_fields, list):
        issues.append(f"{provider_label}_config_fields_not_list")
        config_fields = []

    field_names = {
        field.get("name")
        for field in config_fields
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    }
    required_fields = EXPECTED_STORAGE_PROVIDER_REQUIRED_FIELDS.get(provider_type_key, set())
    missing_fields = sorted(required_fields - field_names)
    if missing_fields:
        issues.append(f"provider_{provider_label}_missing_config_fields={','.join(missing_fields)}")

    for field_index, field in enumerate(config_fields):
        issues.extend(_storage_provider_config_field_issues(field, field_index, provider_label))
    return issues


def check_storage_provider_types(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/storage/provider-types")
    data = payload.get("data")
    issues = []
    if not isinstance(data, list):
        issues.append("provider_types_not_list")
        providers = []
    else:
        providers = data

    provider_types = {
        provider.get("type")
        for provider in providers
        if isinstance(provider, dict) and isinstance(provider.get("type"), str)
    }
    missing_expected = sorted(EXPECTED_STORAGE_PROVIDER_REQUIRED_FIELDS.keys() - provider_types)
    if missing_expected:
        issues.append(f"missing_expected_types={','.join(missing_expected)}")

    for index, provider in enumerate(providers):
        issues.extend(_storage_provider_type_issues(provider, index))

    ok = not issues
    detail = (
        f"providers={len(providers)} "
        f"expected={','.join(sorted(EXPECTED_STORAGE_PROVIDER_REQUIRED_FIELDS.keys()))}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "storage_provider_types",
        ok,
        detail,
        {
            "provider_types": sorted(provider_types),
            "issues": issues,
        },
    )


def _storage_capability_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"capability_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_STORAGE_CAPABILITY_ITEM_KEYS, prefix))
    for key in ("type", "display_name", "label", "config_root_key"):
        if key in item and not isinstance(item.get(key), str):
            issues.append(f"{prefix}_{key}_not_str")
    for key in (
        "browse",
        "validate_path",
        "range_stream",
        "library_root_path",
        "preview",
        "scan",
        "stream",
        "credentials_required",
        "health_check",
        "managed",
        "refresh",
        "redirect_stream",
        "ffmpeg_input",
        "qr_login",
        "sms_login",
        "oauth_login",
        "password_login",
    ):
        if key in item and item.get(key) not in (True, False):
            issues.append(f"{prefix}_{key}_not_bool")
    if item.get("type") == "local" and item.get("config_root_key") != "root_path":
        issues.append(f"{prefix}_local_config_root_key={item.get('config_root_key')}")
    if item.get("type") != "local" and item.get("config_root_key") not in (None, "root"):
        issues.append(f"{prefix}_config_root_key={item.get('config_root_key')}")
    if item.get("browse") is not item.get("preview"):
        issues.append(f"{prefix}_browse_preview_mismatch={item.get('browse')}/{item.get('preview')}")
    if item.get("validate_path") is not item.get("preview"):
        issues.append(f"{prefix}_validate_path_preview_mismatch={item.get('validate_path')}/{item.get('preview')}")
    if item.get("library_root_path") is not item.get("preview"):
        issues.append(f"{prefix}_library_root_path_preview_mismatch={item.get('library_root_path')}/{item.get('preview')}")
    return issues


def check_storage_capabilities(client: SmokeClient) -> CheckResult:
    payload = client.get_json("/api/v1/storage/capabilities")
    data = _response_data(payload)
    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_STORAGE_CAPABILITIES_KEYS, "capabilities"))

    supported_types = data.get("supported_types") if isinstance(data, dict) else None
    if not isinstance(supported_types, list):
        issues.append("supported_types_not_list")
        supported_types = []
    elif not all(isinstance(item, str) for item in supported_types):
        issues.append("supported_types_not_str")

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        issues.append("items_not_list")
        items = []
    item_types = {
        item.get("type")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("type"), str)
    }
    supported_type_set = {item for item in supported_types if isinstance(item, str)}
    if item_types != supported_type_set:
        missing_items = sorted(supported_type_set - item_types)
        extra_items = sorted(item_types - supported_type_set)
        if missing_items:
            issues.append(f"items_missing_types={','.join(missing_items[:5])}")
        if extra_items:
            issues.append(f"items_extra_types={','.join(extra_items[:5])}")

    missing_expected = sorted(EXPECTED_STORAGE_CAPABILITY_TYPES - item_types)
    if missing_expected:
        issues.append(f"missing_expected_types={','.join(missing_expected)}")

    for index, item in enumerate(items):
        issues.extend(_storage_capability_item_issues(item, index))

    ok = not issues
    detail = f"types={len(supported_type_set)} items={len(items)} expected={','.join(sorted(EXPECTED_STORAGE_CAPABILITY_TYPES))}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "storage_capabilities",
        ok,
        detail,
        {
            "supported_types": sorted(supported_type_set),
            "item_types": sorted(item_types),
            "issues": issues,
        },
    )


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


def _browseable_storage_sources(client: SmokeClient) -> list[dict[str, Any]]:
    payload = client.get_json("/api/v1/storage/sources")
    sources = [item for item in _response_list(payload) if isinstance(item, dict)]
    return [
        source
        for source in sources
        if source.get("is_supported") is True
        and source.get("config_valid") is True
        and _source_actions(source).get("can_preview") is True
    ]


def _storage_browse_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"item_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_STORAGE_BROWSE_ITEM_KEYS, prefix))
    if "name" in item and not isinstance(item.get("name"), str):
        issues.append(f"{prefix}_name_not_str")
    if "path" in item and not isinstance(item.get("path"), str):
        issues.append(f"{prefix}_path_not_str")
    if item.get("type") != "dir":
        issues.append(f"{prefix}_type={item.get('type')}")
    if "size" in item and not isinstance(item.get("size"), (int, float)):
        issues.append(f"{prefix}_size_not_number")
    return issues


def check_storage_browse(client: SmokeClient) -> CheckResult:
    sources = _browseable_storage_sources(client)
    if not sources:
        return _result(
            "storage_browse",
            True,
            "skipped no browseable sources",
            {"source_count": 0, "skipped": True},
        )

    source = sources[0]
    source_id = source.get("id")
    payload = client.get_json(
        f"/api/v1/storage/sources/{source_id}/browse",
        {"path": "/", "dirs_only": "true"},
    )
    data = _response_data(payload)
    issues = []
    issues.extend(_dict_missing_keys(data, EXPECTED_STORAGE_BROWSE_KEYS, "browse"))

    browse_source = data.get("source") if isinstance(data, dict) else {}
    if not isinstance(browse_source, dict):
        issues.append("browse_source_not_object")
    elif browse_source.get("id") != source_id:
        issues.append(f"source_id_mismatch={browse_source.get('id')}/{source_id}")

    if data.get("current_path") != "/":
        issues.append(f"current_path={data.get('current_path')}")
    if "parent_path" in data and data.get("parent_path") is not None:
        issues.append(f"parent_path={data.get('parent_path')}")

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        issues.append("items_not_list")
        items = []
    for index, item in enumerate(items[:3]):
        issues.extend(_storage_browse_item_issues(item, index))

    ok = not issues
    source_name = source.get("name") or source.get("display_name")
    detail = f"source={source_id}:{source_name} items={len(items)} path={data.get('current_path')}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "storage_browse",
        ok,
        detail,
        {
            "source_id": source_id,
            "source_name": source.get("name") or source.get("display_name"),
            "item_count": len(items),
            "issues": issues,
        },
    )


def check_storage_health(client: SmokeClient, min_checked: int = 0) -> CheckResult:
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
    if len(health_items) < min_checked:
        issues.append(f"checked_below_min={len(health_items)}/{min_checked}")
        ok = False
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


def _episode_review_summary_issues(summary: Any, expected_total: int | None = None) -> list[str]:
    issues = _dict_missing_keys(summary, EXPECTED_EPISODE_REVIEW_SUMMARY_KEYS, "summary")
    if not isinstance(summary, dict):
        return issues

    for key in ("total_items", "auto_update_count", "manual_suggestion_count", "warning_count"):
        if key in summary and not _json_int(summary.get(key)):
            issues.append(f"summary_{key}_not_int")
    if "issue_code_counts" in summary and not isinstance(summary.get("issue_code_counts"), dict):
        issues.append("summary_issue_code_counts_not_object")
    if expected_total is not None and summary.get("total_items") != expected_total:
        issues.append(f"summary_total_mismatch={summary.get('total_items')}/{expected_total}")
    return issues


def _episode_review_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"item_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_EPISODE_REVIEW_ITEM_KEYS, prefix))
    if "playable" in item and item.get("playable") not in (True, False):
        issues.append(f"{prefix}_playable_not_bool")
    if "metadata_issues" in item and not isinstance(item.get("metadata_issues"), list):
        issues.append(f"{prefix}_metadata_issues_not_list")
    if "episode_diagnostics" in item and not isinstance(item.get("episode_diagnostics"), dict):
        issues.append(f"{prefix}_episode_diagnostics_not_object")
    if "seasons_needing_attention" in item and not isinstance(item.get("seasons_needing_attention"), list):
        issues.append(f"{prefix}_seasons_needing_attention_not_list")
    for key in ("season_count", "auto_update_count", "manual_suggestion_count", "warning_count"):
        if key in item and not _json_int(item.get(key)):
            issues.append(f"{prefix}_{key}_not_int")
    if (
        "diagnostics_endpoint" in item
        and not str(item.get("diagnostics_endpoint") or "").startswith("/api/v1/movies/")
    ):
        issues.append(f"{prefix}_diagnostics_endpoint_invalid")
    if "apply_method" in item and item.get("apply_method") != "PATCH":
        issues.append(f"{prefix}_apply_method={item.get('apply_method')}")
    if (
        "apply_endpoint" in item
        and not str(item.get("apply_endpoint") or "").startswith("/api/v1/movies/")
    ):
        issues.append(f"{prefix}_apply_endpoint_invalid")
    apply_payload = item.get("apply_payload")
    if "apply_payload" in item:
        if not isinstance(apply_payload, dict):
            issues.append(f"{prefix}_apply_payload_not_object")
        elif not isinstance(apply_payload.get("items"), list):
            issues.append(f"{prefix}_apply_payload_items_not_list")

    issues.extend(
        _dict_missing_keys(
            item.get("metadata_state"),
            EXPECTED_METADATA_STATE_KEYS,
            f"{prefix}_metadata_state",
        )
    )
    issues.extend(
        _dict_missing_keys(
            item.get("metadata_actions"),
            EXPECTED_METADATA_ACTION_KEYS,
            f"{prefix}_metadata_actions",
        )
    )
    return issues


def check_episode_review(client: SmokeClient, max_items: int) -> CheckResult:
    payload = client.get_json("/api/v1/metadata/episode-review-items", {"page_size": 20})
    data = _response_data(payload)
    total = _pagination_total(data)
    issues = []

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        issues.append("items_not_list")
        items = []
    if len(items) > 20:
        issues.append(f"too_many_items={len(items)}")
    if total > 0 and not items:
        issues.append("items_empty_with_total")
    for index, item in enumerate(items[:1]):
        issues.extend(_episode_review_item_issues(item, index))

    pagination = data.get("pagination") if isinstance(data, dict) else None
    issues.extend(_pagination_contract_issues(pagination, expected_page_size=20))
    if isinstance(pagination, dict) and pagination.get("total_items") != total:
        issues.append(f"pagination_total_mismatch={pagination.get('total_items')}/{total}")
    issues.extend(_episode_review_summary_issues(data.get("summary") if isinstance(data, dict) else None, total))
    if total > max_items:
        issues.append(f"total_above_max={total}/{max_items}")

    ok = not issues
    titles = [item.get("title") for item in items if isinstance(item, dict)]
    detail = f"total={total} max={max_items} items={len(items)}"
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "episode_review",
        ok,
        detail,
        {
            "total": total,
            "sample_titles": titles[:10],
            "issues": issues,
        },
    )


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


def _resource_governance_plan_item_issues(item: Any, index: int) -> list[str]:
    prefix = f"item_{index}"
    if not isinstance(item, dict):
        return [f"{prefix}_not_object"]

    issues = []
    issues.extend(_dict_missing_keys(item, EXPECTED_RESOURCE_GOVERNANCE_ITEM_KEYS, prefix))
    if item.get("status") not in {"planned", "skipped", "manual_review"}:
        issues.append(f"{prefix}_status={item.get('status')}")
    if item.get("status") == "planned":
        apply_item = item.get("apply_item")
        if not isinstance(apply_item, dict):
            issues.append(f"{prefix}_apply_item_not_object")
        elif apply_item.get("resource_id") != (item.get("resource") or {}).get("resource_id"):
            issues.append(f"{prefix}_apply_item_resource_id_mismatch")
    if "restore_snapshot_available" in item and item.get("restore_snapshot_available") not in (True, False):
        issues.append(f"{prefix}_restore_snapshot_available_not_bool")
    return issues


def _resource_governance_summary_issues(summary: Any, prefix: str) -> list[str]:
    issues = _dict_missing_keys(summary, EXPECTED_RESOURCE_GOVERNANCE_SUMMARY_KEYS, prefix)
    if not isinstance(summary, dict):
        return issues

    for key in ("total", "planned", "skipped", "manual_review"):
        if key in summary and not _json_int(summary.get(key)):
            issues.append(f"{prefix}_{key}_not_int")
    for key in ("planned_resource_ids",):
        if key in summary and not isinstance(summary.get(key), list):
            issues.append(f"{prefix}_{key}_not_list")
    for key in ("issue_code_counts", "skip_reason_counts"):
        if key in summary and not isinstance(summary.get(key), dict):
            issues.append(f"{prefix}_{key}_not_object")
    return issues


def check_resource_governance_plan(client: SmokeClient) -> CheckResult:
    payload = client.post_json(
        "/api/v1/resources/governance/plan",
        {
            "issue_codes": EXPECTED_RESOURCE_GOVERNANCE_ISSUE_CODES,
            "live_check": False,
            "limit": 1,
        },
    )
    data = _response_data(payload)
    issues = []

    issues.extend(_dict_missing_keys(data, EXPECTED_RESOURCE_GOVERNANCE_PLAN_KEYS, "plan"))
    if data.get("dry_run") is not True:
        issues.append("dry_run_not_true")
    if data.get("apply_method") != "POST":
        issues.append(f"apply_method={data.get('apply_method')}")
    if data.get("apply_endpoint") != "/api/v1/resources/governance/jobs":
        issues.append(f"apply_endpoint={data.get('apply_endpoint')}")

    selection = data.get("selection") if isinstance(data.get("selection"), dict) else {}
    selected_issue_codes = selection.get("issue_codes") if isinstance(selection, dict) else None
    if selected_issue_codes != EXPECTED_RESOURCE_GOVERNANCE_ISSUE_CODES:
        issues.append(f"selection_issue_codes={selected_issue_codes}")
    if selection.get("live_check") is not False:
        issues.append(f"selection_live_check={selection.get('live_check')}")
    if selection.get("limit") != 1:
        issues.append(f"selection_limit={selection.get('limit')}")

    plan_items = data.get("items")
    if not isinstance(plan_items, list):
        issues.append("items_not_list")
        plan_items = []
    if len(plan_items) > 1:
        issues.append(f"too_many_items={len(plan_items)}")
    for index, item in enumerate(plan_items[:1]):
        issues.extend(_resource_governance_plan_item_issues(item, index))

    apply_payload = data.get("apply_payload")
    apply_items = []
    if not isinstance(apply_payload, dict):
        issues.append("apply_payload_not_object")
    else:
        if apply_payload.get("confirm") is not True:
            issues.append(f"apply_payload_confirm={apply_payload.get('confirm')}")
        apply_items = apply_payload.get("items")
        if not isinstance(apply_items, list):
            issues.append("apply_payload_items_not_list")
            apply_items = []

    pagination = data.get("pagination")
    issues.extend(_pagination_contract_issues(pagination, expected_page_size=1))
    if isinstance(pagination, dict):
        if pagination.get("limit") != 1:
            issues.append(f"pagination_limit={pagination.get('limit')}")
        if pagination.get("paginated") not in (True, False):
            issues.append("pagination_paginated_not_bool")

    summary = data.get("summary")
    returned_summary = data.get("returned_summary")
    issues.extend(_resource_governance_summary_issues(summary, "summary"))
    issues.extend(_resource_governance_summary_issues(returned_summary, "returned_summary"))
    if isinstance(returned_summary, dict) and returned_summary.get("total") != len(plan_items):
        issues.append(f"returned_summary_total_mismatch={returned_summary.get('total')}/{len(plan_items)}")
    if isinstance(returned_summary, dict) and returned_summary.get("planned") != len(apply_items):
        issues.append(
            f"returned_summary_planned_mismatch={returned_summary.get('planned')}/{len(apply_items)}"
        )

    ok = not issues
    detail = (
        f"dry_run={data.get('dry_run')} items={len(plan_items)} "
        f"apply_items={len(apply_items)} "
        f"total={summary.get('total') if isinstance(summary, dict) else None}"
    )
    if issues:
        detail = f"{detail} issues={'; '.join(issues)}"
    return _result(
        "resource_governance_plan",
        ok,
        detail,
        {
            "dry_run": data.get("dry_run"),
            "item_count": len(plan_items),
            "apply_item_count": len(apply_items),
            "summary": summary if isinstance(summary, dict) else None,
            "returned_summary": returned_summary if isinstance(returned_summary, dict) else None,
            "issues": issues,
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
    expected_version = getattr(args, "expected_version", "")
    expected_openapi_version = getattr(args, "expected_openapi_version", "")
    checks = [
        CheckSpec("health", lambda: check_health(client, expected_version)),
        CheckSpec("auth_me", lambda: check_auth_me(client)),
        CheckSpec(
            "openapi_health_contract",
            lambda: check_openapi_health_contract(client, expected_openapi_version),
        ),
        CheckSpec(
            "docs_index",
            lambda: check_docs_index(client, expected_version, expected_openapi_version),
        ),
        CheckSpec("update_check", lambda: check_update_check(client, expected_version)),
        CheckSpec(
            "openapi_modules",
            lambda: check_openapi_modules(client, args.openapi_module_json_check, expected_openapi_version),
        ),
        CheckSpec("scan", lambda: check_scan(client)),
        CheckSpec("metadata_providers", lambda: check_metadata_providers(client)),
        CheckSpec("tmdb_config", lambda: check_tmdb_config(client)),
        CheckSpec("metadata_overview", lambda: check_metadata_overview(client)),
        CheckSpec("metadata_review_workbench", lambda: check_metadata_review_workbench(client)),
        CheckSpec("libraries", lambda: check_libraries(client)),
        CheckSpec("other_videos", lambda: check_other_videos(client)),
        CheckSpec("catalog_filters", lambda: check_catalog_filters(client)),
        CheckSpec("catalog_movies", lambda: check_catalog_movies(client)),
        CheckSpec("movie_detail", lambda: check_movie_detail(client)),
        CheckSpec("movie_images_status", lambda: check_movie_images_status(client)),
        CheckSpec("movie_resources", lambda: check_movie_resources(client)),
        CheckSpec("movie_seasons", lambda: check_movie_seasons(client)),
        CheckSpec("movie_episode_diagnostics", lambda: check_movie_episode_diagnostics(client)),
        CheckSpec("external_playback", lambda: check_external_playback(client)),
        CheckSpec("subtitle_settings", lambda: check_subtitle_settings(client)),
        CheckSpec("audio_transcode_diagnostics", lambda: check_audio_transcode_diagnostics(client)),
        CheckSpec("featured", lambda: check_featured(client)),
        CheckSpec("homepage_config", lambda: check_homepage_config(client)),
        CheckSpec("homepage", lambda: check_homepage(client)),
        CheckSpec("recommendations", lambda: check_recommendations(client)),
        CheckSpec("movie_context_recommendations", lambda: check_movie_context_recommendations(client)),
        CheckSpec("user_history", lambda: check_user_history(client)),
        CheckSpec("user_favorites", lambda: check_user_favorites(client)),
        CheckSpec("vault_status", lambda: check_vault_status(client)),
        CheckSpec(
            "metadata_work_items_contract",
            lambda: check_metadata_work_items_contract(client),
        ),
        CheckSpec(
            "metadata_reidentify_plan",
            lambda: check_metadata_reidentify_plan(client),
        ),
        CheckSpec("background_jobs", lambda: check_background_jobs(client)),
        CheckSpec(
            "background_jobs_prune",
            lambda: check_background_jobs_prune(client),
        ),
        CheckSpec("storage_provider_types", lambda: check_storage_provider_types(client)),
        CheckSpec("storage_capabilities", lambda: check_storage_capabilities(client)),
        CheckSpec("storage_sources", lambda: check_storage_sources(client, args.min_storage_sources)),
        CheckSpec("storage_browse", lambda: check_storage_browse(client)),
        CheckSpec(
            "metadata_fallback_pipeline_match",
            lambda: check_work_items(client, "fallback_pipeline_match", args.max_fallback_items),
        ),
        CheckSpec("episode_review", lambda: check_episode_review(client, args.max_episode_review_items)),
        CheckSpec(
            "resource_governance",
            lambda: check_resource_governance(client, args.live_check_limit, args.max_resource_actionable),
        ),
        CheckSpec(
            "resource_governance_plan",
            lambda: check_resource_governance_plan(client),
        ),
    ]
    if args.systemd:
        systemd_services = args.systemd_service or list(DEFAULT_SYSTEMD_SERVICES)
        checks.insert(0, CheckSpec("systemd_services", lambda: check_systemd_services(systemd_services, args.timeout)))
    if getattr(args, "tmdb_token_check", False):
        checks.append(CheckSpec("tmdb_token", lambda: check_tmdb_token(client)))
    if getattr(args, "storage_health_check", False):
        checks.append(CheckSpec(
            "storage_health",
            lambda: check_storage_health(client, getattr(args, "min_storage_health_checks", 0)),
        ))

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
        "--expected-version",
        default=DEFAULT_EXPECTED_VERSION,
        help="Expected runtime APP_VERSION; defaults to CYBER_BACKEND_EXPECTED_VERSION when set.",
    )
    parser.add_argument(
        "--expected-openapi-version",
        default=DEFAULT_EXPECTED_OPENAPI_VERSION,
        help=(
            "Expected OpenAPI snapshot version; defaults to "
            "CYBER_BACKEND_EXPECTED_OPENAPI_VERSION when set."
        ),
    )
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
        "--min-storage-health-checks",
        type=int,
        default=0,
        help="Minimum resource-backed storage health checks required when --storage-health-check is set.",
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
