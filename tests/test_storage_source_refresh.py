from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import StorageSource
from backend.app.providers.base import StorageProviderError


class _FakeRefreshProvider:
    def __init__(self):
        self.calls = []

    def refresh_directory(self, path):
        self.calls.append(("refresh_directory", path))
        return [
            {"path": f"{path}/S01E01.mkv", "name": "S01E01.mkv", "isdir": False, "size": 100},
            {"path": f"{path}/Season 2", "name": "Season 2", "isdir": True, "size": 0},
        ]


class _NoRefreshProvider:
    def refresh_directory(self, path):
        raise StorageProviderError("Storage source does not support directory refresh", code=40042)


class StorageSourceRefreshTests(unittest.TestCase):
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

        self.source = StorageSource(
            name="Test OpenList",
            type="openlist",
            config={
                "host": "openlist.local",
                "port": 5244,
                "root": "/",
            },
        )
        db.session.add(self.source)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_refresh_source_directory_returns_fresh_browse_payload(self):
        provider = _FakeRefreshProvider()

        with patch("backend.app.api.storage_routes.provider_factory.get_provider", return_value=provider):
            response = self.client.post(
                f"/api/v1/storage/sources/{self.source.id}/refresh",
                json={"path": "/电影/剑来2", "dirs_only": False},
            )

        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertEqual([("refresh_directory", "电影/剑来2")], provider.calls)
        self.assertTrue(payload["data"]["refreshed"])
        self.assertEqual("电影/剑来2", payload["data"]["refresh_path"])
        self.assertEqual("电影/剑来2", payload["data"]["current_path"])
        self.assertEqual(["Season 2", "S01E01.mkv"], [item["name"] for item in payload["data"]["items"]])
        self.assertTrue(payload["data"]["source"]["actions"]["can_refresh"])

    def test_refresh_source_directory_can_return_directories_only(self):
        provider = _FakeRefreshProvider()

        with patch("backend.app.api.storage_routes.provider_factory.get_provider", return_value=provider):
            response = self.client.post(
                f"/api/v1/storage/sources/{self.source.id}/refresh",
                json={"target_path": "电影/剑来2", "dirs_only": True},
            )

        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertEqual(["Season 2"], [item["name"] for item in payload["data"]["items"]])

    def test_refresh_source_directory_reports_unsupported_provider(self):
        with patch("backend.app.api.storage_routes.provider_factory.get_provider", return_value=_NoRefreshProvider()):
            response = self.client.post(
                f"/api/v1/storage/sources/{self.source.id}/refresh",
                json={"path": "/电影/剑来2"},
            )

        payload = response.get_json()

        self.assertEqual(400, response.status_code)
        self.assertEqual(40042, payload["code"])


if __name__ == "__main__":
    unittest.main()
