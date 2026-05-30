import posixpath
from collections import Counter
from urllib.parse import urlencode

from flask import has_request_context

from backend.app.services.managed_alist import ManagedAListError, ManagedOpenListClient
from backend.app.services.quark_uc_transcode import (
    QUARK_UC_STREAMING_SOURCE_TYPES,
    QuarkUCTranscodeError,
    build_quark_uc_cloud_transcode_playback,
    build_quark_uc_streaming_qualities,
)
from backend.app.services.urls import api_url_for


class CloudTranscodeError(Exception):
    def __init__(self, message, code=50290, http_status=502, data=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.data = data


ALIYUNDRIVE_STREAMING_SOURCE_TYPES = {"aliyundrive"}
ALIYUNDRIVE_STREAMING_RESOLUTIONS = ("ld", "sd", "hd", "fhd", "qhd", "4k")
ALIYUNDRIVE_STREAMING_RESOLUTION_LABELS = {
    "ld": "LD",
    "sd": "SD",
    "hd": "HD",
    "fhd": "FHD",
    "qhd": "QHD",
    "4k": "4K",
}


def cloud_transcode_qualities_endpoint(resource):
    resource_id = getattr(resource, "id", None)
    if not resource_id:
        return None
    if has_request_context():
        return api_url_for("player.get_resource_streaming_qualities", id=resource_id)
    return f"/api/v1/resources/{resource_id}/streaming-qualities"


def cloud_transcode_stream_url(resource, resolution=None):
    resource_id = getattr(resource, "id", None)
    if not resource_id:
        return None
    if has_request_context():
        if resolution:
            return api_url_for("player.stream_resource_transcoded", id=resource_id, resolution=resolution)
        return api_url_for("player.stream_resource_transcoded", id=resource_id)
    suffix = f"?{urlencode({'resolution': resolution})}" if resolution else ""
    return f"/api/v1/resources/{resource_id}/stream-transcoded{suffix}"


def unsupported_cloud_transcode_playback():
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


def build_aliyundrive_cloud_transcode_playback(resource, source_type):
    source_type = str(source_type or "").strip().lower()
    if source_type not in ALIYUNDRIVE_STREAMING_SOURCE_TYPES:
        return unsupported_cloud_transcode_playback()
    return {
        "supported": True,
        "provider": source_type,
        "provider_name": "Aliyundrive",
        "mode": "provider_cloud_transcode",
        "qualities_endpoint": cloud_transcode_qualities_endpoint(resource),
        "stream_endpoint": cloud_transcode_stream_url(resource),
        "resolution_param": "resolution",
        "available_resolutions": list(ALIYUNDRIVE_STREAMING_RESOLUTIONS),
        "recommended_for": ["web_player"],
        "quality_semantics": "provider_cloud_transcode_not_original_file",
        "reason": None,
    }


def build_cloud_transcode_playback(resource, source_type):
    normalized = str(source_type or "").strip().lower()
    if normalized in QUARK_UC_STREAMING_SOURCE_TYPES:
        return build_quark_uc_cloud_transcode_playback(resource, normalized)
    if normalized in ALIYUNDRIVE_STREAMING_SOURCE_TYPES:
        return build_aliyundrive_cloud_transcode_playback(resource, normalized)
    return unsupported_cloud_transcode_playback()


def build_streaming_qualities(resource, selected_resolution=None):
    source = getattr(resource, "source", None)
    source_type = str(getattr(source, "type", "") or "").strip().lower()
    if source_type in QUARK_UC_STREAMING_SOURCE_TYPES:
        try:
            return build_quark_uc_streaming_qualities(resource, selected_resolution=selected_resolution)
        except QuarkUCTranscodeError as exc:
            raise CloudTranscodeError(
                exc.message,
                code=exc.code,
                http_status=exc.http_status,
                data=exc.data,
            ) from exc
    if source_type in ALIYUNDRIVE_STREAMING_SOURCE_TYPES:
        return AliyundriveCloudTranscodeClient().get_resource_streaming_qualities(
            resource,
            selected_resolution=selected_resolution,
        )
    raise CloudTranscodeError(
        "Resource source does not support cloud transcoding",
        code=40074,
        http_status=400,
    )


class AliyundriveCloudTranscodeClient:
    def __init__(self, openlist_client=None):
        self.openlist_client = openlist_client or ManagedOpenListClient()

    def get_resource_streaming_qualities(self, resource, selected_resolution=None):
        source = getattr(resource, "source", None)
        source_config = getattr(source, "config", None) or {}
        if str(source_config.get("auth_state") or "").strip().lower() != "ready":
            raise CloudTranscodeError(
                "Aliyundrive source is not ready",
                code=40912,
                http_status=409,
            )
        path = self._resource_openlist_path(source_config, resource)
        try:
            payload = self.openlist_client.fs_other(path, "video_preview")
        except ManagedAListError as exc:
            raise CloudTranscodeError(
                f"Managed OpenList Aliyundrive video preview failed: {exc.message}",
                code=exc.code,
            ) from exc

        task_list = self._find_live_transcoding_task_list(payload)
        items = self._dedupe_resolution_keys([
            self._normalize_quality_item(resource, item)
            for item in task_list
            if isinstance(item, dict)
        ])
        items = self._sort_quality_items(items)
        selected_item = self._select_quality_item(items, selected_resolution)
        default_resolution = selected_item.get("resolution") if selected_item else None
        return {
            "resource_id": str(getattr(resource, "id", "")),
            "storage_type": "aliyundrive",
            "provider": "Aliyundrive",
            "mode": "provider_cloud_transcode",
            "file": {
                "path": getattr(resource, "path", None),
                "filename": getattr(resource, "filename", None),
            },
            "default_resolution": default_resolution,
            "selected_resolution": default_resolution,
            "selected_item": selected_item,
            "items": items,
            "warnings": [] if items else [{
                "code": "no_provider_transcode_url",
                "message": "Provider returned no cloud transcoding URL",
            }],
        }

    @staticmethod
    def _resource_openlist_path(source_config, resource):
        mount_path = str(source_config.get("mount_path") or "").replace("\\", "/").strip()
        if not mount_path:
            raise CloudTranscodeError(
                "Managed Aliyundrive source has no OpenList mount path",
                code=40061,
                http_status=400,
            )
        resource_path = str(getattr(resource, "path", "") or "").replace("\\", "/").strip()
        if not resource_path:
            raise CloudTranscodeError("Resource path is empty", code=40075, http_status=400)
        return posixpath.normpath(
            "/" + posixpath.join(mount_path.strip("/"), resource_path.strip("/"))
        )

    @classmethod
    def _find_live_transcoding_task_list(cls, payload):
        found = cls._find_dict_with_key(payload, "live_transcoding_task_list")
        if not found:
            return []
        task_list = found.get("live_transcoding_task_list")
        return task_list if isinstance(task_list, list) else []

    @classmethod
    def _find_dict_with_key(cls, value, key):
        if isinstance(value, dict):
            if key in value:
                return value
            for child in value.values():
                found = cls._find_dict_with_key(child, key)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_dict_with_key(child, key)
                if found:
                    return found
        return None

    @staticmethod
    def _first(item, *keys):
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _resolution_slot(cls, item):
        template_id = str(cls._first(item, "template_id", "templateId") or "").strip().lower()
        template_name = str(cls._first(item, "template_name", "templateName", "resolution") or "").strip().lower()
        tokens = f"{template_id} {template_name}"
        height = cls._to_int(cls._first(item, "height", "template_height", "templateHeight"))
        if "4k" in tokens or "2160" in tokens or height >= 2160:
            return "4k"
        if "qhd" in tokens or "1440" in tokens or "2k" in tokens or height >= 1440:
            return "qhd"
        if "fhd" in tokens or "1080" in tokens or height >= 1080:
            return "fhd"
        if "hd" in tokens or "720" in tokens or height >= 720:
            return "hd"
        if "sd" in tokens or "480" in tokens or height >= 480:
            return "sd"
        if "ld" in tokens or "360" in tokens or height > 0:
            return "ld"
        return template_id or template_name

    @staticmethod
    def _to_int(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _dedupe_resolution_keys(cls, items):
        counts = Counter(item.get("_slot") for item in items if item.get("_slot"))
        normalized = []
        for item in items:
            slot = item.pop("_slot", None)
            provider_template_id = str(item.get("provider_template_id") or "").strip()
            if slot and counts.get(slot, 0) == 1:
                item["resolution"] = slot
            elif provider_template_id:
                item["resolution"] = provider_template_id.lower()
            else:
                item["resolution"] = slot or "unknown"
            item["stream_url"] = cloud_transcode_stream_url(item.pop("_resource"), item["resolution"])
            normalized.append(item)
        return normalized

    @classmethod
    def _normalize_quality_item(cls, resource, item):
        slot = cls._resolution_slot(item)
        template_id = str(cls._first(item, "template_id", "templateId") or slot or "").strip()
        provider_label = str(cls._first(item, "template_name", "templateName", "resolution") or "").strip()
        status = str(cls._first(item, "status", "transcode_status", "transcodeStatus") or "").strip()
        url = str(cls._first(item, "url", "preview_url", "previewUrl", "play_url", "playUrl") or "").strip() or None
        unavailable_statuses = {"failed", "error", "running", "processing", "pending"}
        available = bool(url) and status.lower() not in unavailable_statuses
        return {
            "_resource": resource,
            "_slot": slot,
            "label": provider_label or ALIYUNDRIVE_STREAMING_RESOLUTION_LABELS.get(slot, slot.upper()),
            "rank": ALIYUNDRIVE_STREAMING_RESOLUTIONS.index(slot)
            if slot in ALIYUNDRIVE_STREAMING_RESOLUTIONS
            else None,
            "available": available,
            "trans_status": status or None,
            "provider_template_id": template_id,
            "provider_label": provider_label or None,
            "duration": cls._first(item, "duration", "video_duration", "videoDuration"),
            "size": cls._first(item, "size", "template_size", "templateSize"),
            "format": cls._first(item, "format", "container"),
            "width": cls._first(item, "width", "template_width", "templateWidth"),
            "height": cls._first(item, "height", "template_height", "templateHeight"),
            "bitrate": cls._first(item, "bitrate", "bit_rate", "bitRate"),
            "url": url,
        }

    @staticmethod
    def _sort_quality_items(items):
        rank = {resolution: index for index, resolution in enumerate(ALIYUNDRIVE_STREAMING_RESOLUTIONS)}
        return sorted(items, key=lambda item: (
            rank.get(item.get("resolution"), 999),
            str(item.get("provider_template_id") or ""),
        ))

    @staticmethod
    def _select_quality_item(items, selected_resolution):
        available_items = [item for item in items if item.get("available") and item.get("url")]
        if selected_resolution:
            requested = str(selected_resolution or "").strip().lower()
            selected = next((
                item for item in available_items
                if requested in {
                    str(item.get("resolution") or "").lower(),
                    str(item.get("provider_template_id") or "").lower(),
                    str(item.get("label") or "").lower(),
                }
            ), None)
            if not selected:
                raise CloudTranscodeError(
                    "Requested transcoding resolution is not available",
                    code=40913,
                    http_status=409,
                )
            return selected
        if available_items:
            return available_items[-1]
        return None
