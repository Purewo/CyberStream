import hashlib
import html
import os
import posixpath
import re
import tempfile
import time
import uuid
from pathlib import Path

from flask import current_app, has_app_context, has_request_context

from backend import config
from backend.app.providers.factory import provider_factory
from backend.app.services.cdn_assets import (
    supercdn_auto_upload_subtitles_enabled,
    supercdn_serve_asset_urls_enabled,
    upload_file_to_supercdn,
)
from backend.app.services.urls import api_url_for


SUPPORTED_SUBTITLE_EXTENSIONS = {
    ".srt": {
        "format": "srt",
        "mime_type": "application/x-subrip; charset=utf-8",
        "web_player_supported": False,
    },
    ".ass": {
        "format": "ass",
        "mime_type": "text/plain; charset=utf-8",
        "web_player_supported": False,
    },
    ".ssa": {
        "format": "ssa",
        "mime_type": "text/plain; charset=utf-8",
        "web_player_supported": False,
    },
    ".vtt": {
        "format": "vtt",
        "mime_type": "text/vtt; charset=utf-8",
        "web_player_supported": True,
    },
    ".sub": {
        "format": "sub",
        "mime_type": "text/plain; charset=utf-8",
        "web_player_supported": False,
    },
    ".sup": {
        "format": "sup",
        "mime_type": "application/octet-stream",
        "web_player_supported": False,
    },
}

LANGUAGE_PRIORITY = {
    "zh-Hans": 0,
    "zh-Hant": 1,
    "zh": 2,
    "en": 3,
    "ja": 4,
    "ko": 5,
}

LANGUAGE_LABELS = {
    "zh-Hans": "Chinese Simplified",
    "zh-Hant": "Chinese Traditional",
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "unknown": "Unknown",
}

DEFAULT_MARKERS = {"default", "defaults", "默认", "缺省"}
FORCED_MARKERS = {"forced", "force", "only", "强制"}
DIRECTORY_CACHE_TTL_SECONDS = 30
MAX_MANUAL_UPLOAD_SUBTITLE_BYTES = 100 * 1024 * 1024
MAX_WEBVTT_CONVERSION_BYTES = 10 * 1024 * 1024
WEBVTT_CONVERTIBLE_FORMATS = {"srt", "ass", "ssa", "vtt"}

_DIRECTORY_CACHE = {}


class ResourceSubtitleError(ValueError):
    def __init__(self, message, code=40070, http_status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


def clear_subtitle_discovery_cache():
    _DIRECTORY_CACHE.clear()


def build_empty_subtitle_payload(reason="no_sidecar_subtitles_found"):
    return {
        "supported": False,
        "items": [],
        "default_subtitle_id": None,
        "placeholder_url": None,
        "reason": reason,
        "web_player_supported": False,
        "discovery": {
            "mode": "sidecar_same_directory",
            "matched_count": 0,
            "supported_extensions": sorted(SUPPORTED_SUBTITLE_EXTENSIONS.keys()),
        },
    }


def _clean_relative_path(value):
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return ""
    normalized = posixpath.normpath("/" + raw).lstrip("/")
    return "" if normalized == "." else normalized


def _directory_path(path):
    clean_path = _clean_relative_path(path)
    directory = posixpath.dirname(clean_path)
    return "" if directory in {"", "."} else directory


def _filename(path):
    return posixpath.basename(str(path or "").replace("\\", "/"))


def _stem(filename):
    return posixpath.splitext(_filename(filename))[0]


def _extension(filename):
    return posixpath.splitext(str(filename or ""))[1].lower()


def _tokens(value):
    raw = str(value or "").lower()
    return {
        token
        for token in re.split(r"[\s._\-\[\]\(\)]+", raw)
        if token
    }


def _subtitle_matches_resource(resource_filename, subtitle_filename):
    resource_stem = _stem(resource_filename).lower()
    subtitle_stem = _stem(subtitle_filename).lower()
    if not resource_stem or not subtitle_stem:
        return False
    if subtitle_stem == resource_stem:
        return True
    return any(
        subtitle_stem.startswith(f"{resource_stem}{separator}")
        for separator in (".", "-", "_", " ")
    )


def _detect_language(filename):
    stem = _stem(filename)
    tokens = _tokens(stem)
    lower_stem = stem.lower()

    if (
        {"zh", "hans"}.issubset(tokens)
        or tokens.intersection({"chs", "sc", "gb", "gb2312", "simplified"})
        or "zh-hans" in lower_stem
        or "简体" in stem
        or "简中" in stem
    ):
        return "zh-Hans", LANGUAGE_LABELS["zh-Hans"], "filename_token"

    if (
        {"zh", "hant"}.issubset(tokens)
        or tokens.intersection({"cht", "tc", "big5", "traditional"})
        or "zh-hant" in lower_stem
        or "繁体" in stem
        or "繁中" in stem
    ):
        return "zh-Hant", LANGUAGE_LABELS["zh-Hant"], "filename_token"

    if tokens.intersection({"zh", "chi", "zho", "cn", "chinese"}):
        return "zh", LANGUAGE_LABELS["zh"], "filename_token"

    if tokens.intersection({"en", "eng", "english"}):
        return "en", LANGUAGE_LABELS["en"], "filename_token"

    if tokens.intersection({"ja", "jp", "jpn", "japanese"}):
        return "ja", LANGUAGE_LABELS["ja"], "filename_token"

    if tokens.intersection({"ko", "kr", "kor", "korean"}):
        return "ko", LANGUAGE_LABELS["ko"], "filename_token"

    return "unknown", LANGUAGE_LABELS["unknown"], "unknown"


def _has_marker(filename, markers):
    tokens = _tokens(_stem(filename))
    raw = _stem(filename)
    return bool(tokens.intersection(markers) or any(marker in raw for marker in markers))


def _subtitle_id(resource, subtitle_path):
    digest = hashlib.sha1(
        f"{getattr(resource, 'id', '')}\0{subtitle_path}".encode("utf-8")
    ).hexdigest()[:16]
    return f"sub_{digest}"


def _subtitle_url(resource, subtitle_id, output_format=None):
    resource_id = getattr(resource, "id", None)
    if not resource_id:
        return None
    if has_request_context():
        kwargs = {"id": resource_id, "subtitle_id": subtitle_id}
        if output_format:
            kwargs["format"] = output_format
        return api_url_for("player.stream_resource", **kwargs)
    suffix = f"&format={output_format}" if output_format else ""
    return f"/api/v1/resources/{resource_id}/stream?subtitle_id={subtitle_id}{suffix}"


def _web_player_payload(resource, subtitle_id, extension_info, forced=False):
    subtitle_format = extension_info["format"]
    convertible = subtitle_format in WEBVTT_CONVERTIBLE_FORMATS
    native_supported = extension_info["web_player_supported"]
    output_format = None if native_supported else ("vtt" if convertible else None)
    return {
        "supported": bool(native_supported or convertible),
        "kind": "subtitles" if not forced else "forced",
        "url": _subtitle_url(resource, subtitle_id, output_format=output_format) if (native_supported or convertible) else None,
        "format": "vtt" if (native_supported or convertible) else subtitle_format,
        "native_supported": native_supported,
        "requires_conversion": bool(convertible and not native_supported),
        "source_format": subtitle_format,
    }


def _list_directory_items(source, directory):
    source_id = getattr(source, "id", None)
    cache_key = (source_id, getattr(source, "type", None), directory)
    now = time.monotonic()
    cached = _DIRECTORY_CACHE.get(cache_key)
    if cached and now - cached["created_at"] <= DIRECTORY_CACHE_TTL_SECONDS:
        return cached["items"]

    provider = provider_factory.get_provider(source)
    items = provider.list_items(directory)
    _DIRECTORY_CACHE[cache_key] = {
        "created_at": now,
        "items": items,
    }
    return items


def _build_subtitle_item(resource, directory, item):
    name = item.get("name") or _filename(item.get("path"))
    subtitle_path = _clean_relative_path(item.get("path") or posixpath.join(directory, name))
    ext = _extension(name)
    extension_info = SUPPORTED_SUBTITLE_EXTENSIONS[ext]
    language_code, language_label, language_source = _detect_language(name)
    subtitle_id = _subtitle_id(resource, subtitle_path)
    forced = _has_marker(name, FORCED_MARKERS)

    return {
        "id": subtitle_id,
        "source": "sidecar",
        "match": "same_directory_filename",
        "filename": name,
        "path": subtitle_path,
        "format": extension_info["format"],
        "mime_type": extension_info["mime_type"],
        "language": {
            "code": language_code,
            "label": language_label,
            "source": language_source,
        },
        "label": f"{language_label} {extension_info['format'].upper()}",
        "is_default": _has_marker(name, DEFAULT_MARKERS),
        "is_forced": forced,
        "url": _subtitle_url(resource, subtitle_id),
        "web_player": _web_player_payload(resource, subtitle_id, extension_info, forced=forced),
    }


def _sort_subtitle_item(item):
    language_code = (item.get("language") or {}).get("code") or "unknown"
    return (
        0 if item.get("is_default") else 1,
        0 if item.get("source") in {"online_bound", "manual_upload"} else 1,
        LANGUAGE_PRIORITY.get(language_code, 99),
        0 if item.get("format") == "vtt" else 1,
        item.get("filename") or "",
    )


def _cache_dir():
    configured = current_app.config.get("CACHE_DIR") if has_app_context() else None
    return Path(configured or config.CACHE_DIR).expanduser()


def _config_value(name: str, default=None):
    if has_app_context():
        return current_app.config.get(name, default)
    return getattr(config, name, default)


def cached_subtitle_file_path(subtitle):
    storage = subtitle.get("storage") if isinstance(subtitle, dict) else None
    if not isinstance(storage, dict) or storage.get("kind") != "cache":
        return None

    raw_path = _clean_relative_path(storage.get("path"))
    if not raw_path:
        return None

    root = _cache_dir().resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _decode_subtitle_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _normalize_vtt_timestamp(value: str) -> str:
    raw = str(value or "").strip()
    if "," in raw:
        raw = raw.replace(",", ".", 1)
    if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", raw):
        return raw
    if re.match(r"^\d:\d{2}:\d{2}\.\d{2}$", raw):
        return f"0{raw}0"
    if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{2}$", raw):
        return f"{raw}0"
    if re.match(r"^\d:\d{2}:\d{2}\.\d{3}$", raw):
        return f"0{raw}"
    return raw


def _clean_ass_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    text = re.sub(r"\{[^}]*\}", "", text)
    return html.escape(text.strip(), quote=False)


def _srt_to_vtt(text: str) -> str:
    body = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    body = re.sub(
        r"(\d{1,2}:\d{2}:\d{2}),(\d{3})\s+-->\s+(\d{1,2}:\d{2}:\d{2}),(\d{3})",
        lambda match: (
            f"{_normalize_vtt_timestamp(match.group(1) + '.' + match.group(2))} --> "
            f"{_normalize_vtt_timestamp(match.group(3) + '.' + match.group(4))}"
        ),
        body,
    )
    return f"WEBVTT\n\n{body}\n"


def _ass_to_vtt(text: str) -> str:
    columns = []
    cues = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if line.lower().startswith("format:"):
            columns = [item.strip().lower() for item in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue

        payload = line.split(":", 1)[1].lstrip()
        if columns:
            parts = payload.split(",", max(0, len(columns) - 1))
            try:
                start = parts[columns.index("start")]
                end = parts[columns.index("end")]
                cue_text = parts[columns.index("text")]
            except (ValueError, IndexError):
                continue
        else:
            parts = payload.split(",", 9)
            if len(parts) < 10:
                continue
            start, end, cue_text = parts[1], parts[2], parts[9]

        cue_text = _clean_ass_text(cue_text)
        if not cue_text:
            continue
        cues.append(
            f"{_normalize_vtt_timestamp(start)} --> {_normalize_vtt_timestamp(end)}\n{cue_text}"
        )

    return "WEBVTT\n\n" + "\n\n".join(cues) + ("\n" if cues else "")


def convert_subtitle_bytes_to_vtt(content: bytes, source_format: str) -> str:
    if len(content or b"") > MAX_WEBVTT_CONVERSION_BYTES:
        raise ResourceSubtitleError("Subtitle is too large to convert to WebVTT", code=41371, http_status=413)

    subtitle_format = str(source_format or "").strip().lower()
    if subtitle_format not in WEBVTT_CONVERTIBLE_FORMATS:
        raise ResourceSubtitleError("Subtitle format cannot be converted to WebVTT", code=41570, http_status=415)

    text = _decode_subtitle_text(content or b"")
    if subtitle_format == "vtt":
        stripped = text.lstrip("\ufeff")
        return stripped if stripped.startswith("WEBVTT") else f"WEBVTT\n\n{stripped.strip()}\n"
    if subtitle_format == "srt":
        return _srt_to_vtt(text)
    return _ass_to_vtt(text)


def _cached_subtitle_row_path(row):
    return cached_subtitle_file_path({
        "storage": {
            "kind": getattr(row, "storage_kind", None),
            "path": getattr(row, "storage_path", None),
        }
    })


def _safe_cache_filename(filename):
    basename = _filename(filename)
    suffix = Path(basename).suffix.lower()
    stem = Path(basename).stem
    stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", ".", stem).strip(".")
    suffix = re.sub(r"[^a-z0-9.]+", "", suffix) or ".srt"
    return f"{stem or 'subtitle'}{suffix}"


def _unique_cached_subtitle_path(resource, filename):
    resource_id = str(getattr(resource, "id", "") or "unknown")
    safe_filename = _safe_cache_filename(filename)
    stem = Path(safe_filename).stem
    suffix = Path(safe_filename).suffix
    directory = Path("subtitles") / resource_id
    root = _cache_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)

    for index in range(1, 1000):
        candidate_name = safe_filename if index == 1 else f"{stem}.{index}{suffix}"
        relative_path = directory / candidate_name
        absolute_path = (root / relative_path).resolve()
        try:
            absolute_path.relative_to(root)
        except ValueError as e:
            raise ResourceSubtitleError("Invalid subtitle cache path", code=50072, http_status=500) from e
        if not absolute_path.exists():
            return relative_path.as_posix(), absolute_path

    raise ResourceSubtitleError("Unable to allocate subtitle cache filename", code=50073, http_status=500)


def _truthy(value):
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _bound_subtitle_rows(resource):
    relation = getattr(resource, "bound_subtitles", None)
    if relation is None:
        return []
    try:
        rows = relation.all() if hasattr(relation, "all") else list(relation)
    except Exception:
        return []
    return sorted(
        rows,
        key=lambda item: (
            getattr(item, "created_at", None) is None,
            getattr(item, "created_at", None).isoformat() if getattr(item, "created_at", None) else "",
        ),
    )


def _build_bound_subtitle_item(resource, row):
    filename = getattr(row, "filename", None) or _filename(getattr(row, "storage_path", None))
    ext = _extension(filename)
    extension_info = SUPPORTED_SUBTITLE_EXTENSIONS.get(ext)
    if not extension_info:
        return None

    language = getattr(row, "language", None)
    if not isinstance(language, dict) or not language.get("code"):
        language_code, language_label, language_source = _detect_language(filename)
        language = {
            "code": language_code,
            "label": language_label,
            "source": language_source,
        }

    subtitle_id = getattr(row, "id", None)
    if not subtitle_id:
        return None

    metadata = getattr(row, "subtitle_metadata", None) or {}
    provider_id = getattr(row, "provider_id", None)
    provider_name = getattr(row, "provider_name", None) or provider_id or "online"
    label_language = language.get("label") or LANGUAGE_LABELS["unknown"]
    source = getattr(row, "source", None)
    item_source = "manual_upload" if source == "manual_upload" else "online_bound"

    item = {
        "id": subtitle_id,
        "source": item_source,
        "match": "manual_uploaded" if item_source == "manual_upload" else "manual_confirmed_online",
        "filename": filename,
        "path": getattr(row, "storage_path", None),
        "format": getattr(row, "format", None) or extension_info["format"],
        "mime_type": getattr(row, "mime_type", None) or extension_info["mime_type"],
        "language": language,
        "label": f"{label_language} {extension_info['format'].upper()} ({provider_name})",
        "is_default": bool(getattr(row, "is_default", False)),
        "is_forced": False,
        "url": _subtitle_url(resource, subtitle_id),
        "web_player": _web_player_payload(resource, subtitle_id, extension_info),
        "storage": {
            "kind": getattr(row, "storage_kind", None) or "cache",
            "path": getattr(row, "storage_path", None),
        },
    }
    _apply_bound_subtitle_cdn(item, metadata)

    if item_source == "manual_upload":
        item["upload"] = {
            "candidate_id": getattr(row, "candidate_id", None),
            "confirmed": True,
            "meta": metadata,
        }
    else:
        item["online"] = {
            "provider_id": provider_id,
            "provider_name": provider_name,
            "candidate_id": getattr(row, "candidate_id", None),
            "confirmed": True,
            "meta": metadata,
        }
    return item


def _apply_bound_subtitle_cdn(item: dict, metadata: dict) -> None:
    if not supercdn_serve_asset_urls_enabled() or not isinstance(metadata, dict):
        return
    cdn = metadata.get("cdn")
    if not isinstance(cdn, dict) or cdn.get("provider") != "supercdn":
        return
    assets = cdn.get("assets") if isinstance(cdn.get("assets"), dict) else {}
    original = assets.get("original") if isinstance(assets.get("original"), dict) else None
    webvtt = assets.get("webvtt") if isinstance(assets.get("webvtt"), dict) else None

    if original and original.get("status") == "uploaded" and (original.get("url") or original.get("public_url")):
        item["url"] = original.get("url") or original.get("public_url")

    web_player = item.get("web_player") if isinstance(item.get("web_player"), dict) else None
    if web_player and webvtt and webvtt.get("status") == "uploaded" and (webvtt.get("url") or webvtt.get("public_url")):
        web_player["url"] = webvtt.get("url") or webvtt.get("public_url")
        web_player["format"] = "vtt"
        web_player["cdn"] = {
            "provider": "supercdn",
            "bucket": cdn.get("bucket"),
            "route_profile": cdn.get("route_profile"),
            "asset": "webvtt",
        }

    item["cdn"] = {
        "provider": "supercdn",
        "bucket": cdn.get("bucket"),
        "route_profile": cdn.get("route_profile"),
        "status": cdn.get("status"),
        "assets": {
            name: {
                "status": record.get("status"),
                "url": record.get("url") or record.get("public_url"),
                "logical_path": record.get("logical_path"),
                "sha256": record.get("sha256"),
                "reason": record.get("reason"),
            }
            for name, record in assets.items()
            if isinstance(record, dict)
        },
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subtitle_cdn_logical_path(resource, row, variant: str, suffix: str, sha256: str) -> str:
    resource_id = str(getattr(resource, "id", "") or getattr(row, "resource_id", "") or "unknown")
    subtitle_id = str(getattr(row, "id", "") or "unknown")
    clean_suffix = suffix if str(suffix or "").startswith(".") else f".{suffix or 'bin'}"
    return f"subtitles/resources/{resource_id}/{subtitle_id}/{variant}/{sha256}{clean_suffix.lower()}"


def _subtitle_cdn_status(assets: dict) -> str:
    statuses = [
        record.get("status")
        for record in assets.values()
        if isinstance(record, dict) and record.get("status") != "skipped"
    ]
    if statuses and all(status == "uploaded" for status in statuses):
        return "uploaded"
    if any(status == "uploaded" for status in statuses):
        return "partial"
    if any(status == "failed" for status in statuses):
        return "failed"
    return "skipped"


def sync_bound_subtitle_to_cdn(resource, row, *, force=False) -> dict:
    if not supercdn_auto_upload_subtitles_enabled():
        return {
            "provider": "supercdn",
            "status": "skipped",
            "reason": "supercdn_disabled",
        }

    cache_path = _cached_subtitle_row_path(row)
    if not cache_path or not cache_path.exists() or not cache_path.is_file():
        return {
            "provider": "supercdn",
            "status": "skipped",
            "reason": "local_cache_missing",
        }

    metadata = dict(getattr(row, "subtitle_metadata", None) or {})
    existing = metadata.get("cdn") if isinstance(metadata.get("cdn"), dict) else None
    original_sha = _file_sha256(cache_path)
    if (
        existing
        and not _truthy(force)
        and existing.get("provider") == "supercdn"
        and existing.get("status") in {"uploaded", "partial"}
        and ((existing.get("assets") or {}).get("original") or {}).get("sha256") == original_sha
    ):
        return {**existing, "status": "cached", "reason": "already_uploaded"}

    suffix = cache_path.suffix.lower() or f".{getattr(row, 'format', None) or 'txt'}"
    assets = {}
    assets["original"] = upload_file_to_supercdn(
        cache_path,
        logical_path=_subtitle_cdn_logical_path(resource, row, "original", suffix, original_sha),
        asset_type="document",
        cache_control=str(_config_value("SUPERCDN_BUCKET_CACHE_CONTROL", "public, max-age=86400") or ""),
    )

    subtitle_format = str(getattr(row, "format", "") or "").strip().lower()
    if subtitle_format in WEBVTT_CONVERTIBLE_FORMATS:
        try:
            vtt_content = convert_subtitle_bytes_to_vtt(cache_path.read_bytes(), subtitle_format).encode("utf-8")
            vtt_sha = hashlib.sha256(vtt_content).hexdigest()
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=".subtitle-webvtt.", suffix=".vtt")
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(vtt_content)
                assets["webvtt"] = upload_file_to_supercdn(
                    tmp_path,
                    logical_path=_subtitle_cdn_logical_path(resource, row, "webvtt", ".vtt", vtt_sha),
                    asset_type="document",
                    cache_control=str(_config_value("SUPERCDN_BUCKET_CACHE_CONTROL", "public, max-age=86400") or ""),
                )
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception as exc:
            assets["webvtt"] = {
                "provider": "supercdn",
                "enabled": True,
                "status": "failed",
                "reason": "webvtt_conversion_failed",
                "asset_type": "document",
                "logical_path": None,
                "url": None,
                "error": {"code": "webvtt_conversion_failed", "msg": str(exc)},
            }
    else:
        assets["webvtt"] = {
            "provider": "supercdn",
            "enabled": True,
            "status": "skipped",
            "reason": "format_not_webvtt_convertible",
            "asset_type": "document",
            "logical_path": None,
            "url": None,
            "error": None,
        }

    cdn = {
        "provider": "supercdn",
        "bucket": _config_value("SUPERCDN_BUCKET", None),
        "route_profile": _config_value("SUPERCDN_ROUTE_PROFILE", "china_all"),
        "status": _subtitle_cdn_status(assets),
        "assets": assets,
        "updated_at": int(time.time()),
    }
    metadata["cdn"] = cdn
    try:
        from backend.app.extensions import db

        row.subtitle_metadata = metadata
        db.session.add(row)
        db.session.commit()
    except Exception:
        from backend.app.extensions import db

        db.session.rollback()
        raise
    return cdn


def _discover_bound_subtitles(resource):
    items = []
    for row in _bound_subtitle_rows(resource):
        item = _build_bound_subtitle_item(resource, row)
        if not item:
            continue
        path = cached_subtitle_file_path(item)
        if not path or not path.exists() or not path.is_file():
            continue
        items.append(item)
    return items


def _build_subtitle_payload(sidecar_items, bound_items, reason=None, directory=None):
    subtitle_items = list(sidecar_items or []) + list(bound_items or [])
    subtitle_items.sort(key=_sort_subtitle_item)

    default_subtitle_id = None
    if subtitle_items:
        explicit_default = next((item for item in subtitle_items if item.get("is_default")), None)
        default_item = explicit_default or subtitle_items[0]
        default_item["is_default"] = True
        default_subtitle_id = default_item["id"]

    return {
        "supported": bool(subtitle_items),
        "items": subtitle_items,
        "default_subtitle_id": default_subtitle_id,
        "placeholder_url": None,
        "reason": None if subtitle_items else reason or "no_sidecar_subtitles_found",
        "web_player_supported": any(
            (item.get("web_player") or {}).get("supported")
            for item in subtitle_items
        ),
        "discovery": {
            "mode": "sidecar_same_directory_and_bound_online",
            "directory": directory or "/",
            "matched_count": len(subtitle_items),
            "sidecar_count": len(sidecar_items or []),
            "bound_count": len(bound_items or []),
            "supported_extensions": sorted(SUPPORTED_SUBTITLE_EXTENSIONS.keys()),
        },
    }


def discover_resource_subtitles(resource):
    bound_items = _discover_bound_subtitles(resource)
    source = getattr(resource, "source", None)
    if not source:
        return _build_subtitle_payload([], bound_items, reason="storage_source_missing")

    resource_path = _clean_relative_path(getattr(resource, "path", None))
    resource_filename = getattr(resource, "filename", None) or _filename(resource_path)
    if not resource_path or not resource_filename:
        return _build_subtitle_payload([], bound_items, reason="resource_path_missing")

    directory = _directory_path(resource_path)
    try:
        directory_items = _list_directory_items(source, directory)
    except Exception:
        return _build_subtitle_payload([], bound_items, reason="subtitle_discovery_failed", directory=directory or "/")

    subtitle_items = []
    for item in directory_items or []:
        if item.get("isdir"):
            continue
        name = item.get("name") or _filename(item.get("path"))
        if _extension(name) not in SUPPORTED_SUBTITLE_EXTENSIONS:
            continue
        if not _subtitle_matches_resource(resource_filename, name):
            continue
        subtitle_items.append(_build_subtitle_item(resource, directory, item))

    return _build_subtitle_payload(
        subtitle_items,
        bound_items,
        reason="no_sidecar_subtitles_found",
        directory=directory or "/",
    )


def find_resource_subtitle(resource, subtitle_id):
    payload = discover_resource_subtitles(resource)
    for item in payload.get("items") or []:
        if item.get("id") == subtitle_id:
            return item, payload
    return None, payload


def _find_bound_subtitle_row(resource, subtitle_id):
    from backend.app.models import ResourceSubtitle

    return ResourceSubtitle.query.filter_by(
        id=str(subtitle_id or ""),
        resource_id=getattr(resource, "id", None),
    ).first()


def _build_resource_subtitle_mutation_response(resource, subtitle_id=None):
    from backend.app.services.playback import build_resource_playback

    subtitle_payload = discover_resource_subtitles(resource)
    subtitle = None
    if subtitle_id:
        subtitle = next((item for item in subtitle_payload.get("items") or [] if item.get("id") == subtitle_id), None)
    return {
        "resource_id": getattr(resource, "id", None),
        "subtitle_id": subtitle_id,
        "subtitle": subtitle,
        "subtitles": subtitle_payload,
        "playback": build_resource_playback(resource, subtitles=subtitle_payload),
    }


def upload_resource_subtitle(resource, file_storage, set_default=False):
    from backend.app.extensions import db
    from backend.app.models import ResourceSubtitle
    from backend.app.services.online_subtitles import OnlineSubtitleError, normalize_downloaded_subtitle_file

    if not file_storage:
        raise ResourceSubtitleError("subtitle file is required", code=40072, http_status=400)

    filename = str(getattr(file_storage, "filename", "") or "").strip()
    if not filename:
        raise ResourceSubtitleError("subtitle filename is required", code=40073, http_status=400)

    content = file_storage.read(MAX_MANUAL_UPLOAD_SUBTITLE_BYTES + 1)
    if len(content) > MAX_MANUAL_UPLOAD_SUBTITLE_BYTES:
        raise ResourceSubtitleError("subtitle upload is too large", code=41370, http_status=413)

    source_key = uuid.uuid4().hex
    candidate_id = f"upload:{source_key}"
    try:
        normalized = normalize_downloaded_subtitle_file(
            resource,
            "manual",
            source_key,
            filename,
            content,
            meta={
                "manual_upload": True,
                "uploaded_filename": filename,
            },
        )
    except OnlineSubtitleError as e:
        raise ResourceSubtitleError(e.message, code=40074, http_status=400) from e

    storage_path, absolute_path = _unique_cached_subtitle_path(resource, normalized["filename"])
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(normalized["content"])

    metadata = dict(normalized.get("meta") or {})
    metadata.update({
        "manual_upload": True,
        "uploaded_filename": filename,
        "stored_filename": normalized["filename"],
    })

    try:
        if _truthy(set_default):
            ResourceSubtitle.query.filter_by(resource_id=getattr(resource, "id", None)).update(
                {"is_default": False},
                synchronize_session=False,
            )

        row = ResourceSubtitle(
            resource_id=getattr(resource, "id", None),
            source="manual_upload",
            provider_id="manual",
            provider_name="Manual Upload",
            candidate_id=candidate_id,
            filename=_filename(normalized["filename"]),
            storage_kind="cache",
            storage_path=storage_path,
            format=Path(normalized["filename"]).suffix.lower().lstrip(".") or "srt",
            mime_type=normalized["mime_type"],
            size=len(normalized["content"]),
            language=None,
            subtitle_metadata=metadata,
            is_default=_truthy(set_default),
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            os.remove(absolute_path)
        except OSError:
            pass
        raise

    sync_bound_subtitle_to_cdn(resource, row)
    clear_subtitle_discovery_cache()
    response = _build_resource_subtitle_mutation_response(resource, subtitle_id=row.id)
    response.update({
        "uploaded": True,
        "candidate_id": candidate_id,
    })
    return response


def delete_bound_resource_subtitle(resource, subtitle_id):
    from backend.app.extensions import db

    row = _find_bound_subtitle_row(resource, subtitle_id)
    if not row:
        subtitle, _payload = find_resource_subtitle(resource, subtitle_id)
        if subtitle:
            raise ResourceSubtitleError(
                "Only user-bound online subtitles can be removed",
                code=40070,
                http_status=400,
            )
        raise ResourceSubtitleError("Subtitle not found", code=40470, http_status=404)

    cache_path = _cached_subtitle_row_path(row)
    db.session.delete(row)
    db.session.commit()
    clear_subtitle_discovery_cache()

    file_deleted = False
    if cache_path and cache_path.exists() and cache_path.is_file():
        try:
            os.remove(cache_path)
            file_deleted = True
        except OSError:
            file_deleted = False

    response = _build_resource_subtitle_mutation_response(resource, subtitle_id=str(subtitle_id))
    response.update({
        "removed": True,
        "file_deleted": file_deleted,
    })
    return response


def set_default_bound_resource_subtitle(resource, subtitle_id):
    from backend.app.extensions import db
    from backend.app.models import ResourceSubtitle

    row = _find_bound_subtitle_row(resource, subtitle_id)
    if not row:
        subtitle, _payload = find_resource_subtitle(resource, subtitle_id)
        if subtitle:
            raise ResourceSubtitleError(
                "Only user-bound online subtitles can be set as default",
                code=40071,
                http_status=400,
            )
        raise ResourceSubtitleError("Subtitle not found", code=40470, http_status=404)

    cache_path = _cached_subtitle_row_path(row)
    if not cache_path or not cache_path.exists() or not cache_path.is_file():
        raise ResourceSubtitleError("Bound subtitle file is missing", code=40961, http_status=409)

    ResourceSubtitle.query.filter_by(resource_id=getattr(resource, "id", None)).update(
        {"is_default": False},
        synchronize_session=False,
    )
    row.is_default = True
    db.session.commit()
    clear_subtitle_discovery_cache()

    response = _build_resource_subtitle_mutation_response(resource, subtitle_id=str(subtitle_id))
    response.update({
        "default_subtitle_id": str(subtitle_id),
    })
    return response
