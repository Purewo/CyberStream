from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models import Movie
from backend.app.services.metadata_providers.tencent_video import TencentVideoMetadataProvider
from backend.app.services.metadata_scraper import MetadataScraper
from backend.app.services.metadata_types import ScrapeContext


class FakeTencentResponse:
    def __init__(self, payload=None, text=""):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeTencentSession:
    def __init__(self, cover_page_text=None):
        self.trust_env = True
        self.posts = []
        self.gets = []
        self.cover_page_text = cover_page_text

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({
            "url": url,
            "headers": headers or {},
            "json": json or {},
            "timeout": timeout,
        })
        return FakeTencentResponse(payload={
            "ret": 0,
            "msg": "",
            "data": {
                "errcode": 0,
                "normalList": {
                    "itemList": [
                        {
                            "doc": {"dataType": 2, "id": "mzc00200z195unq"},
                            "videoInfo": {
                                "title": "Immortal S03",
                                "year": 2025,
                                "typeName": "Animation",
                                "area": "CN",
                                "descrip": "Beast returns.",
                                "imgUrl": "https://vcover-vt-pic.puui.qpic.cn/poster/260",
                                "imgTag": '{"4":{"info":{"text":"\\u5168 26 \\u96c6"}}}',
                                "actors": ["Alice", "Bob"],
                                "directors": ["Director A"],
                                "coverDoc": {
                                    "richTags": [
                                        {"text": "\u8bc4\u5206 9.4"},
                                        {"text": "Fantasy"},
                                        {"text": "Chinese animation"},
                                    ],
                                },
                            },
                        },
                        {
                            "doc": {"dataType": 1, "id": "short-video"},
                            "videoInfo": {
                                "title": "<em>Immortal S03</em> recap",
                                "year": 0,
                            },
                        },
                    ],
                },
            },
        })

    def get(self, url, headers=None, timeout=None):
        self.gets.append({
            "url": url,
            "headers": headers or {},
            "timeout": timeout,
        })
        if self.cover_page_text is not None:
            return FakeTencentResponse(text=self.cover_page_text)
        return FakeTencentResponse(text="""
<!doctype html>
<html>
<head>
<meta itemprop="name" name="title" content="Immortal S03_Animation_Tencent Video">
<meta itemprop="description" name="description" content="Watch Immortal S03. Starring: Alice, Bob. Beast returns.">
<meta itemprop="contentLocation" content="CN">
<meta property="og:video:tag" content="Immortal S03">
<meta property="og:video:tag" content="Animation">
<meta property="og:video:tag" content="Alice">
<meta property="og:video:tag" content="Fantasy">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [{
    "@type": "VideoObject",
    "name": "Immortal_01",
    "description": "Beast returns.",
    "thumbnailUrl": ["https://vcover-hz-pic.puui.qpic.cn/backdrop/0"],
    "datePublished": "2025-06-12T00:00:00+08:00",
    "actor": [{"@type": "Person", "name": "Alice"}, {"@type": "Person", "name": "Bob"}],
    "partOfSeries": {
      "@type": "TVSeries",
      "name": "Immortal S03",
      "url": "https://v.qq.com/x/cover/mzc00200z195unq.html",
      "numberOfEpisodes": 26,
      "description": "Beast returns.",
      "image": "https://vcover-vt-pic.puui.qpic.cn/poster/0",
      "genre": ["Fantasy"],
      "datePublished": "2025-06-12T00:00:00+08:00",
      "countryOfOrigin": {"@type": "Country", "name": "CN"}
    }
  }]
}
</script>
</head>
<body></body>
</html>
""")


class TencentVideoMetadataProviderTests(unittest.TestCase):
    def build_provider(self, cover_page_text=None):
        provider = TencentVideoMetadataProvider()
        provider.session = FakeTencentSession(cover_page_text=cover_page_text)
        return provider

    def test_search_candidates_uses_single_search_request_and_filters_short_videos(self):
        provider = self.build_provider()

        result = provider.search_candidates("Immortal S03", limit=5, media_type_hint="tv")

        self.assertEqual(1, len(result.items))
        item = result.items[0]
        self.assertEqual("tencent_video", item["provider"])
        self.assertEqual("tencent_video/mzc00200z195unq", item["candidate_id"])
        self.assertEqual("Immortal S03", item["title"])
        self.assertEqual(2025, item["year"])
        self.assertEqual(26, item["episode_count"])
        self.assertEqual(3, item["season"])
        self.assertEqual(9.4, item["rating"])
        self.assertIn("Fantasy", item["category"])
        self.assertEqual(["Alice", "Bob"], item["actors"])
        self.assertEqual(["Director A"], item["directors"])
        self.assertEqual("CN", item["country"])
        self.assertEqual(1, len(provider.session.posts))
        self.assertEqual("Immortal S03", provider.session.posts[0]["json"]["query"])
        self.assertEqual([], provider.session.gets)

    def test_search_candidates_do_not_force_movie_when_episode_evidence_is_tv(self):
        provider = self.build_provider()

        result = provider.search_candidates("Immortal S03", limit=5, media_type_hint="movie")

        self.assertEqual(1, len(result.items))
        self.assertEqual("tv", result.items[0]["media_type"])
        self.assertEqual(26, result.items[0]["episode_count"])

    def test_search_candidates_use_tencent_tv_category_over_movie_hint(self):
        provider = self.build_provider()
        payload = provider.session.post("", json={}).json()
        item = payload["data"]["normalList"]["itemList"][0]
        item["videoInfo"]["imgTag"] = ""
        item["videoInfo"]["typeName"] = "\u7535\u89c6\u5267"

        candidate = provider._candidate_from_search_item(item, media_type_hint="movie")

        self.assertEqual("tv", candidate["media_type"])
        self.assertEqual(["\u7535\u89c6\u5267"], candidate["category"][:1])

    def test_get_details_reads_cover_page_metadata_without_playback_fields(self):
        provider = self.build_provider()

        result = provider.get_details("tencent_video/mzc00200z195unq", media_type_hint="tv")

        self.assertIsNotNone(result)
        metadata = result.metadata
        self.assertEqual("tencent_video/mzc00200z195unq", metadata["tmdb_id"])
        self.assertEqual("TENCENT_VIDEO", metadata["scraper_source"])
        self.assertEqual("Immortal S03", metadata["title"])
        self.assertEqual(2025, metadata["year"])
        self.assertEqual("CN", metadata["country"])
        self.assertEqual(["Alice", "Bob"], metadata["actors"])
        self.assertEqual("https://v.qq.com/x/cover/mzc00200z195unq.html", metadata["source_url"])
        self.assertEqual([
            {
                "season": 3,
                "title": "Immortal S03",
                "overview": "Beast returns.",
                "air_date": "2025-06-12",
                "poster": "https://vcover-vt-pic.puui.qpic.cn/poster/0",
                "episode_count": 26,
            }
        ], metadata["season_metadata"])
        self.assertNotIn("play_url", metadata)
        self.assertNotIn("stream_url", metadata)

    def test_get_details_falls_back_to_cached_search_candidate_for_empty_cover_page(self):
        provider = self.build_provider("""
<!doctype html>
<html>
<head>
<meta name="description" content="Tencent Video landing shell">
</head>
<body></body>
</html>
""")
        search_result = provider.search_candidates("Immortal S03", limit=5, media_type_hint="tv")
        candidate_id = search_result.items[0]["candidate_id"]

        result = provider.get_details(candidate_id, media_type_hint="tv")

        self.assertIsNotNone(result)
        self.assertEqual("search_candidate_cache", result.raw["matched_from"])
        self.assertEqual(0.75, result.confidence)
        metadata = result.metadata
        self.assertEqual(candidate_id, metadata["tmdb_id"])
        self.assertEqual("TENCENT_VIDEO", metadata["scraper_source"])
        self.assertEqual("Immortal S03", metadata["title"])
        self.assertEqual(2025, metadata["year"])
        self.assertEqual("https://vcover-vt-pic.puui.qpic.cn/poster/260", metadata["cover"])
        self.assertEqual(["Alice", "Bob"], metadata["actors"])
        self.assertEqual("CN", metadata["country"])
        self.assertNotIn("play_url", metadata)
        self.assertNotIn("stream_url", metadata)

    def test_cached_details_keep_tv_evidence_over_movie_hint(self):
        provider = self.build_provider("""
<!doctype html>
<html>
<head>
<meta name="description" content="Tencent Video landing shell">
</head>
<body></body>
</html>
""")
        search_result = provider.search_candidates("Immortal S03", limit=5, media_type_hint="movie")
        candidate_id = search_result.items[0]["candidate_id"]

        result = provider.get_details(candidate_id, media_type_hint="movie")

        self.assertIsNotNone(result)
        self.assertEqual("tv", result.metadata["media_type_hint"])

    def test_scrape_is_manual_only_and_does_not_call_network(self):
        provider = self.build_provider()

        attempt = provider.scrape(
            ScrapeContext(title="Immortal S03", year=None, source_id=1, content_type="tv"),
            media_type_hint="tv",
        )

        self.assertIsNone(attempt.result)
        self.assertEqual(["tencent_video_manual_only"], attempt.warnings)
        self.assertEqual([], provider.session.posts)
        self.assertEqual([], provider.session.gets)

    def test_scraper_catalog_lists_tencent_as_manual_only_without_default_order(self):
        scraper = MetadataScraper()
        catalog = scraper.provider_catalog()
        providers = {item["key"]: item for item in catalog["providers"]}

        self.assertEqual(["nfo", "tmdb", "local"], catalog["default_order"])
        self.assertIn("tencent_video", providers)
        self.assertTrue(providers["tencent_video"]["supports_search"])
        self.assertTrue(providers["tencent_video"]["manual_only"])
        self.assertFalse(providers["tencent_video"]["supports_scrape"])

    def test_tencent_video_source_is_non_attention_external_match(self):
        state = Movie.build_metadata_ui_state("TENCENT_VIDEO")

        self.assertEqual("tencent_video", state["source_group"])
        self.assertTrue(state["is_external_match"])
        self.assertFalse(state["needs_attention"])
        self.assertIn("TENCENT_VIDEO", Movie.get_metadata_non_attention_sources())


if __name__ == "__main__":
    unittest.main()
