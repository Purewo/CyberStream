import base64
import json
import logging
import posixpath
import re
import socket
import threading
import time
import uuid
from urllib.parse import urlencode, urljoin, urlparse

import requests
import urllib3.util.connection as urllib3_connection
from flask import current_app

from backend.app.providers.base import StorageProviderError


logger = logging.getLogger(__name__)


class ManagedAListError(StorageProviderError):
    def __init__(self, message, code=50260, data=None):
        super().__init__(message, code=code)
        self.data = data


_ALIYUNDRIVE_DNS_FAMILY_LOCK = threading.RLock()
_ALIYUNDRIVE_DNS_FAMILY_CACHE = {}
_ALIYUNDRIVE_DNS_FAMILY_CACHE_TTL = 300
_ALIYUNDRIVE_DNS_PROBE_TIMEOUT = 0.8


def _aliyundrive_ipv4_gai_family():
    return socket.AF_INET


def _aliyundrive_ipv6_gai_family():
    return socket.AF_INET6


def _aliyundrive_gai_family_callback(family):
    return _aliyundrive_ipv6_gai_family if family == socket.AF_INET6 else _aliyundrive_ipv4_gai_family


def _aliyundrive_cache_key(url):
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def _aliyundrive_cached_family(cache_key):
    now = time.monotonic()
    with _ALIYUNDRIVE_DNS_FAMILY_LOCK:
        cached = _ALIYUNDRIVE_DNS_FAMILY_CACHE.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]
        if cached:
            _ALIYUNDRIVE_DNS_FAMILY_CACHE.pop(cache_key, None)
    return None


def _aliyundrive_store_family(cache_key, family):
    with _ALIYUNDRIVE_DNS_FAMILY_LOCK:
        _ALIYUNDRIVE_DNS_FAMILY_CACHE[cache_key] = (
            family,
            time.monotonic() + _ALIYUNDRIVE_DNS_FAMILY_CACHE_TTL,
        )


def _aliyundrive_clear_family(cache_key, family=None):
    with _ALIYUNDRIVE_DNS_FAMILY_LOCK:
        cached = _ALIYUNDRIVE_DNS_FAMILY_CACHE.get(cache_key)
        if cached and (family is None or cached[0] == family):
            _ALIYUNDRIVE_DNS_FAMILY_CACHE.pop(cache_key, None)


def _aliyundrive_probe_family(addresses, timeout):
    last_error = None
    seen = set()
    for family, socktype, proto, _canonname, sockaddr in addresses:
        key = str(sockaddr)
        if key in seen:
            continue
        seen.add(key)
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return family
        except OSError as exc:
            last_error = exc
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    if last_error:
        raise last_error
    raise OSError("No address available for family probe")


def _aliyundrive_race_dns_families(host, port):
    try:
        addrinfos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        logger.debug("Aliyundrive DNS family probe skipped host=%s error=%s", host, exc)
        return None

    grouped = {
        socket.AF_INET: [],
        socket.AF_INET6: [],
    }
    family_order = []
    for addrinfo in addrinfos:
        family = addrinfo[0]
        if family in grouped:
            grouped[family].append(addrinfo)
            if family not in family_order:
                family_order.append(family)

    families = [family for family in family_order if grouped[family]]
    if len(families) == 1:
        return families[0]
    if not families:
        return None

    result = {}
    done = threading.Event()

    def worker(family):
        try:
            _aliyundrive_probe_family(grouped[family], _ALIYUNDRIVE_DNS_PROBE_TIMEOUT)
        except OSError as exc:
            logger.debug(
                "Aliyundrive DNS family probe failed host=%s family=%s error=%s",
                host,
                family,
                exc,
            )
            return
        if not done.is_set():
            result["family"] = family
            done.set()

    threads = [
        threading.Thread(target=worker, args=(family,), daemon=True)
        for family in families
    ]
    for thread in threads:
        thread.start()

    done.wait(_ALIYUNDRIVE_DNS_PROBE_TIMEOUT)
    for thread in threads:
        thread.join(timeout=0)
    return result.get("family")


def mask_phone_number(phone_number):
    raw = str(phone_number or "").strip()
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    prefix = "+" if raw.startswith("+") else ""
    return f"{prefix}{'*' * max(3, len(digits) - 4)}{digits[-4:]}"


def mask_account_identifier(account):
    raw = str(account or "").strip()
    if not raw:
        return ""
    if "@" in raw:
        local, domain = raw.split("@", 1)
        if not local:
            return f"***@{domain}"
        visible = local[:2] if len(local) > 2 else local[:1]
        return f"{visible}***@{domain}"
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) >= 6 and len(digits) == len(raw):
        return f"{raw[:2]}{'*' * max(1, len(raw) - 6)}{raw[-4:]}"
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}***{raw[-2:]}"


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
    _ALIYUNDRIVE_PUBLIC_API_BASE_URL = "https://api.oplist.org/alicloud"
    _ALIYUNDRIVE_QR_AUTHORIZE_URL = "https://openapi.aliyundrive.com/oauth/authorize/qrcode"
    _ALIYUNDRIVE_QR_STATUS_URL_TEMPLATE = "https://openapi.aliyundrive.com/oauth/qrcode/{sid}/status"
    _ALIYUNDRIVE_TOKEN_URL = "https://openapi.aliyundrive.com/oauth/access_token"
    _ALIYUNDRIVE_RENEW_API_URL = "https://api.oplist.org/alicloud/renewapi"
    _ALIYUNDRIVE_SCOPES = ("user:base", "file:all:read", "file:all:write")
    DEFAULT_BAIDUNETDISK_CLIENT_ID = "hq9yQ9w9kR4YHj1kyYafLygVocobh7Sf"
    DEFAULT_BAIDUNETDISK_CLIENT_SECRET = "YH2VpZcFJHYNnV6vLfHQXDBhcE7ZChyE"
    _BAIDUNETDISK_AUTHORIZE_URL = "https://openapi.baidu.com/oauth/2.0/authorize"
    _BAIDUNETDISK_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
    _BAIDUNETDISK_RENEW_API_URL = "https://api.oplist.org/baiduyun/renewapi"
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

    @staticmethod
    def _normalize_123pan_root_id(root_folder_id):
        raw = str(root_folder_id or "").strip()
        return raw or "0"

    @staticmethod
    def _normalize_123pan_platform(platform):
        raw = str(platform or "").strip()
        return raw or "web"

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
            "root_folder_id": addition.get("root_folder_id") or "",
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
            "root_folder_id": addition.get("root_folder_id") or "0",
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
            "root_folder_id": addition.get("root_folder_id") or "0",
            "link_method": addition.get("link_method") or "download",
            "authenticated": bool(authenticated),
            "auth_state": "ready" if authenticated else "qr_pending",
        }
        if qr_payload:
            state.update(qr_payload)
        return state

    def _pan123_addition(self, storage):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("Managed OpenList returned invalid 123Pan addition") from exc
        if not isinstance(addition, dict):
            raise ManagedAListError("Managed OpenList returned invalid 123Pan addition")
        return addition

    def _build_123pan_state(self, storage_id, storage, username="", root_folder_id="0", platform="web"):
        addition = self._pan123_addition(storage)
        saved_root_id = (
            addition.get("root_folder_id")
            or addition.get("RootFolderID")
            or root_folder_id
            or "0"
        )
        saved_platform = addition.get("platform") or addition.get("Platform") or platform or "web"
        return {
            "storage_id": int(storage_id),
            "mount_path": storage.get("mount_path"),
            "cloud_root_path": "/",
            "root_folder_id": str(saved_root_id),
            "platform": str(saved_platform),
            "account_name_masked": mask_account_identifier(username or addition.get("username") or addition.get("Username")),
            "authenticated": True,
            "auth_state": "ready",
        }

    @staticmethod
    def _normalize_aliyundrive_root_id(root_folder_id):
        raw = str(root_folder_id or "").strip()
        return raw or "root"

    @staticmethod
    def _normalize_aliyundrive_drive_type(drive_type):
        normalized = str(drive_type or "resource").strip().lower()
        if normalized not in {"default", "resource", "backup"}:
            raise ManagedAListError("Invalid Aliyundrive drive type", code=40036)
        return normalized

    @staticmethod
    def _normalize_aliyundrive_alipan_type(alipan_type):
        normalized = str(alipan_type or "default").strip()
        if normalized.lower() in {"", "default"}:
            return "default"
        if normalized.lower() in {"alipantv", "tv"}:
            return "alipanTV"
        raise ManagedAListError("Invalid Aliyundrive alipan type", code=40036)

    def _aliyundrive_auth_config(self, preferred_provider=None):
        mode = str(
            preferred_provider
            or self._config_value("MANAGED_OPENLIST_ALIYUNDRIVE_AUTH_MODE", "auto")
            or "auto"
        ).strip().lower()
        if mode not in {"auto", "official", "openlist", "alistgo"}:
            raise ManagedAListError("Invalid Aliyundrive auth mode", code=40036)

        client_id = str(self._config_value("MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_ID", "") or "").strip()
        client_secret = str(self._config_value("MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_SECRET", "") or "").strip()
        if mode == "official" and (not client_id or not client_secret):
            raise ManagedAListError("Aliyundrive official OAuth credentials are not configured", code=40060)

        if mode == "official" or (mode == "auto" and client_id and client_secret):
            provider = "official"
        elif mode == "alistgo":
            provider = "alistgo"
        else:
            provider = "openlist"
        public_base_url = str(
            self._config_value(
                "MANAGED_OPENLIST_ALIYUNDRIVE_PUBLIC_API_BASE_URL",
                self._ALIYUNDRIVE_PUBLIC_API_BASE_URL,
            )
            or self._ALIYUNDRIVE_PUBLIC_API_BASE_URL
        ).strip().rstrip("/")
        if provider == "openlist" and public_base_url.endswith("/alist/ali_open"):
            public_base_url = self._ALIYUNDRIVE_PUBLIC_API_BASE_URL
        return {
            "provider": provider,
            "client_id": client_id,
            "client_secret": client_secret,
            "public_api_base_url": public_base_url,
            "qr_authorize_url": str(
                self._config_value(
                    "MANAGED_OPENLIST_ALIYUNDRIVE_QR_AUTHORIZE_URL",
                    self._ALIYUNDRIVE_QR_AUTHORIZE_URL,
                )
                or self._ALIYUNDRIVE_QR_AUTHORIZE_URL
            ).strip(),
            "qr_status_url_template": str(
                self._config_value(
                    "MANAGED_OPENLIST_ALIYUNDRIVE_QR_STATUS_URL_TEMPLATE",
                    self._ALIYUNDRIVE_QR_STATUS_URL_TEMPLATE,
                )
                or self._ALIYUNDRIVE_QR_STATUS_URL_TEMPLATE
            ).strip(),
            "token_url": str(
                self._config_value("MANAGED_OPENLIST_ALIYUNDRIVE_TOKEN_URL", self._ALIYUNDRIVE_TOKEN_URL)
                or self._ALIYUNDRIVE_TOKEN_URL
            ).strip(),
            "renew_api_url": str(
                self._config_value("MANAGED_OPENLIST_ALIYUNDRIVE_RENEW_API_URL", self._ALIYUNDRIVE_RENEW_API_URL)
                or self._ALIYUNDRIVE_RENEW_API_URL
            ).strip(),
        }

    @staticmethod
    def _unwrap_aliyundrive_payload(payload):
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _aliyundrive_error_message(payload, fallback):
        if not isinstance(payload, dict):
            return fallback
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return (
            payload.get("message")
            or payload.get("msg")
            or payload.get("error_description")
            or payload.get("error")
            or payload.get("text")
            or data.get("message")
            or data.get("error_description")
            or data.get("error")
            or fallback
        )

    def _pick_aliyundrive_dns_family(self, url):
        cache_key = _aliyundrive_cache_key(url)
        if not cache_key:
            return None

        cached = _aliyundrive_cached_family(cache_key)
        if cached:
            return cached

        family = _aliyundrive_race_dns_families(*cache_key)
        if family:
            _aliyundrive_store_family(cache_key, family)
        return family

    def _clear_aliyundrive_dns_family_cache(self, url, family=None):
        cache_key = _aliyundrive_cache_key(url)
        if cache_key:
            _aliyundrive_clear_family(cache_key, family=family)

    def _session_request_aliyundrive(self, method, url, family=None, **kwargs):
        request = self.session.post if method == "post" else self.session.get
        if family not in (socket.AF_INET, socket.AF_INET6):
            return request(url, timeout=self.timeout, verify=True, **kwargs)

        with _ALIYUNDRIVE_DNS_FAMILY_LOCK:
            original_gai_family = urllib3_connection.allowed_gai_family
            urllib3_connection.allowed_gai_family = _aliyundrive_gai_family_callback(family)
            try:
                return request(url, timeout=self.timeout, verify=True, **kwargs)
            finally:
                urllib3_connection.allowed_gai_family = original_gai_family

    def _request_aliyundrive_json(self, method, url, operation, **kwargs):
        last_error = None
        for attempt in range(2):
            family = self._pick_aliyundrive_dns_family(url)
            try:
                response = self._session_request_aliyundrive(method, url, family=family, **kwargs)
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if family:
                    self._clear_aliyundrive_dns_family_cache(url, family=family)
                if attempt == 0:
                    continue
                raise ManagedAListError(f"Aliyundrive {operation} request failed") from exc
        else:
            raise ManagedAListError(f"Aliyundrive {operation} request failed") from last_error

        fallback = f"HTTP {response.status_code}"
        message = self._aliyundrive_error_message(payload, fallback)
        success_flag = payload.get("success") if isinstance(payload, dict) else None
        error_value = payload.get("error") if isinstance(payload, dict) else None
        if response.status_code >= 400 or error_value or success_flag is False:
            raise ManagedAListError(f"Aliyundrive {operation} failed: {message}")
        return self._unwrap_aliyundrive_payload(payload)

    def _start_aliyundrive_qr_session(self, auth_config):
        if auth_config["provider"] == "official":
            data = self._request_aliyundrive_json(
                "post",
                auth_config["qr_authorize_url"],
                "QR start",
                json={
                    "client_id": auth_config["client_id"],
                    "client_secret": auth_config["client_secret"],
                    "scopes": list(self._ALIYUNDRIVE_SCOPES),
                },
            )
        elif auth_config["provider"] == "openlist":
            data = self._request_aliyundrive_json(
                "get",
                f"{auth_config['public_api_base_url']}/requests",
                "QR start",
                params={
                    "server_use": "true",
                    "driver_txt": "alicloud_tv"
                    if auth_config.get("alipan_type") == "alipanTV"
                    else "alicloud_qr",
                },
            )
        else:
            data = self._request_aliyundrive_json(
                "post",
                f"{auth_config['public_api_base_url']}/qr",
                "QR start",
                json={},
            )

        sid = str(data.get("sid") or data.get("session_id") or data.get("sessionId") or "").strip()
        qr_code_url = str(
            data.get("qrCodeUrl")
            or data.get("qr_code_url")
            or data.get("qrCodeURL")
            or data.get("text")
            or ""
        ).strip()
        if not sid or not qr_code_url:
            raise ManagedAListError("Aliyundrive QR start response is incomplete")
        return {
            "qr_sid": sid,
            "qr_code_url": qr_code_url,
            "qr_code_data_url": qr_code_url,
            "qr_content": qr_code_url,
            "auth_provider": auth_config["provider"],
        }

    def _get_aliyundrive_qr_status(self, qr_sid, auth_config):
        sid = str(qr_sid or "").strip()
        if not sid:
            raise ManagedAListError("Aliyundrive QR session is incomplete", code=40061)
        if auth_config["provider"] == "alistgo":
            public_api_root = auth_config["public_api_base_url"]
            if public_api_root.endswith("/alist/ali_open"):
                public_api_root = public_api_root[: -len("/alist/ali_open")]
            status_url = f"{public_api_root.rstrip('/')}/proxy/https://open.aliyundrive.com/oauth/qrcode/{sid}/status"
        else:
            status_url = auth_config["qr_status_url_template"].format(sid=sid)
        data = self._request_aliyundrive_json("get", status_url, "QR status")
        raw_status = str(data.get("status") or data.get("qr_status") or "").strip()
        auth_code = str(data.get("authCode") or data.get("auth_code") or data.get("code") or "").strip()
        normalized = raw_status.replace("_", "").replace("-", "").replace(" ", "").lower()

        if normalized in {"loginsuccess", "confirmed", "success"}:
            if auth_config["provider"] == "openlist":
                auth_code = sid
            if not auth_code:
                raise ManagedAListError("Aliyundrive QR status response has no auth code")
            return {
                "qr_status": raw_status or "LoginSuccess",
                "auth_state": "qr_allowed",
                "auth_code": auth_code,
                "pending_reason": None,
            }
        if normalized in {"scansuccess", "scaned", "scanned", "waitconfirm", "confirming"}:
            return {
                "qr_status": raw_status,
                "auth_state": "qr_pending",
                "pending_reason": "waiting_for_confirm",
            }
        if "expire" in normalized:
            return {
                "qr_status": raw_status,
                "auth_state": "qr_expired",
                "pending_reason": "qr_expired",
            }
        if "cancel" in normalized:
            return {
                "qr_status": raw_status,
                "auth_state": "qr_canceled",
                "pending_reason": "qr_canceled",
            }
        return {
            "qr_status": raw_status or "WaitLogin",
            "auth_state": "qr_pending",
            "pending_reason": "waiting_for_scan",
        }

    def _exchange_aliyundrive_token(self, auth_code, auth_config):
        code = str(auth_code or "").strip()
        if not code:
            raise ManagedAListError("Aliyundrive auth code is empty", code=40061)

        if auth_config["provider"] == "official":
            data = self._request_aliyundrive_json(
                "post",
                auth_config["token_url"],
                "token exchange",
                json={
                    "client_id": auth_config["client_id"],
                    "client_secret": auth_config["client_secret"],
                    "grant_type": "authorization_code",
                    "code": code,
                },
            )
        elif auth_config["provider"] == "openlist":
            driver_txt = "alicloud_tv" if auth_config.get("alipan_type") == "alipanTV" else "alicloud_qr"
            data = self._request_aliyundrive_json(
                "get",
                f"{auth_config['public_api_base_url']}/callback",
                "token exchange",
                params={
                    "grant_type": "authorization_code",
                    "code": code,
                },
                headers={
                    "Cookie": f"driver_txt={driver_txt}; server_use=true",
                },
            )
        else:
            data = self._request_aliyundrive_json(
                "post",
                f"{auth_config['public_api_base_url']}/code",
                "token exchange",
                json={
                    "client_id": "",
                    "client_secret": "",
                    "grant_type": "authorization_code",
                    "code": code,
                },
            )

        refresh_token = str(data.get("refresh_token") or data.get("refreshToken") or "").strip()
        access_token = str(data.get("access_token") or data.get("accessToken") or "").strip()
        if not refresh_token:
            raise ManagedAListError("Aliyundrive token exchange response has no refresh token")
        return {
            "refresh_token": refresh_token,
            "access_token": access_token,
        }

    def _aliyundrive_addition(self, storage):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("Managed OpenList returned invalid Aliyundrive addition") from exc
        if not isinstance(addition, dict):
            raise ManagedAListError("Managed OpenList returned invalid Aliyundrive addition")
        return addition

    def _build_aliyundrive_state(
        self,
        authenticated,
        root_folder_id="root",
        drive_type="resource",
        alipan_type="default",
        storage_id=None,
        storage=None,
        qr_session=None,
        auth_state=None,
        pending_reason=None,
        qr_status=None,
        auth_provider=None,
    ):
        state = {
            "root_folder_id": root_folder_id,
            "drive_type": drive_type,
            "alipan_type": alipan_type,
            "cloud_root_path": "/",
            "authenticated": bool(authenticated),
            "auth_state": auth_state or ("ready" if authenticated else "qr_pending"),
        }
        if storage_id is not None:
            state["storage_id"] = int(storage_id)
        if storage:
            state["mount_path"] = storage.get("mount_path")
            addition = self._aliyundrive_addition(storage)
            state["drive_type"] = addition.get("drive_type") or state["drive_type"]
            state["root_folder_id"] = addition.get("root_folder_id") or state["root_folder_id"]
            state["alipan_type"] = addition.get("alipan_type") or state["alipan_type"]
        if qr_session:
            state.update({
                "qr_sid": qr_session.get("qr_sid"),
                "qr_code_url": qr_session.get("qr_code_url"),
                "qr_code_data_url": qr_session.get("qr_code_data_url"),
                "qr_content": qr_session.get("qr_content"),
                "auth_provider": qr_session.get("auth_provider") or auth_provider,
            })
        elif auth_provider:
            state["auth_provider"] = auth_provider
        if pending_reason:
            state["pending_reason"] = pending_reason
        if qr_status is not None:
            state["qr_status"] = qr_status
        return state

    def start_aliyundrive_qr(self, root_folder_id="", drive_type="resource", alipan_type="default"):
        root_folder_id = self._normalize_aliyundrive_root_id(root_folder_id)
        drive_type = self._normalize_aliyundrive_drive_type(drive_type)
        alipan_type = self._normalize_aliyundrive_alipan_type(alipan_type)
        auth_config = self._aliyundrive_auth_config()
        auth_config["alipan_type"] = alipan_type
        qr_session = self._start_aliyundrive_qr_session(auth_config)
        return self._build_aliyundrive_state(
            authenticated=False,
            root_folder_id=root_folder_id,
            drive_type=drive_type,
            alipan_type=alipan_type,
            qr_session=qr_session,
            pending_reason="waiting_for_scan",
            qr_status="WaitLogin",
            auth_provider=auth_config["provider"],
        )

    def _create_aliyundrive_openlist_storage(self, refresh_token, root_folder_id, drive_type, alipan_type, auth_config):
        mount_path = self._new_openlist_mount_path("aliyundrive")
        has_official_credentials = (
            auth_config["provider"] == "official"
            and bool(auth_config.get("client_id"))
            and bool(auth_config.get("client_secret"))
        )
        addition = {
            "drive_type": drive_type,
            "root_folder_id": root_folder_id,
            "refresh_token": str(refresh_token or "").strip(),
            "order_by": "name",
            "order_direction": "ASC",
            "use_online_api": not has_official_credentials,
            "alipan_type": alipan_type,
            "api_url_address": auth_config["renew_api_url"],
            "client_id": auth_config["client_id"] if has_official_credentials else "",
            "client_secret": auth_config["client_secret"] if has_official_credentials else "",
            "remove_way": "trash",
            "rapid_upload": False,
            "internal_upload": False,
            "livp_download_format": "jpeg",
        }
        payload = {
            "mount_path": mount_path,
            "driver": "AliyundriveOpen",
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
        if storage.get("driver") != "AliyundriveOpen":
            try:
                self.delete_storage(storage_id)
            except Exception:
                pass
            raise ManagedAListError("Managed OpenList storage is not Aliyundrive", code=40061)
        addition = self._aliyundrive_addition(storage)
        if not addition.get("refresh_token"):
            try:
                self.delete_storage(storage_id)
            except Exception:
                pass
            raise ManagedAListError("Managed OpenList did not save Aliyundrive refresh token")
        return self._build_aliyundrive_state(
            authenticated=True,
            storage_id=storage_id,
            storage=storage,
            root_folder_id=root_folder_id,
            drive_type=drive_type,
            alipan_type=alipan_type,
        )

    def poll_aliyundrive_storage(
        self,
        qr_sid,
        root_folder_id="",
        drive_type="resource",
        alipan_type="default",
        auth_provider=None,
    ):
        root_folder_id = self._normalize_aliyundrive_root_id(root_folder_id)
        drive_type = self._normalize_aliyundrive_drive_type(drive_type)
        alipan_type = self._normalize_aliyundrive_alipan_type(alipan_type)
        auth_config = self._aliyundrive_auth_config(auth_provider)
        auth_config["alipan_type"] = alipan_type
        qr_status = self._get_aliyundrive_qr_status(qr_sid, auth_config)
        if qr_status["auth_state"] != "qr_allowed":
            return self._build_aliyundrive_state(
                authenticated=False,
                root_folder_id=root_folder_id,
                drive_type=drive_type,
                alipan_type=alipan_type,
                auth_state=qr_status["auth_state"],
                pending_reason=qr_status.get("pending_reason"),
                qr_status=qr_status.get("qr_status"),
                auth_provider=auth_config["provider"],
            )

        token_state = self._exchange_aliyundrive_token(qr_status["auth_code"], auth_config)
        ready_state = self._create_aliyundrive_openlist_storage(
            refresh_token=token_state["refresh_token"],
            root_folder_id=root_folder_id,
            drive_type=drive_type,
            alipan_type=alipan_type,
            auth_config=auth_config,
        )
        ready_state["qr_status"] = qr_status.get("qr_status")
        return ready_state

    @staticmethod
    def _normalize_baidunetdisk_root_path(root_path):
        raw = str(root_path or "").replace("\\", "/").strip()
        if not raw or raw == "/":
            return "/"
        return "/" + raw.strip("/")

    @staticmethod
    def _normalize_baidunetdisk_download_api(download_api):
        normalized = str(download_api or "official").strip().lower()
        if normalized not in {"official", "crack", "crack_video"}:
            raise ManagedAListError("Invalid Baidu Netdisk download API", code=40036)
        return normalized

    def _baidunetdisk_oauth_config(self):
        configured_client_id = str(self._config_value("MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_ID", "") or "").strip()
        configured_client_secret = str(self._config_value("MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_SECRET", "") or "").strip()
        uses_builtin_public_client = not configured_client_id and not configured_client_secret
        client_id = configured_client_id or self.DEFAULT_BAIDUNETDISK_CLIENT_ID
        client_secret = configured_client_secret or self.DEFAULT_BAIDUNETDISK_CLIENT_SECRET
        if (configured_client_id and not configured_client_secret) or (configured_client_secret and not configured_client_id):
            raise ManagedAListError("Baidu Netdisk OAuth credentials are incomplete", code=40060)
        if not client_id or not client_secret:
            raise ManagedAListError("Baidu Netdisk OAuth credentials are not configured", code=40060)
        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "callback_mode": "oob" if uses_builtin_public_client else "redirect",
            "authorize_url": str(
                self._config_value("MANAGED_OPENLIST_BAIDUNETDISK_AUTHORIZE_URL", self._BAIDUNETDISK_AUTHORIZE_URL)
                or self._BAIDUNETDISK_AUTHORIZE_URL
            ).strip(),
            "token_url": str(
                self._config_value("MANAGED_OPENLIST_BAIDUNETDISK_TOKEN_URL", self._BAIDUNETDISK_TOKEN_URL)
                or self._BAIDUNETDISK_TOKEN_URL
            ).strip(),
            "renew_api_url": str(
                self._config_value("MANAGED_OPENLIST_BAIDUNETDISK_RENEW_API_URL", self._BAIDUNETDISK_RENEW_API_URL)
                or self._BAIDUNETDISK_RENEW_API_URL
            ).strip(),
        }

    @staticmethod
    def _baidunetdisk_error_message(payload, fallback):
        if not isinstance(payload, dict):
            return fallback
        return (
            payload.get("error_description")
            or payload.get("errmsg")
            or payload.get("error")
            or payload.get("message")
            or fallback
        )

    def _request_baidunetdisk_json(self, url, operation, params=None):
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
                verify=True,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ManagedAListError(f"Baidu Netdisk {operation} request failed") from exc

        if response.status_code >= 400 or payload.get("error"):
            message = self._baidunetdisk_error_message(payload, f"HTTP {response.status_code}")
            raise ManagedAListError(f"Baidu Netdisk {operation} failed: {message}")
        return payload if isinstance(payload, dict) else {}

    def start_baidunetdisk_oauth(self, redirect_uri, root_path="/", download_api="official"):
        root_path = self._normalize_baidunetdisk_root_path(root_path)
        download_api = self._normalize_baidunetdisk_download_api(download_api)
        auth_config = self._baidunetdisk_oauth_config()
        oauth_state = uuid.uuid4().hex + uuid.uuid4().hex
        callback_mode = auth_config["callback_mode"]
        oauth_redirect_uri = "oob" if callback_mode == "oob" else str(redirect_uri or "").strip()
        query = urlencode({
            "client_id": auth_config["client_id"],
            "response_type": "code",
            "redirect_uri": oauth_redirect_uri,
            "scope": "basic,netdisk",
            "state": oauth_state,
            "qrcode": "1",
        })
        return {
            "authenticated": False,
            "auth_state": "oauth_pending",
            "pending_reason": "waiting_for_authorization",
            "authorization_url": f"{auth_config['authorize_url']}?{query}",
            "oauth_state": oauth_state,
            "oauth_callback_mode": callback_mode,
            "oauth_redirect_uri": oauth_redirect_uri,
            "callback_mode": callback_mode,
            "requires_authorization_code": callback_mode == "oob",
            "cloud_root_path": root_path,
            "root_folder_path": root_path,
            "download_api": download_api,
        }

    def _exchange_baidunetdisk_token(self, code, redirect_uri, auth_config):
        auth_code = str(code or "").strip()
        if not auth_code:
            raise ManagedAListError("Baidu Netdisk authorization code is empty", code=40061)
        data = self._request_baidunetdisk_json(
            auth_config["token_url"],
            "token exchange",
            params={
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": auth_config["client_id"],
                "client_secret": auth_config["client_secret"],
                "redirect_uri": str(redirect_uri or "").strip(),
            },
        )
        access_token = str(data.get("access_token") or "").strip()
        refresh_token = str(data.get("refresh_token") or "").strip()
        if not access_token or not refresh_token:
            raise ManagedAListError("Baidu Netdisk token exchange response is incomplete")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": data.get("expires_in"),
        }

    def _baidunetdisk_addition(self, storage):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise ManagedAListError("Managed OpenList returned invalid Baidu Netdisk addition") from exc
        if not isinstance(addition, dict):
            raise ManagedAListError("Managed OpenList returned invalid Baidu Netdisk addition")
        return addition

    def _build_baidunetdisk_state(
        self,
        authenticated,
        root_path="/",
        download_api="official",
        storage_id=None,
        storage=None,
        auth_state=None,
        pending_reason=None,
    ):
        state = {
            "cloud_root_path": root_path,
            "root_folder_path": root_path,
            "download_api": download_api,
            "authenticated": bool(authenticated),
            "auth_state": auth_state or ("ready" if authenticated else "oauth_pending"),
        }
        if storage_id is not None:
            state["storage_id"] = int(storage_id)
        if storage:
            state["mount_path"] = storage.get("mount_path")
            addition = self._baidunetdisk_addition(storage)
            state["root_folder_path"] = addition.get("root_folder_path") or state["root_folder_path"]
            state["cloud_root_path"] = addition.get("root_folder_path") or state["cloud_root_path"]
            state["download_api"] = addition.get("download_api") or state["download_api"]
        if pending_reason:
            state["pending_reason"] = pending_reason
        return state

    def _create_baidunetdisk_openlist_storage(self, token_state, root_path, download_api, auth_config):
        mount_path = self._new_openlist_mount_path("baidunetdisk")
        addition = {
            "root_folder_path": root_path,
            "order_by": "name",
            "order_direction": "asc",
            "download_api": download_api,
            "use_online_api": False,
            "api_url_address": auth_config["renew_api_url"],
            "client_id": auth_config["client_id"],
            "client_secret": auth_config["client_secret"],
            "custom_crack_ua": "netdisk",
            "access_token": token_state["access_token"],
            "refresh_token": token_state["refresh_token"],
            "upload_thread": "3",
            "upload_timeout": 60,
            "upload_api": "https://d.pcs.baidu.com",
            "use_dynamic_upload_api": True,
            "custom_upload_part_size": 0,
            "low_bandwith_upload_mode": False,
            "only_list_video_file": False,
        }
        payload = {
            "mount_path": mount_path,
            "driver": "BaiduNetdisk",
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
        if storage.get("driver") != "BaiduNetdisk":
            try:
                self.delete_storage(storage_id)
            except Exception:
                pass
            raise ManagedAListError("Managed OpenList storage is not Baidu Netdisk", code=40061)
        addition = self._baidunetdisk_addition(storage)
        if not addition.get("refresh_token"):
            try:
                self.delete_storage(storage_id)
            except Exception:
                pass
            raise ManagedAListError("Managed OpenList did not save Baidu Netdisk refresh token")
        return self._build_baidunetdisk_state(
            authenticated=True,
            storage_id=storage_id,
            storage=storage,
            root_path=root_path,
            download_api=download_api,
        )

    def complete_baidunetdisk_oauth(self, code, redirect_uri, root_path="/", download_api="official"):
        root_path = self._normalize_baidunetdisk_root_path(root_path)
        download_api = self._normalize_baidunetdisk_download_api(download_api)
        auth_config = self._baidunetdisk_oauth_config()
        token_state = self._exchange_baidunetdisk_token(code, redirect_uri, auth_config)
        return self._create_baidunetdisk_openlist_storage(
            token_state=token_state,
            root_path=root_path,
            download_api=download_api,
            auth_config=auth_config,
        )

    def create_123pan_storage(self, username, password, root_folder_id="", platform="web"):
        username = str(username or "").strip()
        password = str(password or "")
        if not username:
            raise ManagedAListError("Missing required field: username", code=40001)
        if not password:
            raise ManagedAListError("Missing required field: password", code=40001)

        root_folder_id = self._normalize_123pan_root_id(root_folder_id)
        platform = self._normalize_123pan_platform(platform)
        mount_path = self._new_openlist_mount_path("123pan")
        addition = {
            "username": username,
            "password": password,
            "root_folder_id": root_folder_id,
            "access_token": "",
            "UploadThread": 3,
            "platform": platform,
        }
        payload = {
            "mount_path": mount_path,
            "driver": "123Pan",
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
        if storage.get("driver") != "123Pan":
            try:
                self.delete_storage(storage_id)
            except Exception:
                pass
            raise ManagedAListError("Managed OpenList storage is not 123Pan", code=40061)
        return self._build_123pan_state(
            storage_id=storage_id,
            storage=storage,
            username=username,
            root_folder_id=root_folder_id,
            platform=platform,
        )

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
