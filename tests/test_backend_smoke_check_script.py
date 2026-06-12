from __future__ import annotations

import importlib.util
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT


SCRIPT_PATH = PROJECT_ROOT / "scripts/backend_smoke_check.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("backend_smoke_check", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeSmokeClient:
    last_init = None

    def __init__(self, base_url, timeout=10.0, api_token=None):
        self.base_url = base_url
        self.timeout = timeout
        self.api_token = api_token
        self.cookie_header = ""
        self.login_calls = []
        type(self).last_init = {
            "base_url": base_url,
            "timeout": timeout,
            "api_token": api_token,
        }

    def login(self, username, password):
        self.login_calls.append((username, password))
        self.cookie_header = "cyberstream_session=session-cookie"
        return {
            "data": {
                "user_management_enabled": True,
                "authenticated": True,
                "role": "admin",
                "auth_via": "session",
                "user": {
                    "id": 1,
                    "username": username,
                    "role": "admin",
                    "is_enabled": True,
                },
                "permissions": {
                    "admin": True,
                    "read_catalog": True,
                        "manage_catalog": True,
                        "manage_users": True,
                        "personal_history": True,
                        "personal_favorites": True,
                        "personal_vault": True,
                        "personal_subtitle_settings": True,
                    },
                },
        }

    def get_json(self, path, query=None):
        if path in {"/", "/api/v1/health"}:
            return {"data": {"status": "up", "version": "1.21.0", "database": {"status": "ok", "reason": "ok"}}}
        if path == "/api/v1/auth/me":
            return {
                "data": {
                    "user_management_enabled": False,
                    "authenticated": False,
                    "role": None,
                    "auth_via": None,
                    "user": None,
                    "permissions": {
                        "admin": False,
                        "read_catalog": False,
                        "manage_catalog": False,
                        "manage_users": False,
                        "personal_history": False,
                        "personal_favorites": False,
                        "personal_vault": False,
                        "personal_subtitle_settings": False,
                    },
                },
            }
        if path == "/api/v1/system/update-check":
            current_version = (query or {}).get("current_version") or "1.21.0"
            current_release = (query or {}).get("current_release") or f"{current_version}-pc.0"
            download = {
                "variant": "full",
                "name": "CyberStream_1.21.1-pc.5_full_x64.msi",
                "platform": (query or {}).get("platform") or "windows",
                "arch": (query or {}).get("arch") or "x64",
                "url": "https://qwk.ccwu.cc/cyberstream/CyberStream_1.21.1-pc.5_full_x64.msi",
                "cdn": True,
                "size": 123456,
                "sha256": "a" * 64,
                "content_type": "application/octet-stream",
                "label": "Full installer",
                "notes": None,
            }
            return {
                "data": {
                    "product": "CyberStream",
                    "channel": "stable",
                    "platform": (query or {}).get("platform") or "windows",
                    "arch": (query or {}).get("arch") or "x64",
                    "variant": None,
                    "current": {
                        "version": current_version,
                        "release": current_release,
                        "backend_version": "1.21.0",
                    },
                    "latest": {
                        "version": "1.21.1",
                        "release": "1.21.1-pc.5",
                        "tag": "v1.21.1-pc.5",
                        "title": "CyberStream PC 1.21.1-pc.5",
                        "released_at": None,
                        "notes": None,
                        "notes_url": None,
                        "mandatory": False,
                        "minimum_supported_version": None,
                    },
                    "update_available": True,
                    "downloads": [download],
                    "selected_download": download,
                    "cdn": {
                        "required": True,
                        "validated": True,
                    },
                    "source": "manifest",
                    "warnings": [],
                    "checked_at": "2026-06-07T00:00:00Z",
                },
            }
        if path == "/api/v1/openapi.json":
            return {
                "openapi": "3.0.0",
                "info": {
                    "title": "Cyber Media Center API",
                    "version": "1.21.0-beta",
                },
                "paths": {
                    "/api/v1/health": {
                        "get": {
                            "operationId": "apiHealthCheck",
                            "security": [],
                        },
                    },
                },
                "components": {"schemas": {}},
            }
        if path == "/api/v1/docs":
            keys = [
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
            return {
                "data": {
                    "version": "1.21.0",
                    "openapi_version": "1.21.0-beta",
                    "openapi": {
                        "available": True,
                        "content_type": "application/json",
                        "url": "/api/v1/openapi.json",
                        "docs_url": "/api/v1/docs/openapi.json",
                        "modules_url": "/api/v1/openapi/modules",
                    },
                    "documents": [
                        {
                            "key": key,
                            "title": key,
                            "available": True,
                            "format": "markdown",
                            "content_type": "text/markdown; charset=utf-8",
                            "url": f"/api/v1/docs/{key}",
                        }
                        for key in keys
                    ],
                },
            }
        if path == "/api/v1/openapi/modules":
            keys = [
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
            return {
                "data": {
                    "openapi_version": "1.21.0-beta",
                    "full_url": "/api/v1/openapi.json",
                    "modules": [
                        {
                            "key": key,
                            "available": True,
                            "content_type": "application/json",
                            "path_count": 1,
                            "url": f"/api/v1/openapi/modules/{key}.json",
                        }
                        for key in keys
                    ],
                },
            }
        if path.startswith("/api/v1/openapi/modules/") and path.endswith(".json"):
            return {
                "openapi": "3.0.0",
                "info": {
                    "title": "CyberStream API",
                    "version": "1.21.0-beta",
                },
                "paths": {"/api/v1/health": {"get": {}}},
                "components": {"schemas": {}},
            }
        if path == "/api/v1/aggregator/sources":
            return {
                "data": {
                    "sources": ["bt7274", "btbtla", "rarbt", "yinfans", "renrenys", "hdzu", "4kzhinan"],
                    "priority": ["bt7274", "rarbt", "btbtla", "yinfans", "renrenys", "hdzu", "4kzhinan"],
                    "default": "rarbt",
                },
            }
        if path == "/api/v1/scan":
            return {"data": {"status": "idle", "recent_errors": []}}
        if path == "/api/v1/metadata/providers":
            return {
                "data": {
                    "default_order": ["nfo", "tmdb", "local"],
                    "providers": [
                        {"key": "nfo", "supports_scrape": True, "supports_search": False},
                        {"key": "tmdb", "supports_scrape": True, "supports_search": True},
                        {
                            "key": "anilist",
                            "default_enabled": False,
                            "supports_scrape": True,
                            "supports_search": True,
                        },
                        {"key": "bangumi", "supports_scrape": True, "supports_search": True},
                        {
                            "key": "tencent_video",
                            "manual_only": True,
                            "supports_scrape": False,
                            "supports_search": True,
                        },
                        {"key": "local", "supports_scrape": True, "supports_search": False},
                    ],
                },
            }
        if path == "/api/v1/metadata/overview":
            return {
                "data": {
                    "totals": {
                        "movie_count": 359,
                        "needs_attention_count": 14,
                        "placeholder_count": 0,
                        "local_only_count": 0,
                        "external_match_count": 359,
                        "low_confidence_resource_count": 0,
                        "fallback_resource_count": 139,
                        "locked_movie_count": 0,
                        "nfo_candidate_movie_count": 14,
                    },
                    "source_groups": [
                        {"key": "tmdb", "count": 359},
                    ],
                    "review_priorities": [
                        {"key": "low", "count": 349},
                        {"key": "none", "count": 10},
                    ],
                    "recommended_actions": [
                        {"key": "refresh_metadata", "count": 349},
                        {"key": "none", "count": 10},
                    ],
                    "issues": [
                        {"key": "nfo_candidates_available", "count": 14},
                    ],
                },
            }
        if path == "/api/v1/metadata/review-taxonomy":
            return {
                "data": {
                    "buckets": [
                        {
                            "id": "normal_catalog",
                            "entrypoints": [{"endpoint": "/api/v1/movies", "method": "GET"}],
                        },
                        {
                            "id": "metadata_review",
                            "entrypoints": [{"endpoint": "/api/v1/metadata/work-items", "method": "GET"}],
                        },
                        {
                            "id": "manual_content",
                            "entrypoints": [{"endpoint": "/api/v1/other-videos", "method": "GET"}],
                        },
                        {
                            "id": "episode_review",
                            "entrypoints": [{"endpoint": "/api/v1/metadata/episode-review-items", "method": "GET"}],
                        },
                        {
                            "id": "resource_governance",
                            "entrypoints": [{"endpoint": "/api/v1/resources/governance-summary", "method": "GET"}],
                        },
                        {
                            "id": "catalog_visibility",
                            "entrypoints": [{"endpoint": "/api/v1/movies/{movie_id}/catalog-visibility", "method": "PATCH"}],
                        },
                    ],
                    "actions": [
                        {"id": "none"},
                        {"id": "refresh_metadata", "method": "POST"},
                        {"id": "re_scrape", "method": "POST"},
                        {"id": "batch_reidentify_plan", "method": "POST"},
                        {"id": "match_metadata"},
                        {"id": "review_match", "method": "POST"},
                        {"id": "rename_and_match"},
                        {"id": "edit_episode_metadata", "method": "PATCH"},
                        {"id": "resource_governance_plan", "method": "POST"},
                        {"id": "resource_live_check", "method": "POST"},
                        {"id": "manual_review"},
                        {"id": "create_manual_content", "method": "POST"},
                        {"id": "inspect_metadata", "method": "GET"},
                        {"id": "catalog_publish", "method": "POST"},
                    ],
                },
            }
        if path == "/api/v1/metadata/quality-summary":
            return {
                "data": {
                    "totals": {
                        "movie_count": 359,
                        "issue_movie_count": 1,
                        "bulk_reidentify_movie_count": 0,
                        "episode_review_movie_count": 0,
                    },
                    "actions": [
                        {
                            "id": "bulk_reidentify",
                            "endpoint": "/api/v1/metadata/re-scrape/plan",
                            "method": "POST",
                            "enabled": False,
                        },
                        {
                            "id": "episode_review_queue",
                            "endpoint": "/api/v1/metadata/episode-review-items",
                            "method": "GET",
                            "enabled": False,
                        },
                    ],
                    "issues": [
                        {
                            "code": "nfo_candidates_available",
                            "label": "NFO Candidates Available",
                            "movie_count": 1,
                            "affected_count": 1,
                            "samples": [
                                {
                                    "movie_id": "movie-1",
                                    "title": "Sample Movie",
                                    "scraper_source": "TMDB",
                                    "metadata_state": {
                                        "source_group": "tmdb",
                                        "source_code": "TMDB",
                                        "source_label": "TMDB",
                                        "issue_codes": ["nfo_candidates_available"],
                                        "needs_attention": False,
                                        "review_priority": "low",
                                        "recommended_action": "refresh_metadata",
                                    },
                                    "metadata_actions": {
                                        "can_manual_match": True,
                                        "can_refresh": True,
                                        "can_re_scrape": True,
                                        "primary_action": "refresh_metadata",
                                    },
                                    "matching_issue": {
                                        "code": "nfo_candidates_available",
                                        "count": 1,
                                        "label": "NFO Candidates Available",
                                        "severity": "low",
                                    },
                                },
                            ],
                        },
                    ],
                },
            }
        if path == "/api/v1/user/achievements":
            return {
                "data": {
                    "defs": [
                        {
                            "id": "network_legend",
                            "title": "Network Legend",
                            "desc": "Complete 100 movies",
                            "icon": "Trophy",
                            "category": "milestone",
                            "trigger": {
                                "metric": "completed_movies_count",
                                "op": ">=",
                                "value": 100,
                            },
                        },
                        {
                            "id": "overclock",
                            "title": "Overclock",
                            "desc": "Use 2x playback",
                            "icon": "Gauge",
                            "category": "behavior",
                        },
                    ],
                    "user": [
                        {
                            "id": "network_legend",
                            "unlocked_at": None,
                            "progress": 0,
                        },
                        {
                            "id": "overclock",
                            "unlocked_at": None,
                        },
                    ],
                    "summary": {
                        "total": 2,
                        "unlocked": 0,
                        "milestones": 1,
                        "behaviors": 1,
                        "newly_unlocked_ids": [],
                    },
                },
            }
        if path == "/api/v1/filters":
            return {
                "data": {
                    "genres": [
                        {
                            "name": "动作",
                            "slug": "动作",
                            "count": 1,
                        },
                    ],
                    "years": [
                        {
                            "year": 2024,
                            "count": 1,
                        },
                    ],
                    "countries": [
                        {
                            "name": "Japan",
                            "code": "Japan",
                            "count": 1,
                        },
                    ],
                    "metadata_source_groups": [
                        {
                            "name": "tmdb",
                            "slug": "tmdb",
                            "count": 1,
                        },
                    ],
                    "metadata_review_priorities": [
                        {
                            "name": "low",
                            "slug": "low",
                            "count": 1,
                        },
                    ],
                    "metadata_issue_codes": [
                        {
                            "name": "poster_missing",
                            "slug": "poster_missing",
                            "count": 1,
                        },
                    ],
                },
            }
        if path == "/api/v1/system/tmdb-config":
            return {
                "data": {
                    "token_set": True,
                    "proxy_enabled": True,
                    "proxy_url": "http://127.0.0.1:7890",
                    "proxy_url_redacted": False,
                },
            }
        if path == "/api/v1/system/tmdb-config/check":
            return {
                "data": {
                    "ready": True,
                    "status": "ok",
                    "token_set": True,
                    "token_valid": True,
                    "proxy_enabled": True,
                    "proxy_configured": True,
                    "elapsed_ms": 123,
                    "http_status": 200,
                },
            }
        if path == "/api/v1/storage/provider-types":
            return {
                "data": [
                    {
                        "type": "local",
                        "display_name": "Local Filesystem",
                        "status": "stable",
                        "capabilities": {
                            "preview": True,
                            "scan": True,
                            "stream": True,
                            "ffmpeg_input": True,
                            "health_check": True,
                            "credentials_required": False,
                        },
                        "config_fields": [
                            {
                                "name": "root_path",
                                "type": "string",
                                "required": True,
                                "description": "Local root path",
                            },
                        ],
                    },
                    {
                        "type": "alist",
                        "display_name": "AList",
                        "status": "stable",
                        "capabilities": {
                            "preview": True,
                            "scan": True,
                            "refresh": True,
                            "stream": True,
                            "ffmpeg_input": True,
                            "health_check": True,
                            "credentials_required": True,
                            "redirect_stream": True,
                        },
                        "config_fields": [
                            {"name": "base_url", "type": "string", "required": False},
                            {"name": "host", "type": "string", "required": False},
                            {"name": "root", "type": "string", "required": False},
                        ],
                    },
                    {
                        "type": "openlist",
                        "display_name": "OpenList",
                        "status": "stable",
                        "capabilities": {
                            "preview": True,
                            "scan": True,
                            "refresh": True,
                            "stream": True,
                            "ffmpeg_input": True,
                            "health_check": True,
                            "credentials_required": True,
                            "redirect_stream": True,
                        },
                        "config_fields": [
                            {"name": "base_url", "type": "string", "required": False},
                            {"name": "host", "type": "string", "required": False},
                            {"name": "root", "type": "string", "required": False},
                        ],
                    },
                    {
                        "type": "guangyapan",
                        "display_name": "GuangYaPan",
                        "status": "beta",
                        "capabilities": {
                            "preview": True,
                            "scan": True,
                            "refresh": True,
                            "stream": True,
                            "ffmpeg_input": True,
                            "health_check": True,
                            "credentials_required": False,
                            "redirect_stream": True,
                            "managed": True,
                            "sms_login": True,
                        },
                        "config_fields": [
                            {"name": "alist_storage_id", "type": "integer", "required": True},
                            {"name": "mount_path", "type": "string", "required": True},
                            {"name": "auth_state", "type": "string", "required": False},
                            {"name": "cloud_root_path", "type": "string", "required": False},
                        ],
                    },
                ],
            }
        if path == "/api/v1/storage/capabilities":
            return {
                "data": {
                    "supported_types": ["local", "alist", "openlist", "guangyapan"],
                    "items": [
                        {
                            "type": "local",
                            "display_name": "Local Filesystem",
                            "label": "Local Filesystem",
                            "browse": True,
                            "validate_path": True,
                            "range_stream": True,
                            "library_root_path": True,
                            "config_root_key": "root_path",
                            "preview": True,
                            "scan": True,
                            "stream": True,
                            "ffmpeg_input": True,
                            "health_check": True,
                            "credentials_required": False,
                        },
                        {
                            "type": "alist",
                            "display_name": "AList",
                            "label": "AList",
                            "browse": True,
                            "validate_path": True,
                            "range_stream": True,
                            "library_root_path": True,
                            "config_root_key": "root",
                            "preview": True,
                            "scan": True,
                            "stream": True,
                            "ffmpeg_input": True,
                            "health_check": True,
                            "credentials_required": True,
                        },
                        {
                            "type": "openlist",
                            "display_name": "OpenList",
                            "label": "OpenList",
                            "browse": True,
                            "validate_path": True,
                            "range_stream": True,
                            "library_root_path": True,
                            "config_root_key": "root",
                            "preview": True,
                            "scan": True,
                            "stream": True,
                            "ffmpeg_input": True,
                            "health_check": True,
                            "credentials_required": True,
                        },
                        {
                            "type": "guangyapan",
                            "display_name": "GuangYaPan",
                            "label": "GuangYaPan",
                            "browse": True,
                            "validate_path": True,
                            "range_stream": True,
                            "library_root_path": True,
                            "config_root_key": "root",
                            "preview": True,
                            "scan": True,
                            "stream": True,
                            "health_check": True,
                            "credentials_required": False,
                            "managed": True,
                            "sms_login": True,
                            "redirect_stream": True,
                            "refresh": True,
                        },
                    ],
                },
            }
        if path == "/api/v1/storage/sources":
            return {
                "data": [
                    {
                        "id": 1,
                        "name": "GuangYaPan",
                        "type": "guangyapan",
                        "is_supported": True,
                        "config_valid": True,
                        "config": {"auth_state": "ready"},
                        "capabilities": {"health_check": True},
                        "actions": {
                            "can_preview": True,
                            "can_scan": True,
                            "can_stream": True,
                            "can_refresh": True,
                        },
                        "usage": {
                            "has_resources": True,
                            "resource_count": 464,
                            "library_binding_count": 0,
                        },
                    },
                ],
            }
        if path == "/api/v1/storage/sources/1":
            return {
                "data": {
                    "id": 1,
                    "name": "GuangYaPan",
                    "type": "guangyapan",
                    "display_name": "GuangYaPan",
                    "root_path": "GuangYaPan:/",
                    "status": "unknown",
                    "is_supported": True,
                    "config_valid": True,
                    "config_error": None,
                    "capabilities": {
                        "preview": True,
                        "scan": True,
                        "stream": True,
                        "health_check": True,
                        "managed": True,
                        "sms_login": True,
                        "redirect_stream": True,
                        "refresh": True,
                    },
                    "config": {
                        "auth_state": "ready",
                        "cloud_root_path": "/",
                        "phone_number_masked": "+*********2920",
                    },
                    "actions": {
                        "can_preview": True,
                        "can_scan": True,
                        "can_stream": True,
                        "can_refresh": True,
                    },
                    "usage": {
                        "has_resources": True,
                        "resource_count": 464,
                        "library_binding_count": 0,
                    },
                    "guards": {
                        "can_change_type": False,
                        "can_delete": True,
                        "can_delete_directly": False,
                        "requires_pin_on_delete": True,
                        "requires_keep_metadata_on_delete": True,
                        "has_dependents": True,
                    },
                },
            }
        if path == "/api/v1/storage/sources/1/health":
            return {
                "data": {
                    "id": 1,
                    "name": "GuangYaPan",
                    "type": "guangyapan",
                    "health": {
                        "status": "online",
                        "reason": "ok",
                        "message": "GuangYaPan reachable",
                    },
                },
            }
        if path == "/api/v1/storage/sources/1/browse":
            return {
                "data": {
                    "source": {
                        "id": 1,
                        "name": "GuangYaPan",
                        "type": "guangyapan",
                        "is_supported": True,
                        "config_valid": True,
                        "actions": {
                            "can_preview": True,
                            "can_scan": True,
                            "can_stream": True,
                        },
                    },
                    "current_path": "/",
                    "parent_path": None,
                    "items": [
                        {
                            "name": "Movies",
                            "path": "Movies",
                            "type": "dir",
                            "size": 0,
                        },
                    ],
                },
            }
        if path == "/api/v1/libraries":
            return {
                "data": [
                    {
                        "id": 1,
                        "name": "Movies",
                        "slug": "movies",
                        "description": "Primary movie library",
                        "is_enabled": True,
                        "sort_order": 0,
                        "settings": {},
                        "created_at": "2026-06-07T00:00:00",
                        "updated_at": "2026-06-07T00:00:01",
                    },
                ],
            }
        if path == "/api/v1/other-videos":
            resource_id = "resource-other-1"
            movie_id = "movie-other-1"
            return {
                "data": {
                    "items": [
                        {
                            "resource_id": resource_id,
                            "movie_id": movie_id,
                            "movie_title": "Raw Sample",
                            "movie_original_title": "Raw Sample",
                            "movie_year": None,
                            "movie_manual_content": {
                                "is_manual": False,
                                "media_type": None,
                            },
                            "resource_info": {
                                "file": {
                                    "filename": "Raw.Sample.2026.mp4",
                                    "relative_path": "other/Raw.Sample.2026.mp4",
                                    "size_bytes": 234567,
                                },
                                "display": {
                                    "title": "Raw.Sample.2026.mp4",
                                    "label": "Other video",
                                    "season": None,
                                    "episode": None,
                                },
                                "technical": {
                                    "video_resolution_bucket": "1080p",
                                },
                            },
                            "playback": {
                                "stream_url": f"/api/v1/resources/{resource_id}/stream",
                                "web_player": {
                                    "supported": True,
                                    "url": f"/api/v1/resources/{resource_id}/stream",
                                },
                                "external_player": {
                                    "supported": True,
                                    "url": f"/api/v1/resources/{resource_id}/stream",
                                },
                                "subtitles": {
                                    "items": [],
                                    "settings": {},
                                },
                                "cloud_transcode": {
                                    "supported": False,
                                    "provider": None,
                                    "provider_name": None,
                                    "mode": None,
                                    "qualities_endpoint": None,
                                    "stream_endpoint": None,
                                    "resolution_param": "resolution",
                                    "available_resolutions": [],
                                    "recommended_for": [],
                                    "quality_semantics": None,
                                    "reason": "provider_not_supported",
                                },
                            },
                            "metadata": {
                                "trace": {},
                                "analysis": {
                                    "path_cleaning": {
                                        "title_hint": "Raw Sample",
                                    },
                                },
                                "edit_context": {},
                            },
                            "catalog_visibility": {
                                "effective_status": "hidden",
                                "status": "hidden",
                                "is_visible": False,
                                "can_publish": True,
                            },
                            "metadata_state": {
                                "source_group": "local",
                                "source_code": "LOCAL_FALLBACK",
                                "source_label": "Local Fallback",
                                "issue_codes": ["local_placeholder"],
                                "needs_attention": True,
                                "review_priority": "high",
                                "recommended_action": "match_metadata",
                            },
                            "metadata_issues": [
                                {
                                    "code": "local_placeholder",
                                    "severity": "warning",
                                },
                            ],
                            "metadata_actions": {
                                "can_manual_match": True,
                                "can_refresh": False,
                                "can_re_scrape": True,
                                "primary_action": "match_metadata",
                            },
                            "metadata_match_context": {
                                "suggested_query": "Raw Sample",
                                "suggested_year": None,
                                "suggested_media_type_hint": "movie",
                                "source_media_type_hint": None,
                                "media_type_options": ["movie", "tv"],
                                "title_hint_source": "path_cleaning",
                            },
                            "recommended_resolution": "match_metadata",
                            "actions": {
                                "create_manual_movie": {
                                    "method": "POST",
                                    "endpoint": "/api/v1/movies/manual",
                                    "body": {
                                        "title": "Raw Sample",
                                        "media_type": "movie",
                                        "resource_ids": [resource_id],
                                    },
                                },
                                "match_metadata": {
                                    "search": {
                                        "method": "GET",
                                        "endpoint": f"/api/v1/movies/{movie_id}/metadata/search",
                                        "params": {
                                            "query": "Raw Sample",
                                            "media_type_hint": "movie",
                                        },
                                    },
                                    "preview": {
                                        "method": "POST",
                                        "endpoint": f"/api/v1/movies/{movie_id}/metadata/match",
                                        "body_template": {
                                            "candidate_id": "<candidate_id>",
                                            "provider": "<provider>",
                                            "media_type_hint": "movie",
                                        },
                                    },
                                    "apply": {
                                        "method": "POST",
                                        "endpoint": f"/api/v1/movies/{movie_id}/metadata/match",
                                        "body_template": {
                                            "candidate_id": "<candidate_id>",
                                            "provider": "<provider>",
                                            "media_type_hint": "movie",
                                            "apply": True,
                                        },
                                    },
                                },
                            },
                        },
                    ],
                    "pagination": {
                        "current_page": 1,
                        "page_size": 1,
                        "total_items": 1,
                        "total_pages": 1,
                    },
                    "summary": {
                        "total_items": 1,
                        "manual_movie_count": 0,
                    },
                    "actions": {
                        "create_manual_movie": {
                            "method": "POST",
                            "endpoint": "/api/v1/movies/manual",
                        },
                        "attach_resources": {
                            "method": "POST",
                            "endpoint": "/api/v1/movies/{movie_id}/resources/attach",
                        },
                    },
                },
            }
        if path == "/api/v1/movies":
            page_size = (query or {}).get("page_size") or 1
            metadata_issue_code = (query or {}).get("metadata_issue_code")
            metadata_issue_codes = [metadata_issue_code] if metadata_issue_code else []
            return {
                "data": {
                    "items": [
                        {
                            "id": "movie-1",
                            "title": "Sample Movie",
                            "poster_url": "https://example.test/poster.jpg",
                            "poster_asset_url": "/api/v1/movies/movie-1/images/poster",
                            "poster_asset_urls": {
                                "kind": "poster",
                                "primary_url": "/api/v1/movies/movie-1/images/poster",
                                "fallback_urls": ["https://example.test/poster.jpg"],
                            },
                            "poster_asset_fallback_urls": ["https://example.test/poster.jpg"],
                            "poster_source_info": {
                                "kind": "poster",
                                "provider": "tmdb",
                                "source_type": "external_metadata",
                            },
                            "rating": 7.2,
                            "year": 2024,
                            "country": "Japan",
                            "quality_badge": "HD",
                            "scraper_source": "TMDB",
                            "metadata_state": {
                                "source_group": "tmdb",
                                "source_code": "TMDB",
                                "source_label": "TMDB",
                                "issue_codes": metadata_issue_codes,
                                "needs_attention": bool(metadata_issue_code),
                                "review_priority": "medium" if metadata_issue_code else "low",
                                "recommended_action": "refresh_metadata",
                            },
                            "catalog_visibility": {
                                "effective_status": "published",
                                "status": "published",
                                "is_visible": True,
                                "can_publish": True,
                            },
                            "manual_content": {
                                "is_manual": False,
                                "media_type": None,
                                "scraper_source": "TMDB",
                            },
                            "date_added": "2026-06-07T00:00:00",
                            "updated_at": "2026-06-07T00:00:01",
                            "tags": ["动作"],
                            "source_ids": [1],
                            "season_cards": [],
                            "season_count": 0,
                            "has_multi_season_content": False,
                            "user_data": None,
                        },
                    ],
                    "pagination": {
                        "current_page": 1,
                        "page_size": page_size,
                        "total_items": 1,
                        "total_pages": 1,
                    },
                },
            }
        if path == "/api/v1/movies/movie-1":
            base_payload = FakeSmokeClient.get_json(self, "/api/v1/movies", query=query)
            base_movie = base_payload["data"]["items"][0]
            detail = base_movie.copy()
            detail.update({
                "original_title": "Sample Movie",
                "overview": "A sample movie for smoke tests.",
                "backdrop_url": "https://example.test/backdrop.jpg",
                "backdrop_asset_url": "/api/v1/movies/movie-1/images/backdrop",
                "backdrop_asset_urls": {
                    "kind": "backdrop",
                    "primary_url": "/api/v1/movies/movie-1/images/backdrop",
                    "fallback_urls": ["https://example.test/backdrop.jpg"],
                },
                "backdrop_asset_fallback_urls": ["https://example.test/backdrop.jpg"],
                "backdrop_source_info": {
                    "kind": "backdrop",
                    "provider": "tmdb",
                    "source_type": "external_metadata",
                },
                "director": "Sample Director",
                "actors": [
                    {
                        "name": "Sample Actor",
                        "role": "Actor",
                        "avatar": "",
                    },
                ],
                "metadata_locked_fields": [],
                "metadata_actions": {
                    "can_manual_match": True,
                    "can_refresh": True,
                    "can_re_scrape": True,
                    "primary_action": "refresh_metadata",
                },
                "metadata_diagnostics": {
                    "resource_count": 1,
                },
                "metadata_issues": [],
            })
            return {"data": detail}
        if path == "/api/v1/movies/movie-1/images/status":
            items = []
            for kind, field, public_field, source_url in (
                ("backdrop", "background_cover", "backdrop_url", "https://example.test/backdrop.jpg"),
                ("poster", "cover", "poster_url", "https://example.test/poster.jpg"),
            ):
                local_url = f"/api/v1/movies/movie-1/images/{kind}"
                items.append({
                    "kind": kind,
                    "asset_url": local_url,
                    "asset_urls": {
                        "kind": kind,
                        "strategy": "cdn_local_original",
                        "primary_url": local_url,
                        "url": local_url,
                        "cdn_url": None,
                        "local_url": local_url,
                        "original_url": source_url,
                        "fallback_urls": [source_url],
                        "source": "local",
                    },
                    "fallback_urls": [source_url],
                    "source_url": source_url,
                    "source_info": {
                        "kind": kind,
                        "field": field,
                        "public_field": public_field,
                        "source_url": source_url,
                        "has_source": True,
                        "source_type": "external_metadata",
                        "provider": "tmdb",
                        "provider_label": "TMDB",
                        "scraper_source": "TMDB",
                        "metadata_source_group": "tmdb",
                        "metadata_source_label": "TMDB",
                        "locked": False,
                        "confidence": "high",
                        "evidence": ["image_url_host"],
                    },
                    "has_source": True,
                    "source_valid": True,
                    "source_error": None,
                    "cached": False,
                    "cache_state": "missing",
                    "source_changed": False,
                    "cache": None,
                    "cdn": None,
                })
            return {
                "data": {
                    "movie_id": "movie-1",
                    "title": "Sample Movie",
                    "items": items,
                    "summary": {
                        "total": 2,
                        "cached": 0,
                        "missing": 2,
                        "missing_source": 0,
                        "invalid_source": 0,
                        "stale_source": 0,
                    },
                },
            }
        if path == "/api/v1/movies/movie-1/resources":
            return {
                "data": {
                    "items": [
                        {
                            "id": "resource-1",
                            "resource_info": {
                                "file": {
                                    "filename": "Sample.Movie.2024.1080p.mkv",
                                    "relative_path": "movies/Sample.Movie.2024.1080p.mkv",
                                    "size_bytes": 123456,
                                    "storage_source": {
                                        "id": 1,
                                        "name": "GuangYaPan",
                                        "type": "guangyapan",
                                    },
                                },
                                "display": {
                                    "title": "Sample.Movie.2024.1080p.mkv",
                                    "label": "Movie - 1080P",
                                    "season": None,
                                    "episode": None,
                                    "has_manual_metadata": False,
                                },
                                "technical": {
                                    "video_resolution_bucket": "1080p",
                                    "video_codec_code": "h264",
                                },
                            },
                            "playback": {
                                "stream_url": "/api/v1/resources/resource-1/stream",
                                "web_player": {
                                    "supported": True,
                                    "url": "/api/v1/resources/resource-1/stream",
                                },
                                "external_player": {
                                    "supported": True,
                                    "url": "/api/v1/resources/resource-1/stream",
                                },
                                "subtitles": {
                                    "items": [],
                                    "settings": {},
                                },
                                "cloud_transcode": {
                                    "supported": False,
                                    "provider": None,
                                    "provider_name": None,
                                    "mode": None,
                                    "qualities_endpoint": None,
                                    "stream_endpoint": None,
                                    "resolution_param": "resolution",
                                    "available_resolutions": [],
                                    "recommended_for": [],
                                    "quality_semantics": None,
                                    "reason": "provider_not_supported",
                                },
                                "playback_modes": ["redirect"],
                                "range_supported": True,
                            },
                            "metadata": {
                                "trace": {},
                                "analysis": {},
                                "edit_context": {},
                            },
                            "user_data": None,
                        },
                    ],
                    "groups": {
                        "standalone": {
                            "resource_ids": ["resource-1"],
                            "primary_resource_ids": ["resource-1"],
                            "count": 1,
                            "playback_source_count": 1,
                            "alternate_resource_count": 0,
                            "user_data": None,
                        },
                        "seasons": [],
                        "playback_sources": [
                            {
                                "id": "ps_resource_1",
                                "primary_resource_id": "resource-1",
                                "resource_ids": ["resource-1"],
                                "alternate_resource_ids": [],
                                "count": 1,
                                "is_duplicate_group": False,
                                "duplicate_key": {},
                                "match": {},
                                "display": {
                                    "title": "Sample.Movie.2024.1080p.mkv",
                                    "label": "Movie - 1080P",
                                    "season": None,
                                    "episode": None,
                                    "episode_label": None,
                                },
                                "file": {
                                    "filename": "Sample.Movie.2024.1080p.mkv",
                                    "size_bytes": 123456,
                                },
                                "source_summary": [
                                    {
                                        "id": 1,
                                        "name": "GuangYaPan",
                                        "type": "guangyapan",
                                    },
                                ],
                                "user_data": None,
                            },
                        ],
                    },
                    "summary": {
                        "total_items": 1,
                        "hydrated_item_count": 1,
                        "selected_season": None,
                        "playback_source_count": 1,
                        "hydrated_playback_source_count": 1,
                        "duplicate_group_count": 0,
                        "alternate_resource_count": 0,
                        "season_count": 0,
                        "standalone_count": 1,
                        "edited_items_count": 0,
                        "season_metadata_count": 0,
                        "episode_diagnostics": {},
                        "metadata_source_group": "tmdb",
                        "has_placeholder_metadata": False,
                        "is_local_only_metadata": False,
                        "needs_attention": False,
                        "review_priority": "low",
                    },
                },
            }
        if path == "/api/v1/movies/movie-1/seasons":
            return {
                "data": {
                    "items": [
                        {
                            "season": 1,
                            "title": "Season 1",
                            "display_title": "Season 1",
                            "overview": "The first season.",
                            "air_date": "2026-01-01",
                            "poster_url": "https://example.test/season.jpg",
                            "poster_source": "season",
                            "resource_ids": ["resource-1"],
                            "primary_resource_ids": ["resource-1"],
                            "playback_source_count": 1,
                            "alternate_resource_count": 0,
                            "edited_items_count": 1,
                            "episode_count": 1,
                            "tmdb_episode_count": 1,
                            "expected_episode_count": 1,
                            "aired_episode_count": None,
                            "has_distinct_poster": True,
                            "has_manual_metadata": True,
                            "has_metadata": True,
                            "metadata_edited_at": None,
                            "episode_diagnostics": {
                                "status": "ok",
                                "coverage_status": "complete",
                                "issue_codes": [],
                                "available_episode_count": 1,
                                "available_episode_numbers": [1],
                                "missing_episode_numbers": [],
                                "duplicate_episode_numbers": [],
                                "duplicate_episode_resources": [],
                                "alternate_episode_numbers": [],
                                "alternate_episode_resources": [],
                                "unnumbered_resource_ids": [],
                                "completion_ratio": 1.0,
                                "expected_episode_count": 1,
                                "expected_source": "metadata",
                                "first_episode": 1,
                                "last_episode": 1,
                            },
                            "sort": {
                                "season": 1,
                                "first_episode": 1,
                            },
                            "user_data": None,
                        },
                    ],
                    "summary": {
                        "total_items": 1,
                        "hydrated_item_count": 1,
                        "selected_season": None,
                        "playback_source_count": 1,
                        "hydrated_playback_source_count": 1,
                        "duplicate_group_count": 0,
                        "alternate_resource_count": 0,
                        "season_count": 1,
                        "standalone_count": 0,
                        "edited_items_count": 1,
                        "season_metadata_count": 1,
                        "episode_diagnostics": {
                            "status": "ok",
                            "coverage_status": "complete",
                            "issue_count": 0,
                            "issue_code_counts": {},
                            "season_count": 1,
                            "seasons_needing_attention": [],
                        },
                        "metadata_source_group": "tmdb",
                        "has_placeholder_metadata": False,
                        "is_local_only_metadata": False,
                        "needs_attention": False,
                        "review_priority": "low",
                    },
                },
            }
        if path == "/api/v1/movies/movie-1/episode-diagnostics":
            suggestion = {
                "type": "update_resource_episode",
                "reason": "fill_missing_episode_slot",
                "resource_id": "resource-2",
                "confidence": "high",
                "current": {"season": 1, "episode": None},
                "suggested": {"season": 1, "episode": 2},
                "apply_item": {"id": "resource-2", "season": 1, "episode": 2},
            }
            return {
                "data": {
                    "movie_id": "movie-1",
                    "title": "Sample Movie",
                    "dry_run": True,
                    "apply_method": "PATCH",
                    "apply_endpoint": "/api/v1/movies/movie-1/resources/metadata",
                    "apply_payload": {
                        "items": [
                            {"id": "resource-2", "season": 1, "episode": 2},
                        ],
                    },
                    "summary": {
                        "status": "warning",
                        "coverage_status": "partial",
                        "issue_count": 1,
                        "issue_code_counts": {
                            "missing_episode_numbers": 1,
                        },
                        "season_count": 1,
                        "seasons_needing_attention": [1],
                    },
                    "seasons": [
                        {
                            "season": 1,
                            "title": "Season 1",
                            "display_title": "Season 1",
                            "diagnostics": {
                                "status": "warning",
                                "coverage_status": "partial",
                                "issue_codes": ["missing_episode_numbers"],
                                "missing_episode_numbers": [2],
                            },
                            "affected_resource_ids": ["resource-2"],
                            "affected_resources": [],
                            "suggestions": [suggestion],
                        },
                    ],
                    "suggested_updates": [suggestion],
                    "warnings": [],
                },
            }
        if path == "/api/v1/resources/resource-1/external-playback":
            return {
                "data": {
                    "resource_id": "resource-1",
                    "movie_id": "movie-1",
                    "title": "Sample.Movie.2024.1080p.mkv",
                    "filename": "Sample.Movie.2024.1080p.mkv",
                    "resource_info": {
                        "file": {
                            "filename": "Sample.Movie.2024.1080p.mkv",
                            "relative_path": "movies/Sample.Movie.2024.1080p.mkv",
                            "size_bytes": 123456,
                        },
                        "display": {
                            "title": "Sample.Movie.2024.1080p.mkv",
                            "label": "Movie - 1080P",
                        },
                        "technical": {
                            "video_resolution_label": "1080P",
                            "video_resolution_bucket": "1080p",
                            "video_codec_label": "H.264",
                            "audio_summary_label": "AAC",
                            "extra_tags": [],
                        },
                    },
                    "stream": {
                        "url": "http://example.test/api/v1/resources/resource-1/stream",
                        "mime_type": "video/x-matroska",
                        "storage_type": "guangyapan",
                        "default_mode": "redirect",
                        "playback_modes": ["redirect"],
                        "range_supported": True,
                        "url_type": "http_stream",
                        "requires_local_backend": False,
                        "requires_user_agent_rewrite": False,
                        "reason": None,
                    },
                    "subtitles": {
                        "supported": False,
                        "default_subtitle_id": None,
                        "default_url": None,
                        "items": [],
                    },
                    "handoff": {
                        "supported": True,
                        "method": "http_stream",
                        "manifest_url": "http://example.test/api/v1/resources/resource-1/external-playback",
                        "playlist_url": "http://example.test/api/v1/resources/resource-1/external-playback?format=m3u",
                        "playlist_format": "m3u",
                        "playlist_mime_type": "audio/x-mpegurl",
                        "reason": None,
                    },
                    "player_profiles": [
                        {
                            "key": "vlc",
                            "name": "VLC",
                            "platforms": ["windows", "macos", "linux"],
                            "handoff_methods": ["open_url", "m3u"],
                            "recommended": True,
                        },
                    ],
                    "warnings": [],
                },
            }
        if path == "/api/v1/resources/resource-1/subtitle-settings":
            return {
                "data": {
                    "resource_id": "resource-1",
                    "settings": {
                        "zhSize": 28,
                        "zhColor": "#FFFFFF",
                        "enSize": 22,
                        "enColor": "#FFFFFF",
                        "gap": 6,
                        "offset": 72,
                    },
                    "customized": False,
                    "source": "default",
                    "updated_at": None,
                },
            }
        if path == "/api/v1/resources/resource-1/audio-transcode/diagnostics":
            return {
                "data": {
                    "resource_id": "resource-1",
                    "session_id": None,
                    "active_count": 0,
                    "items": [],
                },
            }
        if path == "/api/v1/featured":
            detail = FakeSmokeClient.get_json(self, "/api/v1/movies/movie-1", query=query)["data"]
            return {"data": [detail]}
        if path == "/api/v1/homepage/config":
            return {
                "data": {
                    "hero_movie_id": None,
                    "sections": [
                        {
                            "key": "action",
                            "title": "动作",
                            "genre": "动作",
                            "mode": "latest",
                            "limit": 15,
                            "movie_ids": [],
                            "enabled": True,
                            "sort_order": 0,
                        },
                    ],
                    "created_at": "2026-06-07T00:00:00",
                    "updated_at": "2026-06-07T00:00:01",
                },
            }
        if path == "/api/v1/homepage":
            hero = FakeSmokeClient.get_json(self, "/api/v1/movies/movie-1", query=query)["data"]
            section_item = FakeSmokeClient.get_json(self, "/api/v1/movies", query=query)["data"]["items"][0].copy()
            section_item["id"] = "movie-2"
            section_item["title"] = "Section Movie"
            return {
                "data": {
                    "hero": {
                        "mode": "latest",
                        "movie": hero,
                    },
                    "sections": [
                        {
                            "key": "action",
                            "title": "动作",
                            "genre": "动作",
                            "mode": "latest",
                            "limit": 15,
                            "items": [section_item],
                        },
                    ],
                },
            }
        if path == "/api/v1/recommendations":
            item = FakeSmokeClient.get_json(self, "/api/v1/movies", query=query)["data"]["items"][0].copy()
            item["recommendation"] = {
                "primary_reason": {
                    "code": "high_rating",
                    "label": "High rating",
                    "weight": 30.0,
                    "detail": "7.5",
                },
                "rank": 1,
                "reason_text": "High rating",
                "reasons": [
                    {
                        "code": "high_rating",
                        "label": "High rating",
                        "weight": 30.0,
                    },
                ],
                "score": 72.5,
                "signals": {
                    "progress_ratio": 0,
                    "quality_badge": "HD",
                    "resource_count": 1,
                },
                "strategy": "default",
            }
            return {"data": [item]}
        if path == "/api/v1/movies/movie-1/recommendations":
            item = FakeSmokeClient.get_json(self, "/api/v1/movies", query=query)["data"]["items"][0].copy()
            item["id"] = "movie-2"
            item["title"] = "Related Sample Movie"
            item["recommendation"] = {
                "primary_reason": {
                    "code": "same_title_family",
                    "label": "Same series",
                    "weight": 180.0,
                    "detail": "sample",
                },
                "rank": 1,
                "reason_text": "Same series",
                "reasons": [
                    {
                        "code": "same_title_family",
                        "label": "Same series",
                        "weight": 180.0,
                    },
                ],
                "score": 259.2,
                "signals": {
                    "progress_ratio": 0,
                    "quality_badge": "HD",
                    "resource_count": 1,
                },
                "strategy": "context",
            }
            return {"data": [item]}
        if path == "/api/v1/user/history":
            movie = FakeSmokeClient.get_json(self, "/api/v1/movies", query=query)["data"]["items"][0].copy()
            return {
                "data": {
                    "items": [
                        {
                            "id": 1,
                            "resource_id": "resource-1",
                            "last_played_at": "2026-06-07T00:00:02",
                            "season": None,
                            "episode": None,
                            "episode_label": "Movie",
                            "label": "Movie",
                            "filename": "Sample.Movie.2024.1080p.mkv",
                            "progress": 120,
                            "duration": 600,
                            "position_sec": 120,
                            "duration_sec": 600,
                            "progress_ratio": 0.2,
                            "progress_percent": 20.0,
                            "poster_url": "https://example.test/poster.jpg",
                            "poster_source": "movie_fallback",
                            "season_poster_url": None,
                            "series_poster_url": "https://example.test/poster.jpg",
                            "season_title": None,
                            "season_display_title": None,
                            "last_watched": "2026-06-07T00:00:02",
                            "view_count": 1,
                            "device_id": "test-device",
                            "device_name": "Test Device",
                            "movie": movie,
                        },
                    ],
                    "pagination": {
                        "current_page": 1,
                        "page_size": 1,
                        "total_items": 1,
                        "total_pages": 1,
                    },
                },
            }
        if path == "/api/v1/user/vault/status":
            return {
                "data": {
                    "configured": False,
                    "unlocked": False,
                    "locked": False,
                    "locked_until": None,
                    "pin_change_limit_per_day": 10,
                    "pin_changes_used_today": 0,
                    "pin_changes_remaining_today": 10,
                },
            }
        if path == "/api/v1/metadata/work-items":
            if (query or {}).get("metadata_issue_code") == "fallback_pipeline_match":
                return {
                    "data": {
                        "items": [],
                        "pagination": {
                            "current_page": 1,
                            "page_size": 20,
                            "total_items": 0,
                            "total_pages": 0,
                        },
                    },
                }
            return {
                "data": {
                    "items": [
                        {
                            "id": "movie-1",
                            "title": "Sample Movie",
                            "scraper_source": "TMDB",
                            "metadata_state": {
                                "source_group": "tmdb",
                                "source_code": "TMDB",
                                "source_label": "TMDB",
                                "issue_codes": [],
                                "needs_attention": False,
                                "review_priority": "low",
                                "recommended_action": "refresh_metadata",
                            },
                            "metadata_actions": {
                                "can_manual_match": True,
                                "can_refresh": True,
                                "can_re_scrape": True,
                                "primary_action": "refresh_metadata",
                            },
                            "metadata_diagnostics": {
                                "resource_count": 1,
                            },
                            "metadata_issues": [],
                            "catalog_visibility": {
                                "effective_status": "published",
                                "status": "published",
                                "is_visible": True,
                                "can_publish": True,
                            },
                            "manual_content": {
                                "is_manual": False,
                            },
                        },
                    ],
                    "pagination": {
                        "current_page": 1,
                        "page_size": 1,
                        "total_items": 1,
                        "total_pages": 1,
                    },
                },
            }
        if path == "/api/v1/metadata/episode-review-items":
            return {
                "data": {
                    "items": [],
                    "pagination": {
                        "current_page": 1,
                        "page_size": 20,
                        "total_items": 0,
                        "total_pages": 0,
                    },
                    "summary": {
                        "total_items": 0,
                        "issue_code_counts": {},
                        "auto_update_count": 0,
                        "manual_suggestion_count": 0,
                        "warning_count": 0,
                    },
                },
            }
        if path == "/api/v1/jobs":
            return {
                "data": {
                    "items": [
                        {
                            "id": "job-1",
                            "type": "metadata_re_scrape",
                            "title": "Metadata re-scrape",
                            "status": "succeeded",
                            "created_at": "2026-06-07T00:00:00",
                            "started_at": "2026-06-07T00:00:01",
                            "finished_at": "2026-06-07T00:00:02",
                            "request": {},
                            "progress": {"current": 1, "total": 1, "message": "done"},
                            "result": {"summary": {"total": 1}},
                            "error": None,
                            "persisted": True,
                        },
                    ],
                    "summary": {
                        "count": 1,
                        "limit": 1,
                        "type": None,
                    },
                },
            }
        if path == "/api/v1/jobs/job-1":
            return {
                "data": {
                    "id": "job-1",
                    "type": "metadata_re_scrape",
                    "title": "Metadata re-scrape",
                    "status": "succeeded",
                    "created_at": "2026-06-07T00:00:00",
                    "started_at": "2026-06-07T00:00:01",
                    "finished_at": "2026-06-07T00:00:02",
                    "request": {},
                    "progress": {"current": 1, "total": 1, "message": "done"},
                    "result": {"summary": {"total": 1}},
                    "error": None,
                    "persisted": True,
                },
            }
        if path == "/api/v1/resources/governance-summary":
            return {
                "data": {
                    "totals": {
                        "resource_count": 464,
                        "live_path_checked_count": 464,
                        "live_path_valid_count": 464,
                        "actionable_issue_count": 0,
                    },
                },
            }
        raise AssertionError(f"unexpected path: {path}")

    def get_json_allow_error(self, path, query=None):
        if path == "/api/v1/resources/resource-1/streaming-qualities":
            return {
                "_http_status": 400,
                "code": 40074,
                "data": None,
                "msg": "Resource source does not support cloud transcoding",
            }
        if path in {"/api/v1/user/favorites", "/api/v1/user/favorites/movie-1"}:
            return {
                "_http_status": 403,
                "code": 40341,
                "data": None,
                "msg": "Vault PIN is not configured",
            }
        return self.get_json(path, query=query)

    def get_text(self, path, query=None):
        if path.startswith("/api/v1/docs/") and query is None:
            key = path.rsplit("/", 1)[-1]
            return {
                "_http_status": 200,
                "_content_type": "text/markdown; charset=utf-8",
                "_content_disposition": None,
                "text": f"# {key}\n\nDocumentation body.\n",
            }
        if path == "/api/v1/resources/resource-1/external-playback" and (query or {}).get("format") == "m3u":
            return {
                "_http_status": 200,
                "_content_type": "audio/x-mpegurl; charset=utf-8",
                "_content_disposition": "attachment; filename=\"cyberstream-resource-1.m3u\"",
                "text": (
                    "#EXTM3U\n"
                    "#EXTINF:-1,Sample.Movie.2024.1080p.mkv\n"
                    "#EXTVLCOPT:network-caching=1000\n"
                    "http://example.test/api/v1/resources/resource-1/stream\n"
                ),
            }
        raise AssertionError(f"unexpected text path: {path}")

    def get_binary_sample(self, path, query=None, headers=None, max_bytes=1024):
        if path == "/api/v1/resources/resource-1/stream" and (headers or {}).get("Range") == "bytes=0-0":
            return {
                "_http_status": 302,
                "_headers": {
                    "Content-Type": "text/html; charset=utf-8",
                    "Location": "https://cdn.example.test/video.mkv",
                },
                "_content_type": "text/html; charset=utf-8",
                "_content_range": None,
                "_accept_ranges": None,
                "_location": "https://cdn.example.test/video.mkv",
                "byte_count": min(max_bytes, 128),
            }
        raise AssertionError(f"unexpected binary path: {path}")

    def post_json(self, path, body=None):
        if path == "/api/v1/metadata/re-scrape/plan":
            issue_codes = (body or {}).get("issue_codes") or [
                "fallback_pipeline_match",
                "poster_missing",
                "low_confidence_resources",
            ]
            return {
                "data": {
                    "dry_run": True,
                    "plan_mode": "keyword_preview",
                    "provider_search": False,
                    "selection": {
                        "issue_codes": issue_codes,
                        "limit": (body or {}).get("limit"),
                        "media_type_hint": None,
                        "metadata_unlocked_fields": [],
                        "movie_ids": None,
                    },
                    "apply_method": "POST",
                    "apply_endpoint": "/api/v1/metadata/re-scrape/jobs",
                    "sync_apply_endpoint": "/api/v1/metadata/re-scrape",
                    "progress_endpoint_template": "/api/v1/jobs/{job_id}",
                    "apply_payload": {
                        "items": [
                            {
                                "id": "movie-1",
                                "search_title": "Sample Movie",
                                "search_year": 2024,
                            },
                        ],
                    },
                    "items": [
                        {
                            "movie_id": "movie-1",
                            "title": "Sample Movie",
                            "scraper_source": "TMDB",
                            "status": "planned",
                            "dry_run": True,
                            "plan_mode": "keyword_preview",
                            "matched_issue_codes": ["poster_missing"],
                            "metadata_state": {
                                "source_group": "tmdb",
                                "source_code": "TMDB",
                                "source_label": "TMDB",
                                "issue_codes": ["poster_missing"],
                                "needs_attention": True,
                                "review_priority": "medium",
                                "recommended_action": "refresh_metadata",
                            },
                            "metadata_actions": {
                                "can_manual_match": True,
                                "can_refresh": True,
                                "can_re_scrape": True,
                                "primary_action": "refresh_metadata",
                            },
                            "search_query": {
                                "search_title": "Sample Movie",
                                "search_year": 2024,
                                "source": "path_parser",
                            },
                            "search_title": "Sample Movie",
                            "search_year": 2024,
                            "preview": None,
                            "diff": None,
                            "resolution": None,
                            "explanation": None,
                            "apply_item": {
                                "id": "movie-1",
                                "search_title": "Sample Movie",
                                "search_year": 2024,
                            },
                        },
                    ],
                    "summary": {
                        "total": 1,
                        "planned": 1,
                        "failed": 0,
                        "apply_item_count": 1,
                        "status_counts": {"planned": 1},
                        "issue_code_counts": {"poster_missing": 1},
                        "failed_movie_ids": [],
                    },
                },
            }
        if path == "/api/v1/metadata/pending-review/backfill":
            dry_run = (body or {}).get("dry_run")
            include_visible = (body or {}).get("include_visible")
            return {
                "data": {
                    "dry_run": dry_run,
                    "include_visible": include_visible,
                    "candidates": [
                        {
                            "movie_id": "movie-1",
                            "title": "Sample Movie",
                            "year": 2024,
                            "action": "would_set_pending_review",
                            "scraper_source": "TMDB_FALLBACK",
                            "metadata_state": {
                                "source_code": "TMDB_FALLBACK",
                                "source_group": "tmdb",
                                "confidence": 0.45,
                                "is_placeholder": False,
                                "is_local_only": False,
                                "issue_codes": ["fallback_pipeline_match"],
                                "primary_issue_code": "fallback_pipeline_match",
                                "review_priority": "medium",
                            },
                            "catalog_visibility_before": {
                                "effective_status": "pending_review",
                                "status": "auto",
                                "is_visible": False,
                                "can_publish": True,
                            },
                            "catalog_visibility_after": None,
                        },
                    ],
                    "updated": [],
                    "skipped": [],
                    "failed": [],
                    "summary": {
                        "scanned": 1,
                        "candidates": 1,
                        "updated": 0,
                        "skipped": 0,
                        "failed": 0,
                    },
                },
            }
        if path == "/api/v1/resources/governance/plan":
            issue_codes = (body or {}).get("issue_codes") or [
                "duplicate_playback_resource",
                "detached_source_resource",
            ]
            return {
                "data": {
                    "generated_at": "2026-06-07T00:00:00",
                    "dry_run": True,
                    "apply_method": "POST",
                    "apply_endpoint": "/api/v1/resources/governance/jobs",
                    "selection": {
                        "issue_codes": issue_codes,
                        "resource_ids": [],
                        "movie_ids": [],
                        "live_check": False,
                        "live_check_limit": 50,
                        "page": None,
                        "page_size": None,
                        "limit": (body or {}).get("limit"),
                    },
                    "items": [
                        {
                            "issue_code": "duplicate_playback_resource",
                            "status": "planned",
                            "action": "remove_resource_index",
                            "resource": {
                                "resource_id": 10,
                                "movie_id": "movie-1",
                                "path": "movies/copy.mkv",
                            },
                            "apply_item": {
                                "type": "remove_resource_index",
                                "issue_code": "duplicate_playback_resource",
                                "resource_id": 10,
                                "primary_resource_id": 11,
                            },
                            "restore_snapshot_available": True,
                        },
                    ],
                    "summary": {
                        "total": 1,
                        "planned": 1,
                        "skipped": 0,
                        "manual_review": 0,
                        "planned_resource_ids": [10],
                        "issue_code_counts": {"duplicate_playback_resource": 1},
                        "skip_reason_counts": {},
                    },
                    "returned_summary": {
                        "total": 1,
                        "planned": 1,
                        "skipped": 0,
                        "manual_review": 0,
                        "planned_resource_ids": [10],
                        "issue_code_counts": {"duplicate_playback_resource": 1},
                        "skip_reason_counts": {},
                    },
                    "pagination": {
                        "paginated": True,
                        "current_page": 1,
                        "page_size": 1,
                        "total_items": 1,
                        "total_pages": 1,
                        "limit": 1,
                    },
                    "apply_payload": {
                        "confirm": True,
                        "items": [
                            {
                                "type": "remove_resource_index",
                                "issue_code": "duplicate_playback_resource",
                                "resource_id": 10,
                                "primary_resource_id": 11,
                            },
                        ],
                    },
                },
            }
        if path == "/api/v1/jobs/prune":
            return {
                "data": {
                    "dry_run": True,
                    "retention_days": (body or {}).get("retention_days"),
                    "cutoff": "2026-05-08T00:00:00",
                    "type": None,
                    "matched": 1,
                    "matched_ids": ["job-1"],
                    "removed": 0,
                    "removed_ids": [],
                    "type_counts": {"metadata_re_scrape": 1},
                    "status_counts": {"succeeded": 1},
                },
            }
        raise AssertionError(f"unexpected post path: {path}")


class BackendSmokeCheckScriptTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_script_module()

    def _args(self, **overrides):
        args = {
            "base_url": "http://example.test",
            "timeout": 1.0,
            "expected_version": "",
            "expected_openapi_version": "",
            "api_token": "",
            "login_username": "",
            "login_password": "",
            "live_check_limit": 500,
            "openapi_module_json_check": False,
            "max_fallback_items": 0,
            "max_episode_review_items": 0,
            "max_resource_actionable": 0,
            "min_storage_sources": 0,
            "min_storage_health_checks": 0,
            "storage_health_check": False,
            "tmdb_token_check": False,
            "systemd": False,
            "systemd_service": None,
        }
        args.update(overrides)
        return Namespace(**args)

    def test_run_checks_passes_when_runtime_contract_is_clean(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args())

        self.assertTrue(all(item.ok for item in results))
        self.assertEqual(
            [
                "health",
                "auth_me",
                "openapi_health_contract",
                "docs_index",
                "docs_content",
                "update_check",
                "openapi_modules",
                "aggregator_sources",
                "scan",
                "metadata_providers",
                "tmdb_config",
                "metadata_overview",
                "metadata_review_workbench",
                "libraries",
                "other_videos",
                "catalog_filters",
                "catalog_metadata_filters",
                "catalog_metadata_issue_filter",
                "catalog_metadata_source_group_filter",
                "catalog_movies",
                "catalog_keyword_search",
                "movie_detail",
                "movie_images_status",
                "movie_resources",
                "streaming_qualities",
                "resource_stream_range",
                "movie_seasons",
                "movie_episode_diagnostics",
                "external_playback",
                "subtitle_settings",
                "audio_transcode_diagnostics",
                "featured",
                "homepage_config",
                "homepage",
                "recommendations",
                "movie_context_recommendations",
                "user_history",
                "user_achievements",
                "user_favorites",
                "vault_status",
                "metadata_work_items_contract",
                "metadata_reidentify_plan",
                "pending_review_backfill_dry_run",
                "background_jobs",
                "background_job_detail",
                "background_jobs_prune",
                "storage_provider_types",
                "storage_capabilities",
                "storage_sources",
                "storage_source_detail",
                "storage_browse",
                "metadata_fallback_pipeline_match",
                "episode_review",
                "resource_governance",
                "resource_governance_plan",
            ],
            [item.name for item in results],
        )

    def test_run_checks_passes_api_token_to_smoke_client(self):
        class TokenAwareClient(FakeSmokeClient):
            last_init = None

        with patch.object(self.module, "SmokeClient", TokenAwareClient):
            self.module.run_checks(self._args(api_token="secret-token"))

        self.assertEqual("secret-token", TokenAwareClient.last_init["api_token"])

    def test_run_checks_logs_in_when_session_credentials_are_configured(self):
        class LoginAwareClient(FakeSmokeClient):
            instance = None

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                type(self).instance = self

            def get_json(self, path, query=None):
                if path == "/api/v1/auth/me" and self.cookie_header:
                    return self.login_calls and self.login(*self.login_calls[-1])
                return super().get_json(path, query=query)

        with patch.object(self.module, "SmokeClient", LoginAwareClient):
            results = self.module.run_checks(self._args(
                login_username="owner",
                login_password="secret-password",
            ))

        self.assertEqual(
            ("owner", "secret-password"),
            LoginAwareClient.instance.login_calls[0],
        )
        self.assertEqual("auth_login", results[1].name)
        self.assertTrue(results[1].ok)

    def test_smoke_client_sends_bearer_authorization_header(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data":{"ok":true}}'

        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        client = self.module.SmokeClient("http://example.test", timeout=2.5, api_token="secret-token")
        with patch.object(self.module.urllib.request, "urlopen", side_effect=fake_urlopen):
            payload = client.get_json("/api/v1/storage/sources")

        self.assertEqual({"data": {"ok": True}}, payload)
        request, timeout = requests[0]
        self.assertEqual(2.5, timeout)
        self.assertEqual("application/json", request.get_header("Accept"))
        self.assertEqual("Bearer secret-token", request.get_header("Authorization"))

    def test_smoke_client_login_stores_session_cookie_for_later_requests(self):
        class FakeHeaders:
            def get_all(self, key):
                if key == "Set-Cookie":
                    return ["cyberstream_session=abc123; HttpOnly; Secure; Path=/"]
                return []

        class FakeResponse:
            headers = FakeHeaders()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'{"data":{"user_management_enabled":true,"authenticated":true,'
                    b'"role":"admin","auth_via":"session","user":{"id":1},'
                    b'"permissions":{"admin":true,"read_catalog":true,'
                    b'"manage_catalog":true,"manage_users":true,'
                    b'"personal_history":true,"personal_favorites":true,'
                    b'"personal_vault":true,"personal_subtitle_settings":true}}}'
                )

        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        client = self.module.SmokeClient("http://example.test", timeout=2.5)
        with patch.object(self.module.urllib.request, "urlopen", side_effect=fake_urlopen):
            client.login("owner", "secret-password")
            client.get_json("/api/v1/storage/sources")

        self.assertEqual("cyberstream_session=abc123", client.cookie_header)
        self.assertEqual(
            "cyberstream_session=abc123",
            requests[1][0].get_header("Cookie"),
        )

    def test_smoke_client_can_get_text_payload(self):
        class FakeHeaders:
            def get(self, key):
                return {
                    "Content-Type": "audio/x-mpegurl; charset=utf-8",
                    "Content-Disposition": "attachment; filename=\"sample.m3u\"",
                }.get(key)

        class FakeResponse:
            status = 200
            headers = FakeHeaders()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"#EXTM3U\nhttp://example.test/video.mkv\n"

        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        client = self.module.SmokeClient("http://example.test", timeout=2.5, api_token="secret-token")
        with patch.object(self.module.urllib.request, "urlopen", side_effect=fake_urlopen):
            payload = client.get_text("/api/v1/resources/resource-1/external-playback", {"format": "m3u"})

        self.assertEqual(200, payload["_http_status"])
        self.assertEqual("audio/x-mpegurl; charset=utf-8", payload["_content_type"])
        self.assertIn("#EXTM3U", payload["text"])
        request, timeout = requests[0]
        self.assertEqual(2.5, timeout)
        self.assertEqual("text/plain, */*", request.get_header("Accept"))
        self.assertEqual("Bearer secret-token", request.get_header("Authorization"))
        self.assertIn("format=m3u", request.full_url)

    def test_smoke_client_can_get_binary_sample_with_range(self):
        class FakeResponse:
            status = 206
            headers = {
                "Content-Type": "video/x-matroska",
                "Content-Range": "bytes 0-0/10",
                "Accept-Ranges": "bytes",
            }

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, max_bytes):
                self.max_bytes = max_bytes
                return b"x"

        class FakeOpener:
            def __init__(self):
                self.requests = []
                self.response = FakeResponse()

            def open(self, request, timeout):
                self.requests.append((request, timeout))
                return self.response

        opener = FakeOpener()
        client = self.module.SmokeClient("http://example.test", timeout=2.5, api_token="secret-token")
        with patch.object(self.module.urllib.request, "build_opener", return_value=opener):
            payload = client.get_binary_sample(
                "/api/v1/resources/resource-1/stream",
                headers={"Range": "bytes=0-0"},
                max_bytes=1,
            )

        self.assertEqual(206, payload["_http_status"])
        self.assertEqual("bytes 0-0/10", payload["_content_range"])
        self.assertEqual(1, payload["byte_count"])
        request, timeout = opener.requests[0]
        self.assertEqual(2.5, timeout)
        self.assertEqual("*/*", request.get_header("Accept"))
        self.assertEqual("bytes=0-0", request.get_header("Range"))
        self.assertEqual("Bearer secret-token", request.get_header("Authorization"))
        self.assertEqual(1, opener.response.max_bytes)

    def test_smoke_client_can_post_json_payload(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data":{"ok":true}}'

        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        client = self.module.SmokeClient("http://example.test", timeout=2.5, api_token="secret-token")
        with patch.object(self.module.urllib.request, "urlopen", side_effect=fake_urlopen):
            payload = client.post_json("/api/v1/metadata/re-scrape/plan", {"limit": 1})

        self.assertEqual({"data": {"ok": True}}, payload)
        request, timeout = requests[0]
        self.assertEqual(2.5, timeout)
        self.assertEqual("POST", request.get_method())
        self.assertEqual("application/json", request.get_header("Accept"))
        self.assertEqual("application/json", request.get_header("Content-type"))
        self.assertEqual("Bearer secret-token", request.get_header("Authorization"))
        self.assertEqual(b'{"limit": 1}', request.data)

    def test_docs_index_fails_when_expected_document_is_missing(self):
        class MissingTerminologyDocClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/docs":
                    payload["data"]["documents"] = [
                        item for item in payload["data"]["documents"]
                        if item["key"] != "terminology"
                    ]
                return payload

        with patch.object(self.module, "SmokeClient", MissingTerminologyDocClient):
            results = self.module.run_checks(self._args())

        docs = next(item for item in results if item.name == "docs_index")
        self.assertFalse(docs.ok)
        self.assertIn("missing=terminology", docs.detail)

    def test_docs_index_fails_when_openapi_links_are_invalid(self):
        class BrokenDocsOpenApiClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/docs":
                    payload["data"]["openapi"]["modules_url"] = "/broken"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenDocsOpenApiClient):
            results = self.module.run_checks(self._args())

        docs = next(item for item in results if item.name == "docs_index")
        self.assertFalse(docs.ok)
        self.assertIn("openapi_links_invalid", docs.detail)

    def test_docs_content_fails_when_markdown_body_is_invalid(self):
        class BrokenDocsContentClient(FakeSmokeClient):
            def get_text(self, path, query=None):
                if path == "/api/v1/docs/api-overview":
                    return {
                        "_http_status": 200,
                        "_content_type": "text/markdown; charset=utf-8",
                        "_content_disposition": None,
                        "text": "API Overview without heading",
                    }
                return super().get_text(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenDocsContentClient):
            results = self.module.run_checks(self._args())

        docs = next(item for item in results if item.name == "docs_content")
        self.assertFalse(docs.ok)
        self.assertIn("api-overview_missing_markdown_heading", docs.detail)

    def test_openapi_index_checks_accept_expected_openapi_version_when_it_matches(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(
                self._args(
                    expected_version="1.21.0",
                    expected_openapi_version="1.21.0-beta",
                )
            )

        health_contract = next(item for item in results if item.name == "openapi_health_contract")
        docs = next(item for item in results if item.name == "docs_index")
        modules = next(item for item in results if item.name == "openapi_modules")
        self.assertTrue(health_contract.ok)
        self.assertTrue(docs.ok)
        self.assertTrue(modules.ok)
        self.assertEqual("1.21.0-beta", health_contract.data["expected_openapi_version"])
        self.assertEqual("1.21.0", docs.data["expected_version"])
        self.assertEqual("1.21.0-beta", docs.data["expected_openapi_version"])
        self.assertEqual("1.21.0-beta", modules.data["expected_openapi_version"])
        self.assertIn("expected_openapi_version=1.21.0-beta", health_contract.detail)
        self.assertIn("expected_version=1.21.0", docs.detail)
        self.assertIn("expected_openapi_version=1.21.0-beta", docs.detail)
        self.assertIn("expected_openapi_version=1.21.0-beta", modules.detail)

    def test_openapi_index_checks_fail_when_expected_openapi_version_does_not_match(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args(expected_openapi_version="1.22.0-beta"))

        health_contract = next(item for item in results if item.name == "openapi_health_contract")
        docs = next(item for item in results if item.name == "docs_index")
        modules = next(item for item in results if item.name == "openapi_modules")
        self.assertFalse(health_contract.ok)
        self.assertFalse(docs.ok)
        self.assertFalse(modules.ok)
        self.assertIn("openapi_version_expected=1.22.0-beta actual=1.21.0-beta", health_contract.detail)
        self.assertIn("openapi_version_expected=1.22.0-beta actual=1.21.0-beta", docs.detail)
        self.assertIn("openapi_version_expected=1.22.0-beta actual=1.21.0-beta", modules.detail)

    def test_docs_index_fails_when_expected_app_version_does_not_match(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args(expected_version="1.22.0"))

        docs = next(item for item in results if item.name == "docs_index")
        self.assertFalse(docs.ok)
        self.assertIn("version_expected=1.22.0 actual=1.21.0", docs.detail)

    def test_openapi_health_contract_fails_when_main_document_is_not_openapi(self):
        class BrokenOpenApiDocumentClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                if path == "/api/v1/openapi.json":
                    return {
                        "info": {"version": "1.21.0-beta"},
                        "paths": {},
                        "components": [],
                    }
                return super().get_json(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenOpenApiDocumentClient):
            results = self.module.run_checks(self._args())

        contract = next(item for item in results if item.name == "openapi_health_contract")
        self.assertFalse(contract.ok)
        self.assertIn("openapi=None", contract.detail)
        self.assertIn("paths_invalid", contract.detail)
        self.assertIn("components_invalid", contract.detail)

    def test_health_fails_when_database_is_not_ok(self):
        class DegradedHealthClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/health":
                    payload["data"]["status"] = "degraded"
                    payload["data"]["database"] = {"status": "down", "reason": "query_failed"}
                return payload

        with patch.object(self.module, "SmokeClient", DegradedHealthClient):
            results = self.module.run_checks(self._args())

        health = next(item for item in results if item.name == "health")
        self.assertFalse(health.ok)
        self.assertIn("api_database=down", health.detail)

    def test_health_accepts_expected_version_when_it_matches(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args(expected_version="1.21.0"))

        health = next(item for item in results if item.name == "health")
        self.assertTrue(health.ok)
        self.assertEqual("1.21.0", health.data["expected_version"])
        self.assertIn("expected_version=1.21.0", health.detail)

    def test_health_fails_when_expected_version_does_not_match(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args(expected_version="1.22.0"))

        health = next(item for item in results if item.name == "health")
        self.assertFalse(health.ok)
        self.assertIn("version_expected=1.22.0 actual=1.21.0", health.detail)

    def test_health_fails_when_root_health_does_not_match_api_health(self):
        class RootMismatchHealthClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/":
                    payload["data"]["database"] = {"status": "down", "reason": "query_failed"}
                return payload

        with patch.object(self.module, "SmokeClient", RootMismatchHealthClient):
            results = self.module.run_checks(self._args())

        health = next(item for item in results if item.name == "health")
        self.assertFalse(health.ok)
        self.assertIn("database_mismatch=down/ok", health.detail)

    def test_resource_governance_fails_when_live_paths_are_invalid(self):
        class BrokenResourceClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/resources/governance-summary":
                    payload["data"]["totals"]["live_path_valid_count"] = 463
                return payload

        with patch.object(self.module, "SmokeClient", BrokenResourceClient):
            results = self.module.run_checks(self._args())

        governance = next(item for item in results if item.name == "resource_governance")
        self.assertFalse(governance.ok)
        self.assertIn("live=463/464", governance.detail)

    def test_openapi_modules_fail_when_expected_module_is_missing(self):
        class MissingAggregatorModuleClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/openapi/modules":
                    payload["data"]["modules"] = [
                        item for item in payload["data"]["modules"]
                        if item["key"] != "aggregator"
                    ]
                return payload

        with patch.object(self.module, "SmokeClient", MissingAggregatorModuleClient):
            results = self.module.run_checks(self._args())

        modules = next(item for item in results if item.name == "openapi_modules")
        self.assertFalse(modules.ok)
        self.assertIn("missing=aggregator", modules.detail)

    def test_openapi_modules_fail_when_index_links_are_invalid(self):
        class BrokenOpenApiModuleIndexClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/openapi/modules":
                    payload["data"]["full_url"] = "/broken/openapi.json"
                    payload["data"]["modules"][0]["content_type"] = "text/plain"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenOpenApiModuleIndexClient):
            results = self.module.run_checks(self._args())

        modules = next(item for item in results if item.name == "openapi_modules")
        self.assertFalse(modules.ok)
        self.assertIn("full_url_invalid", modules.detail)
        self.assertIn("non_json=docs", modules.detail)

    def test_run_checks_can_fetch_openapi_module_json_when_enabled(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args(openapi_module_json_check=True))

        modules = next(item for item in results if item.name == "openapi_modules")
        self.assertTrue(modules.ok)
        self.assertEqual(self.module.EXPECTED_OPENAPI_MODULES, modules.data["fetched"])
        self.assertIn("fetched=11", modules.detail)

    def test_openapi_module_json_check_fails_on_invalid_module_contract(self):
        class BrokenModuleJsonClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                if path == "/api/v1/openapi/modules/metadata.json":
                    return {"openapi": "3.0.0", "paths": {}, "components": []}
                return super().get_json(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenModuleJsonClient):
            results = self.module.run_checks(self._args(openapi_module_json_check=True))

        modules = next(item for item in results if item.name == "openapi_modules")
        self.assertFalse(modules.ok)
        self.assertIn("metadata:invalid_contract:paths_invalid,components_invalid", modules.detail)

    def test_openapi_module_json_check_fails_on_module_version_mismatch(self):
        class MismatchedModuleJsonClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/openapi/modules/metadata.json":
                    payload["info"]["version"] = "1.20.0-beta"
                return payload

        with patch.object(self.module, "SmokeClient", MismatchedModuleJsonClient):
            results = self.module.run_checks(self._args(
                openapi_module_json_check=True,
                expected_openapi_version="1.21.0-beta",
            ))

        modules = next(item for item in results if item.name == "openapi_modules")
        self.assertFalse(modules.ok)
        self.assertIn("metadata:version_expected=1.21.0-beta actual=1.20.0-beta", modules.detail)

    def test_aggregator_sources_fail_when_default_is_unknown(self):
        class BrokenAggregatorSourcesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/aggregator/sources":
                    payload["data"]["default"] = "missing-source"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenAggregatorSourcesClient):
            results = self.module.run_checks(self._args())

        sources = next(item for item in results if item.name == "aggregator_sources")
        self.assertFalse(sources.ok)
        self.assertIn("aggregator_default_unknown=missing-source", sources.detail)

    def test_metadata_providers_fails_when_required_provider_is_missing(self):
        class MissingBangumiClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/metadata/providers":
                    payload["data"]["providers"] = [
                        item for item in payload["data"]["providers"]
                        if item["key"] != "bangumi"
                    ]
                return payload

        with patch.object(self.module, "SmokeClient", MissingBangumiClient):
            results = self.module.run_checks(self._args())

        providers = next(item for item in results if item.name == "metadata_providers")
        self.assertFalse(providers.ok)
        self.assertIn("missing=bangumi", providers.detail)

    def test_metadata_overview_fails_when_total_shape_is_broken(self):
        class BrokenMetadataOverviewClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/metadata/overview":
                    payload["data"]["totals"]["movie_count"] = "359"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenMetadataOverviewClient):
            results = self.module.run_checks(self._args())

        overview = next(item for item in results if item.name == "metadata_overview")
        self.assertFalse(overview.ok)
        self.assertIn("metadata_overview_totals_movie_count_not_int", overview.detail)

    def test_metadata_review_workbench_fails_when_required_bucket_is_missing(self):
        class MissingEpisodeReviewBucketClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/metadata/review-taxonomy":
                    payload["data"]["buckets"] = [
                        item for item in payload["data"]["buckets"]
                        if item["id"] != "episode_review"
                    ]
                return payload

        with patch.object(self.module, "SmokeClient", MissingEpisodeReviewBucketClient):
            results = self.module.run_checks(self._args())

        workbench = next(item for item in results if item.name == "metadata_review_workbench")
        self.assertFalse(workbench.ok)
        self.assertIn("missing_buckets=episode_review", workbench.detail)

    def test_metadata_review_workbench_fails_when_quality_sample_shape_is_broken(self):
        class BrokenQualitySummaryClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/metadata/quality-summary":
                    del payload["data"]["issues"][0]["samples"][0]["metadata_actions"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenQualitySummaryClient):
            results = self.module.run_checks(self._args())

        workbench = next(
            item for item in results
            if item.name == "metadata_review_workbench"
        )
        self.assertFalse(workbench.ok)
        self.assertIn("quality_issue_0_sample_0_missing=metadata_actions", workbench.detail)

    def test_metadata_work_items_contract_fails_when_sample_shape_is_broken(self):
        class BrokenWorkItemsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if (
                    path == "/api/v1/metadata/work-items"
                    and not (query or {}).get("metadata_issue_code")
                ):
                    del payload["data"]["items"][0]["metadata_state"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenWorkItemsClient):
            results = self.module.run_checks(self._args())

        work_items = next(
            item for item in results
            if item.name == "metadata_work_items_contract"
        )
        self.assertFalse(work_items.ok)
        self.assertIn("item_0_missing=metadata_state", work_items.detail)

    def test_fallback_work_items_contract_accepts_valid_sample(self):
        class FallbackWorkItemsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                if (
                    path == "/api/v1/metadata/work-items"
                    and (query or {}).get("metadata_issue_code") == "fallback_pipeline_match"
                ):
                    return {
                        "data": {
                            "items": [
                                {
                                    "id": "movie-fallback-1",
                                    "title": "Fallback Match",
                                    "scraper_source": "TMDB_FALLBACK",
                                    "metadata_state": {
                                        "source_group": "tmdb",
                                        "source_code": "TMDB_FALLBACK",
                                        "source_label": "TMDB fallback",
                                        "issue_codes": ["fallback_pipeline_match"],
                                        "needs_attention": True,
                                        "review_priority": "medium",
                                        "recommended_action": "bulk_reidentify",
                                    },
                                    "metadata_actions": {
                                        "can_manual_match": True,
                                        "can_refresh": True,
                                        "can_re_scrape": True,
                                        "primary_action": "bulk_reidentify",
                                    },
                                    "metadata_diagnostics": {
                                        "resource_count": 1,
                                    },
                                    "metadata_issues": [
                                        {"code": "fallback_pipeline_match"},
                                    ],
                                    "catalog_visibility": {
                                        "effective_status": "pending_review",
                                        "status": "auto",
                                        "is_visible": False,
                                        "can_publish": True,
                                    },
                                    "manual_content": {
                                        "is_manual": False,
                                    },
                                },
                            ],
                            "pagination": {
                                "current_page": 1,
                                "page_size": 20,
                                "total_items": 1,
                                "total_pages": 1,
                            },
                        },
                    }
                return super().get_json(path, query=query)

        with patch.object(self.module, "SmokeClient", FallbackWorkItemsClient):
            results = self.module.run_checks(self._args(max_fallback_items=1))

        fallback = next(
            item for item in results
            if item.name == "metadata_fallback_pipeline_match"
        )
        self.assertTrue(fallback.ok)
        self.assertIn("items=1", fallback.detail)

    def test_fallback_work_items_contract_fails_when_sample_shape_is_broken(self):
        class BrokenFallbackWorkItemsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                if (
                    path == "/api/v1/metadata/work-items"
                    and (query or {}).get("metadata_issue_code") == "fallback_pipeline_match"
                ):
                    return {
                        "data": {
                            "items": [
                                {
                                    "id": "movie-fallback-1",
                                    "title": "Fallback Match",
                                    "scraper_source": "TMDB_FALLBACK",
                                    "metadata_state": {
                                        "source_group": "tmdb",
                                        "source_code": "TMDB_FALLBACK",
                                        "source_label": "TMDB fallback",
                                        "issue_codes": ["fallback_pipeline_match"],
                                        "needs_attention": True,
                                        "review_priority": "medium",
                                        "recommended_action": "bulk_reidentify",
                                    },
                                    "metadata_diagnostics": {
                                        "resource_count": 1,
                                    },
                                    "metadata_issues": [
                                        {"code": "fallback_pipeline_match"},
                                    ],
                                    "catalog_visibility": {
                                        "effective_status": "pending_review",
                                        "status": "auto",
                                        "is_visible": False,
                                        "can_publish": True,
                                    },
                                    "manual_content": {
                                        "is_manual": False,
                                    },
                                },
                            ],
                            "pagination": {
                                "current_page": 1,
                                "page_size": 20,
                                "total_items": 1,
                                "total_pages": 1,
                            },
                        },
                    }
                return super().get_json(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenFallbackWorkItemsClient):
            results = self.module.run_checks(self._args(max_fallback_items=1))

        fallback = next(
            item for item in results
            if item.name == "metadata_fallback_pipeline_match"
        )
        self.assertFalse(fallback.ok)
        self.assertIn("item_0_missing=metadata_actions", fallback.detail)

    def test_catalog_movies_fails_when_sample_shape_is_broken(self):
        class BrokenCatalogMoviesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies":
                    del payload["data"]["items"][0]["metadata_state"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenCatalogMoviesClient):
            results = self.module.run_checks(self._args())

        catalog = next(item for item in results if item.name == "catalog_movies")
        self.assertFalse(catalog.ok)
        self.assertIn("item_0_missing=metadata_state", catalog.detail)

    def test_catalog_keyword_search_fails_when_sample_is_missing(self):
        class BrokenCatalogSearchClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies" and (query or {}).get("keyword"):
                    payload["data"]["items"][0]["id"] = "movie-other"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenCatalogSearchClient):
            results = self.module.run_checks(self._args())

        search = next(item for item in results if item.name == "catalog_keyword_search")
        self.assertFalse(search.ok)
        self.assertIn("sample_missing_from_keyword_results=movie-1", search.detail)

    def test_catalog_filters_fail_when_option_shape_is_broken(self):
        class BrokenCatalogFiltersClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/filters":
                    del payload["data"]["genres"][0]["count"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenCatalogFiltersClient):
            results = self.module.run_checks(self._args())

        filters = next(item for item in results if item.name == "catalog_filters")
        self.assertFalse(filters.ok)
        self.assertIn("genres_0_missing=count", filters.detail)

    def test_catalog_metadata_filters_fail_when_option_shape_is_broken(self):
        class BrokenCatalogMetadataFiltersClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if (
                    path == "/api/v1/filters"
                    and "metadata_source_groups" in ((query or {}).get("include") or "")
                ):
                    del payload["data"]["metadata_source_groups"][0]["slug"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenCatalogMetadataFiltersClient):
            results = self.module.run_checks(self._args())

        filters = next(item for item in results if item.name == "catalog_metadata_filters")
        self.assertFalse(filters.ok)
        self.assertIn("metadata_source_groups_0_missing=slug", filters.detail)

    def test_catalog_metadata_issue_filter_fails_when_item_lacks_issue_code(self):
        class BrokenCatalogMetadataIssueFilterClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies" and (query or {}).get("metadata_issue_code"):
                    payload["data"]["items"][0]["metadata_state"]["issue_codes"] = []
                return payload

        with patch.object(self.module, "SmokeClient", BrokenCatalogMetadataIssueFilterClient):
            results = self.module.run_checks(self._args())

        filters = next(item for item in results if item.name == "catalog_metadata_issue_filter")
        self.assertFalse(filters.ok)
        self.assertIn("item_0_missing_metadata_issue_code=poster_missing", filters.detail)

    def test_catalog_metadata_source_group_filter_fails_when_item_group_mismatches(self):
        class BrokenCatalogMetadataSourceGroupFilterClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies" and (query or {}).get("metadata_source_group"):
                    payload["data"]["items"][0]["metadata_state"]["source_group"] = "local"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenCatalogMetadataSourceGroupFilterClient):
            results = self.module.run_checks(self._args())

        filters = next(item for item in results if item.name == "catalog_metadata_source_group_filter")
        self.assertFalse(filters.ok)
        self.assertIn("item_0_source_group=local/tmdb", filters.detail)

    def test_update_check_fails_when_download_is_not_cdn_validated(self):
        class BrokenUpdateCheckClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/system/update-check":
                    payload["data"]["downloads"][0]["cdn"] = False
                return payload

        with patch.object(self.module, "SmokeClient", BrokenUpdateCheckClient):
            results = self.module.run_checks(self._args(expected_version="1.21.0"))

        update = next(item for item in results if item.name == "update_check")
        self.assertFalse(update.ok)
        self.assertIn("update_download_0_cdn_not_true", update.detail)

    def test_update_check_fails_when_update_has_no_selected_download(self):
        class BrokenUpdateCheckClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/system/update-check":
                    payload["data"]["update_available"] = True
                    payload["data"]["downloads"] = []
                    payload["data"]["selected_download"] = None
                return payload

        with patch.object(self.module, "SmokeClient", BrokenUpdateCheckClient):
            results = self.module.run_checks(self._args(expected_version="1.21.0"))

        update = next(item for item in results if item.name == "update_check")
        self.assertFalse(update.ok)
        self.assertIn("update_available_without_selected_download", update.detail)

    def test_other_videos_fails_when_manual_action_drops_resource_id(self):
        class BrokenOtherVideosClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/other-videos":
                    payload["data"]["items"][0]["actions"]["create_manual_movie"]["body"]["resource_ids"] = []
                return payload

        with patch.object(self.module, "SmokeClient", BrokenOtherVideosClient):
            results = self.module.run_checks(self._args())

        other_videos = next(item for item in results if item.name == "other_videos")
        self.assertFalse(other_videos.ok)
        self.assertIn("other_video_0_action_create_manual_movie_resource_id_missing", other_videos.detail)

    def test_external_playback_fails_when_playlist_url_is_not_m3u(self):
        class BrokenExternalPlaybackClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/resources/resource-1/external-playback":
                    payload["data"]["handoff"]["playlist_url"] = (
                        "http://example.test/api/v1/resources/resource-1/external-playback"
                    )
                return payload

        with patch.object(self.module, "SmokeClient", BrokenExternalPlaybackClient):
            results = self.module.run_checks(self._args())

        external_playback = next(item for item in results if item.name == "external_playback")
        self.assertFalse(external_playback.ok)
        self.assertIn("external_handoff_playlist_url_invalid", external_playback.detail)

    def test_external_playback_fails_when_m3u_stream_url_is_missing(self):
        class BrokenExternalPlaybackM3uClient(FakeSmokeClient):
            def get_text(self, path, query=None):
                if path == "/api/v1/resources/resource-1/external-playback" and (query or {}).get("format") == "m3u":
                    return {
                        "_http_status": 200,
                        "_content_type": "audio/x-mpegurl; charset=utf-8",
                        "_content_disposition": "attachment; filename=\"cyberstream-resource-1.m3u\"",
                        "text": (
                            "#EXTM3U\n"
                            "#EXTINF:-1,Sample.Movie.2024.1080p.mkv\n"
                            "#EXTVLCOPT:network-caching=1000\n"
                            "http://example.test/wrong-resource/stream\n"
                        ),
                    }
                return super().get_text(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenExternalPlaybackM3uClient):
            results = self.module.run_checks(self._args())

        external_playback = next(item for item in results if item.name == "external_playback")
        self.assertFalse(external_playback.ok)
        self.assertIn("external_playlist_missing_stream_url", external_playback.detail)

    def test_auth_me_fails_when_unauthenticated_permissions_are_enabled(self):
        class BrokenAuthMeClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/auth/me":
                    payload["data"]["permissions"]["read_catalog"] = True
                return payload

        with patch.object(self.module, "SmokeClient", BrokenAuthMeClient):
            results = self.module.run_checks(self._args())

        auth_me = next(item for item in results if item.name == "auth_me")
        self.assertFalse(auth_me.ok)
        self.assertIn("unauth_permissions_enabled=read_catalog", auth_me.detail)

    def test_subtitle_settings_fail_when_color_is_invalid(self):
        class BrokenSubtitleSettingsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/resources/resource-1/subtitle-settings":
                    payload["data"]["settings"]["zhColor"] = "white"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenSubtitleSettingsClient):
            results = self.module.run_checks(self._args())

        subtitle_settings = next(item for item in results if item.name == "subtitle_settings")
        self.assertFalse(subtitle_settings.ok)
        self.assertIn("subtitle_display_zhColor_invalid", subtitle_settings.detail)

    def test_audio_transcode_diagnostics_fail_when_active_count_mismatches(self):
        class BrokenAudioDiagnosticsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/resources/resource-1/audio-transcode/diagnostics":
                    payload["data"]["active_count"] = 1
                return payload

        with patch.object(self.module, "SmokeClient", BrokenAudioDiagnosticsClient):
            results = self.module.run_checks(self._args())

        diagnostics = next(item for item in results if item.name == "audio_transcode_diagnostics")
        self.assertFalse(diagnostics.ok)
        self.assertIn("audio_diagnostics_active_count_mismatch=1/0", diagnostics.detail)

    def test_libraries_fail_when_virtual_favorites_leaks_into_list(self):
        class BrokenLibrariesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/libraries":
                    payload["data"][0]["slug"] = "favorites"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenLibrariesClient):
            results = self.module.run_checks(self._args())

        libraries = next(item for item in results if item.name == "libraries")
        self.assertFalse(libraries.ok)
        self.assertIn("library_0_virtual_favorites_in_list", libraries.detail)

    def test_movie_detail_fails_when_detail_shape_is_broken(self):
        class BrokenMovieDetailClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1":
                    del payload["data"]["metadata_actions"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenMovieDetailClient):
            results = self.module.run_checks(self._args())

        detail = next(item for item in results if item.name == "movie_detail")
        self.assertFalse(detail.ok)
        self.assertIn("detail_missing=metadata_actions", detail.detail)

    def test_movie_images_status_fails_when_backdrop_item_is_missing(self):
        class BrokenMovieImagesStatusClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1/images/status":
                    payload["data"]["items"] = [
                        item for item in payload["data"]["items"] if item["kind"] != "backdrop"
                    ]
                    payload["data"]["summary"]["total"] = 1
                return payload

        with patch.object(self.module, "SmokeClient", BrokenMovieImagesStatusClient):
            results = self.module.run_checks(self._args())

        images = next(item for item in results if item.name == "movie_images_status")
        self.assertFalse(images.ok)
        self.assertIn("movie_images_status_missing_kinds=backdrop", images.detail)

    def test_movie_resources_fails_when_playback_source_shape_is_broken(self):
        class BrokenMovieResourcesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1/resources":
                    del payload["data"]["groups"]["playback_sources"][0]["primary_resource_id"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenMovieResourcesClient):
            results = self.module.run_checks(self._args())

        resources = next(item for item in results if item.name == "movie_resources")
        self.assertFalse(resources.ok)
        self.assertIn("playback_source_0_missing=primary_resource_id", resources.detail)

    def test_movie_resources_fails_when_cloud_transcode_shape_is_broken(self):
        class BrokenMovieResourcesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1/resources":
                    payload["data"]["items"][0]["playback"]["cloud_transcode"]["reason"] = False
                return payload

        with patch.object(self.module, "SmokeClient", BrokenMovieResourcesClient):
            results = self.module.run_checks(self._args())

        resources = next(item for item in results if item.name == "movie_resources")
        self.assertFalse(resources.ok)
        self.assertIn("resource_0_playback_cloud_transcode_reason_not_str", resources.detail)

    def test_streaming_qualities_fails_when_supported_payload_shape_is_broken(self):
        class BrokenStreamingQualitiesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1/resources":
                    cloud_transcode = payload["data"]["items"][0]["playback"]["cloud_transcode"]
                    cloud_transcode.update({
                        "supported": True,
                        "provider": "quarktv",
                        "provider_name": "QuarkTV",
                        "mode": "provider_cloud_transcode",
                        "qualities_endpoint": "/api/v1/resources/resource-1/streaming-qualities",
                        "stream_endpoint": "/api/v1/resources/resource-1/stream-transcoded",
                        "available_resolutions": ["low", "4k"],
                        "recommended_for": ["web_player"],
                        "quality_semantics": "provider_cloud_transcode_not_original_file",
                        "reason": None,
                    })
                return payload

            def get_json_allow_error(self, path, query=None):
                if path == "/api/v1/resources/resource-1/streaming-qualities":
                    return {
                        "_http_status": 200,
                        "code": 200,
                        "data": {
                            "resource_id": "resource-1",
                            "storage_type": "quarktv",
                            "provider": "QuarkTV",
                            "mode": "provider_cloud_transcode",
                            "default_resolution": "4k",
                            "selected_resolution": "4k",
                            "selected_item": {
                                "resolution": "4k",
                                "label": "4K",
                                "available": True,
                                "url": "https://provider.example/4k.m3u8",
                                "stream_url": "/bad-stream-url",
                            },
                            "items": [
                                {
                                    "resolution": "4k",
                                    "label": "4K",
                                    "available": True,
                                    "url": "https://provider.example/4k.m3u8",
                                    "stream_url": "/bad-stream-url",
                                },
                            ],
                            "warnings": [],
                        },
                    }
                return super().get_json_allow_error(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenStreamingQualitiesClient):
            results = self.module.run_checks(self._args())

        qualities = next(item for item in results if item.name == "streaming_qualities")
        self.assertFalse(qualities.ok)
        self.assertIn("quality_0_stream_url_invalid", qualities.detail)

    def test_resource_stream_range_fails_when_redirect_location_is_missing(self):
        class BrokenResourceStreamClient(FakeSmokeClient):
            def get_binary_sample(self, path, query=None, headers=None, max_bytes=1024):
                if path == "/api/v1/resources/resource-1/stream":
                    return {
                        "_http_status": 302,
                        "_headers": {"Content-Type": "text/html; charset=utf-8"},
                        "_content_type": "text/html; charset=utf-8",
                        "_content_range": None,
                        "_accept_ranges": None,
                        "_location": None,
                        "byte_count": 128,
                    }
                return super().get_binary_sample(path, query=query, headers=headers, max_bytes=max_bytes)

        with patch.object(self.module, "SmokeClient", BrokenResourceStreamClient):
            results = self.module.run_checks(self._args())

        stream = next(item for item in results if item.name == "resource_stream_range")
        self.assertFalse(stream.ok)
        self.assertIn("resource_stream_redirect_location_missing", stream.detail)

    def test_movie_seasons_fails_when_primary_resource_ids_are_broken(self):
        class BrokenMovieSeasonsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1/seasons":
                    payload["data"]["items"][0]["primary_resource_ids"] = ["missing-resource"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenMovieSeasonsClient):
            results = self.module.run_checks(self._args())

        seasons = next(item for item in results if item.name == "movie_seasons")
        self.assertFalse(seasons.ok)
        self.assertIn("season_0_primary_resource_ids_unknown=missing-resource", seasons.detail)

    def test_movie_episode_diagnostics_fails_when_summary_shape_is_broken(self):
        class BrokenMovieEpisodeDiagnosticsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1/episode-diagnostics":
                    payload["data"]["summary"]["issue_count"] = "1"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenMovieEpisodeDiagnosticsClient):
            results = self.module.run_checks(self._args())

        diagnostics = next(item for item in results if item.name == "movie_episode_diagnostics")
        self.assertFalse(diagnostics.ok)
        self.assertIn("episode_summary_issue_count_not_int", diagnostics.detail)

    def test_featured_fails_when_detail_shape_is_broken(self):
        class BrokenFeaturedClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/featured":
                    del payload["data"][0]["backdrop_asset_url"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenFeaturedClient):
            results = self.module.run_checks(self._args())

        featured = next(item for item in results if item.name == "featured")
        self.assertFalse(featured.ok)
        self.assertIn("detail_missing=backdrop_asset_url", featured.detail)

    def test_homepage_config_fails_when_section_shape_is_broken(self):
        class BrokenHomepageConfigClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/homepage/config":
                    del payload["data"]["sections"][0]["movie_ids"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenHomepageConfigClient):
            results = self.module.run_checks(self._args())

        config = next(item for item in results if item.name == "homepage_config")
        self.assertFalse(config.ok)
        self.assertIn("config_section_0_missing=movie_ids", config.detail)

    def test_homepage_fails_when_section_shape_is_broken(self):
        class BrokenHomepageClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/homepage":
                    del payload["data"]["sections"][0]["items"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenHomepageClient):
            results = self.module.run_checks(self._args())

        homepage = next(item for item in results if item.name == "homepage")
        self.assertFalse(homepage.ok)
        self.assertIn("section_0_missing=items", homepage.detail)

    def test_recommendations_fail_when_reason_shape_is_broken(self):
        class BrokenRecommendationsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/recommendations":
                    del payload["data"][0]["recommendation"]["primary_reason"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenRecommendationsClient):
            results = self.module.run_checks(self._args())

        recommendations = next(item for item in results if item.name == "recommendations")
        self.assertFalse(recommendations.ok)
        self.assertIn("item_0_recommendation_missing=primary_reason", recommendations.detail)

    def test_recommendations_fail_without_crashing_when_primary_reason_is_not_object(self):
        class BrokenRecommendationsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/recommendations":
                    payload["data"][0]["recommendation"]["primary_reason"] = "high_rating"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenRecommendationsClient):
            results = self.module.run_checks(self._args())

        recommendations = next(item for item in results if item.name == "recommendations")
        self.assertFalse(recommendations.ok)
        self.assertIn("item_0_recommendation_primary_reason_not_object", recommendations.detail)

    def test_movie_context_recommendations_fail_when_anchor_is_returned(self):
        class BrokenContextRecommendationsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/movies/movie-1/recommendations":
                    payload["data"][0]["id"] = "movie-1"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenContextRecommendationsClient):
            results = self.module.run_checks(self._args())

        context = next(item for item in results if item.name == "movie_context_recommendations")
        self.assertFalse(context.ok)
        self.assertIn("item_0_is_anchor=movie-1", context.detail)

    def test_user_history_fails_when_is_played_leaks_back(self):
        class BrokenUserHistoryClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/user/history":
                    payload["data"]["items"][0]["is_played"] = True
                return payload

        with patch.object(self.module, "SmokeClient", BrokenUserHistoryClient):
            results = self.module.run_checks(self._args())

        history = next(item for item in results if item.name == "user_history")
        self.assertFalse(history.ok)
        self.assertIn("history_0_has_is_played", history.detail)

    def test_user_achievements_fails_when_user_state_has_unknown_id(self):
        class BrokenUserAchievementsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/user/achievements":
                    payload["data"]["user"].append({
                        "id": "unknown-achievement",
                        "unlocked_at": None,
                    })
                return payload

        with patch.object(self.module, "SmokeClient", BrokenUserAchievementsClient):
            results = self.module.run_checks(self._args())

        achievements = next(item for item in results if item.name == "user_achievements")
        self.assertFalse(achievements.ok)
        self.assertIn("achievement_user_2_unknown_id=unknown-achievement", achievements.detail)

    def test_user_favorites_fails_when_unlocked_list_shape_is_broken(self):
        class BrokenUserFavoritesClient(FakeSmokeClient):
            def get_json_allow_error(self, path, query=None):
                if path == "/api/v1/user/favorites":
                    movie = FakeSmokeClient.get_json(self, "/api/v1/movies", query=query)["data"]["items"][0].copy()
                    return {
                        "_http_status": 200,
                        "code": 200,
                        "data": {
                            "items": [
                                {
                                    "id": 1,
                                    "movie_id": "movie-1",
                                    "created_at": "2026-06-07T00:00:00",
                                    "movie": movie,
                                },
                            ],
                            "movie_ids": ["movie-1"],
                            "total": 2,
                            "library": {
                                "id": "favorites",
                                "name": "我的收藏",
                                "slug": "favorites",
                                "description": "用户收藏的影视条目",
                                "is_enabled": True,
                                "sort_order": -100,
                                "settings": {"virtual": True, "kind": "favorites"},
                                "created_at": None,
                                "updated_at": None,
                                "is_virtual": True,
                                "kind": "favorites",
                                "movie_count": 1,
                                "actions": {
                                    "can_scan": False,
                                    "can_bind_sources": False,
                                    "can_manage_memberships": False,
                                    "can_delete": False,
                                },
                            },
                        },
                    }
                if path == "/api/v1/user/favorites/movie-1":
                    return {
                        "_http_status": 200,
                        "code": 200,
                        "data": {
                            "movie_id": "movie-1",
                            "is_favorite": True,
                            "created_at": "2026-06-07T00:00:00",
                        },
                    }
                return super().get_json_allow_error(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenUserFavoritesClient):
            results = self.module.run_checks(self._args())

        favorites = next(item for item in results if item.name == "user_favorites")
        self.assertFalse(favorites.ok)
        self.assertIn("favorites_total_mismatch=2/1", favorites.detail)

    def test_vault_status_fails_when_state_combination_is_invalid(self):
        class BrokenVaultStatusClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/user/vault/status":
                    payload["data"]["configured"] = False
                    payload["data"]["unlocked"] = True
                return payload

        with patch.object(self.module, "SmokeClient", BrokenVaultStatusClient):
            results = self.module.run_checks(self._args())

        vault = next(item for item in results if item.name == "vault_status")
        self.assertFalse(vault.ok)
        self.assertIn("vault_status_unconfigured_unlocked", vault.detail)

    def test_metadata_reidentify_plan_fails_when_dry_run_contract_is_broken(self):
        class BrokenReidentifyPlanClient(FakeSmokeClient):
            def post_json(self, path, body=None):
                payload = super().post_json(path, body=body)
                if path == "/api/v1/metadata/re-scrape/plan":
                    payload["data"]["dry_run"] = False
                return payload

        with patch.object(self.module, "SmokeClient", BrokenReidentifyPlanClient):
            results = self.module.run_checks(self._args())

        plan = next(item for item in results if item.name == "metadata_reidentify_plan")
        self.assertFalse(plan.ok)
        self.assertIn("dry_run_not_true", plan.detail)

    def test_pending_review_backfill_dry_run_fails_when_updates_are_returned(self):
        class BrokenPendingReviewBackfillClient(FakeSmokeClient):
            def post_json(self, path, body=None):
                payload = super().post_json(path, body=body)
                if path == "/api/v1/metadata/pending-review/backfill":
                    payload["data"]["updated"] = [
                        {
                            "movie_id": "movie-1",
                            "action": "set_pending_review",
                        },
                    ]
                    payload["data"]["summary"]["updated"] = 1
                return payload

        with patch.object(self.module, "SmokeClient", BrokenPendingReviewBackfillClient):
            results = self.module.run_checks(self._args())

        backfill = next(item for item in results if item.name == "pending_review_backfill_dry_run")
        self.assertFalse(backfill.ok)
        self.assertIn("dry_run_updated_not_empty=1", backfill.detail)

    def test_episode_review_fails_when_queue_sample_shape_is_broken(self):
        class BrokenEpisodeReviewClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/metadata/episode-review-items":
                    payload["data"] = {
                        "items": [
                            {
                                "movie_id": "movie-1",
                                "title": "Episode Queue",
                                "playable": True,
                                "primary_resource_id": 1,
                                "scraper_source": "TMDB",
                                "metadata_state": {
                                    "source_group": "tmdb",
                                    "source_code": "TMDB",
                                    "source_label": "TMDB",
                                    "issue_codes": ["missing_episode_numbers"],
                                    "needs_attention": True,
                                    "review_priority": "medium",
                                    "recommended_action": "episode_review_queue",
                                },
                                "metadata_issues": [
                                    {"code": "missing_episode_numbers", "count": 1},
                                ],
                                "episode_diagnostics": {
                                    "status": "warning",
                                },
                                "season_count": 1,
                                "seasons_needing_attention": [1],
                                "auto_update_count": 1,
                                "manual_suggestion_count": 0,
                                "warning_count": 0,
                                "diagnostics_endpoint": "/api/v1/movies/movie-1/episode-diagnostics",
                                "apply_method": "PATCH",
                                "apply_endpoint": "/api/v1/movies/movie-1/resources/metadata",
                                "apply_payload": {
                                    "items": [
                                        {"id": 1, "season": 1, "episode": 2},
                                    ],
                                },
                            },
                        ],
                        "pagination": {
                            "current_page": 1,
                            "page_size": 20,
                            "total_items": 1,
                            "total_pages": 1,
                        },
                        "summary": {
                            "total_items": 1,
                            "issue_code_counts": {"missing_episode_numbers": 1},
                            "auto_update_count": 1,
                            "manual_suggestion_count": 0,
                            "warning_count": 0,
                        },
                    }
                return payload

        with patch.object(self.module, "SmokeClient", BrokenEpisodeReviewClient):
            results = self.module.run_checks(self._args(max_episode_review_items=1))

        episode = next(item for item in results if item.name == "episode_review")
        self.assertFalse(episode.ok)
        self.assertIn("item_0_missing=metadata_actions", episode.detail)

    def test_resource_governance_plan_fails_when_apply_payload_contract_is_broken(self):
        class BrokenResourceGovernancePlanClient(FakeSmokeClient):
            def post_json(self, path, body=None):
                payload = super().post_json(path, body=body)
                if path == "/api/v1/resources/governance/plan":
                    payload["data"]["apply_payload"]["confirm"] = False
                return payload

        with patch.object(self.module, "SmokeClient", BrokenResourceGovernancePlanClient):
            results = self.module.run_checks(self._args())

        plan = next(item for item in results if item.name == "resource_governance_plan")
        self.assertFalse(plan.ok)
        self.assertIn("apply_payload_confirm=False", plan.detail)

    def test_background_jobs_fails_when_summary_contract_is_broken(self):
        class BrokenJobsClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/jobs":
                    payload["data"]["summary"]["count"] = 2
                return payload

        with patch.object(self.module, "SmokeClient", BrokenJobsClient):
            results = self.module.run_checks(self._args())

        jobs = next(item for item in results if item.name == "background_jobs")
        self.assertFalse(jobs.ok)
        self.assertIn("count_mismatch=2/1", jobs.detail)

    def test_background_job_detail_fails_when_progress_contract_is_broken(self):
        class BrokenJobDetailClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/jobs/job-1":
                    payload["data"]["progress"] = "done"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenJobDetailClient):
            results = self.module.run_checks(self._args())

        detail = next(item for item in results if item.name == "background_job_detail")
        self.assertFalse(detail.ok)
        self.assertIn("job_progress_not_object", detail.detail)

    def test_background_jobs_prune_fails_when_dry_run_would_remove_jobs(self):
        class BrokenJobsPruneClient(FakeSmokeClient):
            def post_json(self, path, body=None):
                payload = super().post_json(path, body=body)
                if path == "/api/v1/jobs/prune":
                    payload["data"]["removed"] = 1
                    payload["data"]["removed_ids"] = ["job-1"]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenJobsPruneClient):
            results = self.module.run_checks(self._args())

        prune = next(item for item in results if item.name == "background_jobs_prune")
        self.assertFalse(prune.ok)
        self.assertIn("removed=1", prune.detail)
        self.assertIn("removed_ids=['job-1']", prune.detail)

    def test_storage_sources_fail_when_resource_backed_source_cannot_stream(self):
        class BrokenStorageSourceClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/storage/sources":
                    payload["data"][0]["actions"]["can_stream"] = False
                return payload

        with patch.object(self.module, "SmokeClient", BrokenStorageSourceClient):
            results = self.module.run_checks(self._args())

        storage = next(item for item in results if item.name == "storage_sources")
        self.assertFalse(storage.ok)
        self.assertIn("stream_disabled", storage.detail)

    def test_storage_sources_fail_when_below_minimum_count(self):
        class EmptyStorageClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                if path == "/api/v1/storage/sources":
                    return {"data": []}
                return super().get_json(path, query=query)

        with patch.object(self.module, "SmokeClient", EmptyStorageClient):
            results = self.module.run_checks(self._args(min_storage_sources=1))

        storage = next(item for item in results if item.name == "storage_sources")
        self.assertFalse(storage.ok)
        self.assertIn("sources_below_min=0/1", storage.detail)

    def test_storage_source_detail_fails_when_guards_are_broken(self):
        class BrokenStorageSourceDetailClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/storage/sources/1":
                    payload["data"]["guards"]["can_delete_directly"] = True
                return payload

        with patch.object(self.module, "SmokeClient", BrokenStorageSourceDetailClient):
            results = self.module.run_checks(self._args())

        detail = next(item for item in results if item.name == "storage_source_detail")
        self.assertFalse(detail.ok)
        self.assertIn("storage_source_guards_dependents_can_delete_directly", detail.detail)

    def test_storage_capabilities_fail_when_required_provider_is_missing(self):
        class MissingOpenListCapabilitiesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/storage/capabilities":
                    payload["data"]["supported_types"].remove("openlist")
                    payload["data"]["items"] = [
                        item
                        for item in payload["data"]["items"]
                        if item["type"] != "openlist"
                    ]
                return payload

        with patch.object(self.module, "SmokeClient", MissingOpenListCapabilitiesClient):
            results = self.module.run_checks(self._args())

        capabilities = next(item for item in results if item.name == "storage_capabilities")
        self.assertFalse(capabilities.ok)
        self.assertIn("missing_expected_types=openlist", capabilities.detail)

    def test_storage_provider_types_fail_when_required_config_field_is_missing(self):
        class BrokenProviderTypesClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/storage/provider-types":
                    openlist = next(item for item in payload["data"] if item["type"] == "openlist")
                    openlist["config_fields"] = [
                        field
                        for field in openlist["config_fields"]
                        if field["name"] != "root"
                    ]
                return payload

        with patch.object(self.module, "SmokeClient", BrokenProviderTypesClient):
            results = self.module.run_checks(self._args())

        provider_types = next(item for item in results if item.name == "storage_provider_types")
        self.assertFalse(provider_types.ok)
        self.assertIn("provider_openlist_missing_config_fields=root", provider_types.detail)

    def test_storage_browse_fails_when_dirs_only_returns_file_items(self):
        class BrokenStorageBrowseClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/storage/sources/1/browse":
                    payload["data"]["items"][0]["type"] = "file"
                return payload

        with patch.object(self.module, "SmokeClient", BrokenStorageBrowseClient):
            results = self.module.run_checks(self._args())

        browse = next(item for item in results if item.name == "storage_browse")
        self.assertFalse(browse.ok)
        self.assertIn("item_0_type=file", browse.detail)

    def test_run_checks_can_verify_storage_health_when_enabled(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args(
                storage_health_check=True,
                min_storage_health_checks=1,
            ))

        health = results[-1]
        self.assertEqual("storage_health", health.name)
        self.assertTrue(health.ok)
        self.assertIn("checked=1", health.detail)

    def test_storage_health_fails_when_checked_sources_are_below_minimum(self):
        class NoHealthCapabilityStorageClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/storage/sources":
                    payload["data"][0]["capabilities"]["health_check"] = False
                return payload

        with patch.object(self.module, "SmokeClient", NoHealthCapabilityStorageClient):
            results = self.module.run_checks(self._args(
                storage_health_check=True,
                min_storage_health_checks=1,
            ))

        health = next(item for item in results if item.name == "storage_health")
        self.assertFalse(health.ok)
        self.assertIn("checked_below_min=0/1", health.detail)

    def test_storage_health_fails_when_resource_backed_source_is_offline(self):
        class OfflineStorageHealthClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/storage/sources/1/health":
                    payload["data"]["health"].update({
                        "status": "offline",
                        "reason": "auth_failed",
                    })
                return payload

        with patch.object(self.module, "SmokeClient", OfflineStorageHealthClient):
            results = self.module.run_checks(self._args(storage_health_check=True))

        health = next(item for item in results if item.name == "storage_health")
        self.assertFalse(health.ok)
        self.assertIn("health=offline:auth_failed", health.detail)

    def test_run_checks_can_verify_tmdb_token_when_enabled(self):
        with patch.object(self.module, "SmokeClient", FakeSmokeClient):
            results = self.module.run_checks(self._args(tmdb_token_check=True))

        tmdb = results[-1]
        self.assertEqual("tmdb_token", tmdb.name)
        self.assertTrue(tmdb.ok)
        self.assertIn("status=ok", tmdb.detail)

    def test_tmdb_config_fails_when_proxy_credentials_are_not_marked_redacted(self):
        class BrokenTmdbConfigClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/system/tmdb-config":
                    payload["data"]["proxy_url"] = "http://user:pass@127.0.0.1:7890"
                    payload["data"]["proxy_url_redacted"] = False
                return payload

        with patch.object(self.module, "SmokeClient", BrokenTmdbConfigClient):
            results = self.module.run_checks(self._args())

        tmdb = next(item for item in results if item.name == "tmdb_config")
        self.assertFalse(tmdb.ok)
        self.assertIn("tmdb_config_proxy_url_unredacted_credentials", tmdb.detail)

    def test_tmdb_token_check_fails_when_token_is_not_ready(self):
        class InvalidTmdbClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                payload = super().get_json(path, query=query)
                if path == "/api/v1/system/tmdb-config/check":
                    payload["data"].update({
                        "ready": False,
                        "status": "invalid_token",
                        "token_valid": False,
                        "http_status": 401,
                    })
                return payload

        with patch.object(self.module, "SmokeClient", InvalidTmdbClient):
            results = self.module.run_checks(self._args(tmdb_token_check=True))

        tmdb = next(item for item in results if item.name == "tmdb_token")
        self.assertFalse(tmdb.ok)
        self.assertIn("status=invalid_token", tmdb.detail)

    def test_run_checks_reports_named_failure_when_check_raises(self):
        class BrokenOpenApiClient(FakeSmokeClient):
            def get_json(self, path, query=None):
                if path == "/api/v1/openapi.json":
                    raise RuntimeError("openapi unavailable")
                return super().get_json(path, query=query)

        with patch.object(self.module, "SmokeClient", BrokenOpenApiClient):
            results = self.module.run_checks(self._args())

        failure = next(item for item in results if not item.ok)
        self.assertEqual("openapi_health_contract", failure.name)
        self.assertIn("openapi unavailable", failure.detail)
        self.assertNotIn("<lambda>", [item.name for item in results])

    def test_systemd_check_reports_all_services_active(self):
        completed = self.module.subprocess.CompletedProcess(
            args=["systemctl", "is-active"],
            returncode=0,
            stdout="active\nactive\n",
            stderr="",
        )

        with patch.object(self.module.subprocess, "run", return_value=completed):
            result = self.module.check_systemd_services(["backend", "nginx"], timeout=1.0)

        self.assertTrue(result.ok)
        self.assertEqual({"backend": "active", "nginx": "active"}, result.data["services"])

    def test_run_checks_includes_systemd_failures_when_enabled(self):
        completed = self.module.subprocess.CompletedProcess(
            args=["systemctl", "is-active"],
            returncode=3,
            stdout="active\ninactive\n",
            stderr="",
        )

        with patch.object(self.module, "SmokeClient", FakeSmokeClient), patch.object(
            self.module.subprocess,
            "run",
            return_value=completed,
        ):
            results = self.module.run_checks(self._args(
                systemd=True,
                systemd_service=["backend", "openlist"],
            ))

        systemd = results[0]
        self.assertEqual("systemd_services", systemd.name)
        self.assertFalse(systemd.ok)
        self.assertEqual("inactive", systemd.data["services"]["openlist"])


if __name__ == "__main__":
    unittest.main()
