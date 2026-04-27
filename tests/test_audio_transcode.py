from __future__ import annotations

import io
import sys
import unittest
from unittest.mock import Mock, patch

import requests

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, StorageSource
from backend.app.services.audio_transcode import (
    AudioTranscodeBusyError,
    AudioTranscodeOptions,
    AudioTranscodeStream,
    AudioTranscodeValidationError,
    _AudioTranscodeHttpInputProxy,
    _range_cache,
    build_audio_transcode_command,
    build_audio_transcode_stream_key,
    clear_audio_transcode_resource_cache_if_inactive,
    get_audio_transcode_profile,
    get_audio_transcode_diagnostics,
    parse_audio_transcode_session_id,
    parse_audio_transcode_options,
    record_audio_transcode_history_heartbeat,
    register_active_audio_transcode_stream,
    reset_audio_transcode_runtime_state_for_tests,
    start_audio_transcode_diagnostics,
    stop_active_audio_transcode_stream,
)


class _FakeProxyHandler:
    def __init__(self, range_header=None):
        self.headers = {}
        if range_header:
            self.headers["Range"] = range_header
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = []
        self.error_status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass

    def send_error(self, status, _message=None):
        self.error_status = status


class _FakeProxyResponse:
    def __init__(self, status_code=206, headers=None, chunks=None, error_after_chunks=False):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks or [])
        self.error_after_chunks = error_after_chunks
        self.closed = False

    def iter_content(self, chunk_size=1):
        for chunk in self._chunks:
            yield chunk
        if self.error_after_chunks:
            raise requests.ConnectionError("upstream interrupted")

    def close(self):
        self.closed = True


class AudioTranscodeServiceTests(unittest.TestCase):
    def tearDown(self):
        reset_audio_transcode_runtime_state_for_tests()

    def test_parse_options_accepts_seek_track_and_format(self):
        options = parse_audio_transcode_options({
            "start": "123.456",
            "audio_track": "2",
            "format": "aac",
        })

        self.assertEqual(123.456, options.start_seconds)
        self.assertEqual(2, options.audio_track)
        self.assertEqual("aac", options.format)

    def test_parse_options_rejects_negative_seek(self):
        with self.assertRaises(AudioTranscodeValidationError):
            parse_audio_transcode_options({"start": "-1"})

    def test_parse_session_id_accepts_safe_token(self):
        session_id = parse_audio_transcode_session_id({"session_id": "playback_01:test-2"})

        self.assertEqual("playback_01:test-2", session_id)
        self.assertEqual(
            "resource-id:playback_01:test-2",
            build_audio_transcode_stream_key("resource-id", session_id),
        )

    def test_parse_session_id_rejects_unsafe_token(self):
        with self.assertRaises(AudioTranscodeValidationError):
            parse_audio_transcode_session_id({"session_id": "../bad"})

    def test_build_command_uses_fast_input_seek_and_audio_only_output(self):
        command = build_audio_transcode_command(
            "https://media.example/movie.mkv",
            options=AudioTranscodeOptions(start_seconds=65.5, audio_track=1, format="mp3"),
            ffmpeg_bin="/opt/bin/ffmpeg",
            read_timeout_seconds=10,
        )

        self.assertEqual("/opt/bin/ffmpeg", command[0])
        self.assertLess(command.index("-ss"), command.index("-i"))
        self.assertNotIn("-re", command)
        self.assertIn("65.5", command)
        self.assertIn("0:a:1", command)
        self.assertIn("-vn", command)
        self.assertIn("-sn", command)
        self.assertIn("-dn", command)
        self.assertIn("libmp3lame", command)
        self.assertEqual("pipe:1", command[-1])

    def test_build_command_can_use_ffmpeg_native_realtime_input(self):
        command = build_audio_transcode_command(
            "https://media.example/movie.mkv",
            options=AudioTranscodeOptions(start_seconds=65.5, audio_track=1, format="mp3"),
            ffmpeg_bin="/opt/bin/ffmpeg",
            realtime_input=True,
        )

        self.assertLess(command.index("-re"), command.index("-i"))

    def test_history_heartbeat_touches_matching_active_stream(self):
        profile = get_audio_transcode_profile("mp3")
        stream = AudioTranscodeStream(
            iterator=iter(()),
            profile=profile,
            options=AudioTranscodeOptions(format="mp3"),
            headers={},
            resource_id="resource-1",
            session_id="session-1",
            started_at=1,
            last_history_at=1,
        )

        register_active_audio_transcode_stream("resource-1:session-1", stream)
        try:
            touched = record_audio_transcode_history_heartbeat("resource-1", session_id="session-1")

            self.assertEqual(1, touched)
            self.assertGreater(stream.last_history_at, 1)
        finally:
            stop_active_audio_transcode_stream("resource-1:session-1")

    def test_http_input_proxy_retries_retryable_status_before_headers(self):
        proxy = _AudioTranscodeHttpInputProxy(
            "https://alist.example/d/movie.mkv",
            max_retries=2,
            retry_delay_seconds=0,
        )
        responses = [
            _FakeProxyResponse(status_code=502, headers={"Content-Length": "0"}),
            _FakeProxyResponse(
                status_code=206,
                headers={"Content-Length": "4", "Content-Range": "bytes 0-3/4"},
                chunks=[b"abcd"],
            ),
        ]
        calls = []

        def request(method, url, headers=None, **_kwargs):
            calls.append(dict(headers or {}))
            return responses.pop(0)

        proxy.session.request = request
        handler = _FakeProxyHandler(range_header="bytes=0-")

        proxy.handle(handler)

        self.assertEqual(206, handler.status)
        self.assertEqual(b"abcd", handler.wfile.getvalue())
        self.assertEqual(["bytes=0-", "bytes=0-"], [call.get("Range") for call in calls])

    def test_http_input_proxy_resumes_range_after_upstream_interrupt(self):
        proxy = _AudioTranscodeHttpInputProxy(
            "https://alist.example/d/movie.mkv",
            max_retries=2,
            retry_delay_seconds=0,
        )
        responses = [
            _FakeProxyResponse(
                status_code=206,
                headers={"Content-Length": "6", "Content-Range": "bytes 100-105/200"},
                chunks=[b"ab"],
                error_after_chunks=True,
            ),
            _FakeProxyResponse(
                status_code=206,
                headers={"Content-Length": "4", "Content-Range": "bytes 102-105/200"},
                chunks=[b"cdef"],
            ),
        ]
        calls = []

        def request(method, url, headers=None, **_kwargs):
            calls.append(dict(headers or {}))
            return responses.pop(0)

        proxy.session.request = request
        handler = _FakeProxyHandler(range_header="bytes=100-105")

        proxy.handle(handler)

        self.assertEqual(206, handler.status)
        self.assertEqual(b"abcdef", handler.wfile.getvalue())
        self.assertEqual(["bytes=100-105", "bytes=102-105"], [call.get("Range") for call in calls])

    def test_http_input_proxy_serves_repeated_range_from_memory_cache(self):
        proxy = _AudioTranscodeHttpInputProxy(
            "https://alist.example/d/movie.mkv?sign=one",
            range_cache_enabled=True,
            range_cache_bytes=1024,
            max_retries=0,
        )
        calls = []
        responses = [
            _FakeProxyResponse(
                status_code=206,
                headers={"Content-Length": "6", "Content-Range": "bytes 100-105/200"},
                chunks=[b"abc", b"def"],
            ),
            _FakeProxyResponse(
                status_code=206,
                headers={"Content-Length": "6", "Content-Range": "bytes 100-105/200"},
                chunks=[b"xxxxxx"],
            ),
        ]

        def request(method, url, headers=None, **_kwargs):
            calls.append(dict(headers or {}))
            return responses.pop(0)

        proxy.session.request = request
        first = _FakeProxyHandler(range_header="bytes=100-105")
        second = _FakeProxyHandler(range_header="bytes=100-105")

        proxy.handle(first)
        proxy.handle(second)

        self.assertEqual(b"abcdef", first.wfile.getvalue())
        self.assertEqual(b"abcdef", second.wfile.getvalue())
        self.assertEqual(["bytes=100-105"], [call.get("Range") for call in calls])

    def test_http_input_proxy_serves_nearby_range_from_memory_cache(self):
        proxy = _AudioTranscodeHttpInputProxy(
            "https://alist.example/d/movie.mkv?sign=one",
            range_cache_enabled=True,
            range_cache_bytes=1024,
            max_retries=0,
        )
        responses = [
            _FakeProxyResponse(
                status_code=206,
                headers={"Content-Length": "6", "Content-Range": "bytes 100-105/200"},
                chunks=[b"abcdef"],
            ),
            _FakeProxyResponse(
                status_code=206,
                headers={"Content-Length": "4", "Content-Range": "bytes 102-105/200"},
                chunks=[b"zzzz"],
            ),
        ]

        def request(method, url, headers=None, **_kwargs):
            return responses.pop(0)

        proxy.session.request = request
        first = _FakeProxyHandler(range_header="bytes=100-105")
        nearby = _FakeProxyHandler(range_header="bytes=102-105")

        proxy.handle(first)
        proxy.handle(nearby)

        self.assertEqual(b"abcdef", first.wfile.getvalue())
        self.assertEqual(b"cdef", nearby.wfile.getvalue())

    def test_http_input_proxy_serves_cached_range_without_opening_upstream(self):
        diagnostic_id = start_audio_transcode_diagnostics(
            "resource-1",
            session_id="session-1",
            options=AudioTranscodeOptions(format="mp3"),
            input_url="https://alist.example/d/movie.mkv?sign=one",
            stream_key="resource-1:session-1",
        )
        proxy = _AudioTranscodeHttpInputProxy(
            "https://alist.example/d/movie.mkv?sign=one",
            range_cache_enabled=True,
            range_cache_bytes=1024,
            max_retries=0,
            resource_id="resource-1",
            diagnostic_id=diagnostic_id,
        )
        _range_cache.put(
            proxy.cache_key,
            100,
            b"abcdef",
            resource_id=proxy.resource_id,
            content_length=200,
        )

        def request(_method, _url, **_kwargs):
            raise AssertionError("cached range should not open upstream")

        proxy.session.request = request
        handler = _FakeProxyHandler(range_header="bytes=102-105")

        proxy.handle(handler)

        self.assertEqual(206, handler.status)
        self.assertEqual(b"cdef", handler.wfile.getvalue())
        self.assertIn(("Content-Range", "bytes 102-105/200"), handler.response_headers)
        diagnostics = get_audio_transcode_diagnostics("resource-1", session_id="session-1")
        self.assertEqual(1, diagnostics["active_count"])
        counters = diagnostics["items"][0]["counters"]
        self.assertEqual(1, counters["cache_only_hit_count"])
        self.assertEqual(4, counters["cache_hit_bytes"])
        self.assertEqual(0, counters["upstream_open_count"])
        self.assertEqual(
            "https://alist.example/d/movie.mkv",
            diagnostics["items"][0]["input"]["url"],
        )

    def test_history_without_session_keeps_current_resource_cache_temporarily(self):
        _range_cache.configure(enabled=True, max_bytes=1024)
        _range_cache.put("resource-1:url", 0, b"current-cache", resource_id="resource-1")

        record_audio_transcode_history_heartbeat(
            "resource-1",
            inactive_timeout_seconds=180,
        )
        removed = clear_audio_transcode_resource_cache_if_inactive(
            "resource-1",
            inactive_timeout_seconds=180,
        )

        self.assertEqual(0, removed)
        self.assertEqual(b"current-cache", _range_cache.get("resource-1:url", 0))

    def test_history_switch_clears_previous_resource_cache_when_inactive(self):
        _range_cache.configure(enabled=True, max_bytes=1024)
        _range_cache.put("old-resource:url", 0, b"old-cache", resource_id="old-resource")

        record_audio_transcode_history_heartbeat(
            "old-resource",
            session_id="session-1",
            inactive_timeout_seconds=180,
        )
        record_audio_transcode_history_heartbeat(
            "new-resource",
            session_id="session-1",
            inactive_timeout_seconds=180,
        )

        self.assertEqual(b"", _range_cache.get("old-resource:url", 0))

    def test_history_switch_keeps_previous_resource_cache_when_other_session_active(self):
        _range_cache.configure(enabled=True, max_bytes=1024)
        _range_cache.put("old-resource:url", 0, b"old-cache", resource_id="old-resource")

        record_audio_transcode_history_heartbeat(
            "old-resource",
            session_id="session-1",
            inactive_timeout_seconds=180,
        )
        record_audio_transcode_history_heartbeat(
            "old-resource",
            session_id="session-2",
            inactive_timeout_seconds=180,
        )
        record_audio_transcode_history_heartbeat(
            "new-resource",
            session_id="session-1",
            inactive_timeout_seconds=180,
        )

        self.assertEqual(b"old-cache", _range_cache.get("old-resource:url", 0))


class AudioTranscodeRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "FFMPEG_BIN": "/opt/bin/ffmpeg",
            "FFMPEG_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS": 7,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()

        self.movie = Movie(id="22222222-2222-2222-2222-222222222222", title="Movie")
        self.source = StorageSource(
            id=1,
            name="AList",
            type="alist",
            config={"base_url": "http://alist.local:5244", "token": "token"},
        )
        self.resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            movie_id=self.movie.id,
            source=self.source,
            filename="Movie.TrueHD.mkv",
            path="Movie.TrueHD.mkv",
            tech_specs={"audio_codec": "Dolby TrueHD"},
        )
        db.session.add_all([self.movie, self.source, self.resource])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    @patch("backend.app.api.player_routes.resolve_ffmpeg_binary", return_value="/opt/bin/ffmpeg")
    @patch("backend.app.api.player_routes.provider_factory")
    @patch("backend.app.api.player_routes.create_audio_transcode_stream")
    def test_audio_transcode_route_streams_selected_format(self, create_stream, provider_factory, _resolve):
        provider = Mock()
        provider.get_ffmpeg_input.return_value = "https://media.example/movie.mkv"
        provider_factory.get_provider.return_value = provider
        profile = get_audio_transcode_profile("mp3")
        create_stream.return_value = AudioTranscodeStream(
            iterator=iter([b"abc"]),
            profile=profile,
            options=AudioTranscodeOptions(start_seconds=12.5, audio_track=1, format="mp3"),
            headers={"Content-Type": profile.mime_type, "X-Cyber-Audio-Start": "12.5"},
        )

        response = self.client.get(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode"
            "?start=12.5&audio_track=1&format=mp3"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"abc", response.data)
        self.assertEqual("audio/mpeg", response.content_type)
        provider.get_ffmpeg_input.assert_called_once_with("Movie.TrueHD.mkv")
        options = create_stream.call_args.kwargs["options"]
        self.assertEqual(12.5, options.start_seconds)
        self.assertEqual(1, options.audio_track)
        self.assertEqual("mp3", options.format)
        self.assertEqual(
            7,
            create_stream.call_args.kwargs["history_timeout_seconds"],
        )

    @patch("backend.app.api.player_routes.register_active_audio_transcode_stream", side_effect=lambda _key, stream: stream)
    @patch("backend.app.api.player_routes.stop_active_audio_transcode_stream", return_value=True)
    @patch("backend.app.api.player_routes.resolve_ffmpeg_binary", return_value="/opt/bin/ffmpeg")
    @patch("backend.app.api.player_routes.provider_factory")
    @patch("backend.app.api.player_routes.create_audio_transcode_stream")
    def test_audio_transcode_route_replaces_same_playback_session(
        self,
        create_stream,
        provider_factory,
        _resolve,
        stop_stream,
        register_stream,
    ):
        provider = Mock()
        provider.get_ffmpeg_input.return_value = "https://media.example/movie.mkv"
        provider_factory.get_provider.return_value = provider
        profile = get_audio_transcode_profile("mp3")
        create_stream.return_value = AudioTranscodeStream(
            iterator=iter([b"abc"]),
            profile=profile,
            options=AudioTranscodeOptions(format="mp3"),
            headers={"Content-Type": profile.mime_type},
        )

        response = self.client.get(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode"
            "?session_id=playback_01&format=mp3"
        )

        key = "11111111-1111-1111-1111-111111111111:playback_01"
        self.assertEqual(200, response.status_code)
        self.assertEqual("playback_01", response.headers.get("X-Cyber-Playback-Session"))
        stop_stream.assert_called_once_with(key, preserve_cache=True)
        register_stream.assert_called_once_with(key, create_stream.return_value)

        diagnostics = self.client.get(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode/diagnostics"
            "?session_id=playback_01"
        )
        self.assertEqual(200, diagnostics.status_code)
        payload = diagnostics.get_json()["data"]
        self.assertEqual(1, payload["active_count"])
        self.assertEqual("playback_01", payload["items"][0]["session_id"])
        self.assertEqual(
            "https://media.example/movie.mkv",
            payload["items"][0]["input"]["url"],
        )
        self.assertEqual(0.0, payload["items"][0]["options"]["start_seconds"])

    @patch("backend.app.api.player_routes.register_active_audio_transcode_stream", side_effect=lambda _key, stream: stream)
    @patch("backend.app.api.player_routes.stop_active_audio_transcode_stream", return_value=True)
    @patch("backend.app.api.player_routes.resolve_ffmpeg_binary", return_value="/opt/bin/ffmpeg")
    @patch("backend.app.api.player_routes.provider_factory")
    @patch("backend.app.api.player_routes.create_audio_transcode_stream")
    def test_audio_transcode_route_stops_existing_session_before_resolving_input(
        self,
        create_stream,
        provider_factory,
        _resolve,
        stop_stream,
        _register_stream,
    ):
        events = []
        provider = Mock()
        provider.get_ffmpeg_input.side_effect = lambda _path: events.append("get_input") or "https://media.example/movie.mkv"
        provider_factory.get_provider.return_value = provider
        stop_stream.side_effect = lambda _key, **_kwargs: events.append("stop") or True
        profile = get_audio_transcode_profile("mp3")
        create_stream.return_value = AudioTranscodeStream(
            iterator=iter([b"abc"]),
            profile=profile,
            options=AudioTranscodeOptions(format="mp3"),
            headers={"Content-Type": profile.mime_type},
        )

        response = self.client.get(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode"
            "?session_id=playback_01&format=mp3&start=10"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(["stop", "get_input"], events)
        self.assertEqual(
            3,
            create_stream.call_args.kwargs["acquire_timeout_seconds"],
        )
        self.assertIs(
            True,
            create_stream.call_args.kwargs["realtime_input"],
        )
        self.assertEqual(
            1.5,
            create_stream.call_args.kwargs["output_rate_multiplier"],
        )
        self.assertEqual(
            8,
            create_stream.call_args.kwargs["output_initial_burst_seconds"],
        )

    @patch("backend.app.api.player_routes.resolve_ffmpeg_binary", return_value="/opt/bin/ffmpeg")
    @patch("backend.app.api.player_routes.provider_factory")
    @patch("backend.app.api.player_routes.create_audio_transcode_stream")
    def test_audio_transcode_route_returns_429_when_limiter_is_full(self, create_stream, provider_factory, _resolve):
        provider = Mock()
        provider.get_ffmpeg_input.return_value = "https://media.example/movie.mkv"
        provider_factory.get_provider.return_value = provider
        create_stream.side_effect = AudioTranscodeBusyError("Too many active audio transcode streams")

        response = self.client.get(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode"
        )

        self.assertEqual(429, response.status_code)
        self.assertEqual("5", response.headers.get("Retry-After"))

    @patch("backend.app.api.player_routes.resolve_ffmpeg_binary", return_value="/opt/bin/ffmpeg")
    @patch("backend.app.api.player_routes.provider_factory")
    def test_audio_transcode_route_rejects_invalid_seek(self, provider_factory, _resolve):
        response = self.client.get(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode?start=-1"
        )

        self.assertEqual(400, response.status_code)
        provider_factory.get_provider.assert_not_called()

    @patch("backend.app.api.player_routes.stop_active_audio_transcode_stream", return_value=True)
    def test_audio_transcode_stop_route_stops_session(self, stop_stream):
        response = self.client.delete(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode"
            "?session_id=playback_01"
        )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.get_json()["data"]["stopped"])
        stop_stream.assert_called_once_with(
            "11111111-1111-1111-1111-111111111111:playback_01"
        )


if __name__ == "__main__":
    unittest.main()
