import hashlib
import json
import logging
import posixpath
import time

import requests
from flask import has_request_context

from backend.app.services.managed_alist import ManagedAListError, ManagedOpenListClient
from backend.app.services.urls import api_url_for


logger = logging.getLogger(__name__)


class QuarkUCTranscodeError(Exception):
    def __init__(self, message, code=50290, http_status=502, data=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.data = data


QUARK_UC_STREAMING_SOURCE_TYPES = {"quarktv", "uctv"}
QUARK_UC_STREAMING_RESOLUTIONS = ("low", "normal", "high", "super", "2k", "4k")
QUARK_UC_STREAMING_RESOLUTION_LABELS = {
    "low": "LD",
    "normal": "SD",
    "high": "HD",
    "super": "FHD",
    "2k": "2K",
    "4k": "4K",
}

_COMMON_DEVICE_PARAMS = {
    "device_brand": "Xiaomi",
    "platform": "tv",
    "device_name": "M2004J7AC",
    "device_model": "M2004J7AC",
    "build_device": "M2004J7AC",
    "build_product": "M2004J7AC",
    "device_gpu": "Adreno (TM) 550",
    "activity_rect": "{}",
}

_USER_AGENT = (
    "Mozilla/5.0 (Linux; U; Android 13; zh-cn; M2004J7AC Build/UKQ1.231108.001) "
    "AppleWebKit/533.1 (KHTML, like Gecko) Mobile Safari/533.1"
)

_PROFILES = {
    "quarktv": {
        "provider": "QuarkTV",
        "api": "https://open-api-drive.quark.cn",
        "client_id": "d3194e61504e493eb6222857bccfed94",
        "sign_key": "kw2dvtd7p4t3pjl2d9ed9yc8yej8kw2d",
        "app_ver": "1.8.2.2",
        "channel": "GENERAL",
        "code_api": "http://api.extscreen.com/quarkdrive",
    },
    "uctv": {
        "provider": "UCTV",
        "api": "https://open-api-drive.uc.cn",
        "client_id": "5acf882d27b74502b7040b0c65519aa7",
        "sign_key": "l3srvtd7p42l0d0x1u8d7yc8ye9kki4d",
        "app_ver": "1.7.2.2",
        "channel": "UCTVOFFICIALWEB",
        "code_api": "http://api.extscreen.com/ucdrive",
    },
}


def normalize_quark_uc_streaming_resolution(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in QUARK_UC_STREAMING_RESOLUTIONS else None


def quark_uc_streaming_qualities_endpoint(resource):
    resource_id = getattr(resource, "id", None)
    if not resource_id:
        return None
    if has_request_context():
        return api_url_for("player.get_resource_streaming_qualities", id=resource_id)
    return f"/api/v1/resources/{resource_id}/streaming-qualities"


def quark_uc_streaming_redirect_url(resource, resolution=None):
    resource_id = getattr(resource, "id", None)
    if not resource_id:
        return None
    resolution = normalize_quark_uc_streaming_resolution(resolution)
    if has_request_context():
        if resolution:
            return api_url_for("player.stream_resource_transcoded", id=resource_id, resolution=resolution)
        return api_url_for("player.stream_resource_transcoded", id=resource_id)
    suffix = f"?resolution={resolution}" if resolution else ""
    return f"/api/v1/resources/{resource_id}/stream-transcoded{suffix}"


def build_quark_uc_cloud_transcode_playback(resource, source_type):
    source_type = str(source_type or "").strip().lower()
    supported = source_type in QUARK_UC_STREAMING_SOURCE_TYPES
    if not supported:
        return {
            "supported": False,
            "provider": None,
            "provider_name": None,
            "mode": None,
            "qualities_endpoint": None,
        "stream_endpoint": None,
        "resolution_param": "resolution",
        "available_resolutions": [],
        "recommended_for": [],
        "quality_semantics": None,
        "reason": "provider_not_supported",
    }
    profile = _PROFILES[source_type]
    return {
        "supported": True,
        "provider": source_type,
        "provider_name": profile["provider"],
        "mode": "provider_cloud_transcode",
        "qualities_endpoint": quark_uc_streaming_qualities_endpoint(resource),
        "stream_endpoint": quark_uc_streaming_redirect_url(resource),
        "resolution_param": "resolution",
        "available_resolutions": list(QUARK_UC_STREAMING_RESOLUTIONS),
        "recommended_for": ["web_player"],
        "quality_semantics": "provider_cloud_transcode_not_original_file",
        "reason": None,
    }


def build_quark_uc_streaming_qualities(resource, selected_resolution=None):
    return QuarkUCTranscodeClient().get_resource_streaming_qualities(
        resource,
        selected_resolution=selected_resolution,
    )


class QuarkUCTranscodeClient:
    def __init__(self, openlist_client=None, session=None, timeout=None):
        self.openlist_client = openlist_client or ManagedOpenListClient()
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.timeout = float(timeout or getattr(self.openlist_client, "timeout", 30) or 30)

    def get_resource_streaming_qualities(self, resource, selected_resolution=None):
        source = getattr(resource, "source", None)
        source_type = str(getattr(source, "type", "") or "").strip().lower()
        if source_type not in _PROFILES:
            raise QuarkUCTranscodeError(
                "Resource source does not support cloud transcoding",
                code=40074,
                http_status=400,
            )
        source_config = getattr(source, "config", None) or {}
        if str(source_config.get("auth_state") or "").strip().lower() != "ready":
            raise QuarkUCTranscodeError(
                f"{_PROFILES[source_type]['provider']} source is not ready",
                code=40912,
                http_status=409,
            )
        storage_id = self._storage_id(source_config, source_type)
        try:
            storage = self.openlist_client.get_storage(storage_id)
        except ManagedAListError as exc:
            raise QuarkUCTranscodeError(
                f"Managed OpenList get storage failed: {exc.message}",
                code=exc.code,
            ) from exc
        addition = self._addition(storage, source_type)
        profile = _PROFILES[source_type]
        access_token = self._refresh_access_token(profile, storage, addition)
        file_obj = self._find_resource_file(profile, addition, access_token, resource, storage)
        payload = self._request_api_json(
            profile,
            addition,
            access_token,
            "/file",
            "GET",
            params={
                "method": "streaming",
                "group_by": "source",
                "fid": file_obj["fid"],
                "resolution": ",".join(QUARK_UC_STREAMING_RESOLUTIONS),
                "support": "dolby_vision",
            },
            storage=storage,
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        items = [
            self._normalize_quality_item(resource, item)
            for item in data.get("video_info") or []
            if isinstance(item, dict)
        ]
        items = self._sort_quality_items(items)
        default_resolution = normalize_quark_uc_streaming_resolution(data.get("default_resolution"))
        selected_item = self._select_quality_item(items, selected_resolution, default_resolution)
        return {
            "resource_id": str(getattr(resource, "id", "")),
            "storage_type": source_type,
            "provider": profile["provider"],
            "mode": "provider_cloud_transcode",
            "file": {
                "path": getattr(resource, "path", None),
                "filename": getattr(resource, "filename", None),
                "fid": file_obj.get("fid"),
                "size": file_obj.get("size"),
            },
            "default_resolution": default_resolution,
            "selected_resolution": selected_item.get("resolution") if selected_item else None,
            "selected_item": selected_item,
            "items": items,
            "warnings": [] if items else [{
                "code": "no_provider_transcode_url",
                "message": "Provider returned no cloud transcoding URL",
            }],
        }

    @staticmethod
    def _storage_id(source_config, source_type):
        raw = source_config.get("openlist_storage_id")
        try:
            storage_id = int(raw)
        except (TypeError, ValueError):
            storage_id = 0
        if storage_id <= 0:
            raise QuarkUCTranscodeError(
                f"Managed {_PROFILES[source_type]['provider']} source has no OpenList storage id",
                code=40061,
                http_status=400,
            )
        return storage_id

    @staticmethod
    def _addition(storage, source_type):
        try:
            addition = json.loads(storage.get("addition") or "{}")
        except (TypeError, ValueError) as exc:
            raise QuarkUCTranscodeError(
                f"Managed {_PROFILES[source_type]['provider']} runtime returned invalid addition",
                code=50291,
            ) from exc
        if not isinstance(addition, dict):
            raise QuarkUCTranscodeError(
                f"Managed {_PROFILES[source_type]['provider']} runtime returned invalid addition",
                code=50291,
            )
        return addition

    def _save_addition(self, storage, addition):
        storage["addition"] = json.dumps(addition, ensure_ascii=False)
        self.openlist_client.update_storage(storage)

    @staticmethod
    def _device_id(addition):
        device_id = str(addition.get("device_id") or "").strip()
        if device_id:
            return device_id, False
        device_id = hashlib.md5(str(time.time()).encode("utf-8")).hexdigest()
        addition["device_id"] = device_id
        return device_id, True

    @staticmethod
    def _sign(method, pathname, sign_key, device_id):
        timestamp = str(int(time.time() * 1000))
        req_id = hashlib.md5(f"{device_id}{timestamp}".encode("utf-8")).hexdigest()
        token_data = f"{method.upper()}&{pathname}&{timestamp}&{sign_key}"
        x_pan_token = hashlib.sha256(token_data.encode("utf-8")).hexdigest()
        return timestamp, x_pan_token, req_id

    def _refresh_access_token(self, profile, storage, addition):
        refresh_token = str(addition.get("refresh_token") or "").strip()
        if not refresh_token:
            raise QuarkUCTranscodeError(
                f"{profile['provider']} source has no refresh token",
                code=40912,
                http_status=409,
            )
        device_id, changed = self._device_id(addition)
        _timestamp, _token, req_id = self._sign("POST", "/token", profile["sign_key"], device_id)
        body = {
            "req_id": req_id,
            "app_ver": profile["app_ver"],
            "device_id": device_id,
            **_COMMON_DEVICE_PARAMS,
            "channel": profile["channel"],
            "refresh_token": refresh_token,
        }
        try:
            response = self.session.post(
                f"{profile['code_api']}/token",
                json=body,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "User-Agent": _USER_AGENT,
                },
                timeout=self.timeout,
                verify=True,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise QuarkUCTranscodeError(f"{profile['provider']} token refresh request failed") from exc

        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
        if response.status_code >= 400 or payload.get("code") != 200:
            message = payload.get("message") if isinstance(payload, dict) else None
            raise QuarkUCTranscodeError(
                f"{profile['provider']} token refresh failed: {message or response.status_code}",
                code=50292,
            )
        access_token = str(data.get("access_token") or "").strip()
        next_refresh_token = str(data.get("refresh_token") or "").strip()
        if not access_token or not next_refresh_token:
            raise QuarkUCTranscodeError(
                f"{profile['provider']} token refresh response is incomplete",
                code=50292,
            )
        if next_refresh_token != refresh_token:
            addition["refresh_token"] = next_refresh_token
            changed = True
        if changed:
            try:
                self._save_addition(storage, addition)
            except ManagedAListError:
                logger.exception("%s refresh token persistence failed", profile["provider"])
        return access_token

    def _request_api_json(self, profile, addition, access_token, pathname, method, params=None, storage=None):
        payload = self._request_api_json_once(profile, addition, access_token, pathname, method, params=params)
        if not self._token_invalid(payload):
            return payload

        access_token = self._refresh_access_token(profile, storage or {}, addition)
        payload = self._request_api_json_once(profile, addition, access_token, pathname, method, params=params)
        if self._token_invalid(payload):
            raise QuarkUCTranscodeError(f"{profile['provider']} access token is invalid", code=50293)
        return payload

    def _request_api_json_once(self, profile, addition, access_token, pathname, method, params=None):
        device_id, changed = self._device_id(addition)
        if changed:
            logger.debug("%s generated device id for runtime request", profile["provider"])
        timestamp, token, req_id = self._sign(method, pathname, profile["sign_key"], device_id)
        query = {
            "req_id": req_id,
            "access_token": access_token,
            "app_ver": profile["app_ver"],
            "device_id": device_id,
            **_COMMON_DEVICE_PARAMS,
            "channel": profile["channel"],
        }
        query.update(params or {})
        try:
            response = self.session.request(
                method.upper(),
                f"{profile['api']}{pathname}",
                params=query,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": _USER_AGENT,
                    "x-pan-tm": timestamp,
                    "x-pan-token": token,
                    "x-pan-client-id": profile["client_id"],
                },
                timeout=self.timeout,
                verify=True,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise QuarkUCTranscodeError(f"{profile['provider']} API request failed") from exc
        if response.status_code >= 400:
            message = self._payload_error_message(payload) or f"HTTP {response.status_code}"
            raise QuarkUCTranscodeError(f"{profile['provider']} API request failed: {message}")
        if self._payload_has_error(payload):
            if self._token_invalid(payload):
                return payload
            message = self._payload_error_message(payload) or "provider returned an error"
            raise QuarkUCTranscodeError(f"{profile['provider']} API request failed: {message}")
        return payload

    @staticmethod
    def _payload_has_error(payload):
        if not isinstance(payload, dict):
            return True
        status = payload.get("status")
        errno = payload.get("errno")
        return bool(errno) or (isinstance(status, int) and status not in {0, 200})

    @staticmethod
    def _payload_error_message(payload):
        if not isinstance(payload, dict):
            return None
        return payload.get("error_info") or payload.get("message") or payload.get("msg")

    @classmethod
    def _token_invalid(cls, payload):
        if not isinstance(payload, dict):
            return False
        status = payload.get("status")
        errno = payload.get("errno")
        message = str(cls._payload_error_message(payload) or "").lower()
        return (
            status == -1 and errno in {10001, 11001}
        ) or (
            message
            and (
                "access token" in message
                or "access_token" in message
                or "token invalid" in message
                or "token invalid" in message
            )
        )

    @staticmethod
    def _path_segments(resource):
        raw_path = str(getattr(resource, "path", "") or "").replace("\\", "/").strip()
        normalized = posixpath.normpath("/" + raw_path.strip("/"))
        if normalized in {"/", "."}:
            return []
        return [segment for segment in normalized.strip("/").split("/") if segment and segment != "."]

    def _find_resource_file(self, profile, addition, access_token, resource, storage):
        parent_fid = str(addition.get("root_folder_id") or addition.get("root_id") or "0").strip() or "0"
        segments = self._path_segments(resource)
        if not segments:
            raise QuarkUCTranscodeError("Resource path is empty", code=40075, http_status=400)

        current = None
        for index, segment in enumerate(segments):
            items = self._list_folder(profile, addition, access_token, parent_fid, storage)
            current = next((item for item in items if item.get("filename") == segment), None)
            if not current:
                raise QuarkUCTranscodeError(
                    f"{profile['provider']} file not found: {segment}",
                    code=40404,
                    http_status=404,
                )
            if index < len(segments) - 1:
                if int(current.get("isdir") or 0) != 1:
                    raise QuarkUCTranscodeError(
                        f"{profile['provider']} path segment is not a folder: {segment}",
                        code=40404,
                        http_status=404,
                    )
                parent_fid = str(current.get("fid") or "").strip()
        if not current or not str(current.get("fid") or "").strip():
            raise QuarkUCTranscodeError(f"{profile['provider']} file id is missing", code=50294)
        return current

    def _list_folder(self, profile, addition, access_token, parent_fid, storage):
        page_size = 100
        page_index = 0
        files = []
        order_by = "1" if str(addition.get("order_by") or "").strip() == "file_name" else "3"
        desc = "0" if str(addition.get("order_direction") or "").strip() == "asc" else "1"
        while page_index < 200:
            payload = self._request_api_json(
                profile,
                addition,
                access_token,
                "/file",
                "GET",
                params={
                    "method": "list",
                    "parent_fid": str(parent_fid or "0"),
                    "order_by": order_by,
                    "desc": desc,
                    "category": "",
                    "source": "",
                    "ex_source": "",
                    "list_all": "0",
                    "page_size": str(page_size),
                    "page_index": str(page_index),
                },
                storage=storage,
            )
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            batch = [item for item in data.get("files") or [] if isinstance(item, dict)]
            files.extend(batch)
            try:
                total_count = int(data.get("total_count") or len(files))
            except (TypeError, ValueError):
                total_count = len(files)
            if not batch or len(files) >= total_count:
                break
            page_index += 1
        return files

    @staticmethod
    def _sort_quality_items(items):
        rank = {resolution: index for index, resolution in enumerate(QUARK_UC_STREAMING_RESOLUTIONS)}
        return sorted(items, key=lambda item: rank.get(item.get("resolution"), 999))

    def _normalize_quality_item(self, resource, item):
        resolution = normalize_quark_uc_streaming_resolution(item.get("resolution")) or str(item.get("resolution") or "").strip()
        accessable = item.get("accessable")
        trans_status = str(item.get("trans_status") or "").strip() or None
        url = str(item.get("url") or "").strip() or None
        available = bool(url) and (accessable in {None, "", 1, "1", True})
        dolby_vision = item.get("dolby_vision") if isinstance(item.get("dolby_vision"), dict) else None
        rank = QUARK_UC_STREAMING_RESOLUTIONS.index(resolution) if resolution in QUARK_UC_STREAMING_RESOLUTIONS else None
        return {
            "resolution": resolution,
            "label": QUARK_UC_STREAMING_RESOLUTION_LABELS.get(resolution, resolution.upper()),
            "rank": rank,
            "available": available,
            "accessable": accessable,
            "trans_status": trans_status,
            "duration": item.get("duration"),
            "size": item.get("size"),
            "format": item.get("format"),
            "width": item.get("width"),
            "height": item.get("height"),
            "bitrate": item.get("bitrate"),
            "dolby_vision": dolby_vision,
            "url": url,
            "stream_url": quark_uc_streaming_redirect_url(resource, resolution),
        }

    @staticmethod
    def _select_quality_item(items, selected_resolution, default_resolution):
        available_items = [item for item in items if item.get("available") and item.get("url")]
        if selected_resolution:
            requested = normalize_quark_uc_streaming_resolution(selected_resolution)
            if not requested:
                raise QuarkUCTranscodeError(
                    "Unsupported transcoding resolution",
                    code=40075,
                    http_status=400,
                )
            selected = next((item for item in available_items if item.get("resolution") == requested), None)
            if not selected:
                raise QuarkUCTranscodeError(
                    "Requested transcoding resolution is not available",
                    code=40913,
                    http_status=409,
                )
            return selected
        if default_resolution:
            selected = next((item for item in available_items if item.get("resolution") == default_resolution), None)
            if selected:
                return selected
        if available_items:
            return available_items[-1]
        return None
