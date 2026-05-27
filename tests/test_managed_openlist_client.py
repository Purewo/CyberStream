from __future__ import annotations

import json
import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.managed_alist import ManagedAListError, ManagedOpenListClient


QR_MESSAGE = (
    'failed init storage but storage is already created: failed init storage: need verify: \n'
    '<body><img src="data:image/jpeg;base64,ZmFrZS1xcg=="/>'
    '<br>Or Click here: <a href="qr-uuid">qr-uuid</a></body>'
)
QUARK_UC_QR_MESSAGE = (
    'failed init storage but storage is already created: failed init storage: need verify: \n'
    '<body><img src="data:image/jpeg;base64,cXVhcmstdWMtcXI="/></body>'
)


class FakeResponse:
    def __init__(self, payload, status_code=200, content=b"", headers=None):
        self.payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeOpenListSession:
    def __init__(self, create_qr=True, poll_ready=False, pending_message="E189AccessToken is empty"):
        self.headers = {}
        self.trust_env = True
        self.create_qr = create_qr
        self.poll_ready = poll_ready
        self.pending_message = pending_message
        self.deleted = []
        self.updated = False
        self.created_payload = None

    def post(self, url, json=None, params=None, headers=None, timeout=None, verify=None):
        if url.endswith("/api/admin/storage/create"):
            self.created_payload = json
            if self.create_qr:
                return FakeResponse({"code": 500, "message": QR_MESSAGE, "data": {"id": 88}})
            return FakeResponse({"code": 500, "message": "driver init failed", "data": {"id": 88}})
        if url.endswith("/api/admin/storage/update"):
            self.updated = True
            if self.poll_ready:
                return FakeResponse({"code": 200, "data": None})
            return FakeResponse({"code": 500, "message": self.pending_message, "data": None})
        if url.endswith("/api/admin/storage/delete"):
            self.deleted.append(int(params["id"]))
            return FakeResponse({"code": 200, "data": None})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        if not url.endswith("/api/admin/storage/get"):
            raise AssertionError(url)
        addition = {
            "root_folder_id": "-11",
            "access_token": "access" if self.updated and self.poll_ready else "",
            "order_by": "filename",
            "order_direction": "asc",
            "type": "personal",
            "family_id": "",
            "upload_thread": "3",
            "rapid_upload": False,
        }
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": "189CloudTV",
                "mount_path": "/cyberstream/tianyicloud/test",
                "status": QR_MESSAGE if not addition["access_token"] else "work",
                "addition": json.dumps(addition),
            },
        })


class FakeQuarkUCTVOpenListSession:
    def __init__(self, driver="QuarkTV", create_qr=True, poll_ready=False):
        self.headers = {}
        self.trust_env = True
        self.driver = driver
        self.create_qr = create_qr
        self.poll_ready = poll_ready
        self.deleted = []
        self.updated = False
        self.created_payload = None

    def post(self, url, json=None, params=None, headers=None, timeout=None, verify=None):
        if url.endswith("/api/admin/storage/create"):
            self.created_payload = json
            if self.create_qr:
                return FakeResponse({"code": 500, "message": QUARK_UC_QR_MESSAGE, "data": {"id": 99}})
            return FakeResponse({"code": 500, "message": "driver init failed", "data": {"id": 99}})
        if url.endswith("/api/admin/storage/update"):
            self.updated = True
            if self.poll_ready:
                return FakeResponse({"code": 200, "data": None})
            return FakeResponse({"code": 500, "message": "code is empty", "data": None})
        if url.endswith("/api/admin/storage/delete"):
            self.deleted.append(int(params["id"]))
            return FakeResponse({"code": 200, "data": None})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        if not url.endswith("/api/admin/storage/get"):
            raise AssertionError(url)
        addition = {
            "root_folder_id": "0",
            "order_by": "updated_at",
            "order_direction": "desc",
            "refresh_token": "refresh-token" if self.updated and self.poll_ready else "",
            "device_id": "device",
            "query_token": "query-token",
            "link_method": self.created_payload["addition"] and json.loads(self.created_payload["addition"]).get("link_method", "download")
            if self.created_payload else "download",
        }
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": self.driver,
                "mount_path": f"/cyberstream/{self.driver.lower()}/test",
                "status": QUARK_UC_QR_MESSAGE if not addition["refresh_token"] else "work",
                "addition": json.dumps(addition),
            },
        })


class Fake115OpenListSession:
    def __init__(self, qr_status=0, poll_ready=False):
        self.headers = {}
        self.trust_env = True
        self.qr_status = qr_status
        self.poll_ready = poll_ready
        self.deleted = []
        self.updated = False
        self.created_payload = None

    def post(self, url, json=None, params=None, headers=None, timeout=None, verify=None):
        if url.endswith("/api/admin/storage/create"):
            self.created_payload = json
            return FakeResponse({"code": 500, "message": "failed to login by qrcode", "data": {"id": 115}})
        if url.endswith("/api/admin/storage/update"):
            self.updated = True
            if self.poll_ready:
                return FakeResponse({"code": 200, "data": None})
            return FakeResponse({"code": 500, "message": "failed to login by qrcode", "data": None})
        if url.endswith("/api/admin/storage/delete"):
            self.deleted.append(int(params["id"]))
            return FakeResponse({"code": 200, "data": None})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        if url == "https://qrcodeapi.115.com/api/1.0/web/1.0/token":
            return FakeResponse({
                "state": 1,
                "code": 0,
                "data": {
                    "uid": "115-uid",
                    "time": 1779910679,
                    "sign": "115-sign",
                    "qrcode": "https://115.com/scan/dg-115-uid",
                },
            }, headers={"Content-Type": "application/json"})
        if url == "https://qrcodeapi.115.com/api/1.0/mac/1.0/qrcode":
            self.qr_image_params = dict(params or {})
            return FakeResponse(
                {},
                content=b"fake-png",
                headers={"Content-Type": "image/png"},
            )
        if url == "https://qrcodeapi.115.com/get/status/":
            self.qr_status_params = dict(params or {})
            return FakeResponse({
                "state": 1,
                "code": 0,
                "data": {"status": self.qr_status},
            })
        if not url.endswith("/api/admin/storage/get"):
            raise AssertionError(url)
        payload_addition = json.loads(self.created_payload["addition"]) if self.created_payload else {}
        addition = {
            "root_folder_id": payload_addition.get("root_folder_id", "0"),
            "cookie": "UID=uid;CID=cid;SEID=seid;KID=kid" if self.updated and self.poll_ready else "",
            "qrcode_token": "" if self.updated and self.poll_ready else payload_addition.get("qrcode_token", "115-uid"),
            "qrcode_source": payload_addition.get("qrcode_source", "wechatmini"),
            "page_size": 1000,
            "limit_rate": 2,
        }
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": "115 Cloud",
                "mount_path": "/cyberstream/115cloud/test",
                "status": "work" if addition["cookie"] else "failed to login by qrcode",
                "addition": json.dumps(addition),
            },
        })


class ManagedOpenListClientTests(unittest.TestCase):
    def create_client(self, session):
        return ManagedOpenListClient(
            app_config={
                "MANAGED_OPENLIST_ENABLED": True,
                "MANAGED_OPENLIST_BASE_URL": "http://127.0.0.1:5245",
                "MANAGED_OPENLIST_TOKEN": "token",
                "MANAGED_OPENLIST_USERNAME": "admin",
                "MANAGED_OPENLIST_PASSWORD": "",
                "MANAGED_OPENLIST_TIMEOUT_SECONDS": 30,
                "MANAGED_OPENLIST_VERIFY_SSL": False,
                "MANAGED_OPENLIST_MOUNT_PREFIX": "/cyberstream",
            },
            session=session,
        )

    def test_qr_start_extracts_data_url_and_keeps_openlist_storage(self):
        session = FakeOpenListSession(create_qr=True)
        client = self.create_client(session)

        started = client.create_tianyicloud_storage()

        self.assertEqual(88, started["storage_id"])
        self.assertEqual("qr_pending", started["auth_state"])
        self.assertEqual("data:image/jpeg;base64,ZmFrZS1xcg==", started["qr_code_data_url"])
        self.assertEqual("qr-uuid", started["qr_content"])
        self.assertEqual("/cyberstream/tianyicloud/test", started["mount_path"])
        self.assertEqual("189CloudTV", session.created_payload["driver"])
        self.assertEqual([], session.deleted)

    def test_failed_qr_start_deletes_openlist_orphan_storage(self):
        session = FakeOpenListSession(create_qr=False)
        client = self.create_client(session)

        with self.assertRaises(ManagedAListError):
            client.create_tianyicloud_storage()

        self.assertEqual([88], session.deleted)

    def test_qr_poll_reports_pending_until_scan_finishes(self):
        session = FakeOpenListSession(poll_ready=False)
        client = self.create_client(session)

        state = client.poll_tianyicloud_storage(88)

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_pending", state["auth_state"])
        self.assertEqual("waiting_for_scan", state["pending_reason"])
        self.assertEqual("data:image/jpeg;base64,ZmFrZS1xcg==", state["qr_code_data_url"])
        self.assertTrue(session.updated)

    def test_qr_poll_treats_qrcode_roll_login_fail_as_pending(self):
        session = FakeOpenListSession(
            poll_ready=False,
            pending_message=(
                "failed init storage: res_code: QrCodeRollLoginFail, "
                "res_msg: qrCodeRollLogin() - waiting for scan"
            ),
        )
        client = self.create_client(session)

        state = client.poll_tianyicloud_storage(88)

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_pending", state["auth_state"])
        self.assertEqual("waiting_for_scan", state["pending_reason"])
        self.assertTrue(session.updated)

    def test_qr_poll_marks_ready_after_openlist_update_succeeds(self):
        session = FakeOpenListSession(poll_ready=True)
        client = self.create_client(session)

        state = client.poll_tianyicloud_storage(88)

        self.assertTrue(state["authenticated"])
        self.assertEqual("ready", state["auth_state"])
        self.assertEqual("/cyberstream/tianyicloud/test", state["mount_path"])

    def test_quarktv_qr_start_extracts_data_url_and_keeps_openlist_storage(self):
        session = FakeQuarkUCTVOpenListSession(driver="QuarkTV", create_qr=True)
        client = self.create_client(session)

        started = client.create_quark_uc_tv_storage("quarktv", link_method="streaming")

        self.assertEqual(99, started["storage_id"])
        self.assertEqual("qr_pending", started["auth_state"])
        self.assertEqual("data:image/jpeg;base64,cXVhcmstdWMtcXI=", started["qr_code_data_url"])
        self.assertIsNone(started["qr_content"])
        self.assertEqual("streaming", started["link_method"])
        self.assertEqual("QuarkTV", session.created_payload["driver"])
        self.assertIn("/quarktv/", session.created_payload["mount_path"])
        self.assertEqual([], session.deleted)

    def test_uctv_qr_start_uses_uctv_driver(self):
        session = FakeQuarkUCTVOpenListSession(driver="UCTV", create_qr=True)
        client = self.create_client(session)

        started = client.create_quark_uc_tv_storage("uctv")

        self.assertEqual(99, started["storage_id"])
        self.assertEqual("UCTV", session.created_payload["driver"])
        self.assertEqual("download", started["link_method"])
        self.assertIn("/uctv/", session.created_payload["mount_path"])

    def test_quark_uc_failed_qr_start_deletes_openlist_orphan_storage(self):
        session = FakeQuarkUCTVOpenListSession(driver="QuarkTV", create_qr=False)
        client = self.create_client(session)

        with self.assertRaises(ManagedAListError):
            client.create_quark_uc_tv_storage("quarktv")

        self.assertEqual([99], session.deleted)

    def test_quark_uc_qr_poll_reports_pending_until_scan_finishes(self):
        session = FakeQuarkUCTVOpenListSession(driver="QuarkTV", poll_ready=False)
        client = self.create_client(session)

        state = client.poll_quark_uc_tv_storage(99, "quarktv")

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_pending", state["auth_state"])
        self.assertEqual("waiting_for_scan", state["pending_reason"])
        self.assertEqual("data:image/jpeg;base64,cXVhcmstdWMtcXI=", state["qr_code_data_url"])
        self.assertTrue(session.updated)

    def test_quark_uc_qr_poll_marks_ready_after_openlist_update_succeeds(self):
        session = FakeQuarkUCTVOpenListSession(driver="QuarkTV", poll_ready=True)
        client = self.create_client(session)

        state = client.poll_quark_uc_tv_storage(99, "quarktv")

        self.assertTrue(state["authenticated"])
        self.assertEqual("ready", state["auth_state"])
        self.assertEqual("/cyberstream/quarktv/test", state["mount_path"])

    def test_115cloud_qr_start_fetches_115_qr_and_keeps_openlist_storage(self):
        session = Fake115OpenListSession(qr_status=0)
        client = self.create_client(session)

        started = client.create_115cloud_storage()

        self.assertEqual(115, started["storage_id"])
        self.assertEqual("qr_pending", started["auth_state"])
        self.assertEqual("waiting_for_scan", started["pending_reason"])
        self.assertEqual("data:image/png;base64,ZmFrZS1wbmc=", started["qr_code_data_url"])
        self.assertEqual("https://115.com/scan/dg-115-uid", started["qr_content"])
        self.assertEqual("115-uid", started["qr_uid"])
        self.assertEqual("115-sign", started["qr_sign"])
        self.assertEqual(1779910679, started["qr_time"])
        self.assertEqual("115 Cloud", session.created_payload["driver"])
        self.assertIn("/115cloud/", session.created_payload["mount_path"])
        addition = json.loads(session.created_payload["addition"])
        self.assertEqual("115-uid", addition["qrcode_token"])
        self.assertEqual("wechatmini", addition["qrcode_source"])
        self.assertEqual([], session.deleted)

    def test_115cloud_qr_poll_reports_waiting_for_scan_without_openlist_update(self):
        session = Fake115OpenListSession(qr_status=0, poll_ready=False)
        client = self.create_client(session)

        state = client.poll_115cloud_storage(
            115,
            qr_session={"qr_uid": "115-uid", "qr_sign": "115-sign", "qr_time": 1779910679},
        )

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_pending", state["auth_state"])
        self.assertEqual("waiting_for_scan", state["pending_reason"])
        self.assertEqual(0, state["qr_status"])
        self.assertFalse(session.updated)

    def test_115cloud_qr_poll_marks_ready_after_115_confirm_and_openlist_update(self):
        session = Fake115OpenListSession(qr_status=2, poll_ready=True)
        client = self.create_client(session)

        state = client.poll_115cloud_storage(
            115,
            qr_session={"qr_uid": "115-uid", "qr_sign": "115-sign", "qr_time": 1779910679},
        )

        self.assertTrue(state["authenticated"])
        self.assertEqual("ready", state["auth_state"])
        self.assertEqual(2, state["qr_status"])
        self.assertEqual("/cyberstream/115cloud/test", state["mount_path"])
        self.assertTrue(session.updated)

    def test_115cloud_qr_poll_reports_expired(self):
        session = Fake115OpenListSession(qr_status=-1, poll_ready=False)
        client = self.create_client(session)

        state = client.poll_115cloud_storage(
            115,
            qr_session={"qr_uid": "115-uid", "qr_sign": "115-sign", "qr_time": 1779910679},
        )

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_expired", state["auth_state"])
        self.assertEqual("qr_expired", state["pending_reason"])
        self.assertEqual(-1, state["qr_status"])
        self.assertFalse(session.updated)

if __name__ == "__main__":
    unittest.main()
