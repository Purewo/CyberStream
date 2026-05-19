from __future__ import annotations

import os
import sys
import tempfile
import unittest
from urllib.parse import urlparse

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, StorageSource
from backend.app.services.subtitles import clear_subtitle_discovery_cache


class SubtitleDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        clear_subtitle_discovery_cache()
        self.client = self.app.test_client()

        self.source = StorageSource(
            name="Local Media",
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

    def _movie_with_resource(self):
        movie = Movie(
            tmdb_id="movie/subtitle-test",
            title="Subtitle Test",
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="Movies/Subtitle.Test.2026.mkv",
            filename="Subtitle.Test.2026.mkv",
            size=1234,
            label="Movie - 1080P",
            tech_specs={"resolution": "1080P", "resolution_rank": 1080},
        )
        db.session.add(resource)
        db.session.commit()
        return movie, resource

    def test_resource_playback_exposes_same_directory_sidecar_subtitles(self):
        movie, resource = self._movie_with_resource()
        self._write_file("Movies/Subtitle.Test.2026.mkv", "video")
        self._write_file("Movies/Subtitle.Test.2026.zh-Hans.default.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")
        self._write_file("Movies/Subtitle.Test.2026.en.vtt", "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n")
        self._write_file("Movies/Other.Movie.zh.srt", "1\n00:00:00,000 --> 00:00:01,000\nignore\n")

        response = self.client.get(f"/api/v1/movies/{movie.id}/resources")

        self.assertEqual(200, response.status_code)
        playback = response.get_json()["data"]["items"][0]["playback"]
        subtitles = playback["subtitles"]

        self.assertTrue(subtitles["supported"])
        self.assertEqual(2, len(subtitles["items"]))
        self.assertIsNone(subtitles["reason"])
        self.assertEqual(subtitles["items"][0]["id"], subtitles["default_subtitle_id"])
        self.assertEqual("zh-Hans", subtitles["items"][0]["language"]["code"])
        self.assertTrue(subtitles["items"][0]["is_default"])
        self.assertEqual("srt", subtitles["items"][0]["format"])
        self.assertTrue(subtitles["items"][0]["web_player"]["supported"])
        self.assertTrue(subtitles["items"][0]["web_player"]["requires_conversion"])
        self.assertEqual("vtt", subtitles["items"][0]["web_player"]["format"])
        self.assertTrue(subtitles["web_player_supported"])
        self.assertEqual(
            [item["url"] for item in subtitles["items"]],
            playback["external_player"]["subtitle_urls"],
        )
        self.assertTrue(
            subtitles["items"][0]["url"].endswith(
                f"/api/v1/resources/{resource.id}/stream?subtitle_id={subtitles['items'][0]['id']}"
            )
        )

    def test_stream_endpoint_serves_discovered_subtitle_by_id(self):
        movie, _resource = self._movie_with_resource()
        self._write_file("Movies/Subtitle.Test.2026.zh-Hans.default.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        resources_response = self.client.get(f"/api/v1/movies/{movie.id}/resources")
        subtitle_url = resources_response.get_json()["data"]["items"][0]["playback"]["subtitles"]["items"][0]["url"]
        subtitle_path = urlparse(subtitle_url).path + "?" + urlparse(subtitle_url).query

        response = self.client.get(subtitle_path)

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/x-subrip; charset=utf-8", response.headers["Content-Type"])
        self.assertIn("你好", response.get_data(as_text=True))

    def test_stream_endpoint_can_convert_srt_subtitle_to_webvtt(self):
        movie, _resource = self._movie_with_resource()
        self._write_file("Movies/Subtitle.Test.2026.zh-Hans.default.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        resources_response = self.client.get(f"/api/v1/movies/{movie.id}/resources")
        subtitle = resources_response.get_json()["data"]["items"][0]["playback"]["subtitles"]["items"][0]
        web_url = subtitle["web_player"]["url"]
        web_path = urlparse(web_url).path + "?" + urlparse(web_url).query

        response = self.client.get(web_path)

        self.assertEqual(200, response.status_code)
        self.assertEqual("text/vtt; charset=utf-8", response.headers["Content-Type"])
        body = response.get_data(as_text=True)
        self.assertTrue(body.startswith("WEBVTT"))
        self.assertIn("00:00:00.000 --> 00:00:01.000", body)
        self.assertIn("你好", body)

    def test_stream_endpoint_can_convert_ass_subtitle_to_webvtt(self):
        movie, _resource = self._movie_with_resource()
        self._write_file(
            "Movies/Subtitle.Test.2026.zh-Hans.ass",
            "\n".join([
                "[Script Info]",
                "Title: Subtitle Test",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                r"Dialogue: 0,0:00:02.50,0:00:04.00,Default,,0,0,0,,{\an8}第一行\N第二行",
            ]),
        )

        resources_response = self.client.get(f"/api/v1/movies/{movie.id}/resources")
        subtitle = resources_response.get_json()["data"]["items"][0]["playback"]["subtitles"]["items"][0]
        web_url = subtitle["web_player"]["url"]
        web_path = urlparse(web_url).path + "?" + urlparse(web_url).query

        self.assertEqual("ass", subtitle["format"])
        self.assertEqual("ass", subtitle["web_player"]["source_format"])
        self.assertTrue(subtitle["web_player"]["requires_conversion"])
        response = self.client.get(web_path)

        self.assertEqual(200, response.status_code)
        self.assertEqual("text/vtt; charset=utf-8", response.headers["Content-Type"])
        body = response.get_data(as_text=True)
        self.assertTrue(body.startswith("WEBVTT"))
        self.assertIn("00:00:02.500 --> 00:00:04.000", body)
        self.assertIn("第一行\n第二行", body)
        self.assertNotIn("{\\an8}", body)

    def test_stream_endpoint_rejects_unknown_subtitle_id(self):
        _movie, resource = self._movie_with_resource()
        self._write_file("Movies/Subtitle.Test.2026.zh.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        response = self.client.get(f"/api/v1/resources/{resource.id}/stream?subtitle_id=sub_missing")

        self.assertEqual(404, response.status_code)

    def test_sidecar_subtitle_cannot_be_removed_or_set_default_by_bound_subtitle_api(self):
        movie, resource = self._movie_with_resource()
        self._write_file("Movies/Subtitle.Test.2026.zh-Hans.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        resources_response = self.client.get(f"/api/v1/movies/{movie.id}/resources")
        subtitle_id = resources_response.get_json()["data"]["items"][0]["playback"]["subtitles"]["items"][0]["id"]

        delete_response = self.client.delete(f"/api/v1/resources/{resource.id}/subtitles/{subtitle_id}")
        default_response = self.client.post(f"/api/v1/resources/{resource.id}/subtitles/{subtitle_id}/default")

        self.assertEqual(400, delete_response.status_code)
        self.assertEqual(40070, delete_response.get_json()["code"])
        self.assertEqual(400, default_response.status_code)
        self.assertEqual(40071, default_response.get_json()["code"])


if __name__ == "__main__":
    unittest.main()
