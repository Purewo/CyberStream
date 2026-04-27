from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.tmdb import TMDBScraper


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

    def test_tmdb_scraper_uses_dedicated_proxy_config_and_ignores_env_proxy(self):
        scraper = TMDBScraper()
        self.assertFalse(scraper.session.trust_env)
        self.assertEqual(scraper.proxies, {"http": "http://127.0.0.1:17890", "https": "http://127.0.0.1:17890"})


if __name__ == "__main__":
    unittest.main()
