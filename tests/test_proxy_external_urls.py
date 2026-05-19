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
from backend.app.models import MediaResource, Movie, StorageSource
from backend.app.services.subtitles import clear_subtitle_discovery_cache


class ProxyExternalUrlTests(unittest.TestCase):
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

    def _movie_with_resource(self):
        movie = Movie(
            title="Proxy URL Test",
            original_title="Proxy URL Test",
            year=2026,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="Movies/Proxy.URL.Test.2026.mkv",
            filename="Proxy.URL.Test.2026.mkv",
            size=1234,
            tech_specs={"audio_codec": "Dolby TrueHD Atmos"},
        )
        db.session.add(resource)
        db.session.commit()
        return movie, resource

    def test_playback_and_subtitle_urls_respect_forwarded_https_headers(self):
        movie, resource = self._movie_with_resource()
        self._write_file("Movies/Proxy.URL.Test.2026.zh-Hans.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        response = self.client.get(
            f"/api/v1/movies/{movie.id}/resources",
            base_url="http://127.0.0.1:5004",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "pw.pioneer.fan:84",
            },
        )

        self.assertEqual(200, response.status_code)
        playback = response.get_json()["data"]["items"][0]["playback"]
        subtitle = playback["subtitles"]["items"][0]
        expected_prefix = f"https://pw.pioneer.fan:84/api/v1/resources/{resource.id}"

        self.assertEqual(f"{expected_prefix}/stream", playback["stream_url"])
        self.assertEqual(playback["stream_url"], playback["external_player"]["url"])
        self.assertEqual(f"{expected_prefix}/audio-transcode", playback["audio"]["server_transcode"]["endpoint"])
        self.assertTrue(playback["audio"]["server_transcode"]["url"].startswith(f"{expected_prefix}/audio-transcode?"))
        self.assertEqual(
            f"{expected_prefix}/stream?subtitle_id={subtitle['id']}",
            subtitle["url"],
        )
        self.assertEqual(
            f"{expected_prefix}/stream?subtitle_id={subtitle['id']}&format=vtt",
            subtitle["web_player"]["url"],
        )

    def test_public_base_url_overrides_request_scheme_when_configured(self):
        self.app.config["BACKEND_PUBLIC_BASE_URL"] = "https://api.example.test"
        movie, resource = self._movie_with_resource()

        response = self.client.get(
            f"/api/v1/movies/{movie.id}/resources",
            base_url="http://127.0.0.1:5004",
        )

        self.assertEqual(200, response.status_code)
        playback = response.get_json()["data"]["items"][0]["playback"]
        self.assertEqual(
            f"https://api.example.test/api/v1/resources/{resource.id}/stream",
            playback["stream_url"],
        )

    def test_public_host_without_forwarded_proto_uses_preferred_https_scheme(self):
        movie, resource = self._movie_with_resource()
        self._write_file("Movies/Proxy.URL.Test.2026.zh-Hans.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n")

        response = self.client.get(
            f"/api/v1/movies/{movie.id}/resources",
            base_url="http://pw.pioneer.fan:84",
        )

        self.assertEqual(200, response.status_code)
        playback = response.get_json()["data"]["items"][0]["playback"]
        subtitle = playback["subtitles"]["items"][0]
        expected_prefix = f"https://pw.pioneer.fan:84/api/v1/resources/{resource.id}"

        self.assertEqual(f"{expected_prefix}/stream", playback["stream_url"])
        self.assertEqual(f"{expected_prefix}/audio-transcode", playback["audio"]["server_transcode"]["endpoint"])
        self.assertTrue(playback["audio"]["server_transcode"]["url"].startswith(f"{expected_prefix}/audio-transcode?"))
        self.assertEqual(f"{expected_prefix}/stream?subtitle_id={subtitle['id']}", subtitle["url"])
        self.assertEqual(
            f"{expected_prefix}/stream?subtitle_id={subtitle['id']}&format=vtt",
            subtitle["web_player"]["url"],
        )

    def test_localhost_without_forwarded_proto_keeps_http_for_local_development(self):
        movie, resource = self._movie_with_resource()

        response = self.client.get(
            f"/api/v1/movies/{movie.id}/resources",
            base_url="http://127.0.0.1:5004",
        )

        self.assertEqual(200, response.status_code)
        playback = response.get_json()["data"]["items"][0]["playback"]
        self.assertEqual(
            f"http://127.0.0.1:5004/api/v1/resources/{resource.id}/stream",
            playback["stream_url"],
        )


if __name__ == "__main__":
    unittest.main()
