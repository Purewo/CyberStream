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
    def __init__(self):
        self.trust_env = True
        self.posts = []
        self.gets = []

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
                                "title": "诛仙 第3季",
                                "year": 2025,
                                "typeName": "动漫",
                                "area": "内地",
                                "descrip": "兽神出世。",
                                "imgUrl": "https://vcover-vt-pic.puui.qpic.cn/poster/260",
                                "imgTag": '{"4":{"info":{"text":"全26集"}}}',
                                "actors": ["边江", "段艺璇"],
                                "coverDoc": {
                                    "richTags": [
                                        {"text": "评分 9.4"},
                                        {"text": "东方仙侠"},
                                        {"text": "国漫"},
                                    ],
                                },
                            },
                        },
                        {
                            "doc": {"dataType": 1, "id": "short-video"},
                            "videoInfo": {
                                "title": "<em>诛仙3</em>解说短视频",
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
        return FakeTencentResponse(text="""
<!doctype html>
<html>
<head>
<meta itemprop="name" name="title" content="诛仙第3季_动漫_高清完整版视频在线观看_腾讯视频">
<meta itemprop="description" name="description" content="《诛仙第3季》高清在线观看，领衔主演:边江,段艺璇,锦鲤,剧情简介:兽神出世。">
<meta itemprop="contentLocation" content="内地">
<meta property="og:video:tag" content="诛仙 第3季">
<meta property="og:video:tag" content="动漫">
<meta property="og:video:tag" content="边江">
<meta property="og:video:tag" content="东方仙侠">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [{
    "@type": "VideoObject",
    "name": "诛仙_01",
    "description": "兽神出世。",
    "thumbnailUrl": ["https://vcover-hz-pic.puui.qpic.cn/backdrop/0"],
    "datePublished": "2025-06-12T00:00:00+08:00",
    "actor": [{"@type": "Person", "name": "边江"}, {"@type": "Person", "name": "段艺璇"}],
    "partOfSeries": {
      "@type": "TVSeries",
      "name": "诛仙 第3季",
      "url": "https://v.qq.com/x/cover/mzc00200z195unq.html",
      "numberOfEpisodes": 26,
      "description": "兽神出世。",
      "image": "https://vcover-vt-pic.puui.qpic.cn/poster/0",
      "genre": ["仙侠"],
      "datePublished": "2025-06-12T00:00:00+08:00",
      "countryOfOrigin": {"@type": "Country", "name": "内地"}
    }
  }]
}
</script>
</head>
<body></body>
</html>
""")


class TencentVideoMetadataProviderTests(unittest.TestCase):
    def build_provider(self):
        provider = TencentVideoMetadataProvider()
        provider.session = FakeTencentSession()
        return provider

    def test_search_candidates_uses_single_search_request_and_filters_short_videos(self):
        provider = self.build_provider()

        result = provider.search_candidates("诛仙3", limit=5, media_type_hint="tv")

        self.assertEqual(1, len(result.items))
        item = result.items[0]
        self.assertEqual("tencent_video", item["provider"])
        self.assertEqual("tencent_video/mzc00200z195unq", item["candidate_id"])
        self.assertEqual("诛仙 第3季", item["title"])
        self.assertEqual(2025, item["year"])
        self.assertEqual(26, item["episode_count"])
        self.assertEqual(3, item["season"])
        self.assertEqual(9.4, item["rating"])
        self.assertIn("东方仙侠", item["category"])
        self.assertEqual(1, len(provider.session.posts))
        self.assertEqual("诛仙3", provider.session.posts[0]["json"]["query"])
        self.assertEqual([], provider.session.gets)

    def test_get_details_reads_cover_page_metadata_without_playback_fields(self):
        provider = self.build_provider()

        result = provider.get_details("tencent_video/mzc00200z195unq", media_type_hint="tv")

        self.assertIsNotNone(result)
        metadata = result.metadata
        self.assertEqual("tencent_video/mzc00200z195unq", metadata["tmdb_id"])
        self.assertEqual("TENCENT_VIDEO", metadata["scraper_source"])
        self.assertEqual("诛仙 第3季", metadata["title"])
        self.assertEqual(2025, metadata["year"])
        self.assertEqual("内地", metadata["country"])
        self.assertEqual(["边江", "段艺璇"], metadata["actors"])
        self.assertEqual("https://v.qq.com/x/cover/mzc00200z195unq.html", metadata["source_url"])
        self.assertEqual([
            {
                "season": 3,
                "title": "诛仙 第3季",
                "overview": "兽神出世。",
                "air_date": "2025-06-12",
                "poster": "https://vcover-vt-pic.puui.qpic.cn/poster/0",
                "episode_count": 26,
            }
        ], metadata["season_metadata"])
        self.assertNotIn("play_url", metadata)
        self.assertNotIn("stream_url", metadata)

    def test_scrape_is_manual_only_and_does_not_call_network(self):
        provider = self.build_provider()

        attempt = provider.scrape(
            ScrapeContext(title="诛仙3", year=None, source_id=1, content_type="tv"),
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
