from __future__ import annotations

import json
import socket
import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services import managed_alist as managed_alist_module
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


class FakeTianYiCloudPCOpenListSession:
    def __init__(self, create_qr=True, poll_ready=False, pending_message="QR code has not been scanned yet"):
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
                return FakeResponse({"code": 500, "message": QR_MESSAGE, "data": {"id": 188}})
            return FakeResponse({"code": 500, "message": "driver init failed", "data": {"id": 188}})
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
            "login_type": "qrcode",
            "username": "",
            "password": "",
            "validate_code": "",
            "access_token": "pc-access" if self.updated and self.poll_ready else "",
            "refresh_token": "pc-refresh" if self.updated and self.poll_ready else "",
            "root_folder_id": "-11",
            "order_by": "filename",
            "order_direction": "asc",
            "type": "personal",
            "family_id": "",
            "upload_method": "stream",
            "upload_thread": "3",
            "family_transfer": False,
            "rapid_upload": False,
            "no_use_ocr": True,
            "generate_torrent": False,
        }
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": "189CloudPC",
                "mount_path": "/cyberstream/tianyicloud-pc/test",
                "status": QR_MESSAGE if not addition["access_token"] else "work",
                "addition": json.dumps(addition),
            },
        })


class FakeQuarkUCTVOpenListSession:
    def __init__(
        self,
        driver="QuarkTV",
        create_qr=True,
        poll_ready=False,
        pending_message="code is empty",
        pending_status=QUARK_UC_QR_MESSAGE,
        ready_status="work",
    ):
        self.headers = {}
        self.trust_env = True
        self.driver = driver
        self.create_qr = create_qr
        self.poll_ready = poll_ready
        self.pending_message = pending_message
        self.pending_status = pending_status
        self.ready_status = ready_status
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
            return FakeResponse({"code": 500, "message": self.pending_message, "data": None})
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
                "status": self.pending_status if not addition["refresh_token"] else self.ready_status,
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


class FakeAliyundriveOpenListSession:
    def __init__(self, qr_status="WaitLogin"):
        self.headers = {}
        self.trust_env = True
        self.qr_status = qr_status
        self.deleted = []
        self.created_payload = None
        self.callback_params = None
        self.callback_headers = None

    def post(self, url, json=None, params=None, headers=None, timeout=None, verify=None):
        if url == "https://api.alistgo.com/alist/ali_open/qr":
            return FakeResponse({
                "sid": "ali-sid",
                "qrCodeUrl": "https://openapi.alipan.com/oauth/qrcode/ali-sid",
            })
        if url == "https://api.alistgo.com/alist/ali_open/code":
            return FakeResponse({
                "access_token": "ali-access",
                "refresh_token": "ali-refresh",
            })
        if url.endswith("/api/admin/storage/create"):
            self.created_payload = json
            return FakeResponse({"code": 200, "data": {"id": 188}})
        if url.endswith("/api/admin/storage/delete"):
            self.deleted.append(int(params["id"]))
            return FakeResponse({"code": 200, "data": None})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        if url == "https://api.oplist.org/alicloud/requests":
            return FakeResponse({
                "sid": "ali-sid",
                "text": "https://openapi.alipan.com/oauth/qrcode/ali-sid",
            })
        if url in {
            "https://api.alistgo.com/proxy/https://open.aliyundrive.com/oauth/qrcode/ali-sid/status",
            "https://openapi.aliyundrive.com/oauth/qrcode/ali-sid/status",
        }:
            payload = {"status": self.qr_status}
            if self.qr_status == "LoginSuccess":
                payload["authCode"] = "ali-auth-code"
            return FakeResponse(payload)
        if url == "https://api.oplist.org/alicloud/callback":
            self.callback_params = dict(params or {})
            self.callback_headers = dict(headers or {})
            return FakeResponse({
                "access_token": "ali-access",
                "refresh_token": "ali-refresh",
            })
        if not url.endswith("/api/admin/storage/get"):
            raise AssertionError(url)
        payload_addition = json.loads(self.created_payload["addition"]) if self.created_payload else {}
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": "AliyundriveOpen",
                "mount_path": "/cyberstream/aliyundrive/test",
                "status": "work",
                "addition": json.dumps({
                    "drive_type": payload_addition.get("drive_type", "resource"),
                    "root_folder_id": payload_addition.get("root_folder_id", "root"),
                    "refresh_token": payload_addition.get("refresh_token", "ali-refresh"),
                    "order_by": "name",
                    "order_direction": "ASC",
                    "use_online_api": payload_addition.get("use_online_api", True),
                    "alipan_type": payload_addition.get("alipan_type", "default"),
                    "api_url_address": payload_addition.get(
                        "api_url_address",
                        "https://api.oplist.org/alicloud/renewapi",
                    ),
                    "client_id": payload_addition.get("client_id", ""),
                    "client_secret": payload_addition.get("client_secret", ""),
                    "remove_way": "trash",
                    "rapid_upload": False,
                    "internal_upload": False,
                    "livp_download_format": "jpeg",
                }),
            },
        })


class FakeBaiduNetdiskOpenListSession:
    def __init__(self):
        self.headers = {}
        self.trust_env = True
        self.deleted = []
        self.created_payload = None
        self.token_params = None

    def post(self, url, json=None, params=None, headers=None, timeout=None, verify=None):
        if url.endswith("/api/admin/storage/create"):
            self.created_payload = json
            return FakeResponse({"code": 200, "data": {"id": 211}})
        if url.endswith("/api/admin/storage/delete"):
            self.deleted.append(int(params["id"]))
            return FakeResponse({"code": 200, "data": None})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        if url == "https://openapi.baidu.com/oauth/2.0/token":
            self.token_params = dict(params or {})
            return FakeResponse({
                "access_token": "baidu-access",
                "refresh_token": "baidu-refresh",
                "expires_in": 2592000,
            })
        if not url.endswith("/api/admin/storage/get"):
            raise AssertionError(url)
        payload_addition = json.loads(self.created_payload["addition"]) if self.created_payload else {}
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": "BaiduNetdisk",
                "mount_path": "/cyberstream/baidunetdisk/test",
                "status": "work",
                "addition": json.dumps({
                    "root_folder_path": payload_addition.get("root_folder_path", "/"),
                    "order_by": "name",
                    "order_direction": "asc",
                    "download_api": payload_addition.get("download_api", "official"),
                    "use_online_api": payload_addition.get("use_online_api", False),
                    "api_url_address": payload_addition.get(
                        "api_url_address",
                        "https://api.oplist.org/baiduyun/renewapi",
                    ),
                    "client_id": payload_addition.get("client_id", "baidu-client-id"),
                    "client_secret": payload_addition.get("client_secret", "baidu-client-secret"),
                    "custom_crack_ua": "netdisk",
                    "access_token": payload_addition.get("access_token", "baidu-access"),
                    "refresh_token": payload_addition.get("refresh_token", "baidu-refresh"),
                    "upload_thread": "3",
                    "upload_timeout": 60,
                    "upload_api": "https://d.pcs.baidu.com",
                    "use_dynamic_upload_api": True,
                    "custom_upload_part_size": 0,
                    "low_bandwith_upload_mode": False,
                    "only_list_video_file": False,
                }),
            },
        })


class Fake123PanOpenListSession:
    def __init__(self, create_ok=True):
        self.headers = {}
        self.trust_env = True
        self.create_ok = create_ok
        self.deleted = []
        self.created_payload = None

    def post(self, url, json=None, params=None, headers=None, timeout=None, verify=None):
        if url.endswith("/api/admin/storage/create"):
            self.created_payload = json
            if self.create_ok:
                return FakeResponse({"code": 200, "data": {"id": 123}})
            return FakeResponse({"code": 500, "message": "invalid password", "data": {"id": 123}})
        if url.endswith("/api/admin/storage/delete"):
            self.deleted.append(int(params["id"]))
            return FakeResponse({"code": 200, "data": None})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        if not url.endswith("/api/admin/storage/get"):
            raise AssertionError(url)
        payload_addition = json.loads(self.created_payload["addition"]) if self.created_payload else {}
        return FakeResponse({
            "code": 200,
            "data": {
                "id": int(params["id"]),
                "driver": "123Pan",
                "mount_path": "/cyberstream/123pan/test",
                "status": "work",
                "addition": json.dumps({
                    "username": payload_addition.get("username", "13800000000"),
                    "password": payload_addition.get("password", "secret"),
                    "root_folder_id": payload_addition.get("root_folder_id", "0"),
                    "access_token": payload_addition.get("access_token", "access-token"),
                    "UploadThread": payload_addition.get("UploadThread", 3),
                    "platform": payload_addition.get("platform", "web"),
                }),
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
                "MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_ID": "baidu-client-id",
                "MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_SECRET": "baidu-client-secret",
                "MANAGED_OPENLIST_BAIDUNETDISK_AUTHORIZE_URL": "https://openapi.baidu.com/oauth/2.0/authorize",
                "MANAGED_OPENLIST_BAIDUNETDISK_TOKEN_URL": "https://openapi.baidu.com/oauth/2.0/token",
                "MANAGED_OPENLIST_BAIDUNETDISK_RENEW_API_URL": "https://api.oplist.org/baiduyun/renewapi",
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

    def test_pc_qr_start_uses_189cloudpc_driver(self):
        session = FakeTianYiCloudPCOpenListSession(create_qr=True)
        client = self.create_client(session)

        started = client.create_tianyicloud_pc_qr_storage()

        self.assertEqual(188, started["storage_id"])
        self.assertEqual("pc_qr", started["login_mode"])
        self.assertEqual("qr_pending", started["auth_state"])
        self.assertEqual("data:image/jpeg;base64,ZmFrZS1xcg==", started["qr_code_data_url"])
        self.assertEqual("qr-uuid", started["qr_content"])
        self.assertEqual("/cyberstream/tianyicloud-pc/test", started["mount_path"])
        self.assertEqual("189CloudPC", session.created_payload["driver"])
        addition = json.loads(session.created_payload["addition"])
        self.assertEqual("qrcode", addition["login_type"])
        self.assertEqual("-11", addition["root_folder_id"])
        self.assertEqual([], session.deleted)

    def test_pc_qr_poll_reports_pending_until_scan_finishes(self):
        session = FakeTianYiCloudPCOpenListSession(poll_ready=False)
        client = self.create_client(session)

        state = client.poll_tianyicloud_pc_qr_storage(188)

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_pending", state["auth_state"])
        self.assertEqual("pc_qr", state["login_mode"])
        self.assertEqual("waiting_for_scan", state["pending_reason"])
        self.assertEqual("data:image/jpeg;base64,ZmFrZS1xcg==", state["qr_code_data_url"])
        self.assertTrue(session.updated)

    def test_pc_qr_poll_marks_ready_after_openlist_update_succeeds(self):
        session = FakeTianYiCloudPCOpenListSession(poll_ready=True)
        client = self.create_client(session)

        state = client.poll_tianyicloud_pc_qr_storage(188)

        self.assertTrue(state["authenticated"])
        self.assertEqual("ready", state["auth_state"])
        self.assertEqual("pc_qr", state["login_mode"])
        self.assertEqual("/cyberstream/tianyicloud-pc/test", state["mount_path"])

    def test_pc_qr_poll_reports_expired_state(self):
        session = FakeTianYiCloudPCOpenListSession(
            poll_ready=False,
            pending_message="QR code expired, please try again",
        )
        client = self.create_client(session)

        state = client.poll_tianyicloud_pc_qr_storage(188)

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_expired", state["auth_state"])
        self.assertEqual("qr_expired", state["pending_reason"])

    def test_quarktv_qr_start_extracts_data_url_and_forces_download_link_method(self):
        session = FakeQuarkUCTVOpenListSession(driver="QuarkTV", create_qr=True)
        client = self.create_client(session)

        started = client.create_quark_uc_tv_storage("quarktv", link_method="streaming")

        self.assertEqual(99, started["storage_id"])
        self.assertEqual("qr_pending", started["auth_state"])
        self.assertEqual("data:image/jpeg;base64,cXVhcmstdWMtcXI=", started["qr_code_data_url"])
        self.assertIsNone(started["qr_content"])
        self.assertEqual("download", started["link_method"])
        self.assertEqual("QuarkTV", session.created_payload["driver"])
        self.assertEqual(
            "download",
            json.loads(session.created_payload["addition"])["link_method"],
        )
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

    def test_quark_uc_qr_poll_treats_chinese_unconfirmed_authorization_as_pending(self):
        session = FakeQuarkUCTVOpenListSession(
            driver="QuarkTV",
            poll_ready=False,
            pending_message="failed init storage: 用户未确认授权",
            pending_status="用户未确认授权",
        )
        client = self.create_client(session)

        state = client.poll_quark_uc_tv_storage(99, "quarktv")

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_pending", state["auth_state"])
        self.assertEqual("waiting_for_scan", state["pending_reason"])
        self.assertNotIn("qr_code_data_url", state)
        self.assertTrue(session.updated)

    def test_quark_uc_qr_poll_reports_chinese_expired_qr_code(self):
        session = FakeQuarkUCTVOpenListSession(
            driver="QuarkTV",
            poll_ready=False,
            pending_message="failed init storage: 授权码Code二维码过期",
            pending_status="授权码Code二维码过期",
        )
        client = self.create_client(session)

        state = client.poll_quark_uc_tv_storage(99, "quarktv")

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_expired", state["auth_state"])
        self.assertEqual("qr_expired", state["pending_reason"])
        self.assertNotIn("qr_code_data_url", state)
        self.assertTrue(session.updated)

    def test_quark_uc_qr_poll_reports_device_limit_after_token_update(self):
        session = FakeQuarkUCTVOpenListSession(
            driver="QuarkTV",
            poll_ready=True,
            ready_status="\u8bbe\u5907\u6570\u8d85\u9650",
        )
        client = self.create_client(session)

        state = client.poll_quark_uc_tv_storage(99, "quarktv")

        self.assertFalse(state["authenticated"])
        self.assertEqual("device_limit", state["auth_state"])
        self.assertEqual("device_limit", state["pending_reason"])
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

    def test_aliyundrive_qr_start_uses_openlist_public_tool_fallback(self):
        session = FakeAliyundriveOpenListSession()
        client = self.create_client(session)

        started = client.start_aliyundrive_qr()

        self.assertEqual("qr_pending", started["auth_state"])
        self.assertEqual("waiting_for_scan", started["pending_reason"])
        self.assertEqual("ali-sid", started["qr_sid"])
        self.assertEqual("openlist", started["auth_provider"])
        self.assertEqual("https://openapi.alipan.com/oauth/qrcode/ali-sid", started["qr_code_url"])

    def test_aliyundrive_qr_poll_reports_pending_without_creating_openlist_storage(self):
        session = FakeAliyundriveOpenListSession(qr_status="WaitLogin")
        client = self.create_client(session)

        state = client.poll_aliyundrive_storage("ali-sid")

        self.assertFalse(state["authenticated"])
        self.assertEqual("qr_pending", state["auth_state"])
        self.assertEqual("waiting_for_scan", state["pending_reason"])
        self.assertIsNone(session.created_payload)

    def test_aliyundrive_request_uses_selected_ipv6_family(self):
        session = FakeAliyundriveOpenListSession(qr_status="WaitLogin")
        client = self.create_client(session)
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None, verify=None):
            calls.append(managed_alist_module.urllib3_connection.allowed_gai_family())
            return FakeResponse({"status": "WaitLogin"})

        with patch.object(client, "_pick_aliyundrive_dns_family", return_value=socket.AF_INET6), \
             patch.object(session, "get", side_effect=fake_get):
            self.assertEqual(
                {"status": "WaitLogin"},
                client._request_aliyundrive_json(
                    "get",
                    "https://openapi.aliyundrive.com/oauth/qrcode/ali-sid/status",
                    "QR status",
                ),
            )

        self.assertEqual(socket.AF_INET6, calls[0])

    def test_aliyundrive_qr_poll_creates_openlist_storage_after_login_success(self):
        session = FakeAliyundriveOpenListSession(qr_status="LoginSuccess")
        client = self.create_client(session)

        state = client.poll_aliyundrive_storage("ali-sid")

        self.assertTrue(state["authenticated"])
        self.assertEqual("ready", state["auth_state"])
        self.assertEqual(188, state["storage_id"])
        self.assertEqual("/cyberstream/aliyundrive/test", state["mount_path"])
        self.assertEqual("AliyundriveOpen", session.created_payload["driver"])
        self.assertIn("/aliyundrive/", session.created_payload["mount_path"])
        addition = json.loads(session.created_payload["addition"])
        self.assertEqual("ali-refresh", addition["refresh_token"])
        self.assertEqual("resource", addition["drive_type"])
        self.assertEqual("root", addition["root_folder_id"])
        self.assertTrue(addition["use_online_api"])
        self.assertEqual({"grant_type": "authorization_code", "code": "ali-sid"}, session.callback_params)
        self.assertEqual("driver_txt=alicloud_qr; server_use=true", session.callback_headers.get("Cookie"))

    def test_baidunetdisk_oauth_start_builds_authorization_url(self):
        session = FakeBaiduNetdiskOpenListSession()
        client = self.create_client(session)

        started = client.start_baidunetdisk_oauth(
            redirect_uri="https://cyberstream.example/api/v1/storage/managed/baidunetdisk/oauth/callback",
            root_path="电影",
        )

        self.assertEqual("oauth_pending", started["auth_state"])
        self.assertEqual("waiting_for_authorization", started["pending_reason"])
        self.assertEqual("/电影", started["root_folder_path"])
        self.assertEqual("crack_video", started["download_api"])
        self.assertIn("https://openapi.baidu.com/oauth/2.0/authorize?", started["authorization_url"])
        self.assertIn("client_id=baidu-client-id", started["authorization_url"])
        self.assertIn(
            "redirect_uri=https%3A%2F%2Fcyberstream.example%2Fapi%2Fv1%2Fstorage%2Fmanaged%2Fbaidunetdisk%2Foauth%2Fcallback",
            started["authorization_url"],
        )
        self.assertIn("scope=basic%2Cnetdisk", started["authorization_url"])
        self.assertEqual("redirect", started["callback_mode"])
        self.assertFalse(started["requires_authorization_code"])
        self.assertTrue(started["oauth_state"])

    def test_baidunetdisk_oauth_start_uses_builtin_public_client_by_default(self):
        session = FakeBaiduNetdiskOpenListSession()
        client = ManagedOpenListClient(
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

        started = client.start_baidunetdisk_oauth(
            redirect_uri="https://cyberstream.example/api/v1/storage/managed/baidunetdisk/oauth/callback",
        )

        self.assertIn(
            f"client_id={ManagedOpenListClient.DEFAULT_BAIDUNETDISK_CLIENT_ID}",
            started["authorization_url"],
        )
        self.assertIn("redirect_uri=oob", started["authorization_url"])
        self.assertEqual("oob", started["callback_mode"])
        self.assertTrue(started["requires_authorization_code"])
        self.assertEqual("oob", started["oauth_redirect_uri"])

    def test_baidunetdisk_oauth_complete_creates_openlist_storage(self):
        session = FakeBaiduNetdiskOpenListSession()
        client = self.create_client(session)

        state = client.complete_baidunetdisk_oauth(
            code="baidu-code",
            redirect_uri="https://cyberstream.example/api/v1/storage/managed/baidunetdisk/oauth/callback",
            root_path="/电影",
        )

        self.assertTrue(state["authenticated"])
        self.assertEqual("ready", state["auth_state"])
        self.assertEqual(211, state["storage_id"])
        self.assertEqual("/cyberstream/baidunetdisk/test", state["mount_path"])
        self.assertEqual("BaiduNetdisk", session.created_payload["driver"])
        self.assertIn("/baidunetdisk/", session.created_payload["mount_path"])
        self.assertEqual("baidu-code", session.token_params["code"])
        addition = json.loads(session.created_payload["addition"])
        self.assertEqual("baidu-refresh", addition["refresh_token"])
        self.assertEqual("baidu-access", addition["access_token"])
        self.assertEqual("/电影", addition["root_folder_path"])
        self.assertFalse(addition["use_online_api"])

    def test_123pan_login_creates_openlist_storage(self):
        session = Fake123PanOpenListSession()
        client = self.create_client(session)

        state = client.create_123pan_storage(
            username="13800000000",
            password="secret",
            root_folder_id="0",
        )

        self.assertTrue(state["authenticated"])
        self.assertEqual("ready", state["auth_state"])
        self.assertEqual(123, state["storage_id"])
        self.assertEqual("/cyberstream/123pan/test", state["mount_path"])
        self.assertEqual("13*****0000", state["account_name_masked"])
        self.assertEqual("123Pan", session.created_payload["driver"])
        self.assertIn("/123pan/", session.created_payload["mount_path"])
        addition = json.loads(session.created_payload["addition"])
        self.assertEqual("13800000000", addition["username"])
        self.assertEqual("secret", addition["password"])
        self.assertEqual("0", addition["root_folder_id"])
        self.assertEqual("web", addition["platform"])

    def test_123pan_failed_login_deletes_openlist_orphan_storage(self):
        session = Fake123PanOpenListSession(create_ok=False)
        client = self.create_client(session)

        with self.assertRaises(ManagedAListError):
            client.create_123pan_storage(username="13800000000", password="bad")

        self.assertEqual([123], session.deleted)


if __name__ == "__main__":
    unittest.main()
