from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.api.player_routes import _guess_video_mime_type
from backend.app.models import MediaResource, Movie, StorageSource
from backend.app.services.subtitles import clear_subtitle_discovery_cache, discover_resource_subtitles


class FakeRedirectStreamProvider:
    def __init__(self, stream_location, subtitle_location=None):
        self.stream_location = stream_location
        self.subtitle_location = subtitle_location or stream_location

    def list_items(self, directory):
        if directory != "Movies":
            return []
        return [
            {
                "path": "Movies/External.Playback.Test.2026.zh-Hans.default.srt",
                "name": "External.Playback.Test.2026.zh-Hans.default.srt",
                "isdir": False,
                "size": 42,
            }
        ]

    def get_stream_data(self, path, range_header=None):
        if str(path or "").endswith(".srt"):
            return None, 302, 0, self.subtitle_location
        return None, 302, 0, self.stream_location


class PlayerRoutesTests(unittest.TestCase):
    def test_guess_video_mime_type_uses_resource_extension(self):
        cases = [
            ("movie.mp4", "video/mp4"),
            ("movie.mkv", "video/x-matroska"),
            ("movie.ts", "video/mp2t"),
            ("movie.m2ts", "video/mp2t"),
            ("movie.avi", "video/x-msvideo"),
            ("movie.iso", "application/octet-stream"),
        ]

        for filename, expected_mime in cases:
            with self.subTest(filename=filename):
                resource = MediaResource(filename=filename, path=f"movies/{filename}")
                self.assertEqual(expected_mime, _guess_video_mime_type(resource))


class ExternalPlaybackRouteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TRUST_PROXY_HEADERS": True,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        clear_subtitle_discovery_cache()
        self.client = self.app.test_client()

        self.source = StorageSource(
            name="Local",
            type="local",
            config={"root_path": self.tempdir.name},
        )
        db.session.add(self.source)
        db.session.commit()

    def tearDown(self):
        clear_subtitle_discovery_cache()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.tempdir.cleanup()

    def _write_file(self, relative_path, content=""):
        full_path = os.path.join(self.tempdir.name, *relative_path.split("/"))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _resource(self):
        movie = Movie(
            title="External Playback Test",
            original_title="External Playback Test",
            year=2026,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="Movies/External.Playback.Test.2026.mkv",
            filename="External.Playback.Test.2026.mkv",
            size=1234,
            label="Movie - 1080P",
            tech_specs={"resolution": "1080P", "resolution_rank": 1080, "audio_codec": "AAC"},
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def test_external_playback_manifest_returns_absolute_stream_playlist_and_subtitles(self):
        resource = self._resource()
        self._write_file("Movies/External.Playback.Test.2026.zh-Hans.default.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        response = self.client.get(
            f"/api/v1/resources/{resource.id}/external-playback",
            base_url="http://127.0.0.1:5004",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "pw.pioneer.fan:84",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        expected_prefix = f"https://pw.pioneer.fan:84/api/v1/resources/{resource.id}"

        self.assertTrue(data["handoff"]["supported"])
        self.assertEqual(f"{expected_prefix}/stream", data["stream"]["url"])
        self.assertEqual(f"{expected_prefix}/external-playback", data["handoff"]["manifest_url"])
        self.assertEqual(f"{expected_prefix}/external-playback?format=m3u", data["handoff"]["playlist_url"])
        self.assertEqual("audio/x-mpegurl", data["handoff"]["playlist_mime_type"])
        self.assertEqual(
            f"{expected_prefix}/stream?subtitle_id={data['subtitles']['default_subtitle_id']}",
            data["subtitles"]["default_url"],
        )
        self.assertIn("vlc", {item["key"] for item in data["player_profiles"]})

    def test_external_playback_m3u_includes_stream_and_default_subtitle(self):
        resource = self._resource()
        self._write_file("Movies/External.Playback.Test.2026.zh-Hans.default.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        response = self.client.get(
            f"/api/v1/resources/{resource.id}/external-playback?format=m3u",
            base_url="http://127.0.0.1:5004",
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("audio/x-mpegurl; charset=utf-8", response.headers["Content-Type"])
        body = response.get_data(as_text=True)
        self.assertTrue(body.startswith("#EXTM3U\n"))
        self.assertIn(f"http://127.0.0.1:5004/api/v1/resources/{resource.id}/stream", body)
        self.assertIn("#EXTVLCOPT:sub-file=", body)

    def test_external_playback_rejects_unknown_format(self):
        resource = self._resource()

        response = self.client.get(f"/api/v1/resources/{resource.id}/external-playback?format=pls")

        self.assertEqual(400, response.status_code)
        self.assertEqual(40073, response.get_json()["code"])

    def test_local_stream_honors_suffix_range(self):
        resource = self._resource()
        self._write_file("Movies/External.Playback.Test.2026.mkv", "abcdef")

        response = self.client.get(
            f"/api/v1/resources/{resource.id}/stream",
            headers={"Range": "bytes=-2"},
        )

        self.assertEqual(206, response.status_code)
        self.assertEqual(b"ef", response.data)
        self.assertEqual("bytes 4-5/6", response.headers["Content-Range"])
        self.assertEqual("2", response.headers["Content-Length"])

    def test_local_stream_invalid_range_returns_416_with_content_range(self):
        resource = self._resource()
        self._write_file("Movies/External.Playback.Test.2026.mkv", "abcdef")

        response = self.client.get(
            f"/api/v1/resources/{resource.id}/stream",
            headers={"Range": "bytes=5-2"},
        )

        self.assertEqual(416, response.status_code)
        self.assertEqual("bytes */6", response.headers["Content-Range"])
        self.assertEqual("bytes", response.headers["Accept-Ranges"])

    def test_stream_redirect_allows_public_provider_url(self):
        resource = self._resource()
        provider = FakeRedirectStreamProvider("https://cdn.example.com/media/movie.mkv?token=1")

        with patch("backend.app.api.player_routes.provider_factory.get_provider", return_value=provider):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/stream",
                follow_redirects=False,
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("https://cdn.example.com/media/movie.mkv?token=1", response.headers["Location"])

    def test_stream_redirect_blocks_private_provider_url(self):
        resource = self._resource()
        provider = FakeRedirectStreamProvider("http://127.0.0.1/internal/movie.mkv")

        with patch("backend.app.api.player_routes.provider_factory.get_provider", return_value=provider):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/stream",
                follow_redirects=False,
            )

        self.assertEqual(502, response.status_code)
        self.assertEqual(b"Unsafe stream redirect URL", response.data)
        self.assertNotIn("Location", response.headers)

    def test_subtitle_redirect_blocks_private_provider_url(self):
        resource = self._resource()
        provider = FakeRedirectStreamProvider(
            "https://cdn.example.com/media/movie.mkv",
            subtitle_location="http://127.0.0.1/internal/subtitle.srt",
        )

        with patch("backend.app.api.player_routes.provider_factory.get_provider", return_value=provider):
            subtitle_payload = discover_resource_subtitles(resource)
            subtitle_id = subtitle_payload["items"][0]["id"]
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/stream?subtitle_id={subtitle_id}",
                follow_redirects=False,
            )

        self.assertEqual(502, response.status_code)
        self.assertEqual(b"Unsafe subtitle redirect URL", response.data)
        self.assertNotIn("Location", response.headers)


class CloudTranscodeRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TRUST_PROXY_HEADERS": True,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.source = StorageSource(
            name="QuarkTV",
            type="quarktv",
            config={
                "auth_state": "ready",
                "openlist_storage_id": 21,
                "mount_path": "/cyberstream/quarktv/fake",
                "link_method": "download",
            },
        )
        movie = Movie(
            title="Cloud Transcode Test",
            original_title="Cloud Transcode Test",
            year=2026,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add_all([self.source, movie])
        db.session.commit()

        self.resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="Movies/Cloud.Transcode.Test.mkv",
            filename="Cloud.Transcode.Test.mkv",
            size=1234,
            label="Movie - 2160P",
            tech_specs={"resolution": "2160P", "resolution_rank": 2160},
        )
        db.session.add(self.resource)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _qualities_payload(self):
        resource_id = str(self.resource.id)
        return {
            "resource_id": resource_id,
            "storage_type": "quarktv",
            "provider": "QuarkTV",
            "mode": "provider_cloud_transcode",
            "default_resolution": "4k",
            "selected_resolution": "4k",
            "selected_item": {
                "resolution": "4k",
                "label": "4K",
                "available": True,
                "url": "https://provider.example/4k.m3u8",
                "stream_url": f"/api/v1/resources/{resource_id}/stream-transcoded?resolution=4k",
            },
            "items": [
                {
                    "resolution": "low",
                    "label": "LD",
                    "available": True,
                    "width": 480,
                    "height": 270,
                    "url": "https://provider.example/low.m3u8",
                    "stream_url": f"/api/v1/resources/{resource_id}/stream-transcoded?resolution=low",
                },
                {
                    "resolution": "4k",
                    "label": "4K",
                    "available": True,
                    "width": 3840,
                    "height": 2160,
                    "url": "https://provider.example/4k.m3u8",
                    "stream_url": f"/api/v1/resources/{resource_id}/stream-transcoded?resolution=4k",
                },
            ],
            "warnings": [],
        }

    def test_streaming_qualities_returns_provider_variants(self):
        with patch(
            "backend.app.api.player_routes.build_streaming_qualities",
            return_value=self._qualities_payload(),
        ) as mocked:
            response = self.client.get(f"/api/v1/resources/{self.resource.id}/streaming-qualities")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("QuarkTV", data["provider"])
        self.assertEqual("4k", data["default_resolution"])
        self.assertEqual(["low", "4k"], [item["resolution"] for item in data["items"]])
        mocked.assert_called_once()

    def test_stream_transcoded_redirects_to_selected_provider_url(self):
        with patch(
            "backend.app.api.player_routes.build_streaming_qualities",
            return_value=self._qualities_payload(),
        ) as mocked:
            response = self.client.get(
                f"/api/v1/resources/{self.resource.id}/stream-transcoded?resolution=4k",
                follow_redirects=False,
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("https://provider.example/4k.m3u8", response.headers["Location"])
        mocked.assert_called_once()

    def test_stream_transcoded_blocks_private_provider_url(self):
        payload = self._qualities_payload()
        payload["selected_item"] = {
            **payload["selected_item"],
            "url": "http://127.0.0.1/internal/4k.m3u8",
        }
        with patch(
            "backend.app.api.player_routes.build_streaming_qualities",
            return_value=payload,
        ) as mocked:
            response = self.client.get(
                f"/api/v1/resources/{self.resource.id}/stream-transcoded?resolution=4k",
                follow_redirects=False,
            )

        self.assertEqual(502, response.status_code)
        self.assertEqual(b"Unsafe transcoded stream redirect URL", response.data)
        self.assertNotIn("Location", response.headers)
        mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
