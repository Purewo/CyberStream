from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from flask import current_app, has_app_context

from backend import config


logger = logging.getLogger(__name__)


class SuperCDNAssetError(Exception):
    def __init__(self, message, *, code="supercdn_asset_error", response_status=None):
        super().__init__(message)
        self.code = code
        self.response_status = response_status


def _config_value(name: str, default=None):
    if has_app_context():
        return current_app.config.get(name, default)
    return getattr(config, name, default)


def _truthy(value) -> bool:
    if value is True:
        return True
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def supercdn_assets_enabled() -> bool:
    provider = str(_config_value("CDN_PROVIDER", "none") or "").strip().lower()
    return provider == "supercdn" or _truthy(_config_value("SUPERCDN_ENABLED", False))


def supercdn_serve_asset_urls_enabled() -> bool:
    return _truthy(_config_value("SUPERCDN_SERVE_ASSET_URLS", True))


def supercdn_auto_upload_images_enabled() -> bool:
    return supercdn_assets_enabled() and _truthy(_config_value("SUPERCDN_AUTO_UPLOAD_IMAGES", True))


def supercdn_auto_upload_subtitles_enabled() -> bool:
    return supercdn_assets_enabled() and _truthy(_config_value("SUPERCDN_AUTO_UPLOAD_SUBTITLES", True))


class SuperCDNClient:
    def __init__(self):
        self.base_url = str(_config_value("SUPERCDN_URL", "") or "").strip().rstrip("/")
        self.token = str(_config_value("SUPERCDN_TOKEN", "") or "").strip()
        self.timeout = float(_config_value("SUPERCDN_TIMEOUT_SECONDS", 20) or 20)
        self.bucket = str(_config_value("SUPERCDN_BUCKET", "") or "").strip()
        self.route_profile = str(_config_value("SUPERCDN_ROUTE_PROFILE", "china_all") or "china_all").strip()

        if not self.base_url:
            raise SuperCDNAssetError("SUPERCDN_URL is not configured", code="supercdn_url_missing")
        if not self.token:
            raise SuperCDNAssetError("SUPERCDN_TOKEN is not configured", code="supercdn_token_missing")
        if not self.bucket:
            raise SuperCDNAssetError("SUPERCDN_BUCKET is not configured", code="supercdn_bucket_missing")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _api_url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        merged_headers = {**self._headers(), **headers}
        response = requests.request(
            method,
            self._api_url(path),
            headers=merged_headers,
            timeout=self.timeout,
            **kwargs,
        )
        if response.status_code >= 400:
            raise SuperCDNAssetError(
                _response_error_message(response),
                code="supercdn_request_failed",
                response_status=response.status_code,
            )
        if not response.content:
            return {}
        return response.json()

    def get_bucket(self, bucket: str | None = None):
        slug = bucket or self.bucket
        response = requests.get(
            self._api_url(f"/api/v1/asset-buckets/{slug}"),
            headers=self._headers(),
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise SuperCDNAssetError(
                _response_error_message(response),
                code="supercdn_bucket_lookup_failed",
                response_status=response.status_code,
            )
        return response.json()

    def create_bucket(self, bucket: str | None = None):
        slug = bucket or self.bucket
        payload = {
            "slug": slug,
            "name": str(_config_value("SUPERCDN_BUCKET_NAME", slug) or slug),
            "description": str(_config_value("SUPERCDN_BUCKET_DESCRIPTION", "") or ""),
            "route_profile": self.route_profile,
            "allowed_types": _split_csv(_config_value("SUPERCDN_BUCKET_ALLOWED_TYPES", "image,document")),
            "max_capacity_bytes": 0,
            "max_file_size_bytes": int(_config_value("SUPERCDN_MAX_FILE_SIZE_BYTES", 100 * 1024 * 1024) or 0),
            "default_cache_control": str(
                _config_value("SUPERCDN_BUCKET_CACHE_CONTROL", "public, max-age=86400") or ""
            ),
        }
        try:
            return self._request("POST", "/api/v1/asset-buckets", json=payload)
        except SuperCDNAssetError as exc:
            if exc.response_status == 400:
                existing = self.get_bucket(slug)
                if existing:
                    return existing
            raise

    def ensure_bucket(self):
        if not _truthy(_config_value("SUPERCDN_AUTO_CREATE_BUCKET", True)):
            return self.get_bucket(self.bucket)
        existing = self.get_bucket(self.bucket)
        if existing:
            return existing
        return self.create_bucket(self.bucket)

    def upload_file(self, *, file_path: Path, logical_path: str, asset_type: str, cache_control: str | None = None):
        self.ensure_bucket()
        path = Path(file_path)
        fields = {
            "path": logical_path,
            "asset_type": asset_type,
            "cache_control": cache_control or str(
                _config_value("SUPERCDN_BUCKET_CACHE_CONTROL", "public, max-age=86400") or ""
            ),
        }
        with open(path, "rb") as fh:
            files = {"file": (path.name, fh)}
            return self._request(
                "POST",
                f"/api/v1/asset-buckets/{self.bucket}/objects",
                data=fields,
                files=files,
            )

    def warmup(self, logical_path: str):
        if not _truthy(_config_value("SUPERCDN_WARMUP_AFTER_UPLOAD", False)):
            return None
        method = str(_config_value("SUPERCDN_WARMUP_METHOD", "HEAD") or "HEAD").strip().upper()
        payload = {"path": logical_path, "method": method}
        return self._request("POST", f"/api/v1/asset-buckets/{self.bucket}/warmup", json=payload)


def upload_file_to_supercdn(
    file_path,
    *,
    logical_path: str,
    asset_type: str,
    cache_control: str | None = None,
    enabled: bool | None = None,
) -> dict:
    path = Path(file_path)
    record = {
        "provider": "supercdn",
        "enabled": supercdn_assets_enabled() if enabled is None else bool(enabled),
        "status": "skipped",
        "reason": None,
        "bucket": str(_config_value("SUPERCDN_BUCKET", "") or ""),
        "route_profile": str(_config_value("SUPERCDN_ROUTE_PROFILE", "china_all") or "china_all"),
        "asset_type": asset_type,
        "logical_path": logical_path,
        "cache_control": cache_control or str(_config_value("SUPERCDN_BUCKET_CACHE_CONTROL", "") or ""),
        "size": None,
        "sha256": None,
        "url": None,
        "public_url": None,
        "cdn_url": None,
        "storage_url": None,
        "urls": [],
        "uploaded_at": None,
        "warmup": None,
        "error": None,
    }

    if not record["enabled"]:
        record["reason"] = "supercdn_disabled"
        return record
    if not path.exists() or not path.is_file():
        record["status"] = "failed"
        record["reason"] = "local_file_missing"
        record["error"] = {"code": "local_file_missing", "msg": "Local asset file is missing"}
        return record

    max_bytes = int(_config_value("SUPERCDN_MAX_FILE_SIZE_BYTES", 100 * 1024 * 1024) or 0)
    size = path.stat().st_size
    record["size"] = size
    record["sha256"] = _sha256_file(path)
    if max_bytes > 0 and size > max_bytes:
        record["status"] = "failed"
        record["reason"] = "file_too_large"
        record["error"] = {"code": "file_too_large", "msg": "Asset exceeds SUPERCDN_MAX_FILE_SIZE_BYTES"}
        return record

    try:
        client = SuperCDNClient()
        upload = client.upload_file(
            file_path=path,
            logical_path=logical_path,
            asset_type=asset_type,
            cache_control=record["cache_control"],
        )
        warmup = client.warmup(logical_path)
    except Exception as exc:
        logger.warning("Super CDN upload failed logical_path=%s error=%s", logical_path, exc)
        record["status"] = "failed"
        record["reason"] = getattr(exc, "code", "supercdn_upload_failed")
        record["error"] = {
            "code": getattr(exc, "code", "supercdn_upload_failed"),
            "msg": str(exc),
            "response_status": getattr(exc, "response_status", None),
        }
        return record

    public_url = upload.get("public_url") or upload.get("url")
    urls = upload.get("urls") if isinstance(upload.get("urls"), list) else []
    record.update({
        "status": "uploaded",
        "reason": "uploaded",
        "url": public_url,
        "public_url": public_url,
        "cdn_url": upload.get("cdn_url"),
        "storage_url": upload.get("storage_url"),
        "urls": [item for item in urls if item],
        "uploaded_at": _utc_now(),
        "warmup": warmup,
        "error": None,
    })
    if record["public_url"] and record["public_url"] not in record["urls"]:
        record["urls"].insert(0, record["public_url"])
    return record


def _response_error_message(response) -> str:
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        return str(data.get("error") or data.get("msg") or data)
    return response.text or f"HTTP {response.status_code}"
