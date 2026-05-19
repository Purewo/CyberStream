import importlib.util
import gzip
import io
import os
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path

from flask import current_app, has_app_context

from backend import config


SUPPORTED_ONLINE_SUBTITLE_PROVIDERS = ("subhd", "srtku")
IGNORED_ONLINE_SUBTITLE_PROVIDERS = {
    "opensubtitles": "disabled_low_quality_source",
}
SUBTITLE_SUFFIXES = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}
TEXT_SUBTITLE_SUFFIXES = {".srt", ".ass", ".ssa", ".vtt"}
ONLINE_TEXT_SUBTITLE_FORMATS = {"srt", "ass", "ssa", "vtt"}
ONLINE_BITMAP_SUBTITLE_FORMATS = {"sub", "sup"}
COMPOUND_ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")
MAX_EXTRACTED_SUBTITLE_BYTES = 30 * 1024 * 1024
MAX_NESTED_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 3
DEFAULT_QUERY_ATTEMPT_LIMIT = 6
MAX_QUERY_ATTEMPT_LIMIT = 12
CHINESE_NUMBERS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}


class OnlineSubtitleError(ValueError):
    def __init__(self, message, code=40060, http_status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


def _skill_dir():
    configured = current_app.config.get("GET_SUBTITLES_SKILL_DIR") if has_app_context() else None
    return Path(configured or config.GET_SUBTITLES_SKILL_DIR).expanduser()


def _load_skill_module(module_name):
    script_path = _skill_dir() / "scripts" / f"{module_name}.py"
    if not script_path.exists():
        raise OnlineSubtitleError(
            f"Subtitle skill script missing: {module_name}",
            code=50060,
            http_status=500,
        )
    spec = importlib.util.spec_from_file_location(f"codex_get_subtitles_{module_name}", script_path)
    if not spec or not spec.loader:
        raise OnlineSubtitleError(
            f"Subtitle skill script cannot be loaded: {module_name}",
            code=50061,
            http_status=500,
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_positive_int(value, default, max_value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, max_value))


def _normalize_provider_list(raw):
    if not raw:
        requested = list(SUPPORTED_ONLINE_SUBTITLE_PROVIDERS)
    elif isinstance(raw, str):
        requested = [item.strip().lower() for item in raw.split(",") if item.strip()]
    else:
        requested = [str(item or "").strip().lower() for item in raw if str(item or "").strip()]

    providers = []
    ignored = []
    unsupported = []
    for provider in requested:
        if provider in IGNORED_ONLINE_SUBTITLE_PROVIDERS:
            ignored.append({
                "id": provider,
                "reason": IGNORED_ONLINE_SUBTITLE_PROVIDERS[provider],
            })
            continue
        if provider not in SUPPORTED_ONLINE_SUBTITLE_PROVIDERS:
            unsupported.append(provider)
            continue
        if provider not in providers:
            providers.append(provider)

    return providers, ignored, unsupported


def _resource_search_query(resource, override=None):
    queries = _resource_search_queries(resource, override=override)
    return queries[0] if queries else ""


def _append_query_variant(queries, seen, value):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _append_query_variant(queries, seen, item)
        return

    raw = str(value or "").strip()
    if not raw:
        return
    normalized = re.sub(r"\s+", " ", raw).strip()
    key = normalized.lower()
    if key not in seen:
        queries.append(normalized)
        seen.add(key)


def _chinese_number(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[number]
    if 10 < number < 20:
        return f"十{CHINESE_NUMBERS[number - 10]}"
    if 20 <= number < 100:
        tens, ones = divmod(number, 10)
        suffix = CHINESE_NUMBERS[ones] if ones else ""
        return f"{CHINESE_NUMBERS[tens]}十{suffix}"
    return str(number)


def _append_tv_query_variants(queries, seen, title, season, episode):
    title = str(title or "").strip()
    if not title:
        return
    if season is not None and episode is not None:
        season_text = _chinese_number(season)
        episode_text = _chinese_number(episode)
        _append_query_variant(queries, seen, f"{title} S{int(season):02d}E{int(episode):02d}")
        _append_query_variant(queries, seen, f"{title} 第{season}季 第{episode}集")
        if season_text and episode_text:
            _append_query_variant(queries, seen, f"{title} 第{season_text}季 第{episode_text}集")
    elif episode is not None:
        _append_query_variant(queries, seen, f"{title} EP{int(episode):02d}")
        _append_query_variant(queries, seen, f"{title} 第{episode}集")

    if season is not None:
        season_text = _chinese_number(season)
        _append_query_variant(queries, seen, f"{title} S{int(season):02d}")
        _append_query_variant(queries, seen, f"{title} 第{season}季")
        if season_text:
            _append_query_variant(queries, seen, f"{title} 第{season_text}季")
        _append_query_variant(queries, seen, f"{title} Season {int(season)}")
        _append_query_variant(queries, seen, f"{title} {int(season)}")


def _append_trailing_season_keyword_variants(queries, seen, value):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _append_trailing_season_keyword_variants(queries, seen, item)
        return

    raw = str(value or "").strip()
    match = re.match(r"^(.+?)([0-9]{1,2})$", raw)
    if not match:
        return
    title = match.group(1).strip()
    season = int(match.group(2))
    if not title:
        return
    season_text = _chinese_number(season)
    _append_query_variant(queries, seen, f"{title} {season}")
    _append_query_variant(queries, seen, f"{title} 第{season}季")
    if season_text:
        _append_query_variant(queries, seen, f"{title} 第{season_text}季")


def _resource_search_queries(resource, override=None):
    queries = []
    seen = set()
    _append_query_variant(queries, seen, override)
    _append_trailing_season_keyword_variants(queries, seen, override)

    movie = getattr(resource, "movie", None)
    titles = []
    year = None
    if movie:
        titles.extend([movie.original_title, movie.title])
        year = movie.year
    season = getattr(resource, "season", None)
    episode = getattr(resource, "episode", None)

    for title in titles:
        _append_query_variant(queries, seen, title)
        if year and str(year) not in str(title or ""):
            _append_query_variant(queries, seen, f"{title} {year}")
        _append_tv_query_variants(queries, seen, title, season, episode)

    filename = getattr(resource, "filename", None) or getattr(resource, "path", "")
    filename_stem = Path(str(filename)).stem
    _append_query_variant(queries, seen, filename_stem)
    if year and str(year) not in filename_stem:
        _append_query_variant(queries, seen, f"{filename_stem} {year}")

    return queries


def _to_int(value):
    match = re.search(r"\d+", str(value or "").replace(",", ""))
    return int(match.group(0)) if match else 0


def _detail_id_from_url(url):
    raw = str(url or "").strip().rstrip("/")
    if not raw:
        return ""
    return raw.split("/")[-1]


def _normalize_languages(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value or "").strip()
    return [raw] if raw else []


def _candidate_episode_text(item):
    parts = [
        item.get("title"),
        item.get("film_name"),
        item.get("quality"),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _text_has_any(text, patterns):
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _episode_rank(resource, item):
    season = getattr(resource, "season", None) if resource is not None else None
    episode = getattr(resource, "episode", None) if resource is not None else None
    if season is None and episode is None:
        return 0

    text = _candidate_episode_text(item)
    season_number = int(season) if season is not None else None
    episode_number = int(episode) if episode is not None else None
    season_text = _chinese_number(season_number) if season_number is not None else None
    episode_text = _chinese_number(episode_number) if episode_number is not None else None

    if season_number is not None and episode_number is not None:
        exact_patterns = [
            rf"s0*{season_number}\s*e0*{episode_number}",
            rf"{season_number}\s*x\s*0*{episode_number}",
            rf"第\s*0*{season_number}\s*季\s*第\s*0*{episode_number}\s*[集话話]",
            rf"season\s*0*{season_number}\D+episode\s*0*{episode_number}",
        ]
        if season_text and episode_text:
            exact_patterns.append(rf"第\s*{season_text}\s*季\s*第\s*{episode_text}\s*[集话話]")
        if _text_has_any(text, exact_patterns):
            return 0

    if season_number is not None:
        same_season_patterns = [
            rf"s0*{season_number}(?!\d)",
            rf"season\s*0*{season_number}(?!\d)",
            rf"第\s*0*{season_number}\s*季",
        ]
        if season_text:
            same_season_patterns.append(rf"第\s*{season_text}\s*季")
        if _text_has_any(text, same_season_patterns):
            return 1

        other_season_patterns = [
            r"s0*[0-9]{1,2}",
            r"season\s*[0-9]{1,2}",
            r"第\s*[0-9一二三四五六七八九十]{1,3}\s*季",
        ]
        if _text_has_any(text, other_season_patterns):
            return 3

    return 2


def _has_exact_episode_match(items, resource):
    return any(_episode_rank(resource, item) == 0 for item in items or [])


def _candidate_format_tokens(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return set()
    tokens = set()
    if "subrip" in raw:
        tokens.add("srt")
    for subtitle_format in ONLINE_TEXT_SUBTITLE_FORMATS | ONLINE_BITMAP_SUBTITLE_FORMATS:
        if re.search(rf"(^|[^a-z0-9]){re.escape(subtitle_format)}([^a-z0-9]|$)", raw):
            tokens.add(subtitle_format)
    return tokens


def _preferred_candidate_format(tokens):
    for subtitle_format in ("ass", "srt", "ssa", "vtt", "sub", "sup"):
        if subtitle_format in tokens:
            return subtitle_format
    return None


def _candidate_web_player_payload(format_value):
    tokens = _candidate_format_tokens(format_value)
    source_format = _preferred_candidate_format(tokens)
    if tokens & ONLINE_TEXT_SUBTITLE_FORMATS:
        return {
            "supported": True,
            "format": "vtt",
            "native_supported": source_format == "vtt",
            "requires_conversion": source_format != "vtt",
            "source_format": source_format,
            "reason": None,
        }
    if tokens & ONLINE_BITMAP_SUBTITLE_FORMATS:
        return {
            "supported": False,
            "format": None,
            "native_supported": False,
            "requires_conversion": False,
            "source_format": source_format,
            "reason": "bitmap_subtitle_not_supported",
        }
    return {
        "supported": None,
        "format": None,
        "native_supported": False,
        "requires_conversion": False,
        "source_format": None,
        "reason": "format_unknown_until_download",
    }


def _candidate_web_rank(item):
    tokens = _candidate_format_tokens(item.get("format"))
    if tokens & ONLINE_TEXT_SUBTITLE_FORMATS:
        return 0
    if not tokens:
        return 1
    if tokens & ONLINE_BITMAP_SUBTITLE_FORMATS:
        return 2
    return 1


def _annotate_candidate_compatibility(item):
    item["format_normalized"] = _preferred_candidate_format(_candidate_format_tokens(item.get("format")))
    item["web_player"] = _candidate_web_player_payload(item.get("format"))
    return item


def _candidate_sort_key(item, resource=None):
    provider_rank = {"subhd": 0, "srtku": 1}.get(item.get("provider_id"), 9)
    return (
        _episode_rank(resource, item),
        _candidate_web_rank(item),
        provider_rank,
        -int(item.get("download_count") or 0),
        item.get("title") or "",
    )


def _normalize_subhd_item(item):
    sub_hash = str(item.get("hash") or "").strip()
    if not sub_hash:
        return None
    candidate_id = f"subhd:{sub_hash}"
    return _annotate_candidate_compatibility({
        "id": candidate_id,
        "candidate_id": candidate_id,
        "provider_id": "subhd",
        "provider_name": "SubHD",
        "source_key": sub_hash,
        "title": item.get("title") or item.get("film_name") or "",
        "film_name": item.get("film_name") or "",
        "quality": item.get("quality") or "",
        "download_count": _to_int(item.get("download_number")),
        "download_number": item.get("download_number") or "",
        "update_time": item.get("update_time") or "",
        "language": _normalize_languages(item.get("language")),
        "format": item.get("format") or "",
        "file_size": item.get("file_size") or "",
        "uploader": item.get("uploader") or "",
        "details": {
            "source_key": sub_hash,
        },
    })


def _normalize_srtku_item(item, film_title=None):
    detail_id = _detail_id_from_url(item.get("detail_url"))
    if not detail_id:
        return None
    candidate_id = f"srtku:{detail_id}"
    return _annotate_candidate_compatibility({
        "id": candidate_id,
        "candidate_id": candidate_id,
        "provider_id": "srtku",
        "provider_name": "SrtKu",
        "source_key": detail_id,
        "title": item.get("title") or "",
        "film_name": film_title or "",
        "quality": item.get("quality") or "",
        "download_count": _to_int(item.get("download_number")),
        "download_number": item.get("download_number") or "",
        "update_time": item.get("update_time") or "",
        "language": _normalize_languages(item.get("language")),
        "format": "",
        "file_size": "",
        "uploader": "",
        "details": {
            "source_key": detail_id,
        },
    })


def _search_subhd(query, limit):
    module = _load_skill_module("subhd_core")
    session = module.make_session()
    rows = module.search_subtitle(query, session=session)
    items = []
    for row in rows or []:
        item = _normalize_subhd_item(row)
        if item:
            items.append(item)
        if len(items) >= limit:
            break
    return items


def _search_srtku(query, limit):
    module = _load_skill_module("srtku_core")
    session = module.make_session()
    film_payload = module.search_film(query, page=1, session=session)
    titles = film_payload.get("titles") or []
    list_urls = film_payload.get("list_urls") or []
    items = []

    for index, list_url in enumerate(list_urls[:3]):
        film_title = titles[index] if index < len(titles) else ""
        rows = module.search_subtitle(list_url, session=session)
        for row in rows or []:
            item = _normalize_srtku_item(row, film_title=film_title)
            if item:
                items.append(item)
            if len(items) >= limit:
                return items
    return items


def search_online_subtitles(resource, query=None, providers=None, limit=50, max_query_attempts=None):
    limit = _parse_positive_int(limit, default=50, max_value=50)
    all_search_queries = _resource_search_queries(resource, override=query)
    if not all_search_queries:
        raise OnlineSubtitleError("Subtitle search query is required", code=40060)
    query_attempt_limit = _parse_positive_int(
        max_query_attempts,
        default=DEFAULT_QUERY_ATTEMPT_LIMIT,
        max_value=MAX_QUERY_ATTEMPT_LIMIT,
    )
    search_queries = all_search_queries[:query_attempt_limit]

    provider_ids, ignored, unsupported = _normalize_provider_list(providers)
    provider_errors = []
    provider_query_used = {}
    provider_query_attempts = {}
    items = []

    for provider_id in provider_ids:
        provider_items = []
        for search_query in search_queries:
            provider_query_attempts.setdefault(provider_id, []).append(search_query)
            try:
                query_items = []
                if provider_id == "subhd":
                    query_items = _search_subhd(search_query, limit)
                elif provider_id == "srtku":
                    query_items = _search_srtku(search_query, limit)
                if query_items:
                    provider_items.extend(query_items)
                    provider_query_used[provider_id] = search_query
                    if getattr(resource, "season", None) is None and getattr(resource, "episode", None) is None:
                        break
                    if _has_exact_episode_match(query_items, resource):
                        break
            except Exception as e:
                provider_errors.append({
                    "provider_id": provider_id,
                    "query": search_query,
                    "message": str(e),
                })
                break
        items.extend(provider_items)

    deduped = {}
    for item in items:
        item_id = item.get("id")
        if item_id and item_id not in deduped:
            deduped[item_id] = item

    sorted_items = sorted(deduped.values(), key=lambda item: _candidate_sort_key(item, resource))
    items = []
    count_by_provider = {}
    for item in sorted_items:
        provider_id = item.get("provider_id")
        if count_by_provider.get(provider_id, 0) >= limit:
            continue
        items.append(item)
        count_by_provider[provider_id] = count_by_provider.get(provider_id, 0) + 1

    return {
        "query": all_search_queries[0],
        "query_candidates": all_search_queries,
        "query_attempt_candidates": search_queries,
        "query_attempt_limit": query_attempt_limit,
        "query_attempts_truncated": len(all_search_queries) > len(search_queries),
        "resource_id": getattr(resource, "id", None),
        "movie_id": getattr(resource, "movie_id", None),
        "providers": {
            "enabled": list(SUPPORTED_ONLINE_SUBTITLE_PROVIDERS),
            "used": provider_ids,
            "query_used": provider_query_used,
            "query_attempts": provider_query_attempts,
            "ignored": ignored,
            "unsupported": unsupported,
            "errors": provider_errors,
        },
        "items": items,
        "count": len(items),
        "count_by_provider": count_by_provider,
        "limit_per_provider": limit,
    }


def _parse_candidate_id(candidate_id):
    raw = str(candidate_id or "").strip()
    if ":" not in raw:
        raise OnlineSubtitleError("Invalid subtitle candidate id", code=40061)
    provider_id, source_key = raw.split(":", 1)
    provider_id = provider_id.strip().lower()
    source_key = source_key.strip()
    if provider_id not in SUPPORTED_ONLINE_SUBTITLE_PROVIDERS:
        raise OnlineSubtitleError("Unsupported subtitle provider", code=40062)
    if not source_key or not re.match(r"^[A-Za-z0-9_.-]+$", source_key):
        raise OnlineSubtitleError("Invalid subtitle candidate key", code=40063)
    return provider_id, source_key


def _safe_download_filename(resource, provider_id, source_key, extension):
    base = Path(str(getattr(resource, "filename", "") or getattr(resource, "path", "") or "subtitle")).stem
    base = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", ".", base).strip(".") or "subtitle"
    ext = str(extension or "srt").strip().lower().lstrip(".")
    ext = re.sub(r"[^a-z0-9]+", "", ext) or "srt"
    return f"{base}.{provider_id}.{source_key[:12]}.{ext}"


def _basename(filename):
    raw = str(filename or "").strip().replace("\\", "/")
    return raw.rsplit("/", 1)[-1] or "subtitle"


def _compound_suffix(filename):
    name = _basename(filename).lower()
    for suffix in COMPOUND_ARCHIVE_SUFFIXES:
        if name.endswith(suffix):
            return suffix
    return Path(name).suffix.lower()


def _is_subtitle_filename(filename):
    return Path(_basename(filename)).suffix.lower() in SUBTITLE_SUFFIXES


def _is_supported_archive_kind(kind):
    return kind in {"zip", "7z", "tar", "gzip"}


def _safe_extracted_filename(resource, provider_id, source_key, filename):
    basename = _basename(filename)
    suffix = Path(basename).suffix.lower()
    if suffix not in SUBTITLE_SUFFIXES:
        return _safe_download_filename(resource, provider_id, source_key, "srt")

    stem = Path(basename).stem
    stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", ".", stem).strip(".")
    if not stem:
        return _safe_download_filename(resource, provider_id, source_key, suffix)
    return f"{stem}{suffix}"


def _subtitle_charset(content):
    payload = content or b""
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if payload.startswith(b"\xef\xbb\xbf"):
        return "utf-8"
    try:
        payload.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        try:
            payload.decode("gb18030")
            return "gb18030"
        except UnicodeDecodeError:
            return None


def _subtitle_mime_type(filename, content=None):
    suffix = Path(str(filename or "")).suffix.lower()
    charset = _subtitle_charset(content) if suffix in TEXT_SUBTITLE_SUFFIXES else None
    charset_part = f"; charset={charset}" if charset else ""
    if suffix == ".srt":
        return f"application/x-subrip{charset_part}"
    if suffix == ".vtt":
        return f"text/vtt{charset_part}"
    if suffix in {".ass", ".ssa"}:
        return f"text/plain{charset_part}"
    if suffix == ".sub":
        return f"text/plain{charset_part}"
    if suffix == ".sup":
        return "application/octet-stream"
    return "application/octet-stream"


def _subtitle_rank(filename):
    suffix = Path(_basename(filename)).suffix.lower()
    return {
        ".ass": 0,
        ".ssa": 1,
        ".srt": 2,
        ".vtt": 3,
        ".sub": 4,
        ".sup": 5,
    }.get(suffix, 99)


def _pick_best_subtitle_candidate(candidates):
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            _subtitle_rank(item["filename"]),
            len(_basename(item["filename"])),
            _basename(item["filename"]).lower(),
        ),
    )[0]


def _ensure_subtitle_size(content, filename):
    if len(content) > MAX_EXTRACTED_SUBTITLE_BYTES:
        raise OnlineSubtitleError(
            f"Subtitle file is too large: {_basename(filename)}",
            code=41369,
            http_status=413,
        )


def _ensure_nested_archive_size(content, filename):
    if len(content) > MAX_NESTED_ARCHIVE_BYTES:
        raise OnlineSubtitleError(
            f"Nested subtitle archive is too large: {_basename(filename)}",
            code=41369,
            http_status=413,
        )


def _archive_kind(filename, content):
    suffix = _compound_suffix(filename)
    if content.startswith(b"PK\x03\x04") or content.startswith(b"PK\x05\x06") or suffix == ".zip":
        return "zip"
    if content.startswith(b"7z\xbc\xaf\x27\x1c") or suffix == ".7z":
        return "7z"
    if content.startswith(b"Rar!\x1a\x07") or suffix == ".rar":
        return "rar"
    if suffix in {".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz"}:
        return "tar"
    if suffix == ".gz":
        return "gzip"
    return None


def _candidate_entry_name(parent_entry, entry_name):
    if not parent_entry:
        return entry_name
    return f"{parent_entry}!{entry_name}"


def _collect_subtitle_candidate(filename, content, entry_name):
    _ensure_subtitle_size(content, filename)
    return {
        "filename": _basename(filename),
        "content": content,
        "entry_name": entry_name or filename,
    }


def _extract_zip_subtitles(content, depth=0, parent_entry=None):
    candidates = []
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                entry_name = _candidate_entry_name(parent_entry, info.filename)
                try:
                    data = archive.read(info)
                except RuntimeError as e:
                    raise OnlineSubtitleError(
                        "Subtitle archive is encrypted or password protected",
                        code=50267,
                        http_status=502,
                    ) from e
                if _is_subtitle_filename(info.filename) and not _archive_kind(info.filename, data):
                    candidates.append(_collect_subtitle_candidate(info.filename, data, entry_name))
                    continue

                kind = _archive_kind(info.filename, data)
                if _is_supported_archive_kind(kind) and depth < MAX_ARCHIVE_DEPTH:
                    _ensure_nested_archive_size(data, info.filename)
                    candidates.extend(_extract_archive_subtitles(info.filename, data, depth + 1, entry_name))
    except zipfile.BadZipFile as e:
        raise OnlineSubtitleError("Subtitle zip archive cannot be parsed", code=50267, http_status=502) from e
    return candidates


def _extract_tar_subtitles(content, depth=0, parent_entry=None):
    candidates = []
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                fp = archive.extractfile(member)
                if not fp:
                    continue
                entry_name = _candidate_entry_name(parent_entry, member.name)
                kind = _archive_kind(member.name, b"")
                if _is_subtitle_filename(member.name):
                    data = fp.read(MAX_EXTRACTED_SUBTITLE_BYTES + 1)
                    candidates.append(_collect_subtitle_candidate(member.name, data, entry_name))
                    continue

                if _is_supported_archive_kind(kind) and depth < MAX_ARCHIVE_DEPTH:
                    data = fp.read(MAX_NESTED_ARCHIVE_BYTES + 1)
                    _ensure_nested_archive_size(data, member.name)
                    candidates.extend(_extract_archive_subtitles(member.name, data, depth + 1, entry_name))
                    continue
    except tarfile.TarError as e:
        raise OnlineSubtitleError("Subtitle tar archive cannot be parsed", code=50267, http_status=502) from e
    return candidates


def _extract_7z_subtitles(content, depth=0, parent_entry=None):
    try:
        import py7zr
    except ImportError as e:
        raise OnlineSubtitleError("7z subtitle archive support is not installed", code=50266, http_status=502) from e

    candidates = []
    with tempfile.TemporaryDirectory(prefix="cyber-subtitle-7z-") as tmpdir:
        archive_path = Path(tmpdir) / "download.7z"
        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir()
        archive_path.write_bytes(content)
        try:
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=extract_dir)
        except Exception as e:
            raise OnlineSubtitleError("Subtitle 7z archive cannot be parsed", code=50267, http_status=502) from e

        root = extract_dir.resolve()
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUBTITLE_SUFFIXES:
                if depth >= MAX_ARCHIVE_DEPTH:
                    continue
                kind = _archive_kind(path.name, b"")
                if not _is_supported_archive_kind(kind):
                    continue
                if path.stat().st_size > MAX_NESTED_ARCHIVE_BYTES:
                    raise OnlineSubtitleError(
                        f"Nested subtitle archive is too large: {path.name}",
                        code=41369,
                        http_status=413,
                    )
                entry_name = _candidate_entry_name(parent_entry, str(path.relative_to(root)))
                candidates.extend(_extract_archive_subtitles(path.name, path.read_bytes(), depth + 1, entry_name))
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if resolved.stat().st_size > MAX_EXTRACTED_SUBTITLE_BYTES:
                raise OnlineSubtitleError(
                    f"Subtitle file is too large: {resolved.name}",
                    code=41369,
                    http_status=413,
                )
            data = resolved.read_bytes()
            entry_name = _candidate_entry_name(parent_entry, str(resolved.relative_to(root)))
            candidates.append(_collect_subtitle_candidate(resolved.name, data, entry_name))
    return candidates


def _extract_gzip_subtitle(filename, content, depth=0, parent_entry=None):
    inner_name = _basename(filename)
    if inner_name.lower().endswith(".gz"):
        inner_name = inner_name[:-3]
    try:
        data = gzip.decompress(content)
    except OSError as e:
        raise OnlineSubtitleError("Subtitle gzip archive cannot be parsed", code=50267, http_status=502) from e
    entry_name = _candidate_entry_name(parent_entry, inner_name)
    if _is_subtitle_filename(inner_name) and not _archive_kind(inner_name, data):
        return [_collect_subtitle_candidate(inner_name, data, entry_name)]
    kind = _archive_kind(inner_name, data)
    if _is_supported_archive_kind(kind) and depth < MAX_ARCHIVE_DEPTH:
        _ensure_nested_archive_size(data, inner_name)
        return _extract_archive_subtitles(inner_name, data, depth + 1, entry_name)
    return []


def _extract_archive_subtitles(filename, content, depth=0, parent_entry=None):
    kind = _archive_kind(filename, content)
    if kind == "zip":
        return _extract_zip_subtitles(content, depth=depth, parent_entry=parent_entry)
    if kind == "tar":
        return _extract_tar_subtitles(content, depth=depth, parent_entry=parent_entry)
    if kind == "7z":
        return _extract_7z_subtitles(content, depth=depth, parent_entry=parent_entry)
    if kind == "gzip":
        return _extract_gzip_subtitle(filename, content, depth=depth, parent_entry=parent_entry)
    return []


def normalize_downloaded_subtitle_file(resource, provider_id, source_key, filename, content, meta=None):
    payload = content or b""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    elif not isinstance(payload, bytes):
        payload = bytes(payload)
    if not payload:
        raise OnlineSubtitleError("Downloaded subtitle file is empty", code=50265, http_status=502)

    meta = dict(meta or {})
    raw_filename = _basename(filename or _safe_download_filename(resource, provider_id, source_key, "srt"))

    if _is_subtitle_filename(raw_filename) and not _archive_kind(raw_filename, payload):
        _ensure_subtitle_size(payload, raw_filename)
        safe_filename = _safe_extracted_filename(resource, provider_id, source_key, raw_filename)
        meta.update({
            "provider_id": provider_id,
            "extracted": False,
            "original_filename": raw_filename,
        })
        return {
            "filename": safe_filename,
            "mime_type": _subtitle_mime_type(safe_filename, payload),
            "content": payload,
            "meta": meta,
        }

    kind = _archive_kind(raw_filename, payload)
    if kind == "rar":
        raise OnlineSubtitleError(
            "RAR subtitle archives are not supported by the server",
            code=41566,
            http_status=415,
        )
    if not kind:
        raise OnlineSubtitleError(
            "Downloaded file is not a supported subtitle or archive",
            code=50268,
            http_status=502,
        )

    candidates = _extract_archive_subtitles(raw_filename, payload)

    selected = _pick_best_subtitle_candidate(candidates)
    if not selected:
        raise OnlineSubtitleError(
            "Downloaded archive does not contain a supported subtitle file",
            code=50268,
            http_status=502,
        )

    safe_filename = _safe_extracted_filename(resource, provider_id, source_key, selected["filename"])
    meta.update({
        "provider_id": provider_id,
        "extracted": True,
        "archive_filename": raw_filename,
        "archive_kind": kind,
        "selected_entry": selected.get("entry_name") or selected["filename"],
    })
    return {
        "filename": safe_filename,
        "mime_type": _subtitle_mime_type(safe_filename, selected["content"]),
        "content": selected["content"],
        "meta": meta,
    }


def _download_subhd(resource, source_key):
    module = _load_skill_module("subhd_core")
    session = module.make_session()
    result = module.download_subtitle(source_key, session=session, max_retries=5)
    if not result.get("success"):
        raise OnlineSubtitleError(
            f"SubHD download failed: {result.get('reason') or 'unknown'}",
            code=50260,
            http_status=502,
        )
    filename = _safe_download_filename(resource, "subhd", source_key, result.get("ext") or "zip")
    return normalize_downloaded_subtitle_file(
        resource,
        "subhd",
        source_key,
        filename,
        result.get("content") or b"",
        meta={"attempts": result.get("attempts")},
    )


def _download_srtku(resource, source_key, download_index=0):
    module = _load_skill_module("srtku_core")
    session = module.make_session()
    detail_url = f"{module.BASE}/detail/{source_key}"
    links = module.get_download_links(detail_url, session=session)
    if not links:
        raise OnlineSubtitleError("SrtKu download links not found", code=50261, http_status=502)

    try:
        index = int(download_index)
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(index, len(links) - 1))
    selected = links[index]
    download_url = selected.get("download_links")
    if not download_url:
        raise OnlineSubtitleError("SrtKu download link missing", code=50262, http_status=502)

    with tempfile.TemporaryDirectory(prefix="cyber-subtitle-") as tmpdir:
        result = module.download_subtitle(download_url, outdir=tmpdir, session=session)
        if not result.get("ok"):
            raise OnlineSubtitleError(
                f"SrtKu download failed: {result.get('error') or 'unknown'}",
                code=50263,
                http_status=502,
            )
        selected_path = result.get("selected_subtitle") or result.get("saved_path")
        if not selected_path:
            raise OnlineSubtitleError("SrtKu subtitle file missing", code=50264, http_status=502)
        path = Path(selected_path)
        filename = path.name or _safe_download_filename(resource, "srtku", source_key, path.suffix or "srt")
        return normalize_downloaded_subtitle_file(
            resource,
            "srtku",
            source_key,
            filename,
            path.read_bytes(),
            meta={
                "server": selected.get("provider"),
                "bytes": result.get("bytes"),
                "source_extracted": result.get("extracted"),
            },
        )


def download_online_subtitle(resource, candidate_id, download_index=0):
    provider_id, source_key = _parse_candidate_id(candidate_id)
    if provider_id == "subhd":
        return _download_subhd(resource, source_key)
    if provider_id == "srtku":
        return _download_srtku(resource, source_key, download_index=download_index)
    raise OnlineSubtitleError("Unsupported subtitle provider", code=40062)


def _confirmation_enabled(value):
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "confirmed"}
    return False


def _subtitle_cache_dir():
    configured = current_app.config.get("CACHE_DIR") if has_app_context() else None
    return Path(configured or config.CACHE_DIR).expanduser()


def _safe_resource_stem(resource):
    base = Path(str(getattr(resource, "filename", "") or getattr(resource, "path", "") or "subtitle")).stem
    base = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", ".", base).strip(".")
    return base or "subtitle"


def _safe_bound_subtitle_filename(resource, provider_id, source_key, filename):
    suffix = Path(_basename(filename)).suffix.lower()
    if suffix not in SUBTITLE_SUFFIXES:
        suffix = ".srt"
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "", str(source_key or ""))[:12] or "candidate"
    return f"{_safe_resource_stem(resource)}.online.{provider_id}.{safe_key}{suffix}"


def _unique_bound_storage_path(resource, filename):
    resource_id = str(getattr(resource, "id", "") or "unknown")
    safe_filename = _basename(filename)
    stem = Path(safe_filename).stem
    suffix = Path(safe_filename).suffix
    directory = Path("subtitles") / resource_id
    root = _subtitle_cache_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)

    for index in range(1, 1000):
        candidate_name = safe_filename if index == 1 else f"{stem}.{index}{suffix}"
        relative_path = directory / candidate_name
        absolute_path = (root / relative_path).resolve()
        try:
            absolute_path.relative_to(root)
        except ValueError as e:
            raise OnlineSubtitleError("Invalid subtitle cache path", code=50062, http_status=500) from e
        if not absolute_path.exists():
            return relative_path.as_posix(), absolute_path

    raise OnlineSubtitleError("Unable to allocate subtitle cache filename", code=50063, http_status=500)


def bind_online_subtitle(resource, candidate_id, download_index=0, confirm=False):
    if not _confirmation_enabled(confirm):
        raise OnlineSubtitleError(
            "confirm=true is required before binding an online subtitle",
            code=40064,
            http_status=400,
        )

    provider_id, source_key = _parse_candidate_id(candidate_id)
    normalized_candidate_id = f"{provider_id}:{source_key}"

    from backend.app.extensions import db
    from backend.app.models import ResourceSubtitle
    from backend.app.services.playback import build_resource_playback
    from backend.app.services.subtitles import (
        clear_subtitle_discovery_cache,
        discover_resource_subtitles,
        sync_bound_subtitle_to_cdn,
    )

    existing = ResourceSubtitle.query.filter_by(
        resource_id=getattr(resource, "id", None),
        candidate_id=normalized_candidate_id,
    ).first()
    if existing:
        raise OnlineSubtitleError(
            "Online subtitle candidate is already bound to this resource",
            code=40960,
            http_status=409,
        )

    result = download_online_subtitle(
        resource,
        candidate_id=normalized_candidate_id,
        download_index=download_index,
    )
    filename = _safe_bound_subtitle_filename(resource, provider_id, source_key, result["filename"])
    storage_path, absolute_path = _unique_bound_storage_path(resource, filename)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(result["content"])

    metadata = dict(result.get("meta") or {})
    metadata.update({
        "download_filename": result.get("filename"),
        "manual_confirmed": True,
    })
    row = ResourceSubtitle(
        resource_id=getattr(resource, "id", None),
        source="online",
        provider_id=provider_id,
        provider_name={"subhd": "SubHD", "srtku": "SrtKu"}.get(provider_id, provider_id),
        candidate_id=normalized_candidate_id,
        filename=filename,
        storage_kind="cache",
        storage_path=storage_path,
        format=Path(filename).suffix.lower().lstrip(".") or "srt",
        mime_type=result["mime_type"],
        size=len(result["content"]),
        language=None,
        subtitle_metadata=metadata,
        is_default=False,
    )

    try:
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
    subtitle_payload = discover_resource_subtitles(resource)
    bound_item = next((item for item in subtitle_payload.get("items") or [] if item.get("id") == row.id), None)

    return {
        "resource_id": getattr(resource, "id", None),
        "candidate_id": normalized_candidate_id,
        "confirmed": True,
        "subtitle": bound_item,
        "subtitles": subtitle_payload,
        "playback": build_resource_playback(resource, subtitles=subtitle_payload),
    }
