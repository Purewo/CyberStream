from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models import Movie
from backend.app.services.metadata_providers.anilist import AniListMetadataProvider
from backend.app.services.metadata_scraper import MetadataScraper
from backend.app.services.metadata_types import ScrapeContext


def _media_payload():
    return {
        "id": 154587,
        "idMal": 52991,
        "title": {
            "romaji": "Sousou no Frieren",
            "english": "Frieren: Beyond Journey's End",
            "native": "葬送のフリーレン",
            "userPreferred": "Sousou no Frieren",
        },
        "description": "The adventure is over but life goes on.",
        "startDate": {"year": 2023, "month": 9, "day": 29},
        "coverImage": {
            "extraLarge": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/frieren.jpg",
            "large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/frieren.jpg",
        },
        "bannerImage": "https://s4.anilist.co/file/anilistcdn/media/anime/banner/frieren.jpg",
        "episodes": 28,
        "averageScore": 89,
        "popularity": 300000,
        "genres": ["Adventure", "Drama", "Fantasy"],
        "format": "TV",
        "siteUrl": "https://anilist.co/anime/154587",
        "countryOfOrigin": "JP",
    }


def _chinese_media_payload():
    return {
        "id": 166475,
        "idMal": None,
        "title": {
            "romaji": "Luo Xiaohei Zhan Ji 2",
            "english": "The Legend of Hei 2",
            "native": "罗小黑战记 2",
            "userPreferred": "Luo Xiaohei Zhan Ji 2",
        },
        "description": "A new adventure.",
        "startDate": {"year": 2025, "month": 7, "day": 18},
        "coverImage": {"extraLarge": "https://s4.anilist.co/hei2.jpg", "large": ""},
        "bannerImage": "",
        "episodes": 1,
        "averageScore": 78,
        "popularity": 12000,
        "genres": ["Action", "Fantasy"],
        "format": "MOVIE",
        "siteUrl": "https://anilist.co/anime/166475",
        "countryOfOrigin": "CN",
    }


class FakeAniListResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeAniListSession:
    def __init__(self):
        self.posts = []
        self.trust_env = True

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({
            "url": url,
            "headers": headers or {},
            "json": json or {},
            "timeout": timeout,
        })
        variables = (json or {}).get("variables") or {}
        if variables.get("id") == 154587:
            return FakeAniListResponse({"data": {"Media": _media_payload()}})
        if variables.get("id") == 166475:
            return FakeAniListResponse({"data": {"Media": _chinese_media_payload()}})
        search = variables.get("search")
        if search == "罗小黑战记":
            return FakeAniListResponse({"data": {"Page": {"media": [_chinese_media_payload()]}}})
        return FakeAniListResponse({"data": {"Page": {"media": [_media_payload()]}}})


class FailingAniListSession:
    trust_env = False

    def post(self, url, headers=None, json=None, timeout=None):
        raise RuntimeError("network down")


class AniListMetadataProviderTests(unittest.TestCase):
    def build_provider(self):
        provider = AniListMetadataProvider()
        provider.session = FakeAniListSession()
        return provider

    def test_search_candidates_uses_official_graphql_api(self):
        provider = self.build_provider()

        result = provider.search_candidates("Frieren", year=2023, limit=3, media_type_hint="tv")

        self.assertEqual(1, len(result.items))
        item = result.items[0]
        self.assertEqual("anilist", item["provider"])
        self.assertEqual("anilist/154587", item["candidate_id"])
        self.assertEqual("Frieren: Beyond Journey's End", item["title"])
        self.assertEqual("Sousou no Frieren", item["original_title"])
        self.assertEqual(2023, item["year"])
        self.assertEqual(28, item["episode_count"])
        self.assertEqual(8.9, item["rating"])
        self.assertIn("Fantasy", item["category"])

        call = provider.session.posts[0]
        self.assertEqual("https://graphql.anilist.co", call["url"])
        self.assertIn("User-Agent", call["headers"])
        self.assertEqual("Frieren", call["json"]["variables"]["search"])

    def test_search_prefers_native_title_for_cjk_query(self):
        provider = self.build_provider()

        result = provider.search_candidates("罗小黑战记", limit=3, media_type_hint="movie")

        self.assertEqual(1, len(result.items))
        item = result.items[0]
        self.assertEqual("罗小黑战记 2", item["title"])
        self.assertEqual("movie", item["media_type"])
        self.assertEqual("anilist/166475", item["candidate_id"])

    def test_get_details_accepts_anilist_url(self):
        provider = self.build_provider()

        result = provider.get_details("https://anilist.co/anime/154587", media_type_hint="tv")

        self.assertIsNotNone(result)
        metadata = result.metadata
        self.assertEqual("anilist/154587", metadata["tmdb_id"])
        self.assertEqual("ANILIST", metadata["scraper_source"])
        self.assertEqual("Frieren: Beyond Journey's End", metadata["title"])
        self.assertEqual("Sousou no Frieren", metadata["original_title"])
        self.assertEqual(2023, metadata["year"])
        self.assertEqual("JP", metadata["country"])
        self.assertEqual("https://anilist.co/anime/154587", metadata["source_url"])
        self.assertEqual([
            {
                "season": 1,
                "title": "Frieren: Beyond Journey's End",
                "overview": "The adventure is over but life goes on.",
                "air_date": "2023-09-29",
                "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/frieren.jpg",
                "episode_count": 28,
            }
        ], metadata["season_metadata"])

    def test_get_details_prefers_native_title_for_chinese_anime(self):
        provider = self.build_provider()

        result = provider.get_details("anilist/166475", media_type_hint="movie")

        self.assertIsNotNone(result)
        metadata = result.metadata
        self.assertEqual("罗小黑战记 2", metadata["title"])
        self.assertEqual("Luo Xiaohei Zhan Ji 2", metadata["original_title"])
        self.assertEqual("movie", metadata["media_type_hint"])
        self.assertEqual([], metadata["season_metadata"])

    def test_scrape_can_be_used_when_provider_order_explicitly_includes_anilist(self):
        provider = self.build_provider()

        attempt = provider.scrape(
            ScrapeContext(title="Frieren", year=2023, source_id=1, content_type="tv"),
            media_type_hint="tv",
        )

        self.assertIsNotNone(attempt.result)
        self.assertEqual("ANILIST", attempt.result.metadata["scraper_source"])
        self.assertEqual("anilist/154587", attempt.result.matched_id)

    def test_search_reports_warning_when_anilist_request_fails(self):
        provider = AniListMetadataProvider()
        provider.session = FailingAniListSession()

        with patch("backend.app.services.metadata_providers.anilist.time.sleep"):
            result = provider.search_candidates("Frieren", limit=3, media_type_hint="tv")

        self.assertEqual([], result.items)
        self.assertIn("anilist_search_failed", result.warnings)

    def test_scraper_catalog_lists_anilist_without_default_order(self):
        scraper = MetadataScraper()
        catalog = scraper.provider_catalog()
        providers = {item["key"]: item for item in catalog["providers"]}

        self.assertEqual(["nfo", "tmdb", "local"], catalog["default_order"])
        self.assertIn("anilist", providers)
        self.assertTrue(providers["anilist"]["supports_search"])
        self.assertTrue(providers["anilist"]["supports_scrape"])
        self.assertFalse(providers["anilist"]["default_enabled"])

    def test_anilist_source_is_non_attention_external_match(self):
        state = Movie.build_metadata_ui_state("ANILIST")

        self.assertEqual("anilist", state["source_group"])
        self.assertTrue(state["is_external_match"])
        self.assertFalse(state["needs_attention"])
        self.assertIn("ANILIST", Movie.get_metadata_non_attention_sources())


if __name__ == "__main__":
    unittest.main()
