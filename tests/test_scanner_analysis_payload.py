from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.metadata_types import ScrapeResult
from backend.app.services.scanner import CyberScanner


class ScannerAnalysisPayloadTests(unittest.TestCase):
    def test_resource_payload_carries_cleaning_and_scraping_analysis(self):
        scanner = CyberScanner()
        files = [
            {
                "name": "Green Planet 1.m2ts",
                "path": "我的视频/绿色星球/Green Planet 1.m2ts",
                "size": 1234,
                "_meta": {
                    "title": "Green Planet",
                    "year": None,
                    "season": None,
                    "episode": 1,
                    "parse_mode": "fallback",
                    "parse_strategy": "dirty_release_group",
                    "needs_review": True,
                },
            }
        ]
        scrape_result = ScrapeResult(
            metadata={
                "tmdb_id": "tv/1",
                "title": "The Green Planet",
                "original_title": "The Green Planet",
                "year": 2022,
                "rating": 8.5,
                "description": "",
                "cover": "",
                "background_cover": "",
                "category": [],
                "director": "Unknown",
                "actors": [],
                "country": "Unknown",
                "scraper_source": "TMDB",
            },
            provider="tmdb",
            confidence=0.85,
            matched_id="tv/1",
            warnings=["title_hint_overridden:Green Planet->The Green Planet"],
            raw={
                "final_title_source": "tmdb",
                "final_year_source": "tmdb",
                "provider_order": ["tmdb", "local"],
            },
        )

        with patch("backend.app.services.scanner.db.get_source_by_id", return_value=None), \
                patch("backend.app.services.scanner.metadata_scraper.scrape", return_value=scrape_result), \
                patch("backend.app.services.scanner.db.upsert_movie") as upsert_movie:
            scanner._process_single_entity(
                ("Green Planet", None),
                files,
                source_id=1,
                scrape_enabled=True,
                content_type="tv",
                scraper_policy={"provider_order": ["tmdb", "local"]},
            )

        upsert_movie.assert_called_once()
        _metadata, resource_info, _source_id = upsert_movie.call_args.args
        analysis = resource_info["analysis"]

        self.assertEqual("Green Planet", analysis["path_cleaning"]["title_hint"])
        self.assertEqual("fallback", analysis["path_cleaning"]["parse_mode"])
        self.assertTrue(analysis["path_cleaning"]["needs_review"])
        self.assertEqual("tmdb", analysis["scraping"]["provider"])
        self.assertEqual("tmdb", analysis["scraping"]["final_title_source"])
        self.assertEqual("tmdb", analysis["scraping"]["final_year_source"])
        self.assertEqual(["tmdb", "local"], analysis["scraping"]["provider_order"])


if __name__ == "__main__":
    unittest.main()
