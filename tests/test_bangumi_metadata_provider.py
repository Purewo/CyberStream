from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.metadata_providers.bangumi import BangumiMetadataProvider
from backend.app.services.metadata_types import ScrapeContext


class FakeBangumiResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeBangumiSession:
    def __init__(self):
        self.calls = []
        self.trust_env = True

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.calls.append({
            "method": method,
            "url": url,
            "headers": headers or {},
            "timeout": timeout,
            "kwargs": kwargs,
        })
        if method == "POST":
            return FakeBangumiResponse({
                "data": [{
                    "id": 361761,
                    "type": 2,
                    "name": "葬送のフリーレン",
                    "name_cn": "葬送的芙莉莲",
                    "short_summary": "勇者一行打倒魔王后的故事。",
                    "date": "2023-09-29",
                    "images": {"common": "https://lain.bgm.tv/pic/cover/c/example.jpg"},
                    "eps": 28,
                    "score": 8.7,
                    "rank": 1,
                    "collection_total": 120000,
                }]
            })
        return FakeBangumiResponse({
            "id": 361761,
            "type": 2,
            "name": "葬送のフリーレン",
            "name_cn": "葬送的芙莉莲",
            "summary": "勇者一行打倒魔王后的故事。",
            "date": "2023-09-29",
            "platform": "TV",
            "images": {"large": "https://lain.bgm.tv/pic/cover/l/example.jpg"},
            "eps": 28,
            "total_episodes": 28,
            "rating": {"score": 8.7, "rank": 1, "total": 1000, "count": {}},
            "infobox": [{"key": "导演", "value": "斋藤圭一郎"}],
            "tags": [{"name": "奇幻", "count": 100}, {"name": "漫画改", "count": 80}],
        })


class FailingBangumiSession:
    trust_env = False

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        raise RuntimeError("network down")


class BangumiMetadataProviderTests(unittest.TestCase):
    def build_provider(self):
        provider = BangumiMetadataProvider()
        provider.session = FakeBangumiSession()
        return provider

    def test_search_candidates_uses_official_v0_subject_search(self):
        provider = self.build_provider()

        result = provider.search_candidates("葬送的芙莉莲", year=2023, limit=3, media_type_hint="tv")

        self.assertEqual(1, len(result.items))
        item = result.items[0]
        self.assertEqual("bangumi", item["provider"])
        self.assertEqual("bangumi/361761", item["candidate_id"])
        self.assertEqual("葬送的芙莉莲", item["title"])
        self.assertEqual("葬送のフリーレン", item["original_title"])
        self.assertEqual(2023, item["year"])
        self.assertEqual("tv", item["media_type"])
        self.assertEqual("https://bgm.tv/subject/361761", item["source_url"])
        self.assertEqual(28, item["episode_count"])
        self.assertEqual(2, item["subject_type"])

        call = provider.session.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertIn("/v0/search/subjects", call["url"])
        self.assertIn("User-Agent", call["headers"])
        self.assertIn("https://github.com/Purewo/CyberStream", call["headers"]["User-Agent"])
        self.assertEqual([2], call["kwargs"]["json"]["filter"]["type"])

    def test_search_accepts_bangumi_subject_url(self):
        provider = self.build_provider()

        result = provider.search_candidates("https://bgm.tv/subject/361761", limit=3, media_type_hint="tv")

        self.assertEqual(1, len(result.items))
        self.assertEqual("bangumi/361761", result.items[0]["candidate_id"])
        call = provider.session.calls[0]
        self.assertEqual("GET", call["method"])
        self.assertIn("/v0/subjects/361761", call["url"])

    def test_search_reports_warning_when_bangumi_request_fails(self):
        provider = BangumiMetadataProvider()
        provider.session = FailingBangumiSession()

        with patch("backend.app.services.metadata_providers.bangumi.time.sleep"):
            result = provider.search_candidates("葬送的芙莉莲", limit=3, media_type_hint="tv")

        self.assertEqual([], result.items)
        self.assertIn("bangumi_search_failed", result.warnings)

    def test_scrape_returns_bangumi_metadata(self):
        provider = self.build_provider()

        attempt = provider.scrape(
            ScrapeContext(title="葬送的芙莉莲", year=2023, source_id=1, content_type="tv"),
            media_type_hint="tv",
        )

        self.assertIsNotNone(attempt.result)
        metadata = attempt.result.metadata
        self.assertEqual("bangumi/361761", metadata["tmdb_id"])
        self.assertEqual("BANGUMI", metadata["scraper_source"])
        self.assertEqual("葬送的芙莉莲", metadata["title"])
        self.assertEqual("斋藤圭一郎", metadata["director"])
        self.assertIn("动画", metadata["category"])
        self.assertIn("奇幻", metadata["category"])
        self.assertEqual("https://bgm.tv/subject/361761", metadata["source_url"])

    def test_get_details_accepts_bangumi_subject_url(self):
        provider = self.build_provider()

        result = provider.get_details("https://bgm.tv/subject/361761", media_type_hint="tv")

        self.assertIsNotNone(result)
        self.assertEqual("bangumi/361761", result.metadata["tmdb_id"])


if __name__ == "__main__":
    unittest.main()
