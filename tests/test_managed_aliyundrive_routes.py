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
    seen_poll_requests = []

    def __init__(self):
        pass

    @classmethod
    def reset(cls):
        cls.created_requests = []
        cls.deleted_storage_ids = []
        cls.poll_result = None
        cls.seen_poll_requests = []

    def start_aliyundrive_qr(self, root_folder_id="", drive_type="resource", alipan_type="default"):
        self.created_requests.append({
            "root_folder_id": root_folder_id,
            "drive_type": drive_type,
            "alipan_type": alipan_type,
        })
        return {
            "auth_state": "qr_pending",
            "authenticated": False,
            "pending_reason": "waiting_for_scan",
            "qr_status": "WaitLogin",
            "qr_sid": "ali-sid",
            "qr_code_url": "https://openapi.alipan.com/oauth/qrcode/ali-sid",
            "qr_code_data_url": "https://openapi.alipan.com/oauth/qrcode/ali-sid",
            "qr_content": "https://openapi.alipan.com/oauth/qrcode/ali-sid",
            "auth_provider": "openlist",
            "cloud_root_path": "/",
            "root_folder_id": root_folder_id or "root",
            "drive_type": drive_type,
            "alipan_type": alipan_type,
        }

    def poll_aliyundrive_storage(
        self,
        qr_sid,
        root_folder_id="root",
        drive_type="resource",
        alipan_type="default",
        auth_provider=None,
    ):
        self.seen_poll_requests.append({
            "qr_sid": qr_sid,
            "root_folder_id": root_folder_id,
            "drive_type": drive_type,
            "alipan_type": alipan_type,
            "auth_provider": auth_provider,
        })
        if self.poll_result is not None:
            return dict(self.poll_result)
        return {
            "auth_state": "qr_pending",
            "authenticated": False,
            "pending_reason": "waiting_for_scan",
            "qr_status": "WaitLogin",
            "cloud_root_path": "/",
            "root_folder_id": root_folder_id,
            "drive_type": drive_type,
            "alipan_type": alipan_type,
            "auth_provider": auth_provider,
        }

    def delete_storage(self, storage_id):
        self.deleted_storage_ids.append(int(storage_id))


class ManagedAliyundriveRouteTests(unittest.TestCase):
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

    def test_start_qr_creates_pending_aliyundrive_source_without_openlist_storage(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/aliyundrive/qr/start",
                json={"name": "Ali test"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["qr_started"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertEqual("https://openapi.alipan.com/oauth/qrcode/ali-sid", payload["data"]["qr_code_url"])
        source_data = payload["data"]["source"]
        self.assertEqual("aliyundrive", source_data["type"])
        self.assertNotIn("openlist_storage_id", source_data["config"])
        self.assertNotIn("mount_path", source_data["config"])
        self.assertNotIn("qr_sid", source_data["config"])
        self.assertNotIn("auth_provider", source_data["config"])
        self.assertFalse(source_data["actions"]["can_preview"])
        self.assertFalse(source_data["actions"]["can_scan"])
        self.assertFalse(source_data["actions"]["can_stream"])

        source = StorageSource.query.first()
        self.assertEqual("aliyundrive", source.type)
        self.assertEqual("qr_pending", source.config["auth_state"])
        self.assertEqual("ali-sid", source.config["qr_sid"])
        self.assertNotIn("openlist_storage_id", source.config)
        self.assertEqual(
            [{"root_folder_id": "", "drive_type": "resource", "alipan_type": "default"}],
            FakeManagedOpenListClient.created_requests,
        )

    def test_poll_pending_keeps_source_locked_and_qr_session(self):
        source = StorageSource(
            name="Ali test",
            type="aliyundrive",
            config={
                "auth_state": "qr_pending",
                "cloud_root_path": "/",
                "root_folder_id": "root",
                "drive_type": "resource",
                "alipan_type": "default",
                "qr_sid": "ali-sid",
                "auth_provider": "openlist",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/aliyundrive/qr/poll",
                json={"source_id": source.id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertFalse(payload["data"]["authenticated"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertEqual("waiting_for_scan", payload["data"]["pending_reason"])
        self.assertFalse(payload["data"]["source"]["actions"]["can_preview"])
        stored = db.session.get(StorageSource, source.id)
        self.assertEqual("qr_pending", stored.config["auth_state"])
        self.assertEqual("ali-sid", stored.config["qr_sid"])
        self.assertEqual("openlist", stored.config["auth_provider"])
        self.assertEqual(
            [{
                "qr_sid": "ali-sid",
                "root_folder_id": "root",
                "drive_type": "resource",
                "alipan_type": "default",
                "auth_provider": "openlist",
            }],
            FakeManagedOpenListClient.seen_poll_requests,
        )

    def test_poll_ready_marks_source_ready_and_removes_qr_session(self):
        source = StorageSource(
            name="Ali test",
            type="aliyundrive",
            config={
                "auth_state": "qr_pending",
                "cloud_root_path": "/",
                "root_folder_id": "root",
                "drive_type": "resource",
                "alipan_type": "default",
                "qr_sid": "ali-sid",
                "auth_provider": "openlist",
            },
        )
        db.session.add(source)
        db.session.commit()
        FakeManagedOpenListClient.poll_result = {
            "storage_id": 188,
            "mount_path": "/cyberstream/aliyundrive/fake",
            "auth_state": "ready",
            "authenticated": True,
            "cloud_root_path": "/",
            "root_folder_id": "root",
            "drive_type": "resource",
            "alipan_type": "default",
            "qr_status": "LoginSuccess",
        }

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/aliyundrive/qr/poll",
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

        stored = db.session.get(StorageSource, source.id)
        self.assertEqual(188, stored.config["openlist_storage_id"])
        self.assertEqual("ready", stored.config["auth_state"])
        self.assertNotIn("qr_sid", stored.config)
        self.assertNotIn("auth_provider", stored.config)

    def test_delete_ready_managed_source_removes_openlist_storage_best_effort(self):
        source = StorageSource(
            name="Ali test",
            type="aliyundrive",
            config={
                "openlist_storage_id": 188,
                "mount_path": "/cyberstream/aliyundrive/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "root_folder_id": "root",
                "drive_type": "resource",
                "alipan_type": "default",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual([188], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertIsNone(db.session.get(StorageSource, source.id))


if __name__ == "__main__":
    unittest.main()
