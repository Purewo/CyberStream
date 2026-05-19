from __future__ import annotations

import os
import sys
import tempfile
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.api.player_routes import _guess_video_mime_type
from backend.app.models import MediaResource, Movie, StorageSource
from backend.app.services.subtitles import clear_subtitle_discovery_cache


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


if __name__ == "__main__":
    unittest.main()
