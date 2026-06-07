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
        type(self).last_init = {
            "base_url": base_url,
            "timeout": timeout,
            "api_token": api_token,
        }

    def get_json(self, path, query=None):
        if path in {"/", "/api/v1/health"}:
            return {"data": {"status": "up", "version": "1.21.0", "database": {"status": "ok", "reason": "ok"}}}
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
            return {"data": {"items": [], "pagination": {"total_items": 0}}}
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
                "openapi_health_contract",
                "docs_index",
                "openapi_modules",
                "scan",
                "metadata_providers",
                "metadata_review_workbench",
                "metadata_work_items_contract",
                "metadata_reidentify_plan",
                "background_jobs",
                "storage_sources",
                "metadata_fallback_pipeline_match",
                "episode_review",
                "resource_governance",
            ],
            [item.name for item in results],
        )

    def test_run_checks_passes_api_token_to_smoke_client(self):
        class TokenAwareClient(FakeSmokeClient):
            last_init = None

        with patch.object(self.module, "SmokeClient", TokenAwareClient):
            self.module.run_checks(self._args(api_token="secret-token"))

        self.assertEqual("secret-token", TokenAwareClient.last_init["api_token"])

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
