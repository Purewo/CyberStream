from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.metadata_scraper import MetadataScraper
from backend.app.services.metadata_types import ProviderAttempt, ScrapeContext, ScrapeResult


class FakeProvider:
    def __init__(self, name, year, tmdb_id=None):
        self.name = name
        self.year = year
        self.tmdb_id = tmdb_id or f"{name}/1"

    def scrape(self, context, media_type_hint):
        return ProviderAttempt(
            result=ScrapeResult(
                metadata={
                    "tmdb_id": self.tmdb_id,
                    "title": f"{self.name} title",
                    "original_title": f"{self.name} title",
                    "year": self.year,
                    "rating": 0,
                    "description": "",
                    "cover": "",
                    "background_cover": "",
                    "category": [],
                    "director": "Unknown",
                    "actors": [],
                    "country": "Unknown",
                    "scraper_source": self.name.upper(),
                },
                provider=self.name,
                confidence=0.9,
                matched_id=self.tmdb_id,
                raw={"matched_from": "fake"},
            )
        )


class MetadataScraperMetadataPolicyTests(unittest.TestCase):
    def build_scraper(self, provider):
        scraper = MetadataScraper()
        scraper.providers = {
            provider.name: provider,
            "local": FakeProvider("local", None, tmdb_id="loc-test"),
        }
        return scraper

    def test_tmdb_year_overrides_path_year(self):
        scraper = self.build_scraper(FakeProvider("tmdb", 2022, "movie/1"))
        result = scraper.scrape(
            ScrapeContext(
                title="Wrong Path Year",
                year=2020,
                source_id=1,
                scraper_policy={"provider_order": ["tmdb"]},
            )
        )

        self.assertEqual(2022, result.metadata["year"])
        self.assertEqual("tmdb title", result.metadata["title"])
        self.assertEqual("tmdb", result.raw["final_year_source"])
        self.assertEqual("tmdb", result.raw["final_title_source"])
        self.assertEqual(2020, result.raw["path_year_hint"])
        self.assertEqual(2022, result.raw["scraped_year"])
        self.assertIn("year_hint_overridden:2020->2022", result.warnings)
        self.assertIn("title_hint_overridden:Wrong Path Year->tmdb title", result.warnings)

    def test_nfo_year_overrides_path_year(self):
        scraper = self.build_scraper(FakeProvider("nfo", 2019, "movie/2"))
        result = scraper.scrape(
            ScrapeContext(
                title="NFO Movie",
                year=2018,
                source_id=1,
                scraper_policy={"provider_order": ["nfo"]},
            )
        )

        self.assertEqual(2019, result.metadata["year"])
        self.assertEqual("nfo", result.raw["final_year_source"])
        self.assertIn("year_hint_overridden:2018->2019", result.warnings)

    def test_local_fallback_uses_path_year(self):
        scraper = self.build_scraper(FakeProvider("local", 2077, "loc-test"))
        result = scraper.scrape(
            ScrapeContext(
                title="Local Movie",
                year=2017,
                source_id=1,
                scrape_enabled=False,
                scraper_policy={"provider_order": ["local"]},
            )
        )

        self.assertEqual(2017, result.metadata["year"])
        self.assertEqual("Local Movie", result.metadata["title"])
        self.assertEqual("path_hint", result.raw["final_year_source"])
        self.assertEqual("path_hint", result.raw["final_title_source"])
        self.assertNotIn("year_hint_overridden:2017->2077", result.warnings)
        self.assertNotIn("title_hint_overridden:Local Movie->local title", result.warnings)

    def test_unknown_series_stays_scanner_unknown(self):
        scraper = MetadataScraper()
        result = scraper.scrape(
            ScrapeContext(
                title="UNKNOWN_SHOW_123",
                year=None,
                source_id=1,
            )
        )

        self.assertEqual("Unknown Series", result.metadata["title"])
        self.assertEqual(2077, result.metadata["year"])
        self.assertEqual("scanner_unknown", result.provider)
        self.assertIsNone(result.raw.get("final_year_source"))


if __name__ == "__main__":
    unittest.main()
