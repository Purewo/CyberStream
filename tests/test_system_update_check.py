from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db


class SystemUpdateCheckTests(unittest.TestCase):
    def _create_client(self, **overrides):
        config = {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "UPDATE_CDN_URL_PREFIXES": "https://qwk.ccwu.cc/a/cyberstream-releases",
        }
        config.update(overrides)
        app = create_app(config)
        ctx = app.app_context()
        ctx.push()
        db.drop_all()
        db.create_all()
        self.addCleanup(lambda: self._cleanup(ctx))
        return app.test_client()

    def _cleanup(self, ctx):
        db.session.remove()
        db.drop_all()
        ctx.pop()

    def _write_manifest(self, payload):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "update-manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _manifest(self):
        return {
            "product": "CyberStream",
            "channel": "stable",
            "latest": {
                "version": "1.21.1",
                "release": "1.21.1-pc.2",
                "tag": "v1.21.1-pc.2",
                "title": "CyberStream PC 1.21.1-pc.2",
                "released_at": "2026-05-24T16:30:38Z",
                "mandatory": False,
            },
            "downloads": [
                {
                    "variant": "lite",
                    "platform": "windows",
                    "arch": "x64",
                    "name": "CyberStream_1.21.1-pc.2_lite_x64.msi",
                    "url": "https://qwk.ccwu.cc/a/cyberstream-releases/pc/v1.21.1-pc.2/lite.msi",
                    "size": 97349632,
                    "sha256": "sha256:17bdb10f89740dc696d69807d8dcb08ddf6c2b4b8890f6e1c96bada978fc0b10",
                },
                {
                    "variant": "full",
                    "platform": "windows",
                    "arch": "x64",
                    "name": "CyberStream_1.21.1-pc.2_full_x64.msi",
                    "url": "https://qwk.ccwu.cc/a/cyberstream-releases/pc/v1.21.1-pc.2/full.msi",
                    "size": 128782336,
                    "sha256": "901393efc16dff4ad20c5e2d8b6020623e3fb4c2f2b6bb60ffd68695b02ac522",
                },
                {
                    "variant": "github",
                    "platform": "windows",
                    "arch": "x64",
                    "name": "CyberStream_1.21.1-pc.2_full_x64.msi",
                    "url": "https://github.com/Purewo/CyberStream/releases/download/v1.21.1-pc.2/full.msi",
                },
            ],
        }

    def test_update_check_returns_manifest_release_and_cdn_downloads_only(self):
        manifest_path = self._write_manifest(self._manifest())
        client = self._create_client(UPDATE_MANIFEST_PATH=str(manifest_path))

        response = client.get("/api/v1/system/update-check?current_version=1.21.0")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("manifest", data["source"])
        self.assertEqual("1.21.1", data["latest"]["version"])
        self.assertTrue(data["update_available"])
        self.assertEqual(2, len(data["downloads"]))
        self.assertTrue(all(item["url"].startswith("https://qwk.ccwu.cc/") for item in data["downloads"]))
        self.assertEqual("full", data["selected_download"]["variant"])
        self.assertIn("non_cdn_download_url_ignored", data["warnings"])
        self.assertEqual(
            "17bdb10f89740dc696d69807d8dcb08ddf6c2b4b8890f6e1c96bada978fc0b10",
            data["downloads"][0]["sha256"],
        )

    def test_update_check_can_select_variant_and_compare_release_build(self):
        manifest_path = self._write_manifest(self._manifest())
        client = self._create_client(UPDATE_MANIFEST_PATH=str(manifest_path))

        lite = client.get(
            "/api/v1/system/update-check?current_version=1.21.1&current_release=1.21.1-pc.1&variant=lite"
        ).get_json()["data"]
        current = client.get("/api/v1/system/update-check?current_version=1.21.1").get_json()["data"]

        self.assertTrue(lite["update_available"])
        self.assertEqual(1, len(lite["downloads"]))
        self.assertEqual("lite", lite["selected_download"]["variant"])
        self.assertFalse(current["update_available"])

    def test_update_check_does_not_return_stable_downloads_for_unpublished_channel(self):
        manifest_path = self._write_manifest(self._manifest())
        client = self._create_client(UPDATE_MANIFEST_PATH=str(manifest_path))

        data = client.get("/api/v1/system/update-check?channel=beta").get_json()["data"]

        self.assertEqual("beta", data["channel"])
        self.assertFalse(data["update_available"])
        self.assertEqual([], data["downloads"])
        self.assertIsNone(data["selected_download"])
        self.assertIn("update_channel_not_published", data["warnings"])

    def test_update_check_falls_back_to_source_version_without_downloads(self):
        client = self._create_client(UPDATE_MANIFEST_PATH="/tmp/cyberstream-missing-update-manifest.json")

        data = client.get("/api/v1/system/update-check").get_json()["data"]

        self.assertEqual("source_tree", data["source"])
        self.assertEqual("1.21.1", data["latest"]["version"])
        self.assertEqual([], data["downloads"])
        self.assertIn("update_manifest_missing", data["warnings"])
        self.assertIn("update_downloads_missing", data["warnings"])

    def test_update_check_is_public_even_when_auth_is_enabled(self):
        manifest_path = self._write_manifest(self._manifest())
        client = self._create_client(
            UPDATE_MANIFEST_PATH=str(manifest_path),
            API_TOKEN="secret-token",
            AUTH_ENABLED=True,
        )

        response = client.get("/api/v1/system/update-check")

        self.assertEqual(200, response.status_code)

    def test_update_check_is_public_before_user_login(self):
        manifest_path = self._write_manifest(self._manifest())
        client = self._create_client(
            UPDATE_MANIFEST_PATH=str(manifest_path),
            USER_MANAGEMENT_ENABLED=True,
            SESSION_SECRET="test-session-secret",
            SECRET_KEY="test-session-secret",
        )

        response = client.get("/api/v1/system/update-check")

        self.assertEqual(200, response.status_code)


if __name__ == "__main__":
    unittest.main()
