from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db


class _FakeProvider:
    def __init__(self, items, path_exists_result=True):
        self.items = items
        self.path_exists_result = path_exists_result
        self.calls = []

    def list_items(self, path):
        self.calls.append(("list_items", path))
        return list(self.items)

    def path_exists(self, path):
        self.calls.append(("path_exists", path))
        return self.path_exists_result


class StoragePreviewOptimizationTests(unittest.TestCase):
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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_preview_skips_path_exists_when_directory_listing_is_non_empty(self):
        provider = _FakeProvider([
            {"path": "电影", "name": "电影", "isdir": True, "size": 0},
        ])

        with patch("backend.app.api.storage_routes.provider_factory.create", return_value=provider), \
             patch("backend.app.api.storage_routes.get_source_capabilities", return_value=("alist", {"preview": True})):
            response = self.client.post(
                "/api/v1/storage/preview",
                json={
                    "type": "alist",
                    "config": {"host": "alist.local", "port": 5244, "root": "/"},
                    "target_path": "/",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual([("list_items", "")], provider.calls)

    def test_preview_checks_path_exists_when_listing_is_empty(self):
        provider = _FakeProvider([], path_exists_result=False)

        with patch("backend.app.api.storage_routes.provider_factory.create", return_value=provider):
            response = self.client.post(
                "/api/v1/storage/preview",
                json={
                    "type": "alist",
                    "config": {"host": "alist.local", "port": 5244, "root": "/"},
                    "target_path": "/不存在",
                },
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual([("list_items", "不存在"), ("path_exists", "不存在")], provider.calls)


if __name__ == "__main__":
    unittest.main()
