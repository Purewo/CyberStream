from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db


class StoragePreviewBrowseTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "电影").mkdir()
        (self.root / "剧集").mkdir()
        (self.root / "剧集" / "灵笼").mkdir()
        (self.root / "README.txt").write_text("ignore", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def post_preview(self, target_path="/", dirs_only=True):
        return self.client.post(
            "/api/v1/storage/preview",
            json={
                "type": "local",
                "config": {"root_path": str(self.root)},
                "target_path": target_path,
                "dirs_only": dirs_only,
            },
        )

    def test_preview_returns_browse_payload_for_folder_picker(self):
        response = self.post_preview()
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        data = payload["data"]
        self.assertEqual("local", data["storage_type"])
        self.assertEqual("/", data["current_path"])
        self.assertIsNone(data["parent_path"])
        self.assertEqual(["剧集", "电影"], [item["name"] for item in data["items"]])
        self.assertTrue(all(item["type"] == "dir" for item in data["items"]))

    def test_preview_can_browse_child_path(self):
        response = self.post_preview(target_path="/剧集")
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        data = payload["data"]
        self.assertEqual("剧集", data["current_path"])
        self.assertEqual("/", data["parent_path"])
        self.assertEqual(["灵笼"], [item["name"] for item in data["items"]])

    def test_preview_can_include_files_when_requested(self):
        response = self.post_preview(dirs_only=False)
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertIn("README.txt", [item["name"] for item in payload["data"]["items"]])

    def test_preview_invalid_path_returns_400(self):
        response = self.post_preview(target_path="/不存在")
        payload = response.get_json()

        self.assertEqual(400, response.status_code)
        self.assertEqual(40015, payload["code"])


if __name__ == "__main__":
    unittest.main()
