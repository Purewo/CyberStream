from __future__ import annotations

import json
import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.managed_alist import ManagedAListClient, ManagedAListError
from backend.app.services.accounts import account_scope


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeManagedSession:
    def __init__(self, fail_create=False):
        self.headers = {}
        self.trust_env = True
        self.fail_create = fail_create
        self.deleted = []
        self.updated = False
        self.created_payload = None

    def post(self, url, json=None, params=None, headers=None, timeout=None, verify=None):
        if url.endswith("/api/admin/storage/create"):
            self.created_payload = json
            if self.fail_create:
                return FakeResponse({"code": 500, "message": "send failed", "data": {"id": 91}})
            return FakeResponse({"code": 200, "data": {"id": 77}})
        if url.endswith("/api/admin/storage/update"):
            self.updated = True
            return FakeResponse({"code": 200, "data": None})
        if url.endswith("/api/admin/storage/delete"):
            self.deleted.append(int(params["id"]))
            return FakeResponse({"code": 200, "data": None})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        if not url.endswith("/api/admin/storage/get"):
            raise AssertionError(url)
        addition = {
            "phone_number": "+861380001234",
            "verification_id": "sms-request",
            "access_token": "access" if self.updated else "",
            "refresh_token": "refresh" if self.updated else "",
        }
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": "GuangYaPan",
                "mount_path": "/cyberstream/guangyapan/test",
                "addition": json.dumps(addition),
            },
        })


class ManagedAListClientTests(unittest.TestCase):
    def create_client(self, session):
        return ManagedAListClient(
            app_config={
                "MANAGED_ALIST_ENABLED": True,
                "MANAGED_ALIST_BASE_URL": "http://127.0.0.1:5244",
                "MANAGED_ALIST_TOKEN": "token",
                "MANAGED_ALIST_USERNAME": "admin",
                "MANAGED_ALIST_PASSWORD": "",
                "MANAGED_ALIST_TIMEOUT_SECONDS": 30,
                "MANAGED_ALIST_VERIFY_SSL": False,
                "MANAGED_ALIST_MOUNT_PREFIX": "/cyberstream",
            },
            session=session,
        )

    def test_sms_start_and_verify_use_internal_mount_state(self):
        session = FakeManagedSession()
        client = self.create_client(session)

        started = client.create_guangyapan_storage("+861380001234", root_path="电影")
        verified = client.verify_guangyapan_storage(started["storage_id"], "123456")

        self.assertEqual(77, started["storage_id"])
        self.assertEqual("+********1234", started["phone_number_masked"])
        self.assertEqual("+861380001234", client.get_guangyapan_phone_number(started["storage_id"]))
        self.assertEqual("/cyberstream/guangyapan/test", verified["mount_path"])
        self.assertTrue(session.updated)

    def test_failed_sms_start_deletes_alist_orphan_storage(self):
        session = FakeManagedSession(fail_create=True)
        client = self.create_client(session)

        with self.assertRaises(ManagedAListError):
            client.create_guangyapan_storage("+861380001234")

        self.assertEqual([91], session.deleted)

    def test_source_scope_mount_path_includes_account_and_source(self):
        session = FakeManagedSession()
        with account_scope("account-1"):
            client = self.create_client(session)
            client.set_source_scope(42)

            client.create_guangyapan_storage("+861380001234")

        self.assertTrue(
            session.created_payload["mount_path"].startswith(
                "/cyberstream/accounts/account-1/sources/42/guangyapan/"
            )
        )


if __name__ == "__main__":
    unittest.main()
