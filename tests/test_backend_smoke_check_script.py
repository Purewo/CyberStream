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
    def __init__(self, base_url, timeout=10.0):
        self.base_url = base_url
        self.timeout = timeout

    def get_json(self, path, query=None):
        if path == "/api/v1/health":
            return {"data": {"status": "up", "version": "1.21.0"}}
        if path == "/api/v1/openapi.json":
            return {
                "paths": {
                    "/api/v1/health": {
                        "get": {
                            "operationId": "apiHealthCheck",
                            "security": [],
                        },
                    },
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
        if path == "/api/v1/metadata/work-items":
            total = 0
            if (query or {}).get("metadata_issue_code") == "fallback_pipeline_match":
                total = 0
            return {"data": {"items": [], "pagination": {"total_items": total}}}
        if path == "/api/v1/metadata/episode-review-items":
            return {"data": {"items": [], "pagination": {"total_items": 0}}}
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


class BackendSmokeCheckScriptTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_script_module()

    def _args(self, **overrides):
        args = {
            "base_url": "http://example.test",
            "timeout": 1.0,
            "live_check_limit": 500,
            "max_fallback_items": 0,
            "max_episode_review_items": 0,
            "max_resource_actionable": 0,
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
                "scan",
                "metadata_providers",
                "metadata_fallback_pipeline_match",
                "episode_review",
                "resource_governance",
            ],
            [item.name for item in results],
        )

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
