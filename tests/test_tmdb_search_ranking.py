from __future__ import annotations

import socket
import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.tmdb import TMDBScraper
from backend.app.services import tmdb as tmdb_module


class FakeTMDBResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TMDBSearchRankingTests(unittest.TestCase):
    def build_scraper(self):
        scraper = TMDBScraper()
        scraper.proxies = None
        return scraper

    def test_year_hint_uses_english_variant_for_ascii_titles(self):
        scraper = self.build_scraper()

        def fake_get(url, params=None):
            language = params.get("language")
            has_year = "year" in params
            if language == "zh-CN" and not has_year:
                return {
                    "results": [
                        {
                            "id": 8914,
                            "title": "深海狂鲨",
                            "original_title": "Deep Blue Sea",
                            "release_date": "1999-07-28",
                            "popularity": 8,
                        }
                    ]
                }
            if language == "en-US" and has_year:
                return {
                    "results": [
                        {
                            "id": 667717,
                            "title": "Deep Sea",
                            "original_title": "深海",
                            "release_date": "2023-01-22",
                            "popularity": 3,
                        }
                    ]
                }
            return {"results": []}

        with patch.object(scraper, "_get", side_effect=fake_get):
            self.assertEqual("movie/667717", scraper.search_movie("Deep Sea", 2023, media_type_hint="movie"))

    def test_media_type_hint_uses_multi_search_when_precise_match_exists(self):
        scraper = self.build_scraper()
        urls = []

        def fake_get(url, params=None):
            urls.append(url)
            if url.endswith("/search/multi"):
                return {
                    "results": [
                        {
                            "id": 91314,
                            "media_type": "movie",
                            "title": "变形金刚4：绝迹重生",
                            "original_title": "Transformers: Age of Extinction",
                            "release_date": "2014-06-25",
                            "popularity": 14,
                        }
                    ]
                }
            raise AssertionError(f"unexpected direct endpoint: {url}")

        with patch.object(scraper, "_get", side_effect=fake_get):
            self.assertEqual(
                "movie/91314",
                scraper.search_movie("Transformers Age of Extinction", 2014, media_type_hint="movie"),
            )

        self.assertTrue(urls)
        self.assertTrue(all(url.endswith("/search/multi") for url in urls))

    def test_strict_requires_exact_title_and_year(self):
        scraper = self.build_scraper()

        def fake_get(url, params=None):
            return {
                "results": [
                    {
                        "id": 8914,
                        "title": "深海狂鲨",
                        "original_title": "Deep Blue Sea",
                        "release_date": "1999-07-28",
                        "popularity": 8,
                    },
                    {
                        "id": 667717,
                        "title": "Deep Sea",
                        "original_title": "深海",
                        "release_date": "2023-01-22",
                        "popularity": 3,
                    },
                ]
            }

        with patch.object(scraper, "_get", side_effect=fake_get):
            self.assertEqual("movie/667717", scraper.search_movie("Deep Sea", 2023, strict=True, media_type_hint="movie"))
            self.assertIsNone(scraper.search_movie("Deep Sea", 2022, strict=True, media_type_hint="movie"))

    def test_year_hint_beats_exact_title_with_wrong_year(self):
        scraper = self.build_scraper()

        def fake_get(url, params=None):
            return {
                "results": [
                    {
                        "id": 93560,
                        "media_type": "movie",
                        "title": "Batman and Robin",
                        "original_title": "Batman and Robin",
                        "release_date": "1949-05-26",
                        "popularity": 1,
                    },
                    {
                        "id": 415,
                        "media_type": "movie",
                        "title": "Batman & Robin",
                        "original_title": "Batman & Robin",
                        "release_date": "1997-06-20",
                        "popularity": 7,
                    },
                ]
            }

        with patch.object(scraper, "_get", side_effect=fake_get):
            self.assertEqual(
                "movie/415",
                scraper.search_movie("Batman and Robin", 1997, media_type_hint="movie"),
            )

    def test_year_hint_rejects_low_score_wrong_year_fallback(self):
        scraper = self.build_scraper()

        def fake_get(url, params=None):
            return {
                "results": [
                    {
                        "id": 161620,
                        "media_type": "movie",
                        "title": "Wonder Woman",
                        "original_title": "Wonder Woman",
                        "release_date": "1974-03-12",
                        "popularity": 2,
                    },
                ]
            }

        with patch.object(scraper, "_get", side_effect=fake_get):
            self.assertIsNone(scraper.search_movie("Wonder Woman", 1984, media_type_hint="movie"))

    def test_tmdb_scraper_uses_dedicated_proxy_config_and_ignores_env_proxy(self):
        scraper = TMDBScraper()
        self.assertFalse(scraper.session.trust_env)
        self.assertEqual(scraper.proxies, {"http": "http://127.0.0.1:17890", "https": "http://127.0.0.1:17890"})

    def test_tmdb_scraper_reads_runtime_token_and_proxy_on_each_request(self):
        scraper = TMDBScraper()
        calls = []

        def fake_get(url, headers=None, params=None, proxies=None, timeout=None):
            calls.append({
                "headers": dict(headers or {}),
                "proxies": dict(proxies or {}),
            })
            return FakeTMDBResponse({"ok": True})

        with patch("backend.app.services.tmdb.config.TMDB_TOKEN", "old-token"), \
             patch("backend.app.services.tmdb.config.TMDB_PROXIES", {"http": "http://old", "https": "http://old"}):
            scraper.refresh_runtime_config(reset_session=False)

        with patch.object(scraper.session, "get", side_effect=fake_get), \
             patch("backend.app.services.tmdb.config.TMDB_TOKEN", "new-token"), \
             patch("backend.app.services.tmdb.config.TMDB_PROXIES", {"http": "http://new", "https": "http://new"}):
            self.assertEqual({"ok": True}, scraper._get("https://api.themoviedb.org/test"))

        self.assertEqual("Bearer new-token", calls[0]["headers"]["Authorization"])
        self.assertEqual({"http": "http://new", "https": "http://new"}, calls[0]["proxies"])

    def test_tmdb_scraper_uses_selected_ipv6_family_for_direct_request(self):
        scraper = TMDBScraper()
        calls = []

        def fake_get(url, headers=None, params=None, proxies=None, timeout=None):
            calls.append({
                "family": tmdb_module.urllib3_connection.allowed_gai_family(),
                "proxies": proxies,
            })
            return FakeTMDBResponse({"ok": True})

        with patch.object(scraper, "_pick_dns_family", return_value=socket.AF_INET6), \
             patch.object(scraper.session, "get", side_effect=fake_get), \
             patch("backend.app.services.tmdb.config.TMDB_TOKEN", "token"), \
             patch("backend.app.services.tmdb.config.TMDB_PROXIES", None):
            self.assertEqual({"ok": True}, scraper._get("https://api.themoviedb.org/test"))

        self.assertEqual(socket.AF_INET6, calls[0]["family"])
        self.assertIsNone(calls[0]["proxies"])

    def test_details_fall_back_to_english_when_localized_payload_is_sparse(self):
        scraper = self.build_scraper()
        calls = []

        def fake_get(url, params=None):
            calls.append(params.get("language"))
            if params.get("language") == "zh-CN":
                return {
                    "id": 1312801,
                    "title": "Foundation",
                    "original_title": "Foundation",
                    "release_date": "2024-12-31",
                    "overview": "",
                    "poster_path": None,
                    "backdrop_path": None,
                    "genres": [{"name": "Mystery"}],
                    "production_countries": [{"name": "US"}],
                    "credits": {"cast": [], "crew": []},
                }
            return {
                "id": 1312801,
                "title": "Foundation",
                "original_title": "Foundation",
                "release_date": "2024-12-31",
                "overview": "An old hotel. A missing woman.",
                "poster_path": "/foundation.jpg",
                "backdrop_path": "/foundation-bg.jpg",
                "genres": [{"name": "Mystery"}],
                "production_countries": [{"name": "US"}],
                "credits": {"cast": [], "crew": []},
            }

        with patch.object(scraper, "_get", side_effect=fake_get):
            details = scraper.get_movie_details("movie/1312801")

        self.assertEqual(["zh-CN", "en-US"], calls)
        self.assertEqual("Foundation", details["title"])
        self.assertEqual("An old hotel. A missing woman.", details["description"])
        self.assertEqual("https://image.tmdb.org/t/p/w500/foundation.jpg", details["cover"])
        self.assertEqual("https://image.tmdb.org/t/p/original/foundation-bg.jpg", details["background_cover"])


if __name__ == "__main__":
    unittest.main()
