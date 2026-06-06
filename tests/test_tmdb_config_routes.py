from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db


TMDB_ENV_KEYS = ("TMDB_TOKEN", "TMDB_PROXY_ENABLED", "TMDB_PROXY_URL")


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
        self.refresh_patch.start()

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


if __name__ == "__main__":
    unittest.main()
