from __future__ import annotations

import io
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, ResourceSubtitle, StorageSource


class FakeCDNResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self.payload = payload or {}
        self.status_code = status_code
        self.text = text
        self.content = b"{}"

    def json(self):
        return self.payload


class OnlineSubtitleRouteTests(unittest.TestCase):
    def setUp(self):
        self.cache_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "CACHE_DIR": self.cache_dir.name,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.source = StorageSource(name="Local", type="local", config={"root_path": "/tmp"})
        db.session.add(self.source)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.cache_dir.cleanup()

    def _resource(self):
        movie = Movie(
            title="Online Subtitle Movie",
            original_title="Online Subtitle Movie",
            year=2026,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="Movies/Online.Subtitle.Movie.2026.mkv",
            filename="Online.Subtitle.Movie.2026.mkv",
            size=1000,
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def _episode_resource(self):
        movie = Movie(
            title="Series Title",
            original_title="Series Title",
            year=2026,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="Shows/Series Title/Season 02/Series.Title.S02E01.mkv",
            filename="Series.Title.S02E01.mkv",
            season=2,
            episode=1,
            size=1000,
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def _subtitle_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "not a subtitle")
            archive.writestr(
                "subs/feature.srt",
                "1\n00:00:00,000 --> 00:00:01,000\nSRT\n",
            )
            archive.writestr(
                "subs/feature.ass",
                "[Script Info]\nTitle: Feature\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,ASS\n",
            )
        return buffer.getvalue()

    def _nested_subtitle_zip(self):
        inner_buffer = io.BytesIO()
        with zipfile.ZipFile(inner_buffer, "w") as archive:
            archive.writestr(
                "nested/inner.srt",
                "1\n00:00:00,000 --> 00:00:01,000\nNested\n",
            )

        outer_buffer = io.BytesIO()
        with zipfile.ZipFile(outer_buffer, "w") as archive:
            archive.writestr("packed-subtitles.zip", inner_buffer.getvalue())
        return outer_buffer.getvalue()

    def _fake_skill_module(self, module_name):
        if module_name == "subhd_core":
            module = types.SimpleNamespace()
            module.make_session = lambda: object()
            module.search_subtitle = lambda query, session=None: [
                {
                    "hash": "abc123",
                    "film_name": "Online Subtitle Movie",
                    "title": "Online Subtitle Movie 简英双语",
                    "quality": "转载精修",
                    "download_number": "123",
                    "update_time": "2026-04-28",
                    "language": ["双语", "简体"],
                    "format": "ASS",
                    "file_size": "42KB",
                    "uploader": "tester",
                }
            ]

            def download_subtitle(source_key, session=None, max_retries=5):
                if source_key == "zip123":
                    return {
                        "success": True,
                        "content": self._subtitle_zip(),
                        "ext": "zip",
                        "attempts": 1,
                    }
                if source_key == "nestedzip":
                    return {
                        "success": True,
                        "content": self._nested_subtitle_zip(),
                        "ext": "zip",
                        "attempts": 1,
                    }
                if source_key == "rar123":
                    return {
                        "success": True,
                        "content": b"Rar!\x1a\x07\x00unsupported",
                        "ext": "rar",
                        "attempts": 1,
                    }
                if source_key == "large":
                    return {
                        "success": True,
                        "content": b"1\n00:00:00,000 --> 00:00:01,000\nToo large\n",
                        "ext": "srt",
                        "attempts": 1,
                    }
                return {
                    "success": True,
                    "content": b"1\n00:00:00,000 --> 00:00:01,000\nHello\n",
                    "ext": "srt",
                    "attempts": 1,
                }

            module.download_subtitle = download_subtitle
            return module

        if module_name == "srtku_core":
            module = types.SimpleNamespace()
            module.BASE = "https://srtku.com"
            module.make_session = lambda: object()
            module.search_film = lambda query, page=1, session=None: {
                "titles": ["Online Subtitle Movie"],
                "list_urls": ["https://srtku.com/subs/online-subtitle-movie"],
            }
            module.search_subtitle = lambda list_url, session=None: [
                {
                    "title": "Online Subtitle Movie 特效字幕",
                    "quality": "5",
                    "download_number": "98",
                    "update_time": "2026-04-28",
                    "language": ["简体中文"],
                    "detail_url": "https://srtku.com/detail/srt987",
                }
            ]
            module.get_download_links = lambda detail_url, session=None: [
                {"provider": "server-a", "download_links": "https://srtku.example/a"},
                {"provider": "server-b", "download_links": "https://srtku.example/b"},
            ]

            def download_subtitle(download_url, outdir, session=None):
                suffix = "b" if download_url.endswith("/b") else "a"
                path = Path(outdir) / f"online-subtitle-{suffix}.srt"
                path.write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nSrtKu\n")
                return {
                    "ok": True,
                    "selected_subtitle": str(path),
                    "saved_path": str(path),
                    "bytes": path.stat().st_size,
                    "extracted": False,
                }

            module.download_subtitle = download_subtitle
            return module

        raise AssertionError(module_name)

    def test_online_search_uses_subhd_and_srtku_but_ignores_opensubtitles(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd,srtku,opensubtitles&query=Online%20Subtitle%20Movie"
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(["subhd", "srtku"], data["providers"]["used"])
        self.assertEqual("Online Subtitle Movie", data["providers"]["query_used"]["subhd"])
        self.assertEqual("Online Subtitle Movie", data["providers"]["query_used"]["srtku"])
        self.assertEqual(
            [{"id": "opensubtitles", "reason": "disabled_low_quality_source"}],
            data["providers"]["ignored"],
        )
        self.assertEqual(2, data["count"])
        self.assertEqual({"subhd": 1, "srtku": 1}, data["count_by_provider"])
        self.assertEqual("subhd:abc123", data["items"][0]["id"])
        self.assertEqual("subhd:abc123", data["items"][0]["candidate_id"])
        self.assertEqual("abc123", data["items"][0]["source_key"])
        self.assertEqual("srtku:srt987", data["items"][1]["id"])
        self.assertEqual("srtku:srt987", data["items"][1]["candidate_id"])
        self.assertEqual("srt987", data["items"][1]["source_key"])

    def test_online_search_falls_back_to_resource_title_when_override_has_no_hits(self):
        resource = self._resource()

        def fake_skill_module(module_name):
            module = self._fake_skill_module(module_name)
            if module_name == "subhd_core":
                original_search = module.search_subtitle
                module.search_subtitle = lambda query, session=None: (
                    [] if query == "No Match" else original_search(query, session=session)
                )
            if module_name == "srtku_core":
                original_search_film = module.search_film
                module.search_film = lambda query, page=1, session=None: (
                    {"titles": [], "list_urls": []}
                    if query == "No Match"
                    else original_search_film(query, page=page, session=session)
                )
            return module

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=fake_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd,srtku&query=No%20Match"
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("No Match", data["query"])
        self.assertIn("Online Subtitle Movie", data["query_candidates"])
        self.assertEqual("Online Subtitle Movie", data["providers"]["query_used"]["subhd"])
        self.assertEqual("Online Subtitle Movie", data["providers"]["query_used"]["srtku"])
        self.assertEqual(2, data["count"])

    def test_online_search_accepts_keyword_alias_before_query(self):
        resource = self._resource()

        def fake_skill_module(module_name):
            module = self._fake_skill_module(module_name)
            if module_name == "subhd_core":
                original_search = module.search_subtitle
                module.search_subtitle = lambda query, session=None: (
                    original_search(query, session=session) if query == "Manual Keyword" else []
                )
            if module_name == "srtku_core":
                original_search_film = module.search_film
                module.search_film = lambda query, page=1, session=None: (
                    original_search_film(query, page=page, session=session)
                    if query == "Manual Keyword"
                    else {"titles": [], "list_urls": []}
                )
            return module

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=fake_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd,srtku&query=No%20Match&keyword=Manual%20Keyword"
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("Manual Keyword", data["query"])
        self.assertEqual(["Manual Keyword", "No Match"], data["query_candidates"][:2])
        self.assertEqual("Manual Keyword", data["providers"]["query_used"]["subhd"])
        self.assertEqual("Manual Keyword", data["providers"]["query_used"]["srtku"])
        self.assertEqual(2, data["count"])

    def test_online_search_prioritizes_matching_episode_candidates(self):
        resource = self._episode_resource()

        def fake_skill_module(module_name):
            module = types.SimpleNamespace()
            module.make_session = lambda: object()
            if module_name == "subhd_core":
                def search_subtitle(query, session=None):
                    if query == "Series Title":
                        return [
                            {
                                "hash": "wrong-season",
                                "film_name": "Series Title Season 1",
                                "title": "Series.Title.S01E08.High.Downloads",
                                "download_number": "9999",
                            }
                        ]
                    if query == "Series Title S02E01":
                        return [
                            {
                                "hash": "right-episode",
                                "film_name": "Series Title Season 2",
                                "title": "Series.Title.S02E01.Low.Downloads",
                                "download_number": "1",
                            }
                        ]
                    return []

                module.search_subtitle = search_subtitle
                return module
            if module_name == "srtku_core":
                module.BASE = "https://srtku.com"
                module.search_film = lambda query, page=1, session=None: {"titles": [], "list_urls": []}
                module.search_subtitle = lambda list_url, session=None: []
                return module
            raise AssertionError(module_name)

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=fake_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd&keyword=Series%20Title&max_query_attempts=6"
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("subhd:right-episode", data["items"][0]["id"])
        self.assertEqual("subhd:wrong-season", data["items"][1]["id"])
        self.assertEqual(["Series Title", "Series Title 2026", "Series Title S02E01"], data["providers"]["query_attempts"]["subhd"][:3])

    def test_online_search_accepts_multiple_keywords(self):
        resource = self._resource()

        def fake_skill_module(module_name):
            module = self._fake_skill_module(module_name)
            if module_name == "subhd_core":
                original_search = module.search_subtitle
                module.search_subtitle = lambda query, session=None: (
                    original_search(query, session=session) if query == "Manual Keyword" else []
                )
            if module_name == "srtku_core":
                original_search_film = module.search_film
                module.search_film = lambda query, page=1, session=None: (
                    original_search_film(query, page=page, session=session)
                    if query == "Manual Keyword"
                    else {"titles": [], "list_urls": []}
                )
            return module

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=fake_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd,srtku&keywords=Bad%20Name%EF%BC%8CManual%20Keyword"
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(["Bad Name", "Manual Keyword"], data["query_candidates"][:2])
        self.assertEqual("Manual Keyword", data["providers"]["query_used"]["subhd"])
        self.assertEqual("Manual Keyword", data["providers"]["query_used"]["srtku"])
        self.assertEqual(2, data["count"])

    def test_online_search_adds_tv_season_episode_query_candidates(self):
        resource = self._episode_resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd,srtku&keyword=Series%20Title2"
            )

        self.assertEqual(200, response.status_code)
        query_candidates = response.get_json()["data"]["query_candidates"]
        self.assertIn("Series Title 第2季", query_candidates)
        self.assertIn("Series Title 第二季", query_candidates)
        self.assertIn("Series Title S02E01", query_candidates)
        self.assertIn("Series Title 第二季 第一集", query_candidates)

    def test_online_search_does_not_report_query_used_when_no_provider_hits(self):
        resource = self._episode_resource()

        def fake_empty_skill_module(module_name):
            module = types.SimpleNamespace()
            module.make_session = lambda: object()
            if module_name == "subhd_core":
                module.search_subtitle = lambda query, session=None: []
                return module
            if module_name == "srtku_core":
                module.search_film = lambda query, page=1, session=None: {"titles": [], "list_urls": []}
                module.search_subtitle = lambda list_url, session=None: []
                return module
            raise AssertionError(module_name)

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=fake_empty_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd,srtku&keyword=No%20Hit"
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(0, data["count"])
        self.assertEqual({}, data["providers"]["query_used"])
        self.assertIn("No Hit", data["providers"]["query_attempts"]["subhd"])
        self.assertIn("Series Title S02E01", data["providers"]["query_attempts"]["srtku"])

    def test_online_search_prioritizes_web_text_subtitles_over_bitmap_subtitles(self):
        resource = self._resource()

        def fake_skill_module(module_name):
            module = types.SimpleNamespace()
            module.make_session = lambda: object()
            if module_name == "subhd_core":
                module.search_subtitle = lambda query, session=None: [
                    {
                        "hash": "sup-high",
                        "film_name": "Online Subtitle Movie",
                        "title": "Online Subtitle Movie UHD PGS",
                        "format": "SUP",
                        "download_number": "9999",
                    },
                    {
                        "hash": "ass-low",
                        "film_name": "Online Subtitle Movie",
                        "title": "Online Subtitle Movie Web ASS",
                        "format": "ASS",
                        "download_number": "1",
                    },
                ]
                return module
            if module_name == "srtku_core":
                module.BASE = "https://srtku.com"
                module.search_film = lambda query, page=1, session=None: {"titles": [], "list_urls": []}
                module.search_subtitle = lambda list_url, session=None: []
                return module
            raise AssertionError(module_name)

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=fake_skill_module,
        ):
            response = self.client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search"
                "?providers=subhd&keyword=Online%20Subtitle%20Movie"
            )

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]["items"]
        self.assertEqual("subhd:ass-low", items[0]["candidate_id"])
        self.assertEqual("ass", items[0]["format_normalized"])
        self.assertTrue(items[0]["web_player"]["supported"])
        self.assertTrue(items[0]["web_player"]["requires_conversion"])
        self.assertEqual("subhd:sup-high", items[1]["candidate_id"])
        self.assertEqual("sup", items[1]["format_normalized"])
        self.assertFalse(items[1]["web_player"]["supported"])
        self.assertEqual("bitmap_subtitle_not_supported", items[1]["web_player"]["reason"])

    def test_online_download_returns_subhd_file_stream(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/download",
                json={"candidate_id": "subhd:abc123"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/x-subrip; charset=utf-8", response.headers["Content-Type"])
        self.assertEqual("subhd", response.headers["X-Cyber-Subtitle-Provider"])
        self.assertEqual("false", response.headers["X-Cyber-Subtitle-Extracted"])
        self.assertIn("filename*=UTF-8''", response.headers["Content-Disposition"])
        self.assertIn(b"Hello", response.data)

    def test_online_download_extracts_zip_and_returns_real_subtitle_file(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/download",
                json={"candidate_id": "subhd:zip123"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("text/plain; charset=utf-8", response.headers["Content-Type"])
        self.assertEqual("true", response.headers["X-Cyber-Subtitle-Extracted"])
        self.assertEqual("zip", response.headers["X-Cyber-Subtitle-Archive-Kind"])
        self.assertIn("feature.ass", response.headers["Content-Disposition"])
        self.assertIn(b"Dialogue:", response.data)

    def test_online_download_extracts_nested_zip(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/download",
                json={"candidate_id": "subhd:nestedzip"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/x-subrip; charset=utf-8", response.headers["Content-Type"])
        self.assertEqual("true", response.headers["X-Cyber-Subtitle-Extracted"])
        self.assertEqual("zip", response.headers["X-Cyber-Subtitle-Archive-Kind"])
        self.assertIn("inner.srt", response.headers["Content-Disposition"])
        self.assertIn(b"Nested", response.data)

    def test_online_download_returns_unsupported_media_for_rar_archive(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/download",
                json={"candidate_id": "subhd:rar123"},
            )

        self.assertEqual(415, response.status_code)
        self.assertEqual(41566, response.get_json()["code"])

    def test_online_download_returns_payload_too_large_for_oversized_subtitle(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ), patch("backend.app.services.online_subtitles.MAX_EXTRACTED_SUBTITLE_BYTES", 8):
            response = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/download",
                json={"candidate_id": "subhd:large"},
            )

        self.assertEqual(413, response.status_code)
        self.assertEqual(41369, response.get_json()["code"])
        self.assertIn("too large", response.get_json()["msg"])

    def test_online_download_accepts_string_srtku_download_index(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/download",
                json={"candidate_id": "srtku:srt987", "download_index": "1"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/x-subrip; charset=utf-8", response.headers["Content-Type"])
        self.assertEqual("srtku", response.headers["X-Cyber-Subtitle-Provider"])
        self.assertIn("online-subtitle-b.srt", response.headers["Content-Disposition"])
        self.assertIn(b"SrtKu", response.data)

    def test_online_download_rejects_ignored_opensubtitles_provider(self):
        resource = self._resource()

        response = self.client.post(
            f"/api/v1/resources/{resource.id}/subtitles/online/download",
            json={"candidate_id": "opensubtitles:123"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual(40062, response.get_json()["code"])

    def test_online_bind_requires_manual_confirmation(self):
        resource = self._resource()

        response = self.client.post(
            f"/api/v1/resources/{resource.id}/subtitles/online/bind",
            json={"candidate_id": "subhd:abc123"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual(40064, response.get_json()["code"])

    def test_online_bind_saves_confirmed_subtitle_and_exposes_stream_url(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            response = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/bind",
                json={"candidate_id": "subhd:abc123", "confirm": True},
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        subtitle = data["subtitle"]
        self.assertEqual("online_bound", subtitle["source"])
        self.assertEqual("manual_confirmed_online", subtitle["match"])
        self.assertEqual("subhd:abc123", subtitle["online"]["candidate_id"])
        self.assertTrue(subtitle["online"]["confirmed"])
        self.assertEqual(subtitle["id"], data["playback"]["subtitles"]["default_subtitle_id"])
        self.assertTrue(subtitle["web_player"]["supported"])
        self.assertTrue(subtitle["web_player"]["requires_conversion"])
        self.assertEqual("vtt", subtitle["web_player"]["format"])

        subtitle_url = subtitle["url"]
        stream_path = urlparse(subtitle_url).path + "?" + urlparse(subtitle_url).query
        stream_response = self.client.get(stream_path)

        self.assertEqual(200, stream_response.status_code)
        self.assertIn("application/x-subrip", stream_response.headers["Content-Type"])
        self.assertIn(b"Hello", stream_response.data)
        stream_response.close()

        web_url = subtitle["web_player"]["url"]
        web_path = urlparse(web_url).path + "?" + urlparse(web_url).query
        web_response = self.client.get(web_path)

        self.assertEqual(200, web_response.status_code)
        self.assertEqual("text/vtt; charset=utf-8", web_response.headers["Content-Type"])
        self.assertTrue(web_response.get_data(as_text=True).startswith("WEBVTT"))
        self.assertIn("00:00:00.000 --> 00:00:01.000", web_response.get_data(as_text=True))
        web_response.close()

    def test_online_bind_rejects_duplicate_candidate_without_user_reselection(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            first = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/bind",
                json={"candidate_id": "subhd:abc123", "confirm": True},
            )
            second = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/bind",
                json={"candidate_id": "subhd:abc123", "confirm": True},
            )

        self.assertEqual(200, first.status_code)
        self.assertEqual(409, second.status_code)
        self.assertEqual(40960, second.get_json()["code"])

    def test_manual_upload_subtitle_saves_to_cache_and_exposes_stream_url(self):
        resource = self._resource()

        response = self.client.post(
            f"/api/v1/resources/{resource.id}/subtitles/upload",
            data={
                "file": (
                    io.BytesIO(b"1\n00:00:00,000 --> 00:00:01,000\nManual\n"),
                    "Manual.zh-Hans.srt",
                ),
                "set_default": "true",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        subtitle = data["subtitle"]
        self.assertTrue(data["uploaded"])
        self.assertEqual("manual_upload", subtitle["source"])
        self.assertEqual("manual_uploaded", subtitle["match"])
        self.assertEqual("srt", subtitle["format"])
        self.assertTrue(subtitle["is_default"])
        self.assertEqual(subtitle["id"], data["subtitles"]["default_subtitle_id"])
        self.assertTrue(subtitle["upload"]["confirmed"])
        self.assertTrue(subtitle["web_player"]["supported"])
        self.assertTrue(subtitle["web_player"]["requires_conversion"])

        row = db.session.get(ResourceSubtitle, subtitle["id"])
        self.assertIsNotNone(row)
        self.assertEqual("manual_upload", row.source)
        self.assertTrue((Path(self.cache_dir.name) / row.storage_path).exists())

        subtitle_url = subtitle["url"]
        stream_path = urlparse(subtitle_url).path + "?" + urlparse(subtitle_url).query
        stream_response = self.client.get(stream_path)

        self.assertEqual(200, stream_response.status_code)
        self.assertIn("application/x-subrip", stream_response.headers["Content-Type"])
        self.assertIn(b"Manual", stream_response.data)
        stream_response.close()

    @patch("backend.app.services.cdn_assets.requests.request")
    @patch("backend.app.services.cdn_assets.requests.get")
    def test_manual_upload_subtitle_uploads_original_and_webvtt_to_supercdn_china_all_bucket(
        self,
        mock_cdn_get,
        mock_cdn_request,
    ):
        resource = self._resource()
        self.app.config.update({
            "CDN_PROVIDER": "supercdn",
            "SUPERCDN_ENABLED": True,
            "SUPERCDN_URL": "https://qwk.ccwu.cc",
            "SUPERCDN_TOKEN": "root-token",
            "SUPERCDN_BUCKET": "cyberstream-cn-assets",
            "SUPERCDN_ROUTE_PROFILE": "china_all",
        })
        mock_cdn_get.side_effect = [
            FakeCDNResponse(status_code=404, text="not found"),
            FakeCDNResponse({"slug": "cyberstream-cn-assets", "route_profile": "china_all"}, status_code=200),
        ]

        uploaded_paths = []

        def cdn_request(method, url, **kwargs):
            if url.endswith("/api/v1/asset-buckets"):
                self.assertEqual("china_all", kwargs["json"]["route_profile"])
                self.assertEqual("cyberstream-cn-assets", kwargs["json"]["slug"])
                self.assertEqual(["image", "document"], kwargs["json"]["allowed_types"])
                return FakeCDNResponse({"slug": "cyberstream-cn-assets"}, status_code=201)

            self.assertIn("/api/v1/asset-buckets/cyberstream-cn-assets/objects", url)
            logical_path = kwargs["data"]["path"]
            uploaded_paths.append(logical_path)
            self.assertEqual("document", kwargs["data"]["asset_type"])
            return FakeCDNResponse({
                "bucket": "cyberstream-cn-assets",
                "url": f"/a/cyberstream-cn-assets/{logical_path}",
                "public_url": f"https://qwk.ccwu.cc/a/cyberstream-cn-assets/{logical_path}",
                "urls": [f"https://qwk.ccwu.cc/a/cyberstream-cn-assets/{logical_path}"],
            }, status_code=201)

        mock_cdn_request.side_effect = cdn_request

        response = self.client.post(
            f"/api/v1/resources/{resource.id}/subtitles/upload",
            data={
                "file": (
                    io.BytesIO(b"1\n00:00:00,000 --> 00:00:01,000\nManual\n"),
                    "Manual.zh-Hans.srt",
                ),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(200, response.status_code)
        subtitle = response.get_json()["data"]["subtitle"]
        self.assertTrue(subtitle["url"].startswith("https://qwk.ccwu.cc/a/cyberstream-cn-assets/"))
        self.assertTrue(subtitle["web_player"]["url"].startswith("https://qwk.ccwu.cc/a/cyberstream-cn-assets/"))
        self.assertEqual("supercdn", subtitle["cdn"]["provider"])
        self.assertEqual("china_all", subtitle["cdn"]["route_profile"])
        self.assertEqual("uploaded", subtitle["cdn"]["assets"]["original"]["status"])
        self.assertEqual("uploaded", subtitle["cdn"]["assets"]["webvtt"]["status"])
        self.assertTrue(any("/original/" in path for path in uploaded_paths))
        self.assertTrue(any("/webvtt/" in path for path in uploaded_paths))

        row = db.session.get(ResourceSubtitle, subtitle["id"])
        self.assertEqual("uploaded", row.subtitle_metadata["cdn"]["status"])
        self.assertEqual("china_all", row.subtitle_metadata["cdn"]["route_profile"])

    def test_manual_upload_extracts_supported_archive(self):
        resource = self._resource()

        response = self.client.post(
            f"/api/v1/resources/{resource.id}/subtitles/upload",
            data={
                "file": (
                    io.BytesIO(self._subtitle_zip()),
                    "manual-subtitles.zip",
                ),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(200, response.status_code)
        subtitle = response.get_json()["data"]["subtitle"]
        self.assertEqual("manual_upload", subtitle["source"])
        self.assertEqual("ass", subtitle["format"])
        self.assertEqual("feature.ass", subtitle["filename"])
        self.assertTrue(subtitle["upload"]["meta"]["extracted"])

    def test_online_bound_subtitle_can_be_set_default_and_removed(self):
        resource = self._resource()

        with patch(
            "backend.app.services.online_subtitles._load_skill_module",
            side_effect=self._fake_skill_module,
        ):
            first = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/bind",
                json={"candidate_id": "subhd:abc123", "confirm": True},
            )
            second = self.client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/bind",
                json={"candidate_id": "subhd:def456", "confirm": True},
            )

        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        first_id = first.get_json()["data"]["subtitle"]["id"]
        second_id = second.get_json()["data"]["subtitle"]["id"]

        default_response = self.client.post(
            f"/api/v1/resources/{resource.id}/subtitles/{second_id}/default",
        )

        self.assertEqual(200, default_response.status_code)
        default_data = default_response.get_json()["data"]
        self.assertEqual(second_id, default_data["default_subtitle_id"])
        self.assertEqual(second_id, default_data["subtitles"]["default_subtitle_id"])
        self.assertTrue(default_data["subtitle"]["is_default"])

        row = db.session.get(ResourceSubtitle, first_id)
        first_path = Path(self.cache_dir.name) / row.storage_path
        self.assertTrue(first_path.exists())

        delete_response = self.client.delete(
            f"/api/v1/resources/{resource.id}/subtitles/{first_id}",
        )

        self.assertEqual(200, delete_response.status_code)
        delete_data = delete_response.get_json()["data"]
        self.assertTrue(delete_data["removed"])
        self.assertTrue(delete_data["file_deleted"])
        self.assertFalse(first_path.exists())
        self.assertIsNone(db.session.get(ResourceSubtitle, first_id))
        self.assertEqual(1, ResourceSubtitle.query.filter_by(resource_id=resource.id).count())

    def test_unknown_bound_subtitle_remove_returns_not_found(self):
        resource = self._resource()
        subtitle_id = "sub_sidecar"

        response = self.client.delete(f"/api/v1/resources/{resource.id}/subtitles/{subtitle_id}")

        self.assertEqual(404, response.status_code)
        self.assertEqual(40470, response.get_json()["code"])


if __name__ == "__main__":
    unittest.main()
