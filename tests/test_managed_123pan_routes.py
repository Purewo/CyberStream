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


class FakeManagedOpenListClient:
    created_requests = []
    deleted_storage_ids = []

    def __init__(self):
        pass

    @classmethod
    def reset(cls):
        cls.created_requests = []
        cls.deleted_storage_ids = []

    def create_123pan_storage(self, username, password, root_folder_id="", platform="web"):
        self.created_requests.append({
            "username": username,
            "password": password,
            "root_folder_id": root_folder_id,
            "platform": platform,
        })
        storage_id = 123 + len(self.created_requests) - 1
        return {
            "storage_id": storage_id,
            "mount_path": "/cyberstream/123pan/fake",
            "auth_state": "ready",
            "authenticated": True,
            "cloud_root_path": "/",
            "root_folder_id": root_folder_id or "0",
            "platform": platform or "web",
            "account_name_masked": "13*****0000",
        }

    def delete_storage(self, storage_id):
        self.deleted_storage_ids.append(int(storage_id))


class Managed123PanRouteTests(unittest.TestCase):
    def setUp(self):
        FakeManagedOpenListClient.reset()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "MANAGED_OPENLIST_ENABLED": True,
            "MANAGED_OPENLIST_TOKEN": "openlist-token",
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

    def test_login_creates_ready_123pan_source(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/123pan/login",
                json={
                    "name": "123 test",
                    "username": "13800000000",
                    "password": "secret",
                    "root_folder_id": "0",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["authenticated"])
        self.assertEqual("ready", payload["data"]["auth_state"])
        source_data = payload["data"]["source"]
        self.assertEqual("123pan", source_data["type"])
        self.assertEqual("123Pan", source_data["display_name"])
        self.assertNotIn("openlist_storage_id", source_data["config"])
        self.assertNotIn("mount_path", source_data["config"])
        self.assertNotIn("password", source_data["config"])
        self.assertEqual("13*****0000", source_data["config"]["account_name_masked"])
        self.assertTrue(source_data["actions"]["can_preview"])
        self.assertTrue(source_data["actions"]["can_scan"])
        self.assertTrue(source_data["actions"]["can_stream"])
        self.assertTrue(source_data["actions"]["can_refresh"])

        source = StorageSource.query.first()
        self.assertEqual("123pan", source.type)
        self.assertEqual(123, source.config["openlist_storage_id"])
        self.assertEqual("/cyberstream/123pan/fake", source.config["mount_path"])
        self.assertNotIn("password", source.config)
        self.assertEqual(
            [{
                "username": "13800000000",
                "password": "secret",
                "root_folder_id": "0",
                "platform": "web",
            }],
            FakeManagedOpenListClient.created_requests,
        )

    def test_login_requires_username_and_password(self):
        response = self.client.post(
            "/api/v1/storage/managed/123pan/login",
            json={"username": "13800000000"},
        )

        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertEqual(40001, payload["code"])
        self.assertIn("password", payload["msg"])
        self.assertEqual([], FakeManagedOpenListClient.created_requests)

    def test_restart_login_replaces_openlist_storage_without_new_source(self):
        source = StorageSource(
            name="123 test",
            type="123pan",
            config={
                "openlist_storage_id": 122,
                "mount_path": "/cyberstream/123pan/old",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "root_folder_id": "0",
                "account_name_masked": "13*****0000",
                "platform": "web",
            },
        )
        db.session.add(source)
        db.session.commit()
        source_id = source.id

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/123pan/login/restart",
                json={
                    "source_id": source_id,
                    "username": "13800000000",
                    "password": "secret",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["login_restarted"])
        self.assertTrue(payload["data"]["authenticated"])
        self.assertEqual("ready", payload["data"]["auth_state"])
        self.assertEqual(source_id, payload["data"]["source"]["id"])
        self.assertEqual("13*****0000", payload["data"]["source"]["config"]["account_name_masked"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_scan"])
        self.assertEqual([122], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertEqual(
            [{
                "username": "13800000000",
                "password": "secret",
                "root_folder_id": "0",
                "platform": "web",
            }],
            FakeManagedOpenListClient.created_requests,
        )
        saved = db.session.get(StorageSource, source_id)
        self.assertEqual(123, saved.config["openlist_storage_id"])
        self.assertEqual("ready", saved.config["auth_state"])
        self.assertEqual(1, StorageSource.query.count())

    def test_delete_managed_source_removes_openlist_storage_best_effort(self):
        source = StorageSource(
            name="123 test",
            type="123pan",
            config={
                "openlist_storage_id": 123,
                "mount_path": "/cyberstream/123pan/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "root_folder_id": "0",
                "account_name_masked": "13*****0000",
                "platform": "web",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual([123], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertIsNone(db.session.get(StorageSource, source.id))

    def test_health_hides_local_openlist_runtime_details(self):
        source = StorageSource(
            name="123 test",
            type="123pan",
            config={
                "openlist_storage_id": 123,
                "mount_path": "/cyberstream/123pan/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "root_folder_id": "0",
                "account_name_masked": "13*****0000",
                "platform": "web",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch(
            "backend.app.providers.managed_alist.AListProvider.check_connection",
            return_value={
                "status": "online",
                "reason": "ok",
                "message": "openlist reachable",
                "base_url": "http://127.0.0.1:5245",
                "root": "/cyberstream/123pan/fake",
                "platform": "openlist",
                "site_title": "OpenList",
                "version": "dev",
            },
        ):
            response = self.client.get(f"/api/v1/storage/sources/{source.id}/health")

        health = response.get_json()["data"]["health"]
        self.assertEqual(200, response.status_code)
        self.assertEqual("123Pan reachable", health["message"])
        self.assertNotIn("base_url", health)
        self.assertNotIn("root", health)
        self.assertNotIn("platform", health)


if __name__ == "__main__":
    unittest.main()
