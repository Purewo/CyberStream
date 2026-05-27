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

    def create_quark_uc_tv_storage(self, kind, root_folder_id="", link_method="download"):
        self.created_requests.append({
            "kind": kind,
            "root_folder_id": root_folder_id,
            "link_method": link_method,
        })
        return {
            "storage_id": 99,
            "mount_path": f"/cyberstream/{kind}/fake",
            "auth_state": "qr_pending",
            "authenticated": False,
            "cloud_root_path": "/",
            "link_method": link_method,
            "qr_code_data_url": "data:image/jpeg;base64,cXVhcmstdWMtcXI=",
            "qr_content": None,
        }

    def poll_quark_uc_tv_storage(self, storage_id, kind):
        if self.poll_result is not None:
            result = dict(self.poll_result)
        else:
            result = {
                "storage_id": storage_id,
                "mount_path": f"/cyberstream/{kind}/fake",
                "auth_state": "qr_pending",
                "authenticated": False,
                "cloud_root_path": "/",
                "link_method": "download",
                "pending_reason": "waiting_for_scan",
            }
        result["storage_id"] = storage_id
        return result

    def delete_storage(self, storage_id):
        self.deleted_storage_ids.append(int(storage_id))


class ManagedQuarkUCTVRouteTests(unittest.TestCase):
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

    def test_start_qr_creates_pending_quarktv_source(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/quarktv/qr/start",
                json={
                    "name": "Quark test",
                    "link_method": "streaming",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["qr_started"])
        self.assertEqual("qr_pending", payload["data"]["auth_state"])
        self.assertEqual("data:image/jpeg;base64,cXVhcmstdWMtcXI=", payload["data"]["qr_code_data_url"])
        source_data = payload["data"]["source"]
        self.assertEqual("quarktv", source_data["type"])
        self.assertNotIn("openlist_storage_id", source_data["config"])
        self.assertNotIn("mount_path", source_data["config"])
        self.assertFalse(source_data["actions"]["can_preview"])
        self.assertFalse(source_data["actions"]["can_scan"])
        self.assertFalse(source_data["actions"]["can_stream"])

        source = StorageSource.query.first()
        self.assertEqual("quarktv", source.type)
        self.assertEqual("qr_pending", source.config["auth_state"])
        self.assertEqual(99, source.config["openlist_storage_id"])
        self.assertEqual(
            [{"kind": "quarktv", "root_folder_id": "", "link_method": "streaming"}],
            FakeManagedOpenListClient.created_requests,
        )

    def test_start_qr_creates_pending_uctv_source(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/uctv/qr/start",
                json={"name": "UC test"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("uctv", payload["data"]["source"]["type"])
        self.assertEqual(
            [{"kind": "uctv", "root_folder_id": "", "link_method": "download"}],
            FakeManagedOpenListClient.created_requests,
        )

    def test_poll_pending_keeps_source_locked(self):
        source = StorageSource(
            name="Quark test",
            type="quarktv",
            config={
                "openlist_storage_id": 99,
                "mount_path": "/cyberstream/quarktv/fake",
                "auth_state": "qr_pending",
                "cloud_root_path": "/",
                "link_method": "download",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/quarktv/qr/poll",
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
            name="Quark test",
            type="quarktv",
            config={
                "openlist_storage_id": 99,
                "mount_path": "/cyberstream/quarktv/fake",
                "auth_state": "qr_pending",
                "cloud_root_path": "/",
                "link_method": "download",
            },
        )
        db.session.add(source)
        db.session.commit()
        FakeManagedOpenListClient.poll_result = {
            "mount_path": "/cyberstream/quarktv/fake",
            "auth_state": "ready",
            "authenticated": True,
            "cloud_root_path": "/",
            "link_method": "download",
        }

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/quarktv/qr/poll",
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
            name="UC test",
            type="uctv",
            config={
                "openlist_storage_id": 99,
                "mount_path": "/cyberstream/uctv/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "link_method": "download",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual([99], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertIsNone(db.session.get(StorageSource, source.id))

    def test_health_hides_local_openlist_runtime_details(self):
        source = StorageSource(
            name="Quark test",
            type="quarktv",
            config={
                "openlist_storage_id": 99,
                "mount_path": "/cyberstream/quarktv/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "link_method": "download",
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
                "root": "/cyberstream/quarktv/fake",
                "platform": "openlist",
                "site_title": "OpenList",
                "version": "dev",
            },
        ):
            response = self.client.get(f"/api/v1/storage/sources/{source.id}/health")

        health = response.get_json()["data"]["health"]
        self.assertEqual(200, response.status_code)
        self.assertEqual("QuarkTV reachable", health["message"])
        self.assertNotIn("base_url", health)
        self.assertNotIn("root", health)
        self.assertNotIn("platform", health)


if __name__ == "__main__":
    unittest.main()
