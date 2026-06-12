from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import current_app, has_app_context

from backend import config


DEFAULT_PRODUCT = "CyberStream"
DEFAULT_CHANNEL = "stable"
DEFAULT_PLATFORM = "windows"
DEFAULT_ARCH = "x64"


def _config_value(name: str, default=None):
    if has_app_context():
        return current_app.config.get(name, default)
    return getattr(config, name, default)


def _project_root() -> Path:
    return Path(str(_config_value("BASE_DIR", config.BASE_DIR))).resolve()


def _data_dir() -> Path:
    return Path(str(_config_value("DATA_DIR", config.DATA_DIR))).resolve()


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _split_csv(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    return [str(item).strip().rstrip("/") for item in raw_items if str(item).strip()]


def _manifest_path() -> Path:
    raw = str(_config_value("UPDATE_MANIFEST_PATH", "") or "").strip()
    if not raw:
        return _data_dir() / "update-manifest.json"
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return _data_dir() / path


def _cdn_url_prefixes() -> list[str]:
    configured = _split_csv(_config_value("UPDATE_CDN_URL_PREFIXES", ""))
    if configured:
        return configured
    supercdn_url = str(_config_value("SUPERCDN_URL", "") or "").strip().rstrip("/")
    return [supercdn_url] if supercdn_url else []


def _load_json_file(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_manifest():
    path = _manifest_path()
    if not path.is_file():
        return None, ["update_manifest_missing"]
    try:
        payload = _load_json_file(path)
    except Exception:
        return None, ["update_manifest_invalid"]
    if not isinstance(payload, dict):
        return None, ["update_manifest_invalid"]
    return payload, []


def _release_sort_key(value: str):
    return _version_key(str(value).removeprefix("RELEASE_NOTES_").removesuffix(".md"))


def _source_tree_latest():
    version = str(_config_value("APP_VERSION", config.APP_VERSION) or "").strip() or "unknown"
    tauri_config_path = _project_root() / "pc" / "src-tauri" / "tauri.conf.json"
    if tauri_config_path.is_file():
        try:
            tauri_config = _load_json_file(tauri_config_path)
            package_version = str(tauri_config.get("version") or "").strip()
            if package_version:
                version = package_version
        except Exception:
            pass

    release = version
    release_notes_dir = _project_root() / "pc"
    release_notes = sorted(
        release_notes_dir.glob("RELEASE_NOTES_*.md"),
        key=lambda item: _release_sort_key(item.name),
        reverse=True,
    )
    if release_notes:
        release = release_notes[0].stem.removeprefix("RELEASE_NOTES_")

    return {
        "version": version,
        "release": release,
        "tag": f"v{release}" if release and release != "unknown" else None,
        "title": f"{DEFAULT_PRODUCT} PC {release}" if release and release != "unknown" else DEFAULT_PRODUCT,
        "released_at": None,
        "notes": None,
        "notes_url": None,
        "mandatory": False,
        "minimum_supported_version": None,
    }


def _select_manifest_channel(manifest: dict, channel: str) -> tuple[dict, bool]:
    channels = manifest.get("channels")
    if not isinstance(channels, dict):
        manifest_channel = str(manifest.get("channel") or DEFAULT_CHANNEL).strip()
        return manifest, not manifest_channel or manifest_channel == channel
    selected = channels.get(channel)
    if not isinstance(selected, dict):
        return {}, False
    merged = {key: value for key, value in manifest.items() if key != "channels"}
    merged.update(deepcopy(selected))
    merged.setdefault("channel", channel)
    return merged, True


def _normalize_latest(source: dict) -> dict:
    latest = source.get("latest") if isinstance(source.get("latest"), dict) else source
    version = str(latest.get("version") or "").strip()
    release = str(latest.get("release") or latest.get("build") or version or "").strip()
    tag = str(latest.get("tag") or "").strip()
    if not tag and release:
        tag = f"v{release}"
    title = str(latest.get("title") or latest.get("name") or "").strip()
    return {
        "version": version,
        "release": release,
        "tag": tag or None,
        "title": title or (f"{DEFAULT_PRODUCT} PC {release}" if release else DEFAULT_PRODUCT),
        "released_at": latest.get("released_at") or latest.get("published_at"),
        "notes": latest.get("notes"),
        "notes_url": latest.get("notes_url") or latest.get("release_notes_url"),
        "release_page_url": latest.get("release_page_url"),
        "mandatory": bool(latest.get("mandatory", False)),
        "minimum_supported_version": latest.get("minimum_supported_version"),
    }


def _download_matches(download: dict, *, channel: str, platform: str, arch: str, variant: str | None) -> bool:
    def _matches(field: str, expected: str) -> bool:
        value = str(download.get(field) or "").strip().lower()
        return not value or value == expected.lower()

    if not _matches("channel", channel):
        return False
    if not _matches("platform", platform):
        return False
    if not _matches("arch", arch):
        return False
    if variant:
        return str(download.get("variant") or "").strip().lower() == variant.lower()
    return True


def _url_matches_prefix(url: str, prefix: str) -> bool:
    parsed_url = urlsplit(url)
    parsed_prefix = urlsplit(prefix)
    if not parsed_prefix.scheme or not parsed_prefix.netloc:
        return url.startswith(prefix)
    if parsed_url.scheme != parsed_prefix.scheme:
        return False
    if parsed_url.netloc.lower() != parsed_prefix.netloc.lower():
        return False
    prefix_path = parsed_prefix.path.rstrip("/")
    if not prefix_path:
        return True
    return parsed_url.path == prefix_path or parsed_url.path.startswith(f"{prefix_path}/")


def _is_cdn_url(url: str, prefixes: list[str]) -> bool:
    if not url:
        return False
    if not prefixes:
        return False
    return any(_url_matches_prefix(url, prefix) for prefix in prefixes)


def _normalize_downloads(
    source: dict,
    *,
    channel: str,
    platform: str,
    arch: str,
    variant: str | None,
    cdn_prefixes: list[str],
    warnings: list[str],
) -> list[dict]:
    raw_downloads = source.get("downloads")
    latest = source.get("latest") if isinstance(source.get("latest"), dict) else {}
    if raw_downloads is None and isinstance(latest, dict):
        raw_downloads = latest.get("downloads")
    if not isinstance(raw_downloads, list):
        warnings.append("update_downloads_missing")
        return []

    items = []
    for raw in raw_downloads:
        if not isinstance(raw, dict) or not _download_matches(
            raw,
            channel=channel,
            platform=platform,
            arch=arch,
            variant=variant,
        ):
            continue
        url = str(raw.get("url") or raw.get("download_url") or "").strip()
        if not _is_cdn_url(url, cdn_prefixes):
            warnings.append("non_cdn_download_url_ignored")
            continue
        sha256 = str(raw.get("sha256") or raw.get("digest") or "").strip()
        if sha256.lower().startswith("sha256:"):
            sha256 = sha256.split(":", 1)[1]
        size = raw.get("size")
        try:
            size = int(size) if size not in (None, "") else None
        except (TypeError, ValueError):
            size = None
        items.append({
            "variant": str(raw.get("variant") or "").strip() or None,
            "name": str(raw.get("name") or raw.get("filename") or "").strip() or None,
            "platform": str(raw.get("platform") or platform).strip(),
            "arch": str(raw.get("arch") or arch).strip(),
            "url": url,
            "cdn": True,
            "size": size,
            "sha256": sha256 or None,
            "content_type": str(raw.get("content_type") or raw.get("mime_type") or "").strip() or None,
            "label": str(raw.get("label") or "").strip() or None,
            "notes": raw.get("notes"),
        })
    return items


def _version_key(value: str):
    raw = str(value or "").strip().lower().removeprefix("v")
    key = []
    for token in re.findall(r"\d+|[a-z]+", raw):
        if token.isdigit():
            key.append((1, int(token)))
        else:
            key.append((0, token))
    return key


def _compare_versions(left: str | None, right: str | None) -> int:
    left_key = _version_key(left or "")
    right_key = _version_key(right or "")
    if left_key == right_key:
        return 0
    return 1 if left_key > right_key else -1


def _update_available(current_version: str | None, current_release: str | None, latest: dict) -> bool:
    current_identity = (current_release or current_version or "").strip()
    if not current_identity:
        return False
    latest_identity = latest.get("release") if current_release or "-" in current_identity else latest.get("version")
    return _compare_versions(str(latest_identity or ""), current_identity) > 0


def _select_download(downloads: list[dict], variant: str | None):
    if not downloads:
        return None
    if variant:
        return downloads[0]
    for preferred in ("full", "lite"):
        for item in downloads:
            if str(item.get("variant") or "").lower() == preferred:
                return item
    return downloads[0]


def get_update_check_payload(
    *,
    current_version: str | None = None,
    current_release: str | None = None,
    channel: str | None = None,
    platform: str | None = None,
    arch: str | None = None,
    variant: str | None = None,
) -> dict:
    channel = (channel or str(_config_value("UPDATE_DEFAULT_CHANNEL", DEFAULT_CHANNEL) or DEFAULT_CHANNEL)).strip()
    platform = (platform or DEFAULT_PLATFORM).strip().lower()
    arch = (arch or DEFAULT_ARCH).strip().lower()
    variant = variant.strip().lower() if isinstance(variant, str) and variant.strip() else None

    warnings: list[str] = []
    manifest, manifest_warnings = _read_manifest()
    warnings.extend(manifest_warnings)
    source = "manifest" if manifest else "source_tree"
    if manifest:
        selected_source, channel_available = _select_manifest_channel(manifest, channel)
        if not channel_available:
            warnings.append("update_channel_not_published")
            selected_source = {"product": manifest.get("product") or DEFAULT_PRODUCT}
        latest = _normalize_latest(selected_source)
    else:
        selected_source = {}
        latest = _source_tree_latest()

    cdn_prefixes = _cdn_url_prefixes()
    if manifest and not cdn_prefixes:
        warnings.append("update_cdn_prefixes_missing")
    downloads = _normalize_downloads(
        selected_source,
        channel=channel,
        platform=platform,
        arch=arch,
        variant=variant,
        cdn_prefixes=cdn_prefixes,
        warnings=warnings,
    ) if manifest else []
    if not manifest:
        warnings.append("update_downloads_missing")

    selected_download = _select_download(downloads, variant)
    raw_update_available = _update_available(current_version, current_release, latest)
    update_available = raw_update_available and bool(selected_download)
    return {
        "product": str((selected_source or {}).get("product") or DEFAULT_PRODUCT),
        "channel": channel,
        "platform": platform,
        "arch": arch,
        "variant": variant,
        "current": {
            "version": current_version or None,
            "release": current_release or None,
            "backend_version": str(_config_value("APP_VERSION", config.APP_VERSION) or "unknown"),
        },
        "latest": latest,
        "update_available": update_available,
        "downloads": downloads,
        "selected_download": selected_download,
        "cdn": {
            "required": True,
            "validated": bool(downloads),
        },
        "source": source,
        "warnings": sorted(set(warnings)),
        "checked_at": _utc_now(),
    }
