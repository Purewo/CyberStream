from __future__ import annotations

import copy
import threading
import time
from collections import Counter
from dataclasses import dataclass

from flask import current_app, has_app_context
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.app.models import Library, LibraryMovieMembership, LibrarySource, MediaResource, Movie, UserFavorite, UserLibraryRule
from backend.app.security import get_current_account_id, is_admin_request
from backend.app.services.user_access import current_user_id_for_personal_data
from backend.app.utils.genres import normalize_genres


DEFAULT_FILTER_OPTIONS_CACHE_TTL_SECONDS = 300
_CACHE_MAX_ENTRIES = 256
_CACHE_DIRTY_FLAG = "_cyberstream_filter_options_cache_dirty"


@dataclass
class _CacheEntry:
    expires_at: float
    payload: object


_CACHE_LOCK = threading.RLock()
_CACHE: dict[tuple, _CacheEntry] = {}
_HOOKS_INSTALLED = False


def _normalize_scope_value(value):
    return str(value or "")


def _current_scope_key():
    account_id = _normalize_scope_value(get_current_account_id())
    if is_admin_request():
        return ("admin", account_id, "")

    user_id = current_user_id_for_personal_data()
    if user_id is not None:
        return ("user", account_id, str(user_id))

    return ("public", account_id, "")


def _cache_ttl_seconds():
    if has_app_context():
        raw = current_app.config.get("FILTER_OPTIONS_CACHE_TTL_SECONDS", DEFAULT_FILTER_OPTIONS_CACHE_TTL_SECONDS)
    else:
        raw = DEFAULT_FILTER_OPTIONS_CACHE_TTL_SECONDS
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = DEFAULT_FILTER_OPTIONS_CACHE_TTL_SECONDS
    return max(0, ttl)


def normalize_filter_includes(includes, default=None):
    if includes is None:
        raw_items = list(default or [])
    elif isinstance(includes, str):
        raw_items = includes.split(",")
    else:
        raw_items = list(includes)

    normalized = []
    seen = set()
    for raw_item in raw_items:
        item = str(raw_item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def clear_filter_options_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def _prune_locked(now):
    expired_keys = [key for key, entry in _CACHE.items() if entry.expires_at <= now]
    for key in expired_keys:
        _CACHE.pop(key, None)

    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return

    overflow = len(_CACHE) - _CACHE_MAX_ENTRIES
    for key, _entry in sorted(_CACHE.items(), key=lambda item: item[1].expires_at)[:overflow]:
        _CACHE.pop(key, None)


def get_cached_filter_payload(namespace, includes, builder, *, extra_key=None):
    normalized_includes = tuple(normalize_filter_includes(includes))
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return builder()

    cache_key = (namespace, _current_scope_key(), extra_key, normalized_includes)
    now = time.monotonic()

    with _CACHE_LOCK:
        entry = _CACHE.get(cache_key)
        if entry and entry.expires_at > now:
            return copy.deepcopy(entry.payload)

    payload = builder()
    payload_copy = copy.deepcopy(payload)

    with _CACHE_LOCK:
        _CACHE[cache_key] = _CacheEntry(expires_at=now + ttl, payload=payload_copy)
        _prune_locked(now)

    return copy.deepcopy(payload_copy)


def _row_value(row, index, attr):
    try:
        return row[index]
    except Exception:
        return getattr(row, attr, None)


def build_filter_options_from_rows(rows, includes):
    normalized_includes = normalize_filter_includes(includes)
    rows = list(rows or [])
    data = {}

    if "genres" in normalized_includes:
        counter = Counter()
        for row in rows:
            categories = _row_value(row, 0, "category")
            if categories and isinstance(categories, list):
                for category in normalize_genres(categories):
                    counter[category] += 1
        data["genres"] = [
            {"name": name, "slug": name, "count": count}
            for name, count in counter.most_common()
        ]

    if "years" in normalized_includes:
        counter = Counter()
        for row in rows:
            year = _row_value(row, 1, "year")
            if year is not None:
                counter[year] += 1
        data["years"] = [
            {"year": year, "count": count}
            for year, count in sorted(counter.items(), key=lambda item: item[0], reverse=True)
        ]

    if "countries" in normalized_includes:
        counter = Counter()
        for row in rows:
            country = _row_value(row, 2, "country")
            if country:
                counter[country] += 1
        data["countries"] = [
            {"name": name, "code": name, "count": count}
            for name, count in counter.most_common()
        ]

    return data


def _relevant_mutation_detected(session):
    for collection in (session.new, session.dirty, session.deleted):
        for item in collection:
            if isinstance(item, (Movie, Library, LibrarySource, LibraryMovieMembership, MediaResource, UserFavorite, UserLibraryRule)):
                return True
    return False


def install_filter_options_cache_hooks():
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def _mark_cache_dirty(session, _flush_context, _instances):
        if _relevant_mutation_detected(session):
            session.info[_CACHE_DIRTY_FLAG] = True

    @event.listens_for(Session, "after_commit")
    def _clear_cache_after_commit(session):
        if session.info.pop(_CACHE_DIRTY_FLAG, False):
            clear_filter_options_cache()

    @event.listens_for(Session, "after_rollback")
    def _clear_cache_after_rollback(session):
        session.info.pop(_CACHE_DIRTY_FLAG, None)

    _HOOKS_INSTALLED = True
