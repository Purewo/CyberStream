import logging
import math
import os
import re
import select
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning


logger = logging.getLogger(__name__)
urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_AUDIO_TRANSCODE_MAX_CONCURRENT = 1
DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS = 60
DEFAULT_AUDIO_TRANSCODE_CHUNK_SIZE = 64 * 1024
DEFAULT_AUDIO_TRANSCODE_OUTPUT_CHUNK_SIZE = 16 * 1024
DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS = 180
DEFAULT_AUDIO_TRANSCODE_WATCHDOG_INTERVAL_SECONDS = 5
DEFAULT_HTTP_INPUT_PROXY_CONNECT_TIMEOUT_SECONDS = 30
DEFAULT_HTTP_INPUT_PROXY_MAX_RETRIES = 2
DEFAULT_HTTP_INPUT_PROXY_RETRY_DELAY_SECONDS = 0.5
DEFAULT_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS = 90
DEFAULT_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS = 3
DEFAULT_AUDIO_TRANSCODE_REALTIME_INPUT = False
DEFAULT_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER = 1.5
DEFAULT_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS = 8
DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED = True
DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_BYTES = 256 * 1024 * 1024
DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_READ_BYTES = 8 * 1024 * 1024
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
DIAGNOSTIC_EVENT_LIMIT = 60
DIAGNOSTIC_STREAM_LIMIT = 100


class AudioTranscodeError(Exception):
    status_code = 500
    error_code = "audio_transcode_error"


class AudioTranscodeValidationError(AudioTranscodeError):
    status_code = 400
    error_code = "invalid_audio_transcode_request"


class AudioTranscodeUnavailableError(AudioTranscodeError):
    status_code = 503
    error_code = "audio_transcode_unavailable"


class AudioTranscodeBusyError(AudioTranscodeError):
    status_code = 429
    error_code = "audio_transcode_busy"


@dataclass(frozen=True)
class AudioTranscodeProfile:
    format: str
    mime_type: str
    target_codec: str
    ffmpeg_format: str
    codec_args: tuple
    channels: int = 2
    sample_rate: int = 48000
    bitrate_bps: int = 192000


@dataclass(frozen=True)
class AudioTranscodeOptions:
    start_seconds: float = 0.0
    audio_track: int = 0
    format: str = "mp3"


@dataclass
class AudioTranscodeStream:
    iterator: object
    profile: AudioTranscodeProfile
    options: AudioTranscodeOptions
    headers: dict
    stream_key: str = None
    resource_id: str = None
    session_id: str = None
    diagnostic_id: str = None
    started_at: float = None
    last_history_at: float = None
    closed: bool = False
    preserve_cache_on_close: bool = False
    _close_callback: object = None

    def close(self):
        if callable(self._close_callback):
            self._close_callback()

    def set_close_callback(self, callback):
        self._close_callback = callback

    def touch_history(self, timestamp=None):
        self.last_history_at = timestamp or time.monotonic()

    def seconds_since_history(self, timestamp=None):
        current = timestamp or time.monotonic()
        last_seen = self.last_history_at or self.started_at or current
        return max(0, current - last_seen)


AUDIO_TRANSCODE_PROFILES = {
    "mp3": AudioTranscodeProfile(
        format="mp3",
        mime_type="audio/mpeg",
        target_codec="mp3",
        ffmpeg_format="mp3",
        codec_args=("-c:a", "libmp3lame", "-b:a", "192k"),
    ),
    "aac": AudioTranscodeProfile(
        format="aac",
        mime_type="audio/aac",
        target_codec="aac",
        ffmpeg_format="adts",
        codec_args=("-c:a", "aac", "-b:a", "192k"),
    ),
}

DEFAULT_AUDIO_TRANSCODE_FORMAT = "mp3"

_limiter_lock = threading.Lock()
_limiters = {}
_active_streams_lock = threading.Lock()
_active_streams = {}
_history_sessions_lock = threading.Lock()
_history_sessions = {}
_history_resources = {}
_diagnostics_lock = threading.Lock()
_diagnostics = {}


@dataclass
class _RangeCacheEntry:
    start: int
    data: bytes
    last_access: float

    @property
    def end(self):
        return self.start + len(self.data)


class _AudioTranscodeRangeCache:
    # Cache raw remote input ranges only. Transcoded audio is never cached to
    # disk or memory; this is only for MKV indexes and nearby seek clusters.
    def __init__(self):
        self.enabled = DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED
        self.max_bytes = DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_BYTES
        self.total_bytes = 0
        self.entries = {}
        self.cache_resources = {}
        self.resource_cache_keys = {}
        self.content_lengths = {}
        self.lock = threading.Lock()

    def configure(self, enabled=None, max_bytes=None):
        with self.lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if max_bytes is not None:
                self.max_bytes = max(0, int(max_bytes or 0))
            if not self.enabled or self.max_bytes <= 0:
                self.entries.clear()
                self.cache_resources.clear()
                self.resource_cache_keys.clear()
                self.content_lengths.clear()
                self.total_bytes = 0
                return
            self._evict_locked()

    def get(self, cache_key, start, max_bytes=None):
        if not self.enabled or not cache_key or start is None:
            return b""
        requested_start = int(start)
        remaining = None if max_bytes is None else max(0, int(max_bytes))
        if remaining == 0:
            return b""

        chunks = []
        position = requested_start
        now = time.monotonic()
        with self.lock:
            for entry in sorted(self.entries.get(cache_key, []), key=lambda item: (item.start, item.end)):
                if entry.end <= position:
                    continue
                if entry.start > position:
                    break

                offset = position - entry.start
                chunk = entry.data[offset:]
                if remaining is not None and len(chunk) > remaining:
                    chunk = chunk[:remaining]
                if not chunk:
                    continue

                chunks.append(chunk)
                entry.last_access = now
                position += len(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
        return b"".join(chunks)

    def put(self, cache_key, start, data, resource_id=None, content_length=None):
        if not self.enabled or self.max_bytes <= 0 or not cache_key or start is None or not data:
            return
        payload = bytes(data)
        if len(payload) > self.max_bytes:
            payload = payload[-self.max_bytes:]
            start = int(start) + len(data) - len(payload)

        now = time.monotonic()
        with self.lock:
            self._remember_resource_locked(cache_key, resource_id)
            if content_length:
                self.content_lengths[cache_key] = int(content_length)
            self.entries.setdefault(cache_key, []).append(
                _RangeCacheEntry(start=int(start), data=payload, last_access=now)
            )
            self.total_bytes += len(payload)
            self._evict_locked()

    def content_length(self, cache_key):
        with self.lock:
            return self.content_lengths.get(cache_key)

    def clear_resource(self, resource_id):
        if not resource_id:
            return 0
        resource_id = str(resource_id)
        with self.lock:
            cache_keys = set(self.resource_cache_keys.pop(resource_id, set()))
            removed_bytes = 0
            for cache_key in cache_keys:
                entries = self.entries.pop(cache_key, [])
                removed_bytes += sum(len(entry.data) for entry in entries)
                self.cache_resources.pop(cache_key, None)
                self.content_lengths.pop(cache_key, None)
            self.total_bytes = max(0, self.total_bytes - removed_bytes)
            return removed_bytes

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.cache_resources.clear()
            self.resource_cache_keys.clear()
            self.content_lengths.clear()
            self.total_bytes = 0

    def _remember_resource_locked(self, cache_key, resource_id):
        if not resource_id:
            return
        resource_id = str(resource_id)
        previous_resource_id = self.cache_resources.get(cache_key)
        if previous_resource_id == resource_id:
            return
        if previous_resource_id:
            previous_keys = self.resource_cache_keys.get(previous_resource_id)
            if previous_keys:
                previous_keys.discard(cache_key)
                if not previous_keys:
                    self.resource_cache_keys.pop(previous_resource_id, None)
        self.cache_resources[cache_key] = resource_id
        self.resource_cache_keys.setdefault(resource_id, set()).add(cache_key)

    def _evict_locked(self):
        if self.total_bytes <= self.max_bytes:
            return
        all_entries = [
            (entry.last_access, cache_key, index, entry)
            for cache_key, entries in self.entries.items()
            for index, entry in enumerate(entries)
        ]
        all_entries.sort(key=lambda item: item[0])
        removed = set()
        for _last_access, cache_key, index, entry in all_entries:
            if self.total_bytes <= self.max_bytes:
                break
            removed.add((cache_key, index))
            self.total_bytes -= len(entry.data)

        for cache_key, entries in list(self.entries.items()):
            self.entries[cache_key] = [
                entry for index, entry in enumerate(entries)
                if (cache_key, index) not in removed
            ]
            if not self.entries[cache_key]:
                self.entries.pop(cache_key, None)
                resource_id = self.cache_resources.pop(cache_key, None)
                self.content_lengths.pop(cache_key, None)
                if resource_id and resource_id in self.resource_cache_keys:
                    self.resource_cache_keys[resource_id].discard(cache_key)
                    if not self.resource_cache_keys[resource_id]:
                        self.resource_cache_keys.pop(resource_id, None)


_range_cache = _AudioTranscodeRangeCache()


def start_audio_transcode_diagnostics(resource_id, session_id=None, options=None, input_url=None, stream_key=None):
    diagnostic_id = stream_key or build_audio_transcode_stream_key(resource_id, session_id)
    if not diagnostic_id:
        diagnostic_id = build_anonymous_audio_transcode_stream_key(resource_id or "unknown")

    now = time.time()
    started_monotonic = time.monotonic()
    current_options = options or AudioTranscodeOptions()
    entry = {
        "diagnostic_id": diagnostic_id,
        "resource_id": str(resource_id) if resource_id else None,
        "session_id": session_id,
        "active": True,
        "started_at": _format_epoch_seconds(now),
        "updated_at": _format_epoch_seconds(now),
        "closed_at": None,
        "closed_reason": None,
        "_started_monotonic": started_monotonic,
        "input": {
            "url": _safe_diagnostic_url(input_url),
            "scheme": urlparse(str(input_url or "")).scheme or None,
            "is_http": _should_proxy_http_input(input_url),
        },
        "options": {
            "start_seconds": current_options.start_seconds,
            "audio_track": current_options.audio_track,
            "format": current_options.format,
        },
        "counters": {
            "cache_hit_count": 0,
            "cache_only_hit_count": 0,
            "cache_prefix_hit_count": 0,
            "cache_miss_count": 0,
            "cache_hit_bytes": 0,
            "upstream_open_count": 0,
            "upstream_retry_count": 0,
            "upstream_bytes": 0,
            "ffmpeg_restart_count": 0,
            "output_chunk_count": 0,
            "output_bytes": 0,
            "output_throttle_sleep_ms": 0,
        },
        "timings": {
            "first_audio_byte_ms": None,
        },
        "events": [],
    }

    with _diagnostics_lock:
        _diagnostics[diagnostic_id] = entry
        _append_diagnostic_event_locked(entry, "stream_started")
        _evict_diagnostics_locked()
    logger.info(
        "audio transcode diagnostics started resource_id=%s session_id=%s diagnostic_id=%s input=%s",
        resource_id,
        session_id,
        diagnostic_id,
        entry["input"]["url"],
    )
    return diagnostic_id


def record_audio_transcode_diagnostic(
    diagnostic_id,
    event_type=None,
    counter_updates=None,
    timing_updates=None,
    **fields,
):
    if not diagnostic_id:
        return
    with _diagnostics_lock:
        entry = _diagnostics.get(diagnostic_id)
        if not entry:
            return
        counters = entry.setdefault("counters", {})
        for key, value in (counter_updates or {}).items():
            try:
                counters[key] = counters.get(key, 0) + value
            except TypeError:
                counters[key] = value
        timings = entry.setdefault("timings", {})
        for key, value in (timing_updates or {}).items():
            timings[key] = value
        entry["updated_at"] = _format_epoch_seconds(time.time())
        if event_type:
            _append_diagnostic_event_locked(entry, event_type, **fields)

    if event_type in {
        "cache_only_hit",
        "first_audio_byte",
        "ffmpeg_restart",
        "upstream_retry",
        "first_byte_unavailable",
        "stream_closed",
    }:
        logger.info(
            "audio transcode diagnostic event=%s diagnostic_id=%s fields=%s",
            event_type,
            diagnostic_id,
            fields,
        )


def finish_audio_transcode_diagnostics(diagnostic_id, reason="closed", **fields):
    if not diagnostic_id:
        return
    now = time.time()
    with _diagnostics_lock:
        entry = _diagnostics.get(diagnostic_id)
        if not entry:
            return
        entry["active"] = False
        entry["closed_at"] = _format_epoch_seconds(now)
        entry["closed_reason"] = reason
        entry["updated_at"] = entry["closed_at"]
        _append_diagnostic_event_locked(entry, "stream_closed", reason=reason, **fields)
    logger.info(
        "audio transcode diagnostics closed diagnostic_id=%s reason=%s fields=%s",
        diagnostic_id,
        reason,
        fields,
    )


def get_audio_transcode_diagnostics(resource_id=None, session_id=None):
    resource_id = str(resource_id) if resource_id else None
    with _diagnostics_lock:
        items = []
        for entry in _diagnostics.values():
            if resource_id and entry.get("resource_id") != resource_id:
                continue
            if session_id and entry.get("session_id") != session_id:
                continue
            items.append(_public_diagnostic_entry(entry))

    items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return {
        "resource_id": resource_id,
        "session_id": session_id,
        "active_count": sum(1 for item in items if item.get("active")),
        "items": items,
    }


def _append_diagnostic_event_locked(entry, event_type, **fields):
    now = time.time()
    started = entry.get("_started_monotonic") or time.monotonic()
    event = {
        "type": event_type,
        "at": _format_epoch_seconds(now),
        "age_ms": int((time.monotonic() - started) * 1000),
    }
    for key, value in fields.items():
        if value is not None:
            event[key] = value
    events = entry.setdefault("events", [])
    events.append(event)
    if len(events) > DIAGNOSTIC_EVENT_LIMIT:
        del events[:-DIAGNOSTIC_EVENT_LIMIT]


def _public_diagnostic_entry(entry):
    public = {
        key: value
        for key, value in entry.items()
        if not key.startswith("_")
    }
    public["input"] = dict(public.get("input") or {})
    public["options"] = dict(public.get("options") or {})
    public["counters"] = dict(public.get("counters") or {})
    public["timings"] = dict(public.get("timings") or {})
    public["events"] = [dict(item) for item in public.get("events") or []]
    return public


def _evict_diagnostics_locked():
    if len(_diagnostics) <= DIAGNOSTIC_STREAM_LIMIT:
        return
    closed_entries = sorted(
        [
            (entry.get("updated_at") or "", diagnostic_id)
            for diagnostic_id, entry in _diagnostics.items()
            if not entry.get("active")
        ],
        key=lambda item: item[0],
    )
    for _updated_at, diagnostic_id in closed_entries:
        if len(_diagnostics) <= DIAGNOSTIC_STREAM_LIMIT:
            break
        _diagnostics.pop(diagnostic_id, None)


def _format_epoch_seconds(value):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(value or 0)))


def _safe_diagnostic_url(input_url):
    raw = str(input_url or "")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    return parsed._replace(query="", fragment="").geturl()


class _AudioTranscodeHttpInputProxy:
    def __init__(
        self,
        source_url,
        connect_timeout_seconds=DEFAULT_HTTP_INPUT_PROXY_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS,
        chunk_size=DEFAULT_AUDIO_TRANSCODE_CHUNK_SIZE,
        max_retries=DEFAULT_HTTP_INPUT_PROXY_MAX_RETRIES,
        retry_delay_seconds=DEFAULT_HTTP_INPUT_PROXY_RETRY_DELAY_SECONDS,
        range_cache_enabled=DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED,
        range_cache_bytes=DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_BYTES,
        resource_id=None,
        diagnostic_id=None,
    ):
        self.source_url = source_url
        self.resource_id = str(resource_id) if resource_id else None
        self.diagnostic_id = diagnostic_id
        self.cache_key = _build_input_range_cache_key(source_url, resource_id=self.resource_id)
        self.connect_timeout_seconds = max(1, int(connect_timeout_seconds or DEFAULT_HTTP_INPUT_PROXY_CONNECT_TIMEOUT_SECONDS))
        self.read_timeout_seconds = max(1, int(read_timeout_seconds or DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS))
        self.chunk_size = max(1024, int(chunk_size or DEFAULT_AUDIO_TRANSCODE_CHUNK_SIZE))
        self.max_retries = max(0, int(max_retries if max_retries is not None else DEFAULT_HTTP_INPUT_PROXY_MAX_RETRIES))
        self.retry_delay_seconds = max(0, float(retry_delay_seconds or 0))
        self.range_cache_enabled = bool(range_cache_enabled)
        _range_cache.configure(enabled=range_cache_enabled, max_bytes=range_cache_bytes)
        self.session = requests.Session()
        self.session.trust_env = False
        self.server = None
        self.thread = None
        self.url = None
        self._responses = set()
        self._responses_lock = threading.Lock()
        self._closed = False

    def start(self):
        if self.server:
            return self.url

        handler_class = self._build_handler_class()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.server.daemon_threads = True
        port = self.server.server_address[1]
        extension = os.path.splitext(urlparse(self.source_url).path)[1] or ".bin"
        self.url = f"http://127.0.0.1:{port}/input{extension}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.debug("audio transcode http input proxy started url=%s", self.url)
        record_audio_transcode_diagnostic(
            self.diagnostic_id,
            "input_proxy_started",
            local_url=self.url,
        )
        return self.url

    def close(self):
        if self._closed:
            return
        self._closed = True

        with self._responses_lock:
            responses = list(self._responses)
            self._responses.clear()
        for response in responses:
            self._close_response(response)

        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                logger.debug("audio transcode http input proxy shutdown failed", exc_info=True)
            try:
                self.server.server_close()
            except Exception:
                logger.debug("audio transcode http input proxy close failed", exc_info=True)
        try:
            self.session.close()
        except Exception:
            pass

    def _build_handler_class(self):
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_HEAD(self):
                proxy.handle(self, head_only=True)

            def do_GET(self):
                proxy.handle(self, head_only=False)

            def log_message(self, _format, *_args):
                return

        return Handler

    def handle(self, handler, head_only=False):
        if self._closed:
            handler.send_error(503, "Audio transcode input proxy closed")
            return

        response = None
        headers_sent = False
        range_header = handler.headers.get("Range")
        bytes_sent = 0
        expected_bytes = None
        retry_count = 0
        try:
            # Serve a full cache hit before opening upstream. Opening 115/AList
            # first can block for seconds even when the bytes are already local.
            if not head_only and self._serve_cached_range_without_upstream(handler, range_header):
                return

            while not self._closed:
                response = self._open_upstream_with_retries(handler, range_header=range_header, head_only=head_only)
                self._track_response(response)
                try:
                    if not headers_sent:
                        self._send_response_headers(handler, response)
                        headers_sent = True
                        expected_bytes = _parse_content_length(response.headers.get("Content-Length"))

                    if head_only:
                        return

                    response_start = _response_range_start(response, range_header)
                    cached_bytes = self._write_cached_prefix(
                        handler,
                        response_start,
                        _cache_prefix_read_limit(expected_bytes, bytes_sent),
                    )
                    if cached_bytes > 0:
                        bytes_sent += cached_bytes
                        logger.info(
                            "audio transcode input proxy served range cache start=%s bytes=%s",
                            response_start,
                            cached_bytes,
                        )
                        if _is_response_body_complete(expected_bytes, bytes_sent):
                            return
                        range_header = _resume_range_header(handler.headers.get("Range"), bytes_sent)
                        if not range_header:
                            return
                        continue

                    bytes_read = self._write_response_body(
                        handler,
                        response,
                        cache_start=response_start,
                    )
                    bytes_sent += bytes_read

                    if _is_response_body_complete(expected_bytes, bytes_sent):
                        return
                    if retry_count >= self.max_retries:
                        return

                    next_range = _resume_range_header(handler.headers.get("Range"), bytes_sent)
                    if not next_range:
                        return
                    range_header = next_range
                    retry_count += 1
                    logger.info(
                        "audio transcode input proxy retrying premature eof range=%s retry=%s/%s",
                        range_header,
                        retry_count,
                        self.max_retries,
                    )
                    self._sleep_before_retry()
                finally:
                    self._untrack_response(response)
                    response = None
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass
        except requests.RequestException as e:
            if _is_client_disconnect_error(e):
                logger.debug("audio transcode input proxy client disconnected")
            else:
                logger.warning("audio transcode input proxy failed error=%s", e)
                if not headers_sent:
                    _send_proxy_error(handler)
        except Exception as e:
            logger.warning("audio transcode input proxy failed error=%s", e)
            if not headers_sent:
                _send_proxy_error(handler)
        finally:
            if response is not None:
                self._untrack_response(response)

    def _write_cached_prefix(self, handler, response_start, max_bytes=None):
        if not self.range_cache_enabled:
            return 0
        cached = _range_cache.get(self.cache_key, response_start, max_bytes=max_bytes)
        if not cached:
            return 0
        handler.wfile.write(cached)
        record_audio_transcode_diagnostic(
            self.diagnostic_id,
            "cache_prefix_hit",
            counter_updates={
                "cache_hit_count": 1,
                "cache_prefix_hit_count": 1,
                "cache_hit_bytes": len(cached),
            },
            range_start=response_start,
            bytes=len(cached),
        )
        return len(cached)

    def _write_response_body(self, handler, response, cache_start=None):
        bytes_read = 0
        cache_position = cache_start
        try:
            for chunk in response.iter_content(chunk_size=self.chunk_size):
                if self._closed:
                    break
                if not chunk:
                    continue
                handler.wfile.write(chunk)
                if self.range_cache_enabled and cache_position is not None:
                    _range_cache.put(
                        self.cache_key,
                        cache_position,
                        chunk,
                        resource_id=self.resource_id,
                        content_length=_response_content_total(response),
                    )
                    cache_position += len(chunk)
                bytes_read += len(chunk)
        except requests.RequestException:
            logger.info("audio transcode input proxy upstream interrupted after %s bytes", bytes_read)
        if bytes_read:
            record_audio_transcode_diagnostic(
                self.diagnostic_id,
                counter_updates={"upstream_bytes": bytes_read},
            )
        return bytes_read

    def _serve_cached_range_without_upstream(self, handler, range_header):
        if not self.range_cache_enabled:
            return False
        range_start = _range_header_start(range_header)
        if range_start is None:
            return False
        max_bytes = _requested_range_length(range_header) or DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_READ_BYTES
        max_bytes = min(max_bytes, DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_READ_BYTES)
        cached = _range_cache.get(self.cache_key, range_start, max_bytes=max_bytes)
        if not cached:
            record_audio_transcode_diagnostic(
                self.diagnostic_id,
                "cache_miss",
                counter_updates={"cache_miss_count": 1},
                range_start=range_start,
                requested_bytes=max_bytes,
            )
            return False
        total = _range_cache.content_length(self.cache_key)
        self._send_cached_range_headers(handler, range_start, len(cached), total)
        handler.wfile.write(cached)
        logger.info(
            "audio transcode input proxy served cached range without upstream start=%s bytes=%s",
            range_start,
            len(cached),
        )
        record_audio_transcode_diagnostic(
            self.diagnostic_id,
            "cache_only_hit",
            counter_updates={
                "cache_hit_count": 1,
                "cache_only_hit_count": 1,
                "cache_hit_bytes": len(cached),
            },
            range_start=range_start,
            bytes=len(cached),
            content_length=total,
        )
        return True

    def _send_cached_range_headers(self, handler, start, length, total=None):
        end = start + length - 1
        total_value = str(total) if total else "*"
        handler.send_response(206)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Content-Length", str(length))
        handler.send_header("Content-Range", f"bytes {start}-{end}/{total_value}")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Connection", "close")
        handler.end_headers()

    def _open_upstream_with_retries(self, handler, range_header=None, head_only=False):
        last_error = None
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = self._open_upstream(handler, range_header=range_header, head_only=head_only)
                if not _is_retryable_upstream_status(response.status_code):
                    return response
                last_error = requests.HTTPError(f"retryable upstream status {response.status_code}")
                self._close_response(response)
                response = None
            except requests.RequestException as e:
                last_error = e
                if response is not None:
                    self._close_response(response)

            if attempt >= self.max_retries or self._closed:
                break
            record_audio_transcode_diagnostic(
                self.diagnostic_id,
                "upstream_retry",
                counter_updates={"upstream_retry_count": 1},
                range=range_header,
                attempt=attempt + 1,
                max_retries=self.max_retries,
                error=str(last_error) if last_error else None,
            )
            logger.info(
                "audio transcode input proxy retrying upstream open range=%s retry=%s/%s error=%s",
                range_header,
                attempt + 1,
                self.max_retries,
                last_error,
            )
            self._sleep_before_retry()

        if last_error:
            raise last_error
        raise requests.RequestException("audio transcode input proxy upstream open failed")

    def _open_upstream(self, handler, range_header=None, head_only=False):
        headers = {
            "User-Agent": "CyberPlayer/1.0 AudioTranscodeProxy",
            "Accept": "*/*",
        }
        if range_header:
            headers["Range"] = range_header
        if handler.headers.get("If-Range"):
            headers["If-Range"] = handler.headers["If-Range"]

        method = "HEAD" if head_only else "GET"
        record_audio_transcode_diagnostic(
            self.diagnostic_id,
            "upstream_open",
            counter_updates={"upstream_open_count": 1},
            method=method,
            range=range_header,
        )
        response = self.session.request(
            method,
            self.source_url,
            headers=headers,
            stream=not head_only,
            timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
            verify=False,
            allow_redirects=True,
        )
        record_audio_transcode_diagnostic(
            self.diagnostic_id,
            "upstream_response",
            status_code=response.status_code,
            content_length=response.headers.get("Content-Length"),
            content_range=response.headers.get("Content-Range"),
        )
        return response

    def _sleep_before_retry(self):
        if self.retry_delay_seconds <= 0:
            return
        time.sleep(self.retry_delay_seconds)

    def _send_response_headers(self, handler, response):
        handler.send_response(response.status_code)
        for name in (
            "Content-Type",
            "Content-Length",
            "Content-Range",
            "Accept-Ranges",
            "Last-Modified",
            "ETag",
        ):
            value = response.headers.get(name)
            if value:
                handler.send_header(name, value)
        if not response.headers.get("Accept-Ranges"):
            handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Connection", "close")
        handler.end_headers()

    def _track_response(self, response):
        with self._responses_lock:
            if not self._closed:
                self._responses.add(response)

    def _untrack_response(self, response):
        with self._responses_lock:
            self._responses.discard(response)
        self._close_response(response)

    def _close_response(self, response):
        try:
            response.close()
        except Exception:
            pass


class _AudioTranscodeLimiter:
    def __init__(self, max_concurrent):
        self.max_concurrent = max(1, int(max_concurrent or DEFAULT_AUDIO_TRANSCODE_MAX_CONCURRENT))
        self.active = 0
        self.lock = threading.Lock()

    def acquire(self, timeout_seconds=0):
        deadline = time.monotonic() + max(0, float(timeout_seconds or 0))
        while True:
            with self.lock:
                if self.active < self.max_concurrent:
                    self.active += 1
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def release(self):
        with self.lock:
            self.active = max(0, self.active - 1)


def _get_limiter(max_concurrent):
    normalized = max(1, int(max_concurrent or DEFAULT_AUDIO_TRANSCODE_MAX_CONCURRENT))
    with _limiter_lock:
        limiter = _limiters.get(normalized)
        if not limiter:
            limiter = _AudioTranscodeLimiter(normalized)
            _limiters[normalized] = limiter
        return limiter


def resolve_ffmpeg_binary(binary=None):
    candidates = [
        binary,
        os.getenv("CYBER_FFMPEG_BIN"),
        os.getenv("FFMPEG_BIN"),
        shutil.which("ffmpeg"),
        os.path.expanduser("~/.local/bin/ffmpeg"),
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = os.path.expanduser(str(candidate))
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def is_ffmpeg_available(binary=None):
    return bool(resolve_ffmpeg_binary(binary))


def parse_audio_transcode_options(args):
    start_seconds = _parse_start_seconds(args.get("start", "0"))
    audio_track = _parse_audio_track(args.get("audio_track", args.get("track", "0")))
    requested_format = str(args.get("format") or DEFAULT_AUDIO_TRANSCODE_FORMAT).strip().lower()
    if requested_format not in AUDIO_TRANSCODE_PROFILES:
        raise AudioTranscodeValidationError(f"Unsupported audio transcode format: {requested_format}")
    return AudioTranscodeOptions(
        start_seconds=start_seconds,
        audio_track=audio_track,
        format=requested_format,
    )


def parse_audio_transcode_session_id(args, headers=None):
    raw_value = (
        args.get("session_id")
        or args.get("playback_session")
        or ((headers or {}).get("X-Cyber-Playback-Session") if headers else None)
    )
    if raw_value in (None, ""):
        return None
    session_id = str(raw_value).strip()
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise AudioTranscodeValidationError(
            "session_id must be 1-80 chars and only contain letters, numbers, '.', '_', ':' or '-'"
        )
    return session_id


def build_audio_transcode_stream_key(resource_id, session_id):
    if not session_id:
        return None
    return f"{resource_id}:{session_id}"


def build_anonymous_audio_transcode_stream_key(resource_id):
    return f"{resource_id}:anonymous:{uuid.uuid4().hex}"


def stop_active_audio_transcode_stream(stream_key, preserve_cache=False):
    if not stream_key:
        return False
    with _active_streams_lock:
        stream = _active_streams.pop(stream_key, None)
    if not stream:
        return False
    stream.preserve_cache_on_close = bool(preserve_cache)
    stream.close()
    return True


def register_active_audio_transcode_stream(stream_key, stream):
    if not stream_key or not stream:
        return stream

    original_close_callback = stream._close_callback

    def close_and_unregister():
        if callable(original_close_callback):
            original_close_callback()
        with _active_streams_lock:
            if _active_streams.get(stream_key) is stream:
                _active_streams.pop(stream_key, None)

    stream.stream_key = stream_key
    stream.set_close_callback(close_and_unregister)
    with _active_streams_lock:
        previous_stream = _active_streams.get(stream_key)
        _active_streams[stream_key] = stream
    if previous_stream and previous_stream is not stream:
        previous_stream.close()
    return stream


def record_audio_transcode_history_heartbeat(
    resource_id,
    session_id=None,
    inactive_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
):
    if not resource_id:
        return 0
    timestamp = time.monotonic()
    touched = 0
    with _active_streams_lock:
        streams = list(_active_streams.values())
    for stream in streams:
        if stream.resource_id != str(resource_id):
            continue
        if session_id and stream.session_id and stream.session_id != session_id:
            continue
        stream.touch_history(timestamp)
        touched += 1
    _record_history_session_activity(
        resource_id,
        session_id=session_id,
        timestamp=timestamp,
        inactive_timeout_seconds=inactive_timeout_seconds,
    )
    return touched


def clear_audio_transcode_resource_cache_if_inactive(resource_id, inactive_timeout_seconds=None):
    if not resource_id:
        return 0
    timeout = inactive_timeout_seconds or DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS
    if _is_resource_active(resource_id, inactive_timeout_seconds=timeout):
        return 0
    removed_bytes = _range_cache.clear_resource(resource_id)
    if removed_bytes:
        logger.info(
            "audio transcode resource cache cleared resource_id=%s bytes=%s",
            resource_id,
            removed_bytes,
        )
    return removed_bytes


def reset_audio_transcode_runtime_state_for_tests():
    with _history_sessions_lock:
        _history_sessions.clear()
        _history_resources.clear()
    with _diagnostics_lock:
        _diagnostics.clear()
    _range_cache.clear()


def build_audio_transcode_url_params(options=None):
    current = options or AudioTranscodeOptions()
    return {
        "start": _format_seconds(current.start_seconds),
        "audio_track": str(current.audio_track),
        "format": current.format,
    }


def get_audio_transcode_profile(format_name=None):
    requested_format = str(format_name or DEFAULT_AUDIO_TRANSCODE_FORMAT).strip().lower()
    profile = AUDIO_TRANSCODE_PROFILES.get(requested_format)
    if not profile:
        raise AudioTranscodeValidationError(f"Unsupported audio transcode format: {requested_format}")
    return profile


def build_audio_transcode_command(
    input_url,
    options=None,
    ffmpeg_bin=None,
    read_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS,
    realtime_input=DEFAULT_AUDIO_TRANSCODE_REALTIME_INPUT,
):
    if not input_url:
        raise AudioTranscodeValidationError("Missing ffmpeg input url")

    ffmpeg_path = ffmpeg_bin or resolve_ffmpeg_binary()
    if not ffmpeg_path:
        raise AudioTranscodeUnavailableError("ffmpeg binary is not available")

    current_options = options or AudioTranscodeOptions()
    profile = get_audio_transcode_profile(current_options.format)
    read_timeout_us = max(1, int(read_timeout_seconds or DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS)) * 1000000

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_at_eof",
        "1",
        "-reconnect_delay_max",
        "2",
        "-rw_timeout",
        str(read_timeout_us),
    ]
    if current_options.start_seconds > 0:
        command.extend(["-ss", _format_seconds(current_options.start_seconds)])
    if realtime_input:
        command.append("-re")

    command.extend([
        "-i",
        input_url,
        "-map",
        f"0:a:{current_options.audio_track}",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        str(profile.channels),
        "-ar",
        str(profile.sample_rate),
        *profile.codec_args,
        "-f",
        profile.ffmpeg_format,
        "pipe:1",
    ])
    return command


def create_audio_transcode_stream(
    input_url,
    options=None,
    ffmpeg_bin=None,
    resource_id=None,
    session_id=None,
    diagnostic_id=None,
    max_concurrent=DEFAULT_AUDIO_TRANSCODE_MAX_CONCURRENT,
    read_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS,
    history_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
    chunk_size=DEFAULT_AUDIO_TRANSCODE_CHUNK_SIZE,
    input_retries=DEFAULT_HTTP_INPUT_PROXY_MAX_RETRIES,
    first_byte_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS,
    acquire_timeout_seconds=0,
    realtime_input=DEFAULT_AUDIO_TRANSCODE_REALTIME_INPUT,
    output_rate_multiplier=DEFAULT_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER,
    output_initial_burst_seconds=DEFAULT_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS,
    range_cache_enabled=DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED,
    range_cache_bytes=DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_BYTES,
):
    current_options = options or AudioTranscodeOptions()
    profile = get_audio_transcode_profile(current_options.format)
    limiter = _get_limiter(max_concurrent)

    if not limiter.acquire(timeout_seconds=acquire_timeout_seconds):
        raise AudioTranscodeBusyError("Too many active audio transcode streams")

    process = None
    input_proxy = None
    stderr_lines = deque(maxlen=20)
    stderr_thread = None
    close_lock = threading.Lock()
    closed = False
    stream = None
    ffmpeg_input_url = input_url

    def stop_current_process():
        nonlocal process, input_proxy, stderr_thread
        _stop_process(process)
        if stderr_thread:
            stderr_thread.join(timeout=0.2)
        if input_proxy:
            input_proxy.close()
        process = None
        input_proxy = None
        stderr_thread = None

    def start_current_process():
        nonlocal process, input_proxy, ffmpeg_input_url, stderr_lines, stderr_thread
        stderr_lines = deque(maxlen=20)
        ffmpeg_input_url = input_url
        if _should_proxy_http_input(input_url):
            input_proxy = _AudioTranscodeHttpInputProxy(
                input_url,
                read_timeout_seconds=read_timeout_seconds,
                chunk_size=chunk_size,
                max_retries=input_retries,
                range_cache_enabled=range_cache_enabled,
                range_cache_bytes=range_cache_bytes,
                resource_id=resource_id,
                diagnostic_id=diagnostic_id,
            )
            ffmpeg_input_url = input_proxy.start()
        command = build_audio_transcode_command(
            ffmpeg_input_url,
            options=current_options,
            ffmpeg_bin=ffmpeg_bin,
            read_timeout_seconds=read_timeout_seconds,
            realtime_input=realtime_input,
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        stderr_thread = _start_stderr_drain(process, stderr_lines)
        record_audio_transcode_diagnostic(
            diagnostic_id,
            "ffmpeg_started",
            pid=process.pid,
            proxied_input=ffmpeg_input_url != input_url,
        )

    try:
        start_current_process()
    except Exception:
        stop_current_process()
        limiter.release()
        raise

    started_at = time.monotonic()
    history_timeout = max(1, int(history_timeout_seconds or DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS))
    first_byte_timeout = max(
        1,
        int(first_byte_timeout_seconds or DEFAULT_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS),
    )
    output_bytes_per_second = max(1, int(profile.bitrate_bps / 8))
    output_rate = max(1.0, float(output_rate_multiplier or DEFAULT_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER))
    output_burst_seconds = max(0.0, float(
        output_initial_burst_seconds
        if output_initial_burst_seconds is not None
        else DEFAULT_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS
    ))

    def close_stream():
        nonlocal closed
        with close_lock:
            if closed:
                return
            closed = True
            if stream:
                stream.closed = True
        current_process = process
        stop_current_process()
        current_stderr = list(stderr_lines)
        if current_process and current_process.returncode not in (0, None):
            log_method = (
                logger.debug
                if _is_expected_ffmpeg_output_close(current_process.returncode, current_stderr)
                else logger.warning
            )
            log_method(
                "audio transcode process ended returncode=%s stderr_tail=%s",
                current_process.returncode,
                current_stderr,
            )
        limiter.release()
        finish_audio_transcode_diagnostics(
            diagnostic_id,
            reason="closed",
            returncode=current_process.returncode if current_process else None,
        )
        if not (stream and stream.preserve_cache_on_close):
            clear_audio_transcode_resource_cache_if_inactive(
                resource_id,
                inactive_timeout_seconds=history_timeout,
            )

    def iter_chunks():
        emitted_bytes = 0
        startup_retries = 0
        attempt_started_at = time.monotonic()
        output_started_at = time.monotonic()
        output_chunk_size = min(chunk_size, DEFAULT_AUDIO_TRANSCODE_OUTPUT_CHUNK_SIZE)
        try:
            while True:
                with close_lock:
                    if closed or (stream and stream.closed):
                        break

                if not _wait_for_stdout(process, timeout_seconds=1):
                    returncode = process.poll()
                    if returncode is not None and stderr_thread:
                        stderr_thread.join(timeout=0.2)
                    if emitted_bytes <= 0 and (
                        _is_first_byte_timeout(attempt_started_at, first_byte_timeout)
                        or _is_retryable_ffmpeg_start_failure(returncode, stderr_lines)
                    ):
                        if startup_retries < int(input_retries or 0):
                            startup_retries += 1
                            logger.warning(
                                "audio transcode restarting before first byte retry=%s/%s returncode=%s elapsed=%.1f stderr_tail=%s",
                                startup_retries,
                                input_retries,
                                returncode,
                                time.monotonic() - attempt_started_at,
                                list(stderr_lines),
                            )
                            record_audio_transcode_diagnostic(
                                diagnostic_id,
                                "ffmpeg_restart",
                                counter_updates={"ffmpeg_restart_count": 1},
                                retry=startup_retries,
                                max_retries=int(input_retries or 0),
                                returncode=returncode,
                                elapsed_ms=int((time.monotonic() - attempt_started_at) * 1000),
                                stderr_tail=list(stderr_lines),
                            )
                            stop_current_process()
                            start_current_process()
                            attempt_started_at = time.monotonic()
                            continue
                        logger.warning(
                            "audio transcode first byte unavailable returncode=%s elapsed=%.1f stderr_tail=%s",
                            returncode,
                            time.monotonic() - attempt_started_at,
                            list(stderr_lines),
                        )
                        record_audio_transcode_diagnostic(
                            diagnostic_id,
                            "first_byte_unavailable",
                            returncode=returncode,
                            elapsed_ms=int((time.monotonic() - attempt_started_at) * 1000),
                            stderr_tail=list(stderr_lines),
                        )
                        break
                    continue

                try:
                    chunk = process.stdout.read(output_chunk_size)
                except ValueError:
                    break
                if not chunk:
                    returncode = process.poll()
                    if returncode is not None and stderr_thread:
                        stderr_thread.join(timeout=0.2)
                    if (
                        emitted_bytes <= 0
                        and startup_retries < int(input_retries or 0)
                        and _is_retryable_ffmpeg_start_failure(returncode, stderr_lines)
                    ):
                        startup_retries += 1
                        logger.warning(
                            "audio transcode restarting before first byte retry=%s/%s returncode=%s stderr_tail=%s",
                            startup_retries,
                            input_retries,
                            returncode,
                            list(stderr_lines),
                        )
                        record_audio_transcode_diagnostic(
                            diagnostic_id,
                            "ffmpeg_restart",
                            counter_updates={"ffmpeg_restart_count": 1},
                            retry=startup_retries,
                            max_retries=int(input_retries or 0),
                            returncode=returncode,
                            stderr_tail=list(stderr_lines),
                        )
                        stop_current_process()
                        start_current_process()
                        continue
                    break
                # Output throttling is the current anti-overread mechanism:
                # burst a few seconds to help the browser buffer, then use
                # stdout backpressure to keep ffmpeg from racing far ahead.
                slept_seconds = _sleep_for_output_rate(
                    emitted_bytes + len(chunk),
                    output_started_at,
                    output_bytes_per_second=output_bytes_per_second,
                    rate_multiplier=output_rate,
                    burst_seconds=output_burst_seconds,
                )
                if emitted_bytes == 0:
                    record_audio_transcode_diagnostic(
                        diagnostic_id,
                        "first_audio_byte",
                        timing_updates={
                            "first_audio_byte_ms": int((time.monotonic() - attempt_started_at) * 1000),
                        },
                        bytes=len(chunk),
                    )
                emitted_bytes += len(chunk)
                record_audio_transcode_diagnostic(
                    diagnostic_id,
                    counter_updates={
                        "output_chunk_count": 1,
                        "output_bytes": len(chunk),
                        "output_throttle_sleep_ms": int(slept_seconds * 1000),
                    },
                )
                yield chunk
        finally:
            close_stream()

    headers = {
        "Content-Type": profile.mime_type,
        "Cache-Control": "no-store",
        "Accept-Ranges": "none",
        "X-Accel-Buffering": "no",
        "X-Cyber-Audio-Transcode": "1",
        "X-Cyber-Audio-Start": _format_seconds(current_options.start_seconds),
        "X-Cyber-Audio-Track": str(current_options.audio_track),
        "X-Cyber-Audio-Format": profile.format,
        "X-Cyber-History-Timeout": str(history_timeout),
    }

    stream = AudioTranscodeStream(
        iterator=iter_chunks(),
        profile=profile,
        options=current_options,
        headers=headers,
        resource_id=str(resource_id) if resource_id else None,
        session_id=session_id,
        diagnostic_id=diagnostic_id,
        started_at=started_at,
        last_history_at=started_at,
        _close_callback=close_stream,
    )
    _start_history_watchdog(stream, history_timeout)
    return stream


def _parse_start_seconds(value):
    try:
        start_seconds = float(value or 0)
    except (TypeError, ValueError) as e:
        raise AudioTranscodeValidationError("start must be a non-negative number of seconds") from e
    if not math.isfinite(start_seconds) or start_seconds < 0:
        raise AudioTranscodeValidationError("start must be a non-negative number of seconds")
    return start_seconds


def _parse_audio_track(value):
    try:
        audio_track = int(value or 0)
    except (TypeError, ValueError) as e:
        raise AudioTranscodeValidationError("audio_track must be a non-negative integer") from e
    if audio_track < 0:
        raise AudioTranscodeValidationError("audio_track must be a non-negative integer")
    return audio_track


def _format_seconds(value):
    seconds = float(value or 0)
    formatted = f"{seconds:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _should_proxy_http_input(input_url):
    parsed = urlparse(str(input_url or ""))
    return parsed.scheme in {"http", "https"} and parsed.hostname not in {"127.0.0.1", "localhost"}


def _build_input_range_cache_key(input_url, resource_id=None):
    parsed = urlparse(str(input_url or ""))
    prefix = f"{resource_id}:" if resource_id else ""
    if not parsed.scheme or not parsed.netloc:
        return f"{prefix}{input_url or ''}"
    return f"{prefix}{parsed._replace(query='', fragment='').geturl()}"


def _record_history_session_activity(
    resource_id,
    session_id=None,
    timestamp=None,
    inactive_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
):
    if not resource_id:
        return

    now = timestamp or time.monotonic()
    timeout = max(1, int(inactive_timeout_seconds or DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS))
    resource_id = str(resource_id)
    stale_resource_ids = set()
    previous_resource_id = None

    with _history_sessions_lock:
        for current_resource_id, last_history_at in list(_history_resources.items()):
            if now - last_history_at <= timeout:
                continue
            stale_resource_ids.add(current_resource_id)
            _history_resources.pop(current_resource_id, None)
        _history_resources[resource_id] = now

        for current_session_id, state in list(_history_sessions.items()):
            if now - state["last_history_at"] <= timeout:
                continue
            stale_resource_ids.add(state["resource_id"])
            _history_sessions.pop(current_session_id, None)

        if session_id:
            previous_state = _history_sessions.get(session_id)
            if previous_state and previous_state["resource_id"] != resource_id:
                previous_resource_id = previous_state["resource_id"]
                _history_resources.pop(previous_resource_id, None)

            _history_sessions[session_id] = {
                "resource_id": resource_id,
                "last_history_at": now,
            }

    if previous_resource_id:
        clear_audio_transcode_resource_cache_if_inactive(
            previous_resource_id,
            inactive_timeout_seconds=timeout,
        )
    for stale_resource_id in stale_resource_ids:
        if stale_resource_id != resource_id:
            clear_audio_transcode_resource_cache_if_inactive(
                stale_resource_id,
                inactive_timeout_seconds=timeout,
            )


def _is_resource_active(resource_id, inactive_timeout_seconds=DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS):
    if not resource_id:
        return False
    resource_id = str(resource_id)
    now = time.monotonic()
    timeout = max(1, int(inactive_timeout_seconds or DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS))

    with _active_streams_lock:
        for stream in _active_streams.values():
            if stream.resource_id == resource_id and not stream.closed:
                return True

    with _history_sessions_lock:
        last_resource_history_at = _history_resources.get(resource_id)
        if last_resource_history_at and now - last_resource_history_at <= timeout:
            return True
        for state in _history_sessions.values():
            if state["resource_id"] != resource_id:
                continue
            if now - state["last_history_at"] <= timeout:
                return True
    return False


def _parse_content_length(value):
    try:
        length = int(value)
    except (TypeError, ValueError):
        return None
    return length if length >= 0 else None


def _is_response_body_complete(expected_bytes, bytes_sent):
    return expected_bytes is None or bytes_sent >= expected_bytes


def _remaining_response_bytes(expected_bytes, bytes_sent):
    if expected_bytes is None:
        return None
    return max(0, expected_bytes - bytes_sent)


def _cache_prefix_read_limit(expected_bytes, bytes_sent):
    remaining = _remaining_response_bytes(expected_bytes, bytes_sent)
    if remaining is None:
        return DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_READ_BYTES
    return min(remaining, DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_READ_BYTES)


def _response_range_start(response, fallback_range=None):
    content_range = response.headers.get("Content-Range") if response is not None else None
    if content_range:
        match = re.match(r"bytes\s+(\d+)-\d+/(?:\d+|\*)", str(content_range).strip(), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    range_start = _range_header_start(fallback_range)
    if range_start is not None:
        return range_start
    status_code = int(getattr(response, "status_code", 0) or 0)
    return 0 if status_code == 200 else None


def _response_content_total(response):
    content_range = response.headers.get("Content-Range") if response is not None else None
    if content_range:
        match = re.match(r"bytes\s+\d+-\d+/(\d+|\*)", str(content_range).strip(), flags=re.IGNORECASE)
        if match and match.group(1) != "*":
            return int(match.group(1))
        return None
    content_length = response.headers.get("Content-Length") if response is not None else None
    return _parse_content_length(content_length)


def _range_header_start(range_header):
    if not range_header:
        return None
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", str(range_header).strip())
    if not match:
        return None
    return int(match.group(1))


def _requested_range_length(range_header):
    if not range_header:
        return None
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", str(range_header).strip())
    if not match or not match.group(2):
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    if end < start:
        return None
    return end - start + 1


def _resume_range_header(original_range, bytes_sent):
    if bytes_sent <= 0:
        return original_range
    if not original_range:
        return f"bytes={bytes_sent}-"

    match = re.fullmatch(r"bytes=(\d+)-(\d*)", str(original_range).strip())
    if not match:
        return None

    start = int(match.group(1))
    end = match.group(2)
    next_start = start + bytes_sent
    if end:
        end_value = int(end)
        if next_start > end_value:
            return None
        return f"bytes={next_start}-{end_value}"
    return f"bytes={next_start}-"


def _is_retryable_upstream_status(status_code):
    return int(status_code or 0) in {408, 425, 429, 500, 502, 503, 504}


def _is_client_disconnect_error(error):
    current = error
    while current:
        if isinstance(current, (BrokenPipeError, ConnectionResetError, socket.timeout)):
            return True
        current = getattr(current, "__context__", None) or getattr(current, "__cause__", None)
    message = str(error)
    return "Connection reset by peer" in message or "Broken pipe" in message


def _is_expected_ffmpeg_output_close(returncode, stderr_lines):
    if returncode not in {1, 255}:
        return False
    stderr_text = "\n".join(str(line) for line in stderr_lines)
    expected_markers = (
        "Broken pipe",
        "Error writing trailer of pipe:1",
        "av_interleaved_write_frame(): Broken pipe",
    )
    return any(marker in stderr_text for marker in expected_markers)


def _is_retryable_ffmpeg_start_failure(returncode, stderr_lines):
    if returncode in (0, None):
        return False
    stderr_text = "\n".join(str(line) for line in stderr_lines)
    retryable_markers = (
        "End of file",
        "Connection timed out",
        "Input/output error",
        "Server returned",
        "Invalid data found when processing input",
        "Error in the pull function",
    )
    return any(marker in stderr_text for marker in retryable_markers)


def _wait_for_stdout(process, timeout_seconds=1):
    if not process or not process.stdout:
        return False
    try:
        ready, _write_ready, _error_ready = select.select([process.stdout], [], [], timeout_seconds)
    except (OSError, ValueError):
        return True
    return bool(ready)


def _is_first_byte_timeout(attempt_started_at, first_byte_timeout_seconds):
    return time.monotonic() - attempt_started_at >= first_byte_timeout_seconds


def _sleep_for_output_rate(
    emitted_bytes,
    output_started_at,
    output_bytes_per_second,
    rate_multiplier=DEFAULT_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER,
    burst_seconds=DEFAULT_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS,
):
    if emitted_bytes <= 0:
        return 0.0
    bytes_per_second = max(1, int(output_bytes_per_second or 1))
    multiplier = max(1.0, float(rate_multiplier or 1.0))
    burst_bytes = max(0, int(bytes_per_second * max(0.0, float(burst_seconds or 0.0))))
    throttled_bytes = emitted_bytes - burst_bytes
    if throttled_bytes <= 0:
        return 0.0
    target_elapsed = throttled_bytes / (bytes_per_second * multiplier)
    actual_elapsed = time.monotonic() - output_started_at
    sleep_seconds = target_elapsed - actual_elapsed
    if sleep_seconds > 0:
        actual_sleep = min(sleep_seconds, 1.0)
        time.sleep(actual_sleep)
        return actual_sleep
    return 0.0


def _send_proxy_error(handler):
    try:
        handler.send_error(502, "Audio transcode input proxy failed")
    except Exception:
        pass


def _start_stderr_drain(process, stderr_lines):
    def drain():
        try:
            for raw_line in iter(process.stderr.readline, b""):
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    stderr_lines.append(line)
        except Exception:
            logger.debug("ffmpeg stderr drain failed", exc_info=True)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    return thread


def _start_history_watchdog(stream, history_timeout_seconds):
    def watch():
        while True:
            time.sleep(DEFAULT_AUDIO_TRANSCODE_WATCHDOG_INTERVAL_SECONDS)
            if stream.closed:
                break
            if stream.seconds_since_history() < history_timeout_seconds:
                continue
            logger.warning(
                "audio transcode stopped by history watchdog resource_id=%s session_id=%s idle_seconds=%.1f timeout_seconds=%s",
                stream.resource_id,
                stream.session_id,
                stream.seconds_since_history(),
                history_timeout_seconds,
            )
            stream.close()
            break

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()


def _stop_process(process):
    if not process:
        return
    if process.stdout:
        try:
            process.stdout.close()
        except Exception:
            pass
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
