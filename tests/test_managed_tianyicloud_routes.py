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
    poll_result = None

    def __init__(self):
        pass

    @classmethod
    def reset(cls):
        cls.created_requests = []
        cls.deleted_storage_ids = []
        cls.poll_result = None

    def create_tianyicloud_storage(self, root_folder_id="", cloud_type="personal"):
        self.created_requests.append({
            "root_folder_id": root_folder_id,
            "cloud_type": cloud_type,
        })
        storage_id = 88 + len(self.created_requests) - 1
        return {
            "storage_id": storage_id,
            "mount_path": "/cyberstream/tianyicloud/fake",
            "auth_state": "qr_pending",
            "authenticated": False,
            "cloud_type": cloud_type,
            "cloud_root_path": "/",
            "root_folder_id": root_folder_id or "-11",
            "qr_code_data_url": "data:image/jpeg;base64,ZmFrZS1xcg==",
            "qr_content": "qr-uuid",
        }

    def poll_tianyicloud_storage(self, storage_id):
        if self.poll_result is not None:
            result = dict(self.poll_result)
        else:
            result = {
                "storage_id": storage_id,
                "mount_path": "/cyberstream/tianyicloud/fake",
                "auth_state": "qr_pending",
                "authenticated": False,
                "cloud_type": "personal",
                "cloud_root_path": "/",
                "root_folder_id": "-11",
                "pending_reason": "waiting_for_scan",
            }
        result["storage_id"] = storage_id
        return result

    def delete_storage(self, storage_id):
        self.deleted_storage_ids.append(int(storage_id))


class ManagedTianYiCloudRouteTests(unittest.TestCase):
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

    def test_start_qr_creates_pending_tianyicloud_source(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/tianyicloud/qr/start",
                json={
                    "name": "天翼云盘测试",
                    "cloud_type": "personal",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["qr_started"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertEqual("data:image/jpeg;base64,ZmFrZS1xcg==", payload["data"]["qr_code_data_url"])
        source_data = payload["data"]["source"]
        self.assertEqual("tianyicloud", source_data["type"])
        self.assertNotIn("openlist_storage_id", source_data["config"])
        self.assertNotIn("mount_path", source_data["config"])
        self.assertFalse(source_data["actions"]["can_preview"])
        self.assertFalse(source_data["actions"]["can_scan"])
        self.assertFalse(source_data["actions"]["can_stream"])

        source = StorageSource.query.first()
        self.assertEqual("tianyicloud", source.type)
        self.assertEqual("qr_pending", source.config["auth_state"])
        self.assertEqual(88, source.config["openlist_storage_id"])
        self.assertEqual(
            [{"root_folder_id": "", "cloud_type": "personal"}],
            FakeManagedOpenListClient.created_requests,
        )

    def test_restart_qr_replaces_openlist_storage_without_new_source(self):
        source = StorageSource(
            name="天翼云盘测试",
            type="tianyicloud",
            config={
                "openlist_storage_id": 87,
                "mount_path": "/cyberstream/tianyicloud/old",
                "auth_state": "ready",
                "cloud_type": "personal",
                "cloud_root_path": "/",
                "root_folder_id": "-11",
            },
        )
        db.session.add(source)
        db.session.commit()
        source_id = source.id

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/tianyicloud/qr/restart",
                json={"source_id": source_id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["qr_restarted"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertEqual(source_id, payload["data"]["source"]["id"])
        self.assertEqual("qr_pending", payload["data"]["source"]["config"]["auth_state"])
        self.assertEqual("-11", payload["data"]["source"]["config"]["root_folder_id"])
        self.assertFalse(payload["data"]["source"]["actions"]["can_scan"])
        self.assertEqual([87], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertEqual(
            [{"root_folder_id": "-11", "cloud_type": "personal"}],
            FakeManagedOpenListClient.created_requests,
        )
        saved = db.session.get(StorageSource, source_id)
        self.assertEqual(88, saved.config["openlist_storage_id"])
        self.assertEqual("qr_pending", saved.config["auth_state"])
        self.assertEqual(1, StorageSource.query.count())

    def test_poll_pending_keeps_source_locked(self):
        source = StorageSource(
            name="天翼云盘测试",
            type="tianyicloud",
            config={
                "openlist_storage_id": 88,
                "mount_path": "/cyberstream/tianyicloud/fake",
                "auth_state": "qr_pending",
                "cloud_type": "personal",
                "cloud_root_path": "/",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/tianyicloud/qr/poll",
                json={"source_id": source.id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertFalse(payload["data"]["authenticated"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertFalse(payload["data"]["source"]["actions"]["can_preview"])
        self.assertEqual("qr_pending", db.session.get(StorageSource, source.id).config["auth_state"])

    def test_poll_ready_marks_source_ready(self):
        source = StorageSource(
            name="天翼云盘测试",
            type="tianyicloud",
            config={
                "openlist_storage_id": 88,
                "mount_path": "/cyberstream/tianyicloud/fake",
                "auth_state": "qr_pending",
                "cloud_type": "personal",
                "cloud_root_path": "/",
            },
        )
        db.session.add(source)
        db.session.commit()
        FakeManagedOpenListClient.poll_result = {
            "mount_path": "/cyberstream/tianyicloud/fake",
            "auth_state": "ready",
            "authenticated": True,
            "cloud_type": "personal",
            "cloud_root_path": "/",
        }

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/tianyicloud/qr/poll",
                json={"source_id": source.id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["authenticated"])
        self.assertEqual("ready", payload["data"]["source"]["config"]["auth_state"])
        self.assertNotIn("openlist_storage_id", payload["data"]["source"]["config"])
        self.assertNotIn("mount_path", payload["data"]["source"]["config"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_preview"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_scan"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_stream"])
        self.assertEqual("ready", db.session.get(StorageSource, source.id).config["auth_state"])

    def test_delete_managed_source_removes_openlist_storage_best_effort(self):
        source = StorageSource(
            name="天翼云盘测试",
            type="tianyicloud",
            config={
                "openlist_storage_id": 88,
                "mount_path": "/cyberstream/tianyicloud/fake",
                "auth_state": "ready",
                "cloud_type": "personal",
                "cloud_root_path": "/",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual([88], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertIsNone(db.session.get(StorageSource, source.id))

    def test_health_hides_local_openlist_runtime_details(self):
        source = StorageSource(
            name="天翼云盘测试",
            type="tianyicloud",
            config={
                "openlist_storage_id": 88,
                "mount_path": "/cyberstream/tianyicloud/fake",
                "auth_state": "ready",
                "cloud_type": "personal",
                "cloud_root_path": "/",
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
                "root": "/cyberstream/tianyicloud/fake",
                "platform": "openlist",
                "site_title": "OpenList",
                "version": "dev",
            },
        ):
            response = self.client.get(f"/api/v1/storage/sources/{source.id}/health")

        health = response.get_json()["data"]["health"]
        self.assertEqual(200, response.status_code)
        self.assertEqual("TianYiCloud reachable", health["message"])
        self.assertNotIn("base_url", health)
        self.assertNotIn("root", health)
        self.assertNotIn("platform", health)


if __name__ == "__main__":
    unittest.main()
