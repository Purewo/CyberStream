from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.metadata_scraper import MetadataScraper
from backend.app.services.metadata_types import CandidateSearchResult, ProviderAttempt, ScrapeContext, ScrapeResult


class BrokenProvider:
    name = "tmdb"

    def scrape(self, context, media_type_hint):
        raise TypeError("boom")


class LocalProvider:
    name = "local"

    def scrape(self, context, media_type_hint):
        return ProviderAttempt(
            result=ScrapeResult(
                metadata={
                    "tmdb_id": "loc-test",
                    "title": context.title,
                    "original_title": context.title,
                    "year": context.year or 2077,
                    "rating": 0,
                    "description": "Local fallback",
                    "cover": "",
                    "background_cover": "",
                    "category": ["Local"],
                    "director": "Unknown",
                    "actors": [],
                    "country": "Unknown",
                    "scraper_source": "Local",
                },
                provider="local",
                confidence=0.0,
                raw={"matched_from": "local"},
            )
        )


class SearchWarningProvider:
    name = "bangumi"
    supports_search = True

    def search_candidates(self, query, *, year=None, limit=8, media_type_hint=None):
        return CandidateSearchResult(warnings=["bangumi_search_failed"])


class MetadataScraperProviderFailoverTests(unittest.TestCase):
    def test_provider_exception_falls_back_to_local(self):
        scraper = MetadataScraper()
        scraper.providers = {
            "tmdb": BrokenProvider(),
            "local": LocalProvider(),
        }

        result = scraper.scrape(
            ScrapeContext(
                title="Deep Sea",
                year=2023,
                source_id=1,
                scraper_policy={"provider_order": ["tmdb", "local"]},
            )
        )

        self.assertEqual("local", result.provider)
        self.assertEqual("Deep Sea", result.metadata["title"])
        self.assertTrue(
            any(item.startswith("provider_error:tmdb:TypeError:boom") for item in result.warnings),
            msg=result.warnings,
        )

    def test_search_warning_without_candidates_marks_attempt_failed(self):
        scraper = MetadataScraper()
        scraper.providers = {
            "bangumi": SearchWarningProvider(),
        }

        result = scraper.search_candidates(
            ScrapeContext(
                title="葬送的芙莉莲",
                year=None,
                source_id=1,
                scraper_policy={"provider_order": ["bangumi"]},
            ),
            "葬送的芙莉莲",
            media_type_hint="tv",
        )

        attempts = result["providers"]["attempts"]
        self.assertEqual("failed", attempts[0]["status"])
        self.assertEqual(["bangumi:bangumi_search_failed"], attempts[0]["warnings"])
        self.assertEqual([], result["items"])


if __name__ == "__main__":
    unittest.main()
