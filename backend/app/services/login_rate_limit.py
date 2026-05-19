from __future__ import annotations

import threading
from datetime import datetime, timedelta

from flask import current_app, request


_LOCK = threading.Lock()
_ATTEMPTS = {}


def _config_int(key, default):
    try:
        return int(current_app.config.get(key, default))
    except (TypeError, ValueError):
        return default


def _enabled():
    return bool(current_app.config.get("LOGIN_RATE_LIMIT_ENABLED", True))


def _client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.remote_addr or "unknown"


def _key(username):
    return f"{_client_ip()}:{str(username or '').strip().lower()}"


def _prune_record(record, now, window_seconds):
    cutoff = now - timedelta(seconds=window_seconds)
    record["failures"] = [item for item in record.get("failures", []) if item >= cutoff]
    if not record["failures"] and not record.get("locked_until"):
        return True
    return False


def check_login_rate_limit(username):
    if not _enabled():
        return None

    now = datetime.utcnow()
    window_seconds = max(1, _config_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300))
    key = _key(username)
    with _LOCK:
        record = _ATTEMPTS.get(key)
        if not record:
            return None

        locked_until = record.get("locked_until")
        if locked_until and now < locked_until:
            return max(1, int((locked_until - now).total_seconds()))

        if locked_until and now >= locked_until:
            record["locked_until"] = None
        if _prune_record(record, now, window_seconds):
            _ATTEMPTS.pop(key, None)
    return None


def record_login_failure(username):
    if not _enabled():
        return None

    now = datetime.utcnow()
    key = _key(username)
    max_attempts = max(1, _config_int("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 5))
    window_seconds = max(1, _config_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300))
    lock_seconds = max(1, _config_int("LOGIN_RATE_LIMIT_LOCK_SECONDS", 900))
    with _LOCK:
        record = _ATTEMPTS.setdefault(key, {"failures": [], "locked_until": None})
        _prune_record(record, now, window_seconds)
        record["failures"].append(now)
        if len(record["failures"]) >= max_attempts:
            record["locked_until"] = now + timedelta(seconds=lock_seconds)
            return lock_seconds
    return None


def clear_login_failures(username):
    if not _enabled():
        return
    with _LOCK:
        _ATTEMPTS.pop(_key(username), None)


def clear_all_login_failures():
    with _LOCK:
        _ATTEMPTS.clear()
