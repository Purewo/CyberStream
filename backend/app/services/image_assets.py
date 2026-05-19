from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import current_app, has_app_context

from backend import config
from backend.app.services.cdn_assets import (
    supercdn_auto_upload_images_enabled,
    supercdn_serve_asset_urls_enabled,
    upload_file_to_supercdn,
)


IMAGE_KINDS = {"poster", "backdrop"}
MIMETYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
EXTENSION_MIMETYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
BLOCKED_HOSTS = {"localhost"}
IMAGE_SOURCE_FIELDS = {
    "poster": ("cover", "poster_url"),
    "backdrop": ("background_cover", "backdrop_url"),
}
SCRAPER_SOURCE_GROUPS = {
    "BANGUMI": ("bangumi", "Bangumi"),
    "TENCENT_VIDEO": ("tencent_video", "Tencent Video"),
    "TMDB": ("tmdb", "TMDB"),
    "TMDB_STRICT": ("tmdb", "TMDB"),
    "TMDB_FALLBACK": ("tmdb", "TMDB"),
    "NFO": ("nfo", "NFO"),
    "NFO_LOCAL": ("nfo", "NFO"),
    "NFO_TMDB": ("nfo_tmdb", "NFO + TMDB"),
    "LOCAL_FALLBACK": ("local", "Local fallback"),
    "LOCAL_ORPHAN": ("local", "Local orphan"),
}


class MovieImageAssetError(Exception):
    def __init__(self, msg, *, code=50080, http_status=500):
        super().__init__(msg)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class MovieImageAsset:
    path: Path
    mimetype: str
    cache_status: str
    source: str
    max_age_seconds: int


def _cache_root() -> Path:
    configured = current_app.config.get("CACHE_DIR") if has_app_context() else None
    return Path(configured or config.CACHE_DIR).expanduser()


def _config_value(name: str, default):
    if has_app_context():
        return current_app.config.get(name, default)
    return getattr(config, name, default)


def _is_truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _utc_timestamp(value) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_source_url(source_url: str) -> str:
    raw = str(source_url or "").strip()
    if not raw:
        raise MovieImageAssetError("Movie image source is empty", code=40480, http_status=404)

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MovieImageAssetError("Movie image source URL is invalid", code=40080, http_status=400)

    host = parsed.hostname.strip().lower()
    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        raise MovieImageAssetError("Movie image source host is not allowed", code=40081, http_status=400)

    try:
        host_ip = ip_address(host)
    except ValueError:
        host_ip = None
    if host_ip and (host_ip.is_private or host_ip.is_loopback or host_ip.is_link_local or host_ip.is_unspecified):
        raise MovieImageAssetError("Movie image source host is not allowed", code=40081, http_status=400)

    return raw


def _movie_image_source(movie, kind: str) -> str:
    if kind == "poster":
        return movie.cover
    if kind == "backdrop":
        return movie.background_cover
    raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)


def movie_image_original_url(movie, kind: str, *, validate=False) -> str | None:
    if kind not in IMAGE_KINDS:
        return None
    source_url = _movie_image_source(movie, kind)
    if not source_url:
        return None

    raw = str(source_url or "").strip()
    if not raw:
        return None
    if validate:
        return _validate_source_url(raw)
    return raw


def movie_image_local_asset_url(movie, kind: str) -> str | None:
    if kind not in IMAGE_KINDS:
        return None
    if not movie_image_original_url(movie, kind):
        return None

    path = movie_image_asset_path(movie.id, kind)
    public_base_url = _asset_public_base_url()
    if public_base_url:
        return f"{public_base_url}{path}"
    return path


def movie_image_asset_url(movie, kind: str) -> str | None:
    if kind not in IMAGE_KINDS:
        return None
    source_url = movie_image_original_url(movie, kind)
    if not source_url:
        return None

    metadata = _load_metadata(movie.id, kind)
    cdn_url = _cdn_asset_url_from_metadata(source_url, metadata)
    if cdn_url:
        return cdn_url

    return movie_image_local_asset_url(movie, kind)


def movie_image_asset_urls(movie, kind: str) -> dict:
    """Return the preferred image URL and the explicit fallback chain.

    Frontends should load ``primary_url`` first. On image load failure, try
    ``fallback_urls`` in order. The intended order is CDN, local backend image
    endpoint, then the original metadata URL.
    """
    if kind not in IMAGE_KINDS:
        return {
            "kind": kind,
            "strategy": "cdn_local_original",
            "primary_url": None,
            "url": None,
            "cdn_url": None,
            "local_url": None,
            "original_url": None,
            "fallback_urls": [],
            "source": "unsupported_kind",
        }

    original_url = movie_image_original_url(movie, kind)
    local_url = movie_image_local_asset_url(movie, kind)
    cdn_url = None
    if original_url:
        metadata = _load_metadata(movie.id, kind)
        cdn_url = _cdn_asset_url_from_metadata(original_url, metadata)

    ordered_urls = [
        ("cdn", cdn_url),
        ("local", local_url),
        ("original", original_url),
    ]
    primary_source = None
    primary_url = None
    fallback_urls = []
    seen = set()
    for source, url in ordered_urls:
        if not url or url in seen:
            continue
        seen.add(url)
        if primary_url is None:
            primary_source = source
            primary_url = url
        else:
            fallback_urls.append(url)

    return {
        "kind": kind,
        "strategy": "cdn_local_original",
        "primary_url": primary_url,
        "url": primary_url,
        "cdn_url": cdn_url,
        "local_url": local_url,
        "original_url": original_url,
        "fallback_urls": fallback_urls,
        "source": primary_source or "none",
    }


def _asset_dir(movie_id: str) -> Path:
    return (_cache_root() / "images" / "movies" / str(movie_id)).resolve()


def _asset_public_base_url() -> str | None:
    raw = str(_config_value("IMAGE_ASSET_PUBLIC_BASE_URL", "") or "").strip()
    return raw.rstrip("/") or None


def _cdn_asset_url_from_metadata(source_url: str, metadata: dict | None) -> str | None:
    if not supercdn_serve_asset_urls_enabled() or not isinstance(metadata, dict):
        return None
    if metadata.get("source_url") != source_url:
        return None
    cdn = metadata.get("cdn")
    if not isinstance(cdn, dict):
        return None
    if cdn.get("provider") != "supercdn" or cdn.get("status") != "uploaded":
        return None
    return cdn.get("url") or cdn.get("public_url")


def _cdn_purge_provider() -> str:
    raw = str(_config_value("IMAGE_ASSET_CDN_PURGE_PROVIDER", "noop") or "noop").strip().lower()
    return raw or "noop"


def movie_image_asset_path(movie_id: str, kind: str) -> str:
    return f"/api/v1/movies/{movie_id}/images/{kind}"


def _metadata_provider_from_scraper_source(scraper_source: str | None) -> tuple[str, str]:
    source = str(scraper_source or "").strip().upper()
    return SCRAPER_SOURCE_GROUPS.get(source, ("unknown", "Unknown"))


def _provider_from_image_url(source_url: str | None) -> tuple[str | None, str | None]:
    raw = str(source_url or "").strip()
    if not raw:
        return None, None

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host.endswith("image.tmdb.org") or host == "tmdb.org" or host.endswith(".tmdb.org"):
        return "tmdb", "TMDB"
    if host.endswith("bgm.tv") or host.endswith("bangumi.tv") or "bangumi" in host:
        return "bangumi", "Bangumi"
    if host.endswith("v.qq.com") or host.endswith("qpic.cn") or host.endswith("puui.qpic.cn"):
        return "tencent_video", "Tencent Video"
    if parsed.scheme in {"http", "https"}:
        return "external", "External URL"
    return "local", "Local path"


def movie_image_source_info(movie, kind: str) -> dict:
    if kind not in IMAGE_KINDS:
        raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)

    field, public_field = IMAGE_SOURCE_FIELDS[kind]
    source_url = str(_movie_image_source(movie, kind) or "").strip()
    scraper_source = getattr(movie, "scraper_source", None)
    metadata_group, metadata_label = _metadata_provider_from_scraper_source(scraper_source)
    url_provider, url_provider_label = _provider_from_image_url(source_url)
    locked_fields = []
    get_locked_fields = getattr(movie, "get_locked_fields", None)
    if callable(get_locked_fields):
        locked_fields = get_locked_fields() or []
    locked = field in set(locked_fields)

    evidence = []
    if locked:
        provider = "manual"
        provider_label = "Manual edit"
        source_type = "manual_override"
        confidence = "medium"
        evidence.append("metadata_field_locked")
    elif url_provider in {"tmdb", "bangumi"}:
        provider = url_provider
        provider_label = url_provider_label
        source_type = "external_metadata"
        confidence = "high"
        evidence.append("image_url_host")
    elif metadata_group in {"tmdb", "bangumi", "nfo", "nfo_tmdb"}:
        provider = metadata_group
        provider_label = metadata_label
        source_type = "metadata_provider"
        confidence = "medium"
        evidence.append("scraper_source")
    elif url_provider:
        provider = url_provider
        provider_label = url_provider_label
        source_type = "image_url"
        confidence = "low"
        evidence.append("image_url_host")
    elif source_url:
        provider = metadata_group
        provider_label = metadata_label
        source_type = "metadata_provider"
        confidence = "low"
        evidence.append("scraper_source")
    else:
        provider = "none"
        provider_label = "No image source"
        source_type = "missing"
        confidence = "none"

    return {
        "kind": kind,
        "field": field,
        "public_field": public_field,
        "source_url": source_url or None,
        "has_source": bool(source_url),
        "source_type": source_type,
        "provider": provider,
        "provider_label": provider_label,
        "scraper_source": scraper_source,
        "metadata_source_group": metadata_group,
        "metadata_source_label": metadata_label,
        "locked": locked,
        "confidence": confidence,
        "evidence": evidence,
    }


def _metadata_path(movie_id: str, kind: str) -> Path:
    return _asset_dir(movie_id) / f"{kind}.json"


def _load_metadata(movie_id: str, kind: str) -> dict:
    path = _metadata_path(movie_id, kind)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_metadata(movie_id: str, kind: str, data: dict) -> None:
    path = _metadata_path(movie_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=f".{kind}.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, sort_keys=True)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _cached_path(movie_id: str, kind: str, metadata: dict | None = None) -> Path | None:
    metadata = metadata if metadata is not None else _load_metadata(movie_id, kind)
    filename = metadata.get("filename") if isinstance(metadata, dict) else None
    if filename:
        candidate = (_asset_dir(movie_id) / filename).resolve()
        try:
            candidate.relative_to(_asset_dir(movie_id))
        except ValueError:
            return None
        if candidate.exists() and candidate.is_file():
            return candidate

    for candidate in sorted(_asset_dir(movie_id).glob(f"{kind}.*")):
        if candidate.suffix.lower() in EXTENSION_MIMETYPES and candidate.is_file():
            return candidate
    return None


def _relative_cache_path(path: Path) -> str:
    root = _cache_root().resolve()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return path.name


def _mimetype_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return EXTENSION_MIMETYPES.get(suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_cdn_logical_path(movie_id: str, kind: str, path: Path, sha256: str) -> str:
    suffix = path.suffix.lower() or ".bin"
    return f"images/movies/{movie_id}/{kind}/{sha256}{suffix}"


def _extension_for_response(source_url: str, content_type: str | None) -> str:
    mimetype = (content_type or "").split(";", 1)[0].strip().lower()
    if mimetype in MIMETYPE_EXTENSIONS:
        return MIMETYPE_EXTENSIONS[mimetype]

    suffix = Path(urlparse(source_url).path).suffix.lower()
    if suffix in EXTENSION_MIMETYPES:
        return suffix

    raise MovieImageAssetError("Movie image source did not return a supported image type", code=50280, http_status=502)


def _validate_image_signature(path: Path, extension: str) -> None:
    with open(path, "rb") as fh:
        header = fh.read(16)

    if extension in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff"):
        return
    if extension == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if extension == ".webp" and len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return
    if extension == ".gif" and (header.startswith(b"GIF87a") or header.startswith(b"GIF89a")):
        return

    raise MovieImageAssetError("Movie image source did not return valid image content", code=50283, http_status=502)


def _proxies_for_url(source_url: str):
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if host.endswith("tmdb.org"):
        return _config_value("TMDB_PROXIES", None)
    return None


def _fetch_image(source_url: str, target: Path) -> tuple[int, str]:
    max_bytes = int(_config_value("IMAGE_ASSET_MAX_BYTES", 20 * 1024 * 1024))
    timeout = float(_config_value("IMAGE_ASSET_TIMEOUT_SECONDS", 15))
    response = requests.get(
        source_url,
        stream=True,
        timeout=timeout,
        proxies=_proxies_for_url(source_url),
        headers={"User-Agent": f"CyberMedia/{getattr(config, 'APP_VERSION', 'unknown')} image-cache"},
    )
    try:
        response.raise_for_status()
        extension = _extension_for_response(source_url, response.headers.get("Content-Type"))
        if target.suffix.lower() != extension:
            target = target.with_suffix(extension)

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=target.suffix, dir=str(target.parent))
        bytes_written = 0
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise MovieImageAssetError("Movie image source is too large", code=50281, http_status=502)
                    fh.write(chunk)
            _validate_image_signature(Path(tmp_path), extension)
            os.replace(tmp_path, target)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        return bytes_written, target.name
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def resolve_movie_image_asset(movie, kind: str, *, refresh=False) -> MovieImageAsset:
    if kind not in IMAGE_KINDS:
        raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)

    source_url = _validate_source_url(_movie_image_source(movie, kind))
    source_info = movie_image_source_info(movie, kind)
    metadata = _load_metadata(movie.id, kind)
    cached = _cached_path(movie.id, kind, metadata)
    max_age_seconds = int(_config_value("IMAGE_ASSET_CACHE_MAX_AGE_SECONDS", 24 * 60 * 60))

    if cached and metadata.get("source_url") == source_url and not _is_truthy(refresh):
        return MovieImageAsset(
            path=cached,
            mimetype=_mimetype_for_path(cached),
            cache_status="hit",
            source=f"movie.{kind}",
            max_age_seconds=max_age_seconds,
        )

    target = _asset_dir(movie.id) / f"{kind}.jpg"
    try:
        size, filename = _fetch_image(source_url, target)
        saved_path = _asset_dir(movie.id) / filename
        _write_metadata(movie.id, kind, {
            "source_url": source_url,
            "filename": filename,
            "mimetype": _mimetype_for_path(saved_path),
            "size": size,
            "updated_at": int(time.time()),
            "source_info": source_info,
        })
        if supercdn_auto_upload_images_enabled():
            sync_movie_image_asset_to_cdn(movie, kind, force=True)
        return MovieImageAsset(
            path=saved_path,
            mimetype=_mimetype_for_path(saved_path),
            cache_status="miss" if not cached else "refresh",
            source=f"movie.{kind}",
            max_age_seconds=max_age_seconds,
        )
    except MovieImageAssetError:
        if cached:
            return MovieImageAsset(
                path=cached,
                mimetype=_mimetype_for_path(cached),
                cache_status="stale",
                source=f"movie.{kind}",
                max_age_seconds=max_age_seconds,
            )
        raise
    except requests.RequestException as e:
        if cached:
            return MovieImageAsset(
                path=cached,
                mimetype=_mimetype_for_path(cached),
                cache_status="stale",
                source=f"movie.{kind}",
                max_age_seconds=max_age_seconds,
            )
        raise MovieImageAssetError(f"Failed to fetch movie image: {e}", code=50282, http_status=502) from e


def get_movie_image_cache_status(movie, kind: str) -> dict:
    if kind not in IMAGE_KINDS:
        raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)

    source_url = str(_movie_image_source(movie, kind) or "").strip()
    source_info = movie_image_source_info(movie, kind)
    asset_urls = movie_image_asset_urls(movie, kind)
    metadata = _load_metadata(movie.id, kind)
    cached = _cached_path(movie.id, kind, metadata)
    source_error = None
    source_valid = False

    if source_url:
        try:
            _validate_source_url(source_url)
            source_valid = True
        except MovieImageAssetError as e:
            source_error = {
                "code": e.code,
                "msg": str(e),
            }

    metadata_source_url = metadata.get("source_url") if isinstance(metadata, dict) else None
    source_changed = bool(cached and metadata_source_url and metadata_source_url != source_url)

    if not source_url:
        cache_state = "missing_source"
    elif source_error:
        cache_state = "invalid_source"
    elif cached and source_changed:
        cache_state = "stale_source"
    elif cached:
        cache_state = "cached"
    else:
        cache_state = "missing"

    cache_payload = None
    if cached:
        updated_at = metadata.get("updated_at") if isinstance(metadata, dict) else None
        try:
            age_seconds = max(0, int(time.time()) - int(updated_at)) if updated_at else None
        except (TypeError, ValueError):
            age_seconds = None

        cache_payload = {
            "filename": cached.name,
            "relative_path": _relative_cache_path(cached),
            "mimetype": metadata.get("mimetype") or _mimetype_for_path(cached),
            "size": int(metadata.get("size") or cached.stat().st_size),
            "updated_at": _utc_timestamp(updated_at),
            "updated_at_epoch": updated_at,
            "age_seconds": age_seconds,
            "source_url": metadata_source_url,
            "source_matches_current": bool(metadata_source_url == source_url),
            "source_info": metadata.get("source_info") if isinstance(metadata.get("source_info"), dict) else None,
        }

    return {
        "kind": kind,
        "asset_url": asset_urls["primary_url"],
        "asset_urls": asset_urls,
        "fallback_urls": asset_urls["fallback_urls"],
        "source_url": source_url or None,
        "source_info": source_info,
        "has_source": bool(source_url),
        "source_valid": source_valid,
        "source_error": source_error,
        "cached": bool(cached),
        "cache_state": cache_state,
        "source_changed": source_changed,
        "cache": cache_payload,
        "cdn": metadata.get("cdn") if isinstance(metadata.get("cdn"), dict) else None,
    }


def get_movie_image_cache_statuses(movie, kinds=None) -> dict:
    selected_kinds = list(kinds or sorted(IMAGE_KINDS))
    items = [get_movie_image_cache_status(movie, kind) for kind in selected_kinds]
    return {
        "movie_id": movie.id,
        "title": movie.title,
        "items": items,
        "summary": {
            "total": len(items),
            "cached": sum(1 for item in items if item["cached"]),
            "missing": sum(1 for item in items if item["cache_state"] == "missing"),
            "missing_source": sum(1 for item in items if item["cache_state"] == "missing_source"),
            "invalid_source": sum(1 for item in items if item["cache_state"] == "invalid_source"),
            "stale_source": sum(1 for item in items if item["cache_state"] == "stale_source"),
        },
    }


def clear_movie_image_asset_cache(movie, kind: str) -> dict:
    if kind not in IMAGE_KINDS:
        raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)

    before = get_movie_image_cache_status(movie, kind)
    movie_id = str(movie.id)
    asset_dir = _asset_dir(movie_id)
    metadata = _load_metadata(movie_id, kind)
    candidates: list[Path] = []

    filename = metadata.get("filename") if isinstance(metadata, dict) else None
    if filename:
        candidate = (asset_dir / filename).resolve()
        try:
            candidate.relative_to(asset_dir)
            candidates.append(candidate)
        except ValueError:
            pass

    if asset_dir.exists():
        for candidate in sorted(asset_dir.glob(f"{kind}.*")):
            if candidate.suffix.lower() in EXTENSION_MIMETYPES and candidate.is_file():
                candidates.append(candidate.resolve())

    deleted_files = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            candidate.relative_to(asset_dir)
        except ValueError:
            continue
        if not candidate.exists() or not candidate.is_file():
            continue

        deleted_file = {
            "filename": candidate.name,
            "relative_path": _relative_cache_path(candidate),
            "mimetype": _mimetype_for_path(candidate),
        }
        try:
            candidate.unlink()
            deleted_files.append(deleted_file)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MovieImageAssetError("Failed to clear movie image cache", code=50081, http_status=500) from exc

    metadata_file = _metadata_path(movie_id, kind)
    deleted_metadata = False
    try:
        if metadata_file.exists() and metadata_file.is_file():
            metadata_file.unlink()
            deleted_metadata = True
    except OSError as exc:
        raise MovieImageAssetError("Failed to clear movie image metadata", code=50082, http_status=500) from exc

    try:
        if asset_dir.exists() and not any(asset_dir.iterdir()):
            asset_dir.rmdir()
    except OSError:
        pass

    after = get_movie_image_cache_status(movie, kind)
    return {
        "movie_id": movie.id,
        "title": movie.title,
        "kind": kind,
        "status": "cleared" if deleted_files or deleted_metadata else "missing",
        "deleted_files": deleted_files,
        "deleted_metadata": deleted_metadata,
        "before": before,
        "after": after,
    }


def plan_movie_image_cdn_purge(movie, kind: str) -> dict:
    if kind not in IMAGE_KINDS:
        raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)

    asset_path = movie_image_asset_path(movie.id, kind)
    asset_url = movie_image_asset_url(movie, kind)
    provider = _cdn_purge_provider()

    result = {
        "provider": provider,
        "status": "skipped",
        "reason": None,
        "asset_path": asset_path,
        "asset_url": asset_url,
        "urls": [],
        "error": None,
    }

    if not asset_url:
        result["reason"] = "missing_asset_url"
        return result

    result["urls"] = [asset_url]
    if provider in {"noop", "manual"}:
        result["status"] = "planned"
        result["reason"] = "cdn_provider_not_configured" if provider == "noop" else "manual_purge_required"
        return result

    result["status"] = "failed"
    result["reason"] = "unsupported_provider"
    result["error"] = {
        "code": 50180,
        "msg": f"Unsupported image CDN purge provider: {provider}",
    }
    return result


def sync_movie_image_asset_to_cdn(movie, kind: str, *, force=False) -> dict:
    if kind not in IMAGE_KINDS:
        raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)

    metadata = _load_metadata(movie.id, kind)
    cached = _cached_path(movie.id, kind, metadata)
    source_url = str(_movie_image_source(movie, kind) or "").strip()
    if not cached:
        return {
            "provider": "supercdn",
            "status": "skipped",
            "reason": "local_cache_missing",
            "bucket": _config_value("SUPERCDN_BUCKET", None),
            "route_profile": _config_value("SUPERCDN_ROUTE_PROFILE", "china_all"),
            "asset_type": "image",
            "logical_path": None,
            "url": None,
            "error": None,
        }
    if metadata.get("source_url") != source_url:
        return {
            "provider": "supercdn",
            "status": "skipped",
            "reason": "stale_source",
            "bucket": _config_value("SUPERCDN_BUCKET", None),
            "route_profile": _config_value("SUPERCDN_ROUTE_PROFILE", "china_all"),
            "asset_type": "image",
            "logical_path": None,
            "url": None,
            "error": None,
        }

    file_sha = _sha256_file(cached)
    existing = metadata.get("cdn") if isinstance(metadata.get("cdn"), dict) else None
    if (
        not _is_truthy(force)
        and existing
        and existing.get("provider") == "supercdn"
        and existing.get("status") == "uploaded"
        and existing.get("sha256") == file_sha
        and existing.get("url")
    ):
        return {**existing, "status": "cached", "reason": "already_uploaded"}

    logical_path = _image_cdn_logical_path(movie.id, kind, cached, file_sha)
    upload = upload_file_to_supercdn(
        cached,
        logical_path=logical_path,
        asset_type="image",
        cache_control=_config_value("SUPERCDN_BUCKET_CACHE_CONTROL", "public, max-age=86400"),
    )
    upload.update({
        "source_url": source_url,
        "kind": kind,
        "filename": cached.name,
    })
    if upload.get("status") in {"uploaded", "failed"}:
        metadata["cdn"] = upload
        _write_metadata(movie.id, kind, metadata)
    return upload


def refresh_movie_image_asset_for_cdn(
    movie,
    kind: str,
    *,
    purge=True,
    clear_cache=False,
    preload=True,
    refresh=True,
) -> dict:
    if kind not in IMAGE_KINDS:
        raise MovieImageAssetError("Unsupported movie image kind", code=40082, http_status=400)

    before = get_movie_image_cache_status(movie, kind)
    purge_result = plan_movie_image_cdn_purge(movie, kind) if purge else None
    clear_result = clear_movie_image_asset_cache(movie, kind) if clear_cache else None
    preload_result = preload_movie_image_asset(movie, kind, refresh=refresh) if preload else None
    cdn_result = sync_movie_image_asset_to_cdn(movie, kind, force=False) if supercdn_auto_upload_images_enabled() else None
    after = get_movie_image_cache_status(movie, kind)

    status = "planned"
    reason = "purge_planned" if purge_result else "no_purge_requested"
    error = None
    if purge_result and purge_result["status"] == "failed":
        status = "failed"
        reason = purge_result["reason"]
        error = purge_result.get("error")
    elif preload_result and preload_result["status"] == "failed":
        status = "failed"
        reason = preload_result["reason"]
        error = preload_result.get("error")
    elif cdn_result and cdn_result.get("status") == "failed":
        status = "failed"
        reason = cdn_result.get("reason")
        error = cdn_result.get("error")
    elif preload_result and preload_result["status"] in {"cached", "stale"}:
        status = "refreshed"
        reason = preload_result["reason"]
    elif clear_result and clear_result["status"] == "cleared":
        status = "cleared"
        reason = "local_cache_cleared"
    elif preload_result and preload_result["status"] == "skipped":
        status = "skipped"
        reason = preload_result["reason"]
    elif purge_result and purge_result["status"] == "skipped":
        status = "skipped"
        reason = purge_result["reason"]

    return {
        "movie_id": movie.id,
        "title": movie.title,
        "kind": kind,
        "status": status,
        "reason": reason,
        "error": error,
        "asset_url": before.get("asset_url") or after.get("asset_url"),
        "before": before,
        "after": after,
        "purge": purge_result,
        "clear_cache": clear_result,
        "preload": preload_result,
        "cdn": cdn_result or after.get("cdn"),
    }


def preload_movie_image_asset(movie, kind: str, *, refresh=False) -> dict:
    before = get_movie_image_cache_status(movie, kind)
    if before["cache_state"] == "missing_source":
        return {
            "movie_id": movie.id,
            "title": movie.title,
            "kind": kind,
            "status": "skipped",
            "reason": "missing_source",
            "before": before,
            "after": before,
        }
    if before["cache_state"] == "invalid_source":
        return {
            "movie_id": movie.id,
            "title": movie.title,
            "kind": kind,
            "status": "failed",
            "reason": "invalid_source",
            "error": before.get("source_error"),
            "before": before,
            "after": before,
        }

    try:
        asset = resolve_movie_image_asset(movie, kind, refresh=refresh)
        after = get_movie_image_cache_status(movie, kind)
        status = "stale" if asset.cache_status == "stale" else "cached"
        return {
            "movie_id": movie.id,
            "title": movie.title,
            "kind": kind,
            "status": status,
            "reason": asset.cache_status,
            "before": before,
            "after": after,
        }
    except MovieImageAssetError as e:
        return {
            "movie_id": movie.id,
            "title": movie.title,
            "kind": kind,
            "status": "failed",
            "reason": "fetch_failed",
            "error": {
                "code": e.code,
                "msg": str(e),
            },
            "before": before,
            "after": get_movie_image_cache_status(movie, kind),
        }
