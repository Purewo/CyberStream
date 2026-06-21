from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.services import tmdb as tmdb_module
from backend.app.services.tmdb import TMDBScraper


TMDB_ENV_KEYS = (
    "TMDB_TOKEN",
    "CYBER_TMDB_TOKEN_POOL",
    "TMDB_TOKEN_POOL",
    "TMDB_PROXY_ENABLED",
    "TMDB_PROXY_URL",
)


class TmdbConfigRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="cyber-tmdb-config-")
        self.env_path = Path(self.temp_dir) / ".env.local"
        self.original_env = {key: os.environ.get(key) for key in TMDB_ENV_KEYS}
        for key in TMDB_ENV_KEYS:
            os.environ.pop(key, None)

        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TMDB_TOKEN": "",
            "CYBER_TMDB_TOKEN_POOL": "",
            "TMDB_TOKEN_POOL_RAW": "",
            "TMDB_TOKEN_POOL": [],
            "TMDB_PROXY_ENABLED": True,
            "TMDB_PROXY_URL": "",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.env_path_patch = patch(
            "backend.app.api.system_routes._env_local_path",
            return_value=str(self.env_path),
        )
        self.env_path_patch.start()
        self.refresh_patch = patch("backend.app.api.system_routes._refresh_runtime_config")
        self.refresh_runtime_config_mock = self.refresh_patch.start()

    def tearDown(self):
        self.refresh_patch.stop()
        self.env_path_patch.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_put_rejects_non_object_payload(self):
        response = self.client.put("/api/v1/system/tmdb-config", json=["token"])

        self.assertEqual(400, response.status_code)
        self.assertEqual(40027, response.get_json()["code"])

    def test_put_rejects_token_env_line_injection_without_mutating_state(self):
        self.env_path.write_text("KEEP=1\n", encoding="utf-8")
        os.environ["TMDB_TOKEN"] = "old-token"

        response = self.client.put("/api/v1/system/tmdb-config", json={
            "token": "valid-token\nINJECTED=1",
        })

        self.assertEqual(400, response.status_code)
        self.assertEqual(40028, response.get_json()["code"])
        self.assertEqual("KEEP=1\n", self.env_path.read_text(encoding="utf-8"))
        self.assertEqual("old-token", os.environ.get("TMDB_TOKEN"))
        self.assertIsNone(os.environ.get("INJECTED"))

    def test_put_rejects_proxy_url_env_line_injection_without_mutating_state(self):
        self.env_path.write_text("KEEP=1\n", encoding="utf-8")

        response = self.client.put("/api/v1/system/tmdb-config", json={
            "proxy_url": "http://127.0.0.1:7890\nINJECTED=1",
        })

        self.assertEqual(400, response.status_code)
        self.assertEqual(40023, response.get_json()["code"])
        self.assertEqual("KEEP=1\n", self.env_path.read_text(encoding="utf-8"))
        self.assertIsNone(os.environ.get("TMDB_PROXY_URL"))
        self.assertIsNone(os.environ.get("INJECTED"))

    def test_put_write_failure_does_not_mutate_runtime_env_or_leak_exception(self):
        os.environ["TMDB_TOKEN"] = "old-token"
        with patch(
            "backend.app.api.system_routes._write_env_file",
            side_effect=OSError("secret filesystem path"),
        ):
            response = self.client.put("/api/v1/system/tmdb-config", json={
                "token": "new-token",
            })

        payload = response.get_json()
        self.assertEqual(500, response.status_code)
        self.assertEqual(50010, payload["code"])
        self.assertEqual("写入 .env.local 失败", payload["msg"])
        self.assertEqual("old-token", os.environ.get("TMDB_TOKEN"))

    def test_put_writes_env_file_atomically_with_private_permissions(self):
        self.env_path.write_text("KEEP=1\nTMDB_TOKEN=old\n", encoding="utf-8")

        response = self.client.put("/api/v1/system/tmdb-config", json={
            "token": "new-token",
            "proxy_enabled": False,
            "proxy_url": "http://user:pass@127.0.0.1:7890",
        })

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["token_set"])
        self.assertFalse(data["proxy_enabled"])
        self.assertEqual("http://***:***@127.0.0.1:7890", data["proxy_url"])
        self.assertTrue(data["proxy_url_redacted"])
        self.assertEqual("new-token", os.environ["TMDB_TOKEN"])
        self.assertEqual("false", os.environ["TMDB_PROXY_ENABLED"])
        self.assertEqual("http://user:pass@127.0.0.1:7890", os.environ["TMDB_PROXY_URL"])
        self.assertEqual(
            "KEEP=1\nTMDB_TOKEN=new-token\nTMDB_PROXY_ENABLED=false\nTMDB_PROXY_URL=http://user:pass@127.0.0.1:7890\n",
            self.env_path.read_text(encoding="utf-8"),
        )
        self.assertEqual(0o600, stat.S_IMODE(self.env_path.stat().st_mode))
        self.assertEqual([], list(Path(self.temp_dir).glob(".env.local.*.tmp")))

    def test_get_redacts_proxy_credentials(self):
        os.environ["TMDB_PROXY_URL"] = "socks5://user:pass@proxy.example:1080"

        response = self.client.get("/api/v1/system/tmdb-config")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("socks5://***:***@proxy.example:1080", data["proxy_url"])
        self.assertTrue(data["proxy_url_redacted"])
        self.assertNotIn("pass", data["proxy_url"])

    def test_get_reports_token_pool_status_without_leaking_values(self):
        os.environ["CYBER_TMDB_TOKEN_POOL"] = "token-a, token-b token-a"

        response = self.client.get("/api/v1/system/tmdb-config")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["token_set"])
        self.assertEqual(2, data["token_pool_size"])
        self.assertTrue(data["token_pool_enabled"])
        self.assertNotIn("token-a", str(data))

    def test_put_redacted_proxy_placeholder_preserves_existing_secret_value(self):
        self.env_path.write_text(
            "TMDB_PROXY_URL=http://user:pass@127.0.0.1:7890\n",
            encoding="utf-8",
        )
        os.environ["TMDB_PROXY_URL"] = "http://user:pass@127.0.0.1:7890"

        response = self.client.put("/api/v1/system/tmdb-config", json={
            "proxy_enabled": False,
            "proxy_url": "http://***:***@127.0.0.1:7890",
        })

        self.assertEqual(200, response.status_code)
        self.assertEqual("http://user:pass@127.0.0.1:7890", os.environ["TMDB_PROXY_URL"])
        self.assertIn(
            "TMDB_PROXY_URL=http://user:pass@127.0.0.1:7890",
            self.env_path.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "TMDB_PROXY_ENABLED=false",
            self.env_path.read_text(encoding="utf-8"),
        )
        self.assertTrue(response.get_json()["data"]["proxy_url_redacted"])

    def test_check_returns_tmdb_status_without_leaking_token(self):
        status = {
            "ready": True,
            "token_set": True,
            "token_valid": True,
            "status": "ok",
            "message": "TMDB token is valid",
            "http_status": 200,
            "tmdb_status_code": 1,
            "tmdb_status_message": "Success.",
            "proxy_enabled": True,
            "proxy_configured": False,
            "elapsed_ms": 42,
        }
        with patch(
            "backend.app.api.system_routes.tmdb_scraper.check_token_status",
            return_value=status,
        ) as check_mock:
            response = self.client.get("/api/v1/system/tmdb-config/check")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(status, data)
        self.assertNotIn("token", data)
        check_mock.assert_called_once_with()
        self.refresh_runtime_config_mock.assert_called()

    def test_check_reports_runtime_refresh_failure(self):
        self.refresh_runtime_config_mock.side_effect = RuntimeError("secret path")

        response = self.client.get("/api/v1/system/tmdb-config/check")

        payload = response.get_json()
        self.assertEqual(500, response.status_code)
        self.assertEqual(50011, payload["code"])
        self.assertEqual("刷新 TMDB 运行配置失败", payload["msg"])


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class TMDBTokenCheckTests(unittest.TestCase):
    def create_scraper(self, token="valid-token", token_pool=""):
        patches = [
            patch.object(tmdb_module.config, "TMDB_TOKEN", token),
            patch.object(tmdb_module.config, "CYBER_TMDB_TOKEN_POOL", token_pool),
            patch.object(tmdb_module.config, "TMDB_TOKEN_POOL_RAW", ""),
            patch.object(
                tmdb_module.config,
                "TMDB_TOKEN_POOL",
                tmdb_module.config._build_tmdb_token_pool(token_pool, "", token),
            ),
            patch.object(tmdb_module.config, "TMDB_PROXY_ENABLED", False),
            patch.object(tmdb_module.config, "TMDB_PROXY_URL", ""),
            patch.object(tmdb_module.config, "TMDB_PROXIES", None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        scraper = TMDBScraper()
        self.addCleanup(scraper.session.close)
        return scraper

    def test_check_token_status_reports_missing_token_without_network(self):
        scraper = self.create_scraper(token="")

        with patch.object(scraper, "_session_get") as session_get:
            status = scraper.check_token_status()

        self.assertFalse(status["ready"])
        self.assertFalse(status["token_set"])
        self.assertFalse(status["token_valid"])
        self.assertEqual(0, status["token_pool_size"])
        self.assertEqual("missing_token", status["status"])
        session_get.assert_not_called()

    def test_check_token_status_accepts_valid_tmdb_response(self):
        scraper = self.create_scraper()

        with patch.object(scraper, "_pick_dns_family", return_value=None), patch.object(
            scraper,
            "_session_get",
            return_value=_FakeResponse(200, {
                "success": True,
                "status_code": 1,
                "status_message": "Success.",
            }),
        ):
            status = scraper.check_token_status()

        self.assertTrue(status["ready"])
        self.assertTrue(status["token_set"])
        self.assertTrue(status["token_valid"])
        self.assertEqual(1, status["token_pool_size"])
        self.assertEqual(1, status["token_valid_count"])
        self.assertEqual("ok", status["status"])
        self.assertEqual(200, status["http_status"])
        self.assertEqual(1, status["tmdb_status_code"])

    def test_check_token_status_reports_invalid_token(self):
        scraper = self.create_scraper(token="bad-token")

        with patch.object(scraper, "_pick_dns_family", return_value=None), patch.object(
            scraper,
            "_session_get",
            return_value=_FakeResponse(401, {
                "success": False,
                "status_code": 7,
                "status_message": "Invalid API key: You must be granted a valid key.",
            }),
        ):
            status = scraper.check_token_status()

        self.assertFalse(status["ready"])
        self.assertTrue(status["token_set"])
        self.assertFalse(status["token_valid"])
        self.assertEqual(1, status["token_pool_size"])
        self.assertEqual(0, status["token_valid_count"])
        self.assertEqual(1, status["token_invalid_count"])
        self.assertEqual("invalid_token", status["status"])
        self.assertEqual(401, status["http_status"])
        self.assertEqual(7, status["tmdb_status_code"])

    def test_check_token_status_reports_proxy_error(self):
        scraper = self.create_scraper()

        with patch.object(scraper, "_pick_dns_family", return_value=None), patch.object(
            scraper,
            "_session_get",
            side_effect=requests.exceptions.ProxyError("proxy down"),
        ):
            status = scraper.check_token_status()

        self.assertFalse(status["ready"])
        self.assertTrue(status["token_set"])
        self.assertEqual("proxy_error", status["status"])
        self.assertIsNone(status["http_status"])

    def test_requests_rotate_through_configured_token_pool(self):
        scraper = self.create_scraper(token="", token_pool="token-a,token-b")
        calls = []

        def fake_get(url, headers=None, params=None, proxies=None, timeout=None):
            calls.append(headers["Authorization"])
            return _FakeResponse(200, {"ok": True})

        with patch.object(scraper, "_pick_dns_family", return_value=None), patch.object(
            scraper.session,
            "get",
            side_effect=fake_get,
        ):
            self.assertEqual({"ok": True}, scraper._get("https://api.themoviedb.org/test"))
            self.assertEqual({"ok": True}, scraper._get("https://api.themoviedb.org/test"))

        self.assertEqual(["Bearer token-a", "Bearer token-b"], calls)

    def test_check_token_status_reports_partial_token_pool(self):
        scraper = self.create_scraper(token="", token_pool="valid-token,bad-token")

        def fake_session_get(url, params=None, family=None, timeout=10, token=None):
            if token == "valid-token":
                return _FakeResponse(200, {
                    "success": True,
                    "status_code": 1,
                    "status_message": "Success.",
                })
            return _FakeResponse(401, {
                "success": False,
                "status_code": 7,
                "status_message": "Invalid API key.",
            })

        with patch.object(scraper, "_pick_dns_family", return_value=None), patch.object(
            scraper,
            "_session_get",
            side_effect=fake_session_get,
        ):
            status = scraper.check_token_status()

        self.assertTrue(status["ready"])
        self.assertTrue(status["token_set"])
        self.assertTrue(status["token_valid"])
        self.assertEqual("partial_ok", status["status"])
        self.assertEqual(2, status["token_pool_size"])
        self.assertEqual(1, status["token_valid_count"])
        self.assertEqual(1, status["token_invalid_count"])
        self.assertEqual([0, 1], [item["token_index"] for item in status["token_checks"]])
        self.assertNotIn("valid-token", str(status))


if __name__ == "__main__":
    unittest.main()
