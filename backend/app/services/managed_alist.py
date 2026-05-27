import base64
import json
import posixpath
import re
import time
import uuid
from urllib.parse import urljoin

import requests
from flask import current_app

from backend.app.providers.base import StorageProviderError


class ManagedAListError(StorageProviderError):
    def __init__(self, message, code=50260, data=None):
        super().__init__(message, code=code)
        self.data = data


def mask_phone_number(phone_number):
    raw = str(phone_number or "").strip()
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    prefix = "+" if raw.startswith("+") else ""
    return f"{prefix}{'*' * max(3, len(digits) - 4)}{digits[-4:]}"


class ManagedAListClient:
    """Small admin API client for the localhost-only managed AList process."""

    CONFIG_PREFIX = "MANAGED_ALIST"
    RUNTIME_LABEL = "AList"
    USER_AGENT = "CyberStream/managed-alist"

    def __init__(self, app_config=None, session=None):
        cfg = app_config or current_app.config
        self.app_config = cfg
        prefix = self.CONFIG_PREFIX
        if not bool(cfg.get(f"{prefix}_ENABLED", False)):
            raise ManagedAListError(f"Managed {self.RUNTIME_LABEL} is disabled", code=40060)

        self.base_url = str(cfg.get(f"{prefix}_BASE_URL") or "").strip().rstrip("/")
        self.token = str(cfg.get(f"{prefix}_TOKEN") or "").strip()
        self.username = str(cfg.get(f"{prefix}_USERNAME") or "").strip()
        self.password = str(cfg.get(f"{prefix}_PASSWORD") or "").strip()
        self.timeout = float(cfg.get(f"{prefix}_TIMEOUT_SECONDS") or 30)
        self.verify_ssl = bool(cfg.get(f"{prefix}_VERIFY_SSL", False))
        self.mount_prefix = self._normalize_mount_path(cfg.get(f"{prefix}_MOUNT_PREFIX") or "/cyberstream")
        if not self.base_url:
            raise ManagedAListError(f"Managed {self.RUNTIME_LABEL} base URL is not configured", code=40060)
        if not self.token and not (self.username and self.password):
            raise ManagedAListError(f"Managed {self.RUNTIME_LABEL} credentials are not configured", code=40060)

        self.session = session or requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
        })

    @staticmethod
    def _normalize_mount_path(value):
        raw = str(value or "").replace("\\", "/").strip()
        normalized = posixpath.normpath("/" + raw.strip("/"))
        return "/" if normalized == "." else normalized

    def _url(self, path):
        return urljoin(self.base_url + "/", str(path or "").lstrip("/"))

    def _parse_response(self, response, operation):
        try:
            payload = response.json()
        except ValueError as exc:
            raise ManagedAListError(f"Managed {self.RUNTIME_LABEL} {operation} returned invalid JSON") from exc

        if response.status_code >= 400 or payload.get("code") != 200:
            message = payload.get("message") or f"HTTP {response.status_code}"
            raise ManagedAListError(
                f"Managed {self.RUNTIME_LABEL} {operation} failed: {message}",
                data=payload.get("data"),
            )
        return payload.get("data")

    def _authorization(self):
        if self.token:
            return self.token
        response = self.session.post(
            self._url("/api/auth/login"),
            json={"username": self.username, "password": self.password},
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        data = self._parse_response(response, "login") or {}
        self.token = str(data.get("token") or "").strip()
        if not self.token:
            raise ManagedAListError(f"Managed {self.RUNTIME_LABEL} login returned no token")
        return self.token

    def _headers(self):
        return {"Authorization": self._authorization()}

    def get_storage(self, storage_id):
        response = self.session.get(
            self._url("/api/admin/storage/get"),
            params={"id": int(storage_id)},
            headers=self._headers(),
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        return self._parse_response(response, "get storage") or {}

    def create_storage(self, payload):
        response = self.session.post(
            self._url("/api/admin/storage/create"),
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        return self._parse_response(response, "create storage") or {}

    def update_storage(self, payload):
        response = self.session.post(
            self._url("/api/admin/storage/update"),
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        self._parse_response(response, "update storage")

    def delete_storage(self, storage_id):
        response = self.session.post(
            self._url("/api/admin/storage/delete"),
            params={"id": int(storage_id)},
            headers=self._headers(),
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        self._parse_response(response, "delete storage")

    @staticmethod
    def _addition(storage):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("Managed storage runtime returned invalid addition") from exc
        if not isinstance(addition, dict):
            raise ManagedAListError("Managed storage runtime returned invalid addition")
        return addition

    def _new_mount_path(self):
        suffix = uuid.uuid4().hex[:12]
        return posixpath.join(self.mount_prefix, "guangyapan", suffix)

    def create_guangyapan_storage(self, phone_number, root_path="", captcha_token=""):
        mount_path = self._new_mount_path()
        addition = {
            "root_path": str(root_path or "").strip(),
            "phone_number": str(phone_number or "").strip(),
            "captcha_token": str(captcha_token or "").strip(),
            "send_code": True,
            "verify_code": "",
            "verification_id": "",
            "access_token": "",
            "refresh_token": "",
            "client_id": "aMe-8VSlkrbQXpUR",
            "device_id": "",
            "page_size": 100,
            "order_by": 3,
            "sort_type": 1,
        }
        payload = {
            "mount_path": mount_path,
            "driver": "GuangYaPan",
            "cache_expiration": 30,
            "addition": json.dumps(addition, ensure_ascii=False),
            "remark": "Managed by CyberStream",
            "disabled": False,
            "disable_index": False,
            "enable_sign": False,
            "web_proxy": False,
            "webdav_policy": "302_redirect",
            "proxy_range": False,
            "down_proxy_url": "",
            "down_proxy_sign": True,
        }
        created = None
        try:
            created = self.create_storage(payload)
        except ManagedAListError as exc:
            storage_id = (exc.data or {}).get("id") if isinstance(exc.data, dict) else None
            if storage_id is not None:
                try:
                    self.delete_storage(storage_id)
                except Exception:
                    pass
            raise
        storage_id = created.get("id")
        if storage_id is None:
            raise ManagedAListError("Managed AList did not return a storage id")
        storage = self.get_storage(storage_id)
        saved_addition = self._addition(storage)
        if not saved_addition.get("verification_id"):
            try:
                self.delete_storage(storage_id)
            except Exception:
                pass
            raise ManagedAListError("GuangYaPan SMS request did not return a verification id")
        return {
            "storage_id": int(storage_id),
            "mount_path": storage.get("mount_path") or mount_path,
            "phone_number_masked": mask_phone_number(phone_number),
            "cloud_root_path": str(root_path or "").strip() or "/",
        }

    def verify_guangyapan_storage(self, storage_id, verify_code):
        storage = self.get_storage(storage_id)
        if storage.get("driver") != "GuangYaPan":
            raise ManagedAListError("Managed AList storage is not GuangYaPan", code=40061)
        addition = self._addition(storage)
        addition["verify_code"] = str(verify_code or "").strip()
        addition["send_code"] = False
        storage["addition"] = json.dumps(addition, ensure_ascii=False)
        self.update_storage(storage)

        verified = self.get_storage(storage_id)
        verified_addition = self._addition(verified)
        if not (verified_addition.get("access_token") or verified_addition.get("refresh_token")):
            raise ManagedAListError("GuangYaPan SMS verification did not complete")
        return {
            "storage_id": int(storage_id),
            "mount_path": verified.get("mount_path") or storage.get("mount_path"),
        }


class ManagedOpenListClient(ManagedAListClient):
    """Admin API client for the localhost-only managed OpenList process."""

    CONFIG_PREFIX = "MANAGED_OPENLIST"
    RUNTIME_LABEL = "OpenList"
    USER_AGENT = "CyberStream/managed-openlist"
    DEFAULT_115_QRCODE_SOURCE = "wechatmini"
    _QR_DATA_URL_RE = re.compile(r"data:image/(?:png|jpe?g);base64,[A-Za-z0-9+/=]+")
    _QR_CONTENT_RE = re.compile(r"<a\s+[^>]*href=[\"']([^\"']+)[\"']", re.IGNORECASE)
    _PAN115_QR_TOKEN_URL = "https://qrcodeapi.115.com/api/1.0/web/1.0/token"
    _PAN115_QR_IMAGE_URL = "https://qrcodeapi.115.com/api/1.0/mac/1.0/qrcode"
    _PAN115_QR_STATUS_URL = "https://qrcodeapi.115.com/get/status/"
    _QUARK_UC_DEFINITIONS = {
        "quarktv": {
            "driver": "QuarkTV",
            "display_name": "QuarkTV",
        },
        "uctv": {
            "driver": "UCTV",
            "display_name": "UCTV",
        },
    }

    def _new_tianyicloud_mount_path(self):
        suffix = uuid.uuid4().hex[:12]
        return posixpath.join(self.mount_prefix, "tianyicloud", suffix)

    def _new_openlist_mount_path(self, source_type):
        suffix = uuid.uuid4().hex[:12]
        return posixpath.join(self.mount_prefix, source_type, suffix)

    def _config_value(self, key, default=None):
        return self.app_config.get(key, default) if hasattr(self.app_config, "get") else default

    def _tianyicloud_addition(self, storage):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("Managed OpenList returned invalid TianYiCloud addition") from exc
        if not isinstance(addition, dict):
            raise ManagedAListError("Managed OpenList returned invalid TianYiCloud addition")
        return addition

    def _extract_tianyicloud_qr(self, message):
        text = str(message or "")
        data_url_match = self._QR_DATA_URL_RE.search(text)
        if not data_url_match:
            return None
        content_match = self._QR_CONTENT_RE.search(text)
        return {
            "qr_code_data_url": data_url_match.group(0),
            "qr_content": content_match.group(1) if content_match else None,
        }

    def _extract_openlist_qr(self, message):
        return self._extract_tianyicloud_qr(message)

    @staticmethod
    def _is_tianyicloud_qr_pending(message):
        normalized = str(message or "").lower()
        pending_markers = (
            "e189accesstoken is empty",
            "need verify",
            "qrcodeloginresult",
            "qrcoderollloginfail",
            "qrcoderolllogin()",
            "not scan",
            "not scanned",
            "not login",
            "not logged",
            "pending",
        )
        return any(marker in normalized for marker in pending_markers)

    @staticmethod
    def _normalize_tianyicloud_type(cloud_type):
        normalized = str(cloud_type or "personal").strip().lower()
        if normalized not in {"personal", "family"}:
            raise ManagedAListError("Invalid TianYiCloud cloud type", code=40036)
        return normalized

    @staticmethod
    def _normalize_tianyicloud_root_id(root_folder_id, cloud_type):
        raw = str(root_folder_id or "").strip()
        if raw:
            return raw
        return "" if cloud_type == "family" else "-11"

    def _build_tianyicloud_state(self, storage_id, storage, authenticated, qr_payload=None):
        addition = self._tianyicloud_addition(storage)
        state = {
            "storage_id": int(storage_id),
            "mount_path": storage.get("mount_path"),
            "cloud_type": addition.get("type") or "personal",
            "cloud_root_path": "/",
            "authenticated": bool(authenticated),
            "auth_state": "ready" if authenticated else "qr_pending",
        }
        if qr_payload:
            state.update(qr_payload)
        return state

    @staticmethod
    def _normalize_115_root_id(root_folder_id):
        raw = str(root_folder_id or "").strip()
        return raw or "0"

    @staticmethod
    def _normalize_115_qrcode_source(qrcode_source):
        normalized = str(qrcode_source or ManagedOpenListClient.DEFAULT_115_QRCODE_SOURCE).strip().lower()
        allowed = {"web", "android", "ios", "tv", "alipaymini", "wechatmini", "qandroid"}
        if normalized not in allowed:
            raise ManagedAListError("Invalid 115 Cloud QR code source", code=40036)
        return normalized

    def _request_115_json(self, url, operation, params=None):
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
                verify=True,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ManagedAListError(f"115 Cloud {operation} request failed") from exc

        if response.status_code >= 400 or payload.get("state") != 1:
            message = payload.get("message") or payload.get("error") or f"HTTP {response.status_code}"
            raise ManagedAListError(f"115 Cloud {operation} failed: {message}")
        return payload.get("data") or {}

    def _fetch_115_qr_data_url(self, uid):
        try:
            response = self.session.get(
                self._PAN115_QR_IMAGE_URL,
                params={"uid": uid},
                timeout=self.timeout,
                verify=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagedAListError("115 Cloud QR image request failed") from exc

        content_type = (response.headers.get("Content-Type") or "image/png").split(";", 1)[0].strip()
        if not content_type.startswith("image/") or not response.content:
            raise ManagedAListError("115 Cloud QR image response is invalid")
        encoded = base64.b64encode(response.content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    def _start_115_qr_session(self):
        data = self._request_115_json(self._PAN115_QR_TOKEN_URL, "QR token")
        uid = str(data.get("uid") or "").strip()
        sign = str(data.get("sign") or "").strip()
        qrcode_content = str(data.get("qrcode") or "").strip()
        try:
            qr_time = int(data.get("time"))
        except (TypeError, ValueError):
            qr_time = None

        if not uid or not sign or not qr_time or not qrcode_content:
            raise ManagedAListError("115 Cloud QR token response is incomplete")

        return {
            "qr_uid": uid,
            "qr_sign": sign,
            "qr_time": qr_time,
            "qr_content": qrcode_content,
            "qr_code_data_url": self._fetch_115_qr_data_url(uid),
        }

    def _get_115_qr_status(self, qr_session):
        try:
            qr_time = int(qr_session.get("qr_time"))
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("115 Cloud QR session is incomplete", code=40061) from exc

        uid = str(qr_session.get("qr_uid") or "").strip()
        sign = str(qr_session.get("qr_sign") or "").strip()
        if not uid or not sign:
            raise ManagedAListError("115 Cloud QR session is incomplete", code=40061)

        data = self._request_115_json(
            self._PAN115_QR_STATUS_URL,
            "QR status",
            params={
                "uid": uid,
                "time": str(qr_time),
                "sign": sign,
                "_": str(int(time.time() * 1000)),
            },
        )
        try:
            status = int(data.get("status"))
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("115 Cloud QR status response is invalid") from exc

        if status == 0:
            return {"status": status, "auth_state": "qr_pending", "pending_reason": "waiting_for_scan"}
        if status == 1:
            return {"status": status, "auth_state": "qr_pending", "pending_reason": "waiting_for_confirm"}
        if status == 2:
            return {"status": status, "auth_state": "qr_allowed", "pending_reason": None}
        if status == -1:
            return {"status": status, "auth_state": "qr_expired", "pending_reason": "qr_expired"}
        if status == -2:
            return {"status": status, "auth_state": "qr_canceled", "pending_reason": "qr_canceled"}
        return {"status": status, "auth_state": "qr_pending", "pending_reason": "waiting_for_scan"}

    def _115_addition(self, storage):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("Managed OpenList returned invalid 115 Cloud addition") from exc
        if not isinstance(addition, dict):
            raise ManagedAListError("Managed OpenList returned invalid 115 Cloud addition")
        return addition

    @staticmethod
    def _is_115_qr_pending(message):
        normalized = str(message or "").lower()
        pending_markers = (
            "failed to login by qrcode",
            "qrcode",
            "qr code",
            "waiting",
            "not scan",
            "not scanned",
            "not login",
            "not logged",
            "pending",
        )
        return any(marker in normalized for marker in pending_markers)

    @staticmethod
    def _is_115_qr_expired(message):
        normalized = str(message or "").lower()
        return "qrcode expired" in normalized or "qr code expired" in normalized

    def _build_115_state(
        self,
        storage_id,
        storage,
        authenticated,
        qr_session=None,
        auth_state=None,
        pending_reason=None,
        qr_status=None,
    ):
        addition = self._115_addition(storage)
        state = {
            "storage_id": int(storage_id),
            "mount_path": storage.get("mount_path"),
            "cloud_root_path": "/",
            "qrcode_source": addition.get("qrcode_source") or self.DEFAULT_115_QRCODE_SOURCE,
            "authenticated": bool(authenticated),
            "auth_state": auth_state or ("ready" if authenticated else "qr_pending"),
        }
        if pending_reason:
            state["pending_reason"] = pending_reason
        if qr_status is not None:
            state["qr_status"] = qr_status
        if qr_session:
            state.update({
                "qr_uid": qr_session.get("qr_uid"),
                "qr_sign": qr_session.get("qr_sign"),
                "qr_time": qr_session.get("qr_time"),
                "qr_code_data_url": qr_session.get("qr_code_data_url"),
                "qr_content": qr_session.get("qr_content"),
            })
        return state

    @classmethod
    def _normalize_quark_uc_kind(cls, kind):
        normalized = str(kind or "").strip().lower()
        definition = cls._QUARK_UC_DEFINITIONS.get(normalized)
        if not definition:
            raise ManagedAListError("Invalid managed OpenList QR provider", code=40036)
        return normalized, definition

    @staticmethod
    def _normalize_quark_uc_root_id(root_folder_id):
        raw = str(root_folder_id or "").strip()
        return raw or "0"

    @staticmethod
    def _normalize_quark_uc_link_method(link_method):
        normalized = str(link_method or "download").strip().lower()
        if normalized not in {"download", "streaming"}:
            raise ManagedAListError("Invalid QuarkTV/UCTV link method", code=40036)
        return normalized

    def _quark_uc_addition(self, storage):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("Managed OpenList returned invalid QuarkTV/UCTV addition") from exc
        if not isinstance(addition, dict):
            raise ManagedAListError("Managed OpenList returned invalid QuarkTV/UCTV addition")
        return addition

    @staticmethod
    def _is_quark_uc_qr_pending(message):
        normalized = str(message or "").lower()
        pending_markers = (
            "need verify",
            "query_token",
            "query token",
            "code is empty",
            "empty code",
            "not scan",
            "not scanned",
            "not login",
            "not logged",
            "qrcode",
            "qr code",
            "waiting",
            "pending",
        )
        return any(marker in normalized for marker in pending_markers)

    def _build_quark_uc_state(self, kind, storage_id, storage, authenticated, qr_payload=None):
        addition = self._quark_uc_addition(storage)
        state = {
            "storage_id": int(storage_id),
            "mount_path": storage.get("mount_path"),
            "driver": storage.get("driver"),
            "kind": kind,
            "cloud_root_path": "/",
            "link_method": addition.get("link_method") or "download",
            "authenticated": bool(authenticated),
            "auth_state": "ready" if authenticated else "qr_pending",
        }
        if qr_payload:
            state.update(qr_payload)
        return state

    def create_tianyicloud_storage(self, root_folder_id="", cloud_type="personal"):
        cloud_type = self._normalize_tianyicloud_type(cloud_type)
        root_folder_id = self._normalize_tianyicloud_root_id(root_folder_id, cloud_type)
        mount_path = self._new_tianyicloud_mount_path()
        addition = {
            "root_folder_id": root_folder_id,
            "access_token": "",
            "order_by": "filename",
            "order_direction": "asc",
            "type": cloud_type,
            "family_id": "",
            "upload_thread": "3",
            "rapid_upload": False,
        }
        payload = {
            "mount_path": mount_path,
            "driver": "189CloudTV",
            "cache_expiration": 30,
            "addition": json.dumps(addition, ensure_ascii=False),
            "remark": "Managed by CyberStream",
            "disabled": False,
            "disable_index": False,
            "enable_sign": False,
            "web_proxy": False,
            "webdav_policy": "302_redirect",
            "proxy_range": False,
            "down_proxy_url": "",
            "down_proxy_sign": True,
        }

        try:
            created = self.create_storage(payload)
        except ManagedAListError as exc:
            storage_id = (exc.data or {}).get("id") if isinstance(exc.data, dict) else None
            qr_payload = self._extract_tianyicloud_qr(exc.message)
            if storage_id is not None and qr_payload:
                storage = self.get_storage(storage_id)
                return self._build_tianyicloud_state(
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    qr_payload=qr_payload,
                )
            if storage_id is not None:
                try:
                    self.delete_storage(storage_id)
                except Exception:
                    pass
            raise

        storage_id = created.get("id")
        if storage_id is None:
            raise ManagedAListError("Managed OpenList did not return a storage id")
        storage = self.get_storage(storage_id)
        addition = self._tianyicloud_addition(storage)
        if addition.get("access_token"):
            return self._build_tianyicloud_state(storage_id, storage, authenticated=True)
        qr_payload = self._extract_tianyicloud_qr(storage.get("status"))
        if qr_payload:
            return self._build_tianyicloud_state(
                storage_id=storage_id,
                storage=storage,
                authenticated=False,
                qr_payload=qr_payload,
            )
        try:
            self.delete_storage(storage_id)
        except Exception:
            pass
        raise ManagedAListError("Managed OpenList did not return a TianYiCloud QR code")

    def poll_tianyicloud_storage(self, storage_id):
        storage = self.get_storage(storage_id)
        if storage.get("driver") != "189CloudTV":
            raise ManagedAListError("Managed OpenList storage is not TianYiCloud", code=40061)

        addition = self._tianyicloud_addition(storage)
        if addition.get("access_token"):
            return self._build_tianyicloud_state(storage_id, storage, authenticated=True)
        current_qr_payload = self._extract_tianyicloud_qr(storage.get("status"))

        try:
            self.update_storage(storage)
        except ManagedAListError as exc:
            qr_payload = self._extract_tianyicloud_qr(exc.message) or current_qr_payload
            if qr_payload or self._is_tianyicloud_qr_pending(exc.message):
                state = self._build_tianyicloud_state(
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    qr_payload=qr_payload,
                )
                state["pending_reason"] = "waiting_for_scan"
                return state
            raise

        verified = self.get_storage(storage_id)
        verified_addition = self._tianyicloud_addition(verified)
        return self._build_tianyicloud_state(
            storage_id=storage_id,
            storage=verified,
            authenticated=bool(verified_addition.get("access_token")),
        )

    def create_115cloud_storage(self, root_folder_id="", qrcode_source=None):
        root_folder_id = self._normalize_115_root_id(root_folder_id)
        qrcode_source = self._normalize_115_qrcode_source(qrcode_source)
        qr_session = self._start_115_qr_session()
        mount_path = self._new_openlist_mount_path("115cloud")
        addition = {
            "cookie": "",
            "qrcode_token": qr_session["qr_uid"],
            "qrcode_source": qrcode_source,
            "page_size": 1000,
            "limit_rate": 2,
            "root_folder_id": root_folder_id,
        }
        payload = {
            "mount_path": mount_path,
            "driver": "115 Cloud",
            "cache_expiration": 30,
            "addition": json.dumps(addition, ensure_ascii=False),
            "remark": "Managed by CyberStream",
            "disabled": False,
            "disable_index": False,
            "enable_sign": False,
            "web_proxy": False,
            "webdav_policy": "302_redirect",
            "proxy_range": False,
            "down_proxy_url": "",
            "down_proxy_sign": True,
        }

        try:
            created = self.create_storage(payload)
        except ManagedAListError as exc:
            storage_id = (exc.data or {}).get("id") if isinstance(exc.data, dict) else None
            if storage_id is not None and self._is_115_qr_pending(exc.message):
                storage = self.get_storage(storage_id)
                return self._build_115_state(
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    qr_session=qr_session,
                    auth_state="qr_pending",
                    pending_reason="waiting_for_scan",
                    qr_status=0,
                )
            if storage_id is not None:
                try:
                    self.delete_storage(storage_id)
                except Exception:
                    pass
            raise

        storage_id = created.get("id")
        if storage_id is None:
            raise ManagedAListError("Managed OpenList did not return a storage id")
        storage = self.get_storage(storage_id)
        addition = self._115_addition(storage)
        return self._build_115_state(
            storage_id=storage_id,
            storage=storage,
            authenticated=bool(addition.get("cookie")),
            qr_session=None if addition.get("cookie") else qr_session,
            auth_state="ready" if addition.get("cookie") else "qr_pending",
            pending_reason=None if addition.get("cookie") else "waiting_for_scan",
            qr_status=None if addition.get("cookie") else 0,
        )

    def poll_115cloud_storage(self, storage_id, qr_session=None):
        storage = self.get_storage(storage_id)
        if storage.get("driver") != "115 Cloud":
            raise ManagedAListError("Managed OpenList storage is not 115 Cloud", code=40061)

        addition = self._115_addition(storage)
        if addition.get("cookie"):
            return self._build_115_state(storage_id, storage, authenticated=True)

        qr_status = None
        if qr_session:
            qr_status = self._get_115_qr_status(qr_session)
            if qr_status["auth_state"] in {"qr_pending", "qr_expired", "qr_canceled"}:
                return self._build_115_state(
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    auth_state=qr_status["auth_state"],
                    pending_reason=qr_status.get("pending_reason"),
                    qr_status=qr_status["status"],
                )

        try:
            self.update_storage(storage)
        except ManagedAListError as exc:
            if qr_status and qr_status.get("auth_state") == "qr_allowed":
                raise
            if self._is_115_qr_expired(exc.message):
                return self._build_115_state(
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    auth_state="qr_expired",
                    pending_reason="qr_expired",
                    qr_status=-1,
                )
            if self._is_115_qr_pending(exc.message):
                return self._build_115_state(
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    auth_state="qr_pending",
                    pending_reason="waiting_for_scan",
                    qr_status=qr_status["status"] if qr_status else None,
                )
            raise

        verified = self.get_storage(storage_id)
        verified_addition = self._115_addition(verified)
        return self._build_115_state(
            storage_id=storage_id,
            storage=verified,
            authenticated=bool(verified_addition.get("cookie")),
            auth_state="ready" if verified_addition.get("cookie") else "qr_pending",
            pending_reason=None if verified_addition.get("cookie") else "waiting_for_scan",
            qr_status=qr_status["status"] if qr_status else None,
        )

    def create_quark_uc_tv_storage(self, kind, root_folder_id="", link_method="download"):
        kind, definition = self._normalize_quark_uc_kind(kind)
        root_folder_id = self._normalize_quark_uc_root_id(root_folder_id)
        link_method = self._normalize_quark_uc_link_method(link_method)
        mount_path = self._new_openlist_mount_path(kind)
        addition = {
            "root_folder_id": root_folder_id,
            "order_by": "updated_at",
            "order_direction": "desc",
            "refresh_token": "",
            "device_id": "",
            "query_token": "",
            "link_method": link_method,
        }
        payload = {
            "mount_path": mount_path,
            "driver": definition["driver"],
            "cache_expiration": 30,
            "addition": json.dumps(addition, ensure_ascii=False),
            "remark": "Managed by CyberStream",
            "disabled": False,
            "disable_index": False,
            "enable_sign": False,
            "web_proxy": False,
            "webdav_policy": "302_redirect",
            "proxy_range": False,
            "down_proxy_url": "",
            "down_proxy_sign": True,
        }

        try:
            created = self.create_storage(payload)
        except ManagedAListError as exc:
            storage_id = (exc.data or {}).get("id") if isinstance(exc.data, dict) else None
            qr_payload = self._extract_openlist_qr(exc.message)
            if storage_id is not None and qr_payload:
                storage = self.get_storage(storage_id)
                return self._build_quark_uc_state(
                    kind=kind,
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    qr_payload=qr_payload,
                )
            if storage_id is not None:
                try:
                    self.delete_storage(storage_id)
                except Exception:
                    pass
            raise

        storage_id = created.get("id")
        if storage_id is None:
            raise ManagedAListError("Managed OpenList did not return a storage id")
        storage = self.get_storage(storage_id)
        addition = self._quark_uc_addition(storage)
        if addition.get("refresh_token"):
            return self._build_quark_uc_state(kind, storage_id, storage, authenticated=True)
        qr_payload = self._extract_openlist_qr(storage.get("status"))
        if qr_payload:
            return self._build_quark_uc_state(
                kind=kind,
                storage_id=storage_id,
                storage=storage,
                authenticated=False,
                qr_payload=qr_payload,
            )
        try:
            self.delete_storage(storage_id)
        except Exception:
            pass
        raise ManagedAListError(f"Managed OpenList did not return a {definition['display_name']} QR code")

    def poll_quark_uc_tv_storage(self, storage_id, kind):
        kind, definition = self._normalize_quark_uc_kind(kind)
        storage = self.get_storage(storage_id)
        if storage.get("driver") != definition["driver"]:
            raise ManagedAListError(
                f"Managed OpenList storage is not {definition['display_name']}",
                code=40061,
            )

        addition = self._quark_uc_addition(storage)
        if addition.get("refresh_token"):
            return self._build_quark_uc_state(kind, storage_id, storage, authenticated=True)
        current_qr_payload = self._extract_openlist_qr(storage.get("status"))

        try:
            self.update_storage(storage)
        except ManagedAListError as exc:
            qr_payload = self._extract_openlist_qr(exc.message) or current_qr_payload
            if qr_payload or self._is_quark_uc_qr_pending(exc.message):
                state = self._build_quark_uc_state(
                    kind=kind,
                    storage_id=storage_id,
                    storage=storage,
                    authenticated=False,
                    qr_payload=qr_payload,
                )
                state["pending_reason"] = "waiting_for_scan"
                return state
            raise

        verified = self.get_storage(storage_id)
        verified_addition = self._quark_uc_addition(verified)
        return self._build_quark_uc_state(
            kind=kind,
            storage_id=storage_id,
            storage=verified,
            authenticated=bool(verified_addition.get("refresh_token")),
        )
