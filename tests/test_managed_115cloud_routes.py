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
    DEFAULT_115_QRCODE_SOURCE = "wechatmini"
    created_requests = []
    deleted_storage_ids = []
    poll_result = None
    seen_qr_sessions = []

    def __init__(self):
        pass

    @classmethod
    def reset(cls):
        cls.created_requests = []
        cls.deleted_storage_ids = []
        cls.poll_result = None
        cls.seen_qr_sessions = []

    def create_115cloud_storage(self, root_folder_id="", qrcode_source="wechatmini"):
        self.created_requests.append({
            "root_folder_id": root_folder_id,
            "qrcode_source": qrcode_source,
        })
        return {
            "storage_id": 115,
            "mount_path": "/cyberstream/115cloud/fake",
            "auth_state": "qr_pending",
            "authenticated": False,
            "cloud_root_path": "/",
            "qrcode_source": qrcode_source,
            "qr_uid": "115-uid",
            "qr_sign": "115-sign",
            "qr_time": 1779910679,
            "qr_code_data_url": "data:image/png;base64,ZmFrZS1wbmc=",
            "qr_content": "https://115.com/scan/dg-115-uid",
        }

    def poll_115cloud_storage(self, storage_id, qr_session=None):
        self.seen_qr_sessions.append(dict(qr_session or {}))
        if self.poll_result is not None:
            result = dict(self.poll_result)
        else:
            result = {
                "storage_id": storage_id,
                "mount_path": "/cyberstream/115cloud/fake",
                "auth_state": "qr_pending",
                "authenticated": False,
                "cloud_root_path": "/",
                "qrcode_source": "wechatmini",
                "pending_reason": "waiting_for_scan",
                "qr_status": 0,
            }
        result["storage_id"] = storage_id
        return result

    def delete_storage(self, storage_id):
        self.deleted_storage_ids.append(int(storage_id))


class Managed115CloudRouteTests(unittest.TestCase):
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

    def test_start_qr_creates_pending_115cloud_source(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/115cloud/qr/start",
                json={
                    "name": "115 test",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["qr_started"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertEqual("data:image/png;base64,ZmFrZS1wbmc=", payload["data"]["qr_code_data_url"])
        self.assertEqual("https://115.com/scan/dg-115-uid", payload["data"]["qr_content"])
        source_data = payload["data"]["source"]
        self.assertEqual("115cloud", source_data["type"])
        self.assertNotIn("openlist_storage_id", source_data["config"])
        self.assertNotIn("mount_path", source_data["config"])
        self.assertNotIn("qr_uid", source_data["config"])
        self.assertNotIn("qr_sign", source_data["config"])
        self.assertNotIn("qr_time", source_data["config"])
        self.assertFalse(source_data["actions"]["can_preview"])
        self.assertFalse(source_data["actions"]["can_scan"])
        self.assertFalse(source_data["actions"]["can_stream"])

        source = StorageSource.query.first()
        self.assertEqual("115cloud", source.type)
        self.assertEqual("qr_pending", source.config["auth_state"])
        self.assertEqual(115, source.config["openlist_storage_id"])
        self.assertEqual("115-uid", source.config["qr_uid"])
        self.assertEqual(
            [{"root_folder_id": "", "qrcode_source": "wechatmini"}],
            FakeManagedOpenListClient.created_requests,
        )

    def test_start_qr_allows_explicit_qrcode_source_override(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/115cloud/qr/start",
                json={
                    "name": "115 test",
                    "qrcode_source": "web",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [{"root_folder_id": "", "qrcode_source": "web"}],
            FakeManagedOpenListClient.created_requests,
        )

    def test_poll_pending_keeps_source_locked_and_updates_state(self):
        source = StorageSource(
            name="115 test",
            type="115cloud",
            config={
                "openlist_storage_id": 115,
                "mount_path": "/cyberstream/115cloud/fake",
                "auth_state": "qr_pending",
                "cloud_root_path": "/",
                "qrcode_source": "wechatmini",
                "qr_uid": "115-uid",
                "qr_sign": "115-sign",
                "qr_time": 1779910679,
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/115cloud/qr/poll",
                json={"source_id": source.id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertFalse(payload["data"]["authenticated"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertEqual("waiting_for_scan", payload["data"]["pending_reason"])
        self.assertEqual(0, payload["data"]["qr_status"])
        self.assertFalse(payload["data"]["source"]["actions"]["can_preview"])
        self.assertEqual(
            [{"qr_uid": "115-uid", "qr_sign": "115-sign", "qr_time": 1779910679}],
            FakeManagedOpenListClient.seen_qr_sessions,
        )
        self.assertEqual("qr_pending", db.session.get(StorageSource, source.id).config["auth_state"])

    def test_poll_expired_marks_source_expired_and_locked(self):
        source = StorageSource(
            name="115 test",
            type="115cloud",
            config={
                "openlist_storage_id": 115,
                "mount_path": "/cyberstream/115cloud/fake",
                "auth_state": "qr_pending",
                "cloud_root_path": "/",
                "qrcode_source": "wechatmini",
                "qr_uid": "115-uid",
                "qr_sign": "115-sign",
                "qr_time": 1779910679,
            },
        )
        db.session.add(source)
        db.session.commit()
        FakeManagedOpenListClient.poll_result = {
            "mount_path": "/cyberstream/115cloud/fake",
            "auth_state": "qr_expired",
            "authenticated": False,
            "cloud_root_path": "/",
            "qrcode_source": "wechatmini",
            "pending_reason": "qr_expired",
            "qr_status": -1,
        }

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/115cloud/qr/poll",
                json={"source_id": source.id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertFalse(payload["data"]["authenticated"])
        self.assertEqual("qr_expired", payload["data"]["auth_state"])
        self.assertFalse(payload["data"]["source"]["actions"]["can_preview"])
        self.assertEqual("qr_expired", db.session.get(StorageSource, source.id).config["auth_state"])

    def test_poll_ready_marks_source_ready_and_removes_qr_session(self):
        source = StorageSource(
            name="115 test",
            type="115cloud",
            config={
                "openlist_storage_id": 115,
                "mount_path": "/cyberstream/115cloud/fake",
                "auth_state": "qr_pending",
                "cloud_root_path": "/",
                "qrcode_source": "wechatmini",
                "qr_uid": "115-uid",
                "qr_sign": "115-sign",
                "qr_time": 1779910679,
            },
        )
        db.session.add(source)
        db.session.commit()
        FakeManagedOpenListClient.poll_result = {
            "mount_path": "/cyberstream/115cloud/fake",
            "auth_state": "ready",
            "authenticated": True,
            "cloud_root_path": "/",
            "qrcode_source": "wechatmini",
        }

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/115cloud/qr/poll",
                json={"source_id": source.id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["authenticated"])
        self.assertEqual("ready", payload["data"]["source"]["config"]["auth_state"])
        self.assertNotIn("openlist_storage_id", payload["data"]["source"]["config"])
        self.assertNotIn("mount_path", payload["data"]["source"]["config"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_preview"])
        saved_config = db.session.get(StorageSource, source.id).config
        self.assertEqual("ready", saved_config["auth_state"])
        self.assertNotIn("qr_uid", saved_config)
        self.assertNotIn("qr_sign", saved_config)
        self.assertNotIn("qr_time", saved_config)

    def test_delete_managed_source_removes_openlist_storage_best_effort(self):
        source = StorageSource(
            name="115 test",
            type="115cloud",
            config={
                "openlist_storage_id": 115,
                "mount_path": "/cyberstream/115cloud/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "qrcode_source": "wechatmini",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual([115], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertIsNone(db.session.get(StorageSource, source.id))

    def test_health_hides_local_openlist_runtime_details(self):
        source = StorageSource(
            name="115 test",
            type="115cloud",
            config={
                "openlist_storage_id": 115,
                "mount_path": "/cyberstream/115cloud/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "qrcode_source": "wechatmini",
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
                "root": "/cyberstream/115cloud/fake",
                "platform": "openlist",
                "site_title": "OpenList",
                "version": "dev",
            },
        ):
            response = self.client.get(f"/api/v1/storage/sources/{source.id}/health")

        health = response.get_json()["data"]["health"]
        self.assertEqual(200, response.status_code)
        self.assertEqual("115 Cloud reachable", health["message"])
        self.assertNotIn("base_url", health)
        self.assertNotIn("root", health)
        self.assertNotIn("platform", health)


if __name__ == "__main__":
    unittest.main()
