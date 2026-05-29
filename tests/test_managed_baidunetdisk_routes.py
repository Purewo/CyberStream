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
    completed_requests = []
    deleted_storage_ids = []
    callback_mode = "redirect"

    def __init__(self):
        pass

    @classmethod
    def reset(cls):
        cls.created_requests = []
        cls.completed_requests = []
        cls.deleted_storage_ids = []
        cls.callback_mode = "redirect"

    def start_baidunetdisk_oauth(self, redirect_uri, root_path="/", download_api="official"):
        callback_mode = self.callback_mode
        self.created_requests.append({
            "redirect_uri": redirect_uri,
            "root_path": root_path,
            "download_api": download_api,
        })
        return {
            "authenticated": False,
            "auth_state": "oauth_pending",
            "pending_reason": "waiting_for_authorization",
            "authorization_url": "https://openapi.baidu.com/oauth/2.0/authorize?state=baidu-state",
            "oauth_state": "baidu-state",
            "oauth_callback_mode": callback_mode,
            "oauth_redirect_uri": "oob" if callback_mode == "oob" else redirect_uri,
            "callback_mode": callback_mode,
            "requires_authorization_code": callback_mode == "oob",
            "cloud_root_path": root_path or "/",
            "root_folder_path": root_path or "/",
            "download_api": download_api,
        }

    def complete_baidunetdisk_oauth(self, code, redirect_uri, root_path="/", download_api="official"):
        self.completed_requests.append({
            "code": code,
            "redirect_uri": redirect_uri,
            "root_path": root_path,
            "download_api": download_api,
        })
        return {
            "storage_id": 211,
            "mount_path": "/cyberstream/baidunetdisk/fake",
            "authenticated": True,
            "auth_state": "ready",
            "cloud_root_path": root_path or "/",
            "root_folder_path": root_path or "/",
            "download_api": download_api,
        }

    def delete_storage(self, storage_id):
        self.deleted_storage_ids.append(int(storage_id))


class ManagedBaiduNetdiskRouteTests(unittest.TestCase):
    def setUp(self):
        FakeManagedOpenListClient.reset()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BACKEND_PUBLIC_BASE_URL": "https://cyberstream.example",
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

    def test_start_oauth_creates_pending_baidunetdisk_source(self):
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/baidunetdisk/oauth/start",
                json={"name": "Baidu test"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["oauth_started"])
        self.assertEqual("oauth_pending", payload["data"]["auth_state"])
        self.assertIn("https://openapi.baidu.com/oauth/2.0/authorize", payload["data"]["authorization_url"])
        self.assertEqual("redirect", payload["data"]["callback_mode"])
        self.assertFalse(payload["data"]["requires_authorization_code"])
        self.assertIsNone(payload["data"]["authorization_code_submit_url"])
        self.assertEqual(
            "https://cyberstream.example/api/v1/storage/managed/baidunetdisk/oauth/callback",
            payload["data"]["callback_url"],
        )
        source_data = payload["data"]["source"]
        self.assertEqual("baidunetdisk", source_data["type"])
        self.assertNotIn("openlist_storage_id", source_data["config"])
        self.assertNotIn("mount_path", source_data["config"])
        self.assertNotIn("oauth_state", source_data["config"])
        self.assertFalse(source_data["actions"]["can_preview"])

        source = StorageSource.query.first()
        self.assertEqual("baidunetdisk", source.type)
        self.assertEqual("oauth_pending", source.config["auth_state"])
        self.assertEqual("baidu-state", source.config["oauth_state"])
        self.assertEqual("redirect", source.config["oauth_callback_mode"])
        self.assertEqual(
            "https://cyberstream.example/api/v1/storage/managed/baidunetdisk/oauth/callback",
            source.config["oauth_redirect_uri"],
        )
        self.assertEqual(
            [{
                "redirect_uri": "https://cyberstream.example/api/v1/storage/managed/baidunetdisk/oauth/callback",
                "root_path": "",
                "download_api": "official",
            }],
            FakeManagedOpenListClient.created_requests,
        )

    def test_restart_oauth_preserves_source_and_keeps_old_openlist_until_ready(self):
        source = StorageSource(
            name="Baidu test",
            type="baidunetdisk",
            config={
                "openlist_storage_id": 210,
                "mount_path": "/cyberstream/baidunetdisk/old",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "root_folder_path": "/",
                "download_api": "official",
            },
        )
        db.session.add(source)
        db.session.commit()
        source_id = source.id

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/baidunetdisk/oauth/restart",
                json={"source_id": source_id},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["oauth_restarted"])
        self.assertTrue(payload["data"]["oauth_started"])
        self.assertEqual("oauth_pending", payload["data"]["auth_state"])
        self.assertEqual(210, payload["data"]["replaced_openlist_storage_id"])
        self.assertFalse(payload["data"]["old_openlist_storage_deleted"])
        self.assertEqual(source_id, payload["data"]["source"]["id"])
        self.assertEqual("oauth_pending", payload["data"]["source"]["config"]["auth_state"])
        self.assertFalse(payload["data"]["source"]["actions"]["can_preview"])
        self.assertEqual([], FakeManagedOpenListClient.deleted_storage_ids)
        saved = db.session.get(StorageSource, source_id)
        self.assertEqual(210, saved.config["openlist_storage_id"])
        self.assertEqual("baidu-state", saved.config["oauth_state"])
        self.assertEqual("oauth_pending", saved.config["auth_state"])
        self.assertEqual(1, StorageSource.query.count())

    def test_start_oob_oauth_returns_authorization_code_contract(self):
        FakeManagedOpenListClient.callback_mode = "oob"
        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/baidunetdisk/oauth/start",
                json={"name": "Baidu test"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("oob", payload["data"]["callback_mode"])
        self.assertTrue(payload["data"]["requires_authorization_code"])
        self.assertIsNone(payload["data"]["callback_url"])
        self.assertEqual(
            "https://cyberstream.example/api/v1/storage/managed/baidunetdisk/oauth/complete",
            payload["data"]["authorization_code_submit_url"],
        )
        source = StorageSource.query.first()
        self.assertEqual("oob", source.config["oauth_callback_mode"])
        self.assertEqual("oob", source.config["oauth_redirect_uri"])
        self.assertNotIn("oauth_callback_mode", payload["data"]["source"]["config"])
        self.assertNotIn("oauth_redirect_uri", payload["data"]["source"]["config"])

    def test_poll_pending_keeps_source_locked(self):
        source = StorageSource(
            name="Baidu test",
            type="baidunetdisk",
            config={
                "auth_state": "oauth_pending",
                "cloud_root_path": "/",
                "root_folder_path": "/",
                "download_api": "official",
                "oauth_state": "baidu-state",
            },
        )
        db.session.add(source)
        db.session.commit()

        response = self.client.post(
            "/api/v1/storage/managed/baidunetdisk/oauth/poll",
            json={"source_id": source.id},
        )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertFalse(payload["data"]["authenticated"])
        self.assertEqual("oauth_pending", payload["data"]["auth_state"])
        self.assertEqual("waiting_for_authorization", payload["data"]["pending_reason"])
        self.assertFalse(payload["data"]["source"]["actions"]["can_preview"])

    def test_callback_marks_source_ready_and_removes_oauth_state(self):
        source = StorageSource(
            name="Baidu test",
            type="baidunetdisk",
            config={
                "auth_state": "oauth_pending",
                "cloud_root_path": "/",
                "root_folder_path": "/",
                "download_api": "official",
                "oauth_state": "baidu-state",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.get(
                "/api/v1/storage/managed/baidunetdisk/oauth/callback?state=baidu-state&code=baidu-code"
            )

        self.assertEqual(200, response.status_code)
        self.assertIn("Authorization completed", response.get_data(as_text=True))
        stored = db.session.get(StorageSource, source.id)
        self.assertEqual("ready", stored.config["auth_state"])
        self.assertEqual(211, stored.config["openlist_storage_id"])
        self.assertNotIn("oauth_state", stored.config)
        self.assertTrue(stored.to_dict()["actions"]["can_preview"])
        self.assertEqual("baidu-code", FakeManagedOpenListClient.completed_requests[0]["code"])

    def test_complete_oob_oauth_marks_source_ready(self):
        source = StorageSource(
            name="Baidu test",
            type="baidunetdisk",
            config={
                "openlist_storage_id": 210,
                "mount_path": "/cyberstream/baidunetdisk/old",
                "auth_state": "oauth_pending",
                "cloud_root_path": "/",
                "root_folder_path": "/",
                "download_api": "official",
                "oauth_state": "baidu-state",
                "oauth_callback_mode": "oob",
                "oauth_redirect_uri": "oob",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.post(
                "/api/v1/storage/managed/baidunetdisk/oauth/complete",
                json={"source_id": source.id, "authorization_code": "baidu-code"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["data"]["authenticated"])
        stored = db.session.get(StorageSource, source.id)
        self.assertEqual("ready", stored.config["auth_state"])
        self.assertEqual("oob", FakeManagedOpenListClient.completed_requests[0]["redirect_uri"])
        self.assertNotIn("oauth_state", stored.config)
        self.assertNotIn("oauth_callback_mode", stored.config)
        self.assertNotIn("oauth_redirect_uri", stored.config)
        self.assertEqual([210], FakeManagedOpenListClient.deleted_storage_ids)

    def test_delete_ready_managed_source_removes_openlist_storage_best_effort(self):
        source = StorageSource(
            name="Baidu test",
            type="baidunetdisk",
            config={
                "openlist_storage_id": 211,
                "mount_path": "/cyberstream/baidunetdisk/fake",
                "auth_state": "ready",
                "cloud_root_path": "/",
                "root_folder_path": "/",
                "download_api": "official",
            },
        )
        db.session.add(source)
        db.session.commit()

        with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
            response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(200, response.status_code)
        self.assertEqual([211], FakeManagedOpenListClient.deleted_storage_ids)
        self.assertIsNone(db.session.get(StorageSource, source.id))

    def test_oauth_callback_is_public_when_api_token_auth_is_enabled(self):
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BACKEND_PUBLIC_BASE_URL": "https://cyberstream.example",
            "AUTH_ENABLED": True,
            "API_TOKEN": "secret-token",
            "MANAGED_OPENLIST_ENABLED": True,
            "MANAGED_OPENLIST_TOKEN": "openlist-token",
        })
        with app.app_context():
            db.drop_all()
            db.create_all()
            source = StorageSource(
                name="Baidu test",
                type="baidunetdisk",
                config={
                    "auth_state": "oauth_pending",
                    "cloud_root_path": "/",
                    "root_folder_path": "/",
                    "download_api": "official",
                    "oauth_state": "baidu-state",
                },
            )
            db.session.add(source)
            db.session.commit()

            with patch("backend.app.api.storage_routes.ManagedOpenListClient", FakeManagedOpenListClient):
                response = app.test_client().get(
                    "/api/v1/storage/managed/baidunetdisk/oauth/callback?state=baidu-state&code=baidu-code"
                )

            db.session.remove()
            db.drop_all()

        self.assertEqual(200, response.status_code)


if __name__ == "__main__":
    unittest.main()
