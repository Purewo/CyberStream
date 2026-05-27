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


class FakeManagedAListClient:
    created_requests = []
    verified_requests = []
    deleted_storage_ids = []

    def __init__(self):
        pass

    @classmethod
    def reset(cls):
        cls.created_requests = []
        cls.verified_requests = []
        cls.deleted_storage_ids = []

    def create_guangyapan_storage(self, phone_number, root_path="", captcha_token=""):
        self.created_requests.append({
            "phone_number": phone_number,
            "root_path": root_path,
            "captcha_token": captcha_token,
        })
        return {
            "storage_id": 77,
            "mount_path": "/cyberstream/guangyapan/fake",
            "phone_number_masked": "*******1234",
            "cloud_root_path": root_path or "/",
        }

    def verify_guangyapan_storage(self, storage_id, verify_code):
        self.verified_requests.append({
            "storage_id": storage_id,
            "verify_code": verify_code,
        })
        return {
            "storage_id": storage_id,
            "mount_path": "/cyberstream/guangyapan/fake",
        }

    def delete_storage(self, storage_id):
        self.deleted_storage_ids.append(int(storage_id))


class ManagedGuangYaPanRouteTests(unittest.TestCase):
    def setUp(self):
        FakeManagedAListClient.reset()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "MANAGED_ALIST_ENABLED": True,
            "MANAGED_ALIST_TOKEN": "alist-token",
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

    def test_start_sms_creates_pending_guangyapan_source(self):
        with patch("backend.app.api.storage_routes.ManagedAListClient", FakeManagedAListClient):
            response = self.client.post(
                "/api/v1/storage/managed/guangyapan/sms/start",
                json={
                    "name": "光鸭测试",
                    "phone_number": "+861380001234",
                    "root_path": "电影",
                    "captcha_token": "captcha",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["verification_sent"])
        self.assertEqual("sms_pending", payload["data"]["auth_state"])
        source_data = payload["data"]["source"]
        self.assertEqual("guangyapan", source_data["type"])
        self.assertEqual("*******1234", source_data["config"]["phone_number_masked"])
        self.assertNotIn("1380001234", str(source_data["config"]))
        self.assertNotIn("alist_storage_id", source_data["config"])
        self.assertNotIn("mount_path", source_data["config"])
        self.assertFalse(source_data["actions"]["can_preview"])
        self.assertFalse(source_data["actions"]["can_scan"])
        self.assertFalse(source_data["actions"]["can_stream"])

        source = StorageSource.query.first()
        self.assertEqual("guangyapan", source.type)
        self.assertEqual("sms_pending", source.config["auth_state"])
        self.assertEqual(77, source.config["alist_storage_id"])
        self.assertEqual("/电影", source.config["cloud_root_path"])
        self.assertEqual(
            [{"phone_number": "+861380001234", "root_path": "电影", "captcha_token": "captcha"}],
            FakeManagedAListClient.created_requests,
        )

    def test_verify_sms_marks_source_ready(self):
        source = StorageSource(
            name="光鸭测试",
            type="guangyapan",
            config={
                "alist_storage_id": 77,
                "mount_path": "/cyberstream/guangyapan/fake",
                "auth_state": "sms_pending",
                "phone_number_masked": "*******1234",
                "cloud_root_path": "/电影",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedAListClient", FakeManagedAListClient):
            response = self.client.post(
                "/api/v1/storage/managed/guangyapan/sms/verify",
                json={"source_id": source.id, "verify_code": "123456"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["verified"])
        self.assertEqual("ready", payload["data"]["source"]["config"]["auth_state"])
        self.assertNotIn("alist_storage_id", payload["data"]["source"]["config"])
        self.assertNotIn("mount_path", payload["data"]["source"]["config"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_preview"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_scan"])
        self.assertTrue(payload["data"]["source"]["actions"]["can_stream"])
        refreshed = db.session.get(StorageSource, source.id)
        self.assertEqual("ready", refreshed.config["auth_state"])
        self.assertEqual(
            [{"storage_id": 77, "verify_code": "123456"}],
            FakeManagedAListClient.verified_requests,
        )

    def test_delete_managed_source_removes_alist_storage_best_effort(self):
        source = StorageSource(
            name="光鸭测试",
            type="guangyapan",
            config={
                "alist_storage_id": 77,
                "mount_path": "/cyberstream/guangyapan/fake",
                "auth_state": "ready",
                "phone_number_masked": "*******1234",
                "cloud_root_path": "/",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedAListClient", FakeManagedAListClient):
            response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual([77], FakeManagedAListClient.deleted_storage_ids)
        self.assertIsNone(db.session.get(StorageSource, source.id))

    def test_health_hides_local_alist_runtime_details(self):
        source = StorageSource(
            name="光鸭测试",
            type="guangyapan",
            config={
                "alist_storage_id": 77,
                "mount_path": "/cyberstream/guangyapan/fake",
                "auth_state": "ready",
                "phone_number_masked": "*******1234",
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
                "message": "alist reachable",
                "base_url": "http://127.0.0.1:5244",
                "root": "/cyberstream/guangyapan/fake",
                "platform": "alist",
                "site_title": "AList",
                "version": "dev",
            },
        ):
            response = self.client.get(f"/api/v1/storage/sources/{source.id}/health")

        health = response.get_json()["data"]["health"]
        self.assertEqual(200, response.status_code)
        self.assertEqual("GuangYaPan reachable", health["message"])
        self.assertNotIn("base_url", health)
        self.assertNotIn("root", health)
        self.assertNotIn("platform", health)


if __name__ == "__main__":
    unittest.main()
