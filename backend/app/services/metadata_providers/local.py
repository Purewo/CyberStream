import hashlib

from backend.app.services.metadata_providers.base import MetadataProviderBase
from backend.app.services.metadata_types import ProviderAttempt, ScrapeContext, ScrapeResult


class LocalFallbackProvider(MetadataProviderBase):
    name = 'local'

    def _normalize_content_type_hint(self, content_type):
        content_type = (content_type or '').strip().lower()
        if content_type in {'movie', 'tv'}:
            return content_type
        return None

    def _local_categories(self, content_type=None):
        media_type = self._normalize_content_type_hint(content_type)
        if media_type == 'movie':
            return ["Movie", "Local"]
        if media_type == 'tv':
            return ["TV", "Local"]
        return ["Local"]

    def _generate_stable_id(self, title, year, content_type=None):
        media_type = self._normalize_content_type_hint(content_type)
        if media_type:
            raw = f"{media_type}|{title.strip().lower()}|{year}"
            return f"loc-{media_type}-" + hashlib.md5(raw.encode()).hexdigest()[:12]

        raw = f"{title.strip().lower()}|{year}"
        return "loc-" + hashlib.md5(raw.encode()).hexdigest()[:12]

    def scrape(self, context: ScrapeContext, media_type_hint: str | None) -> ProviderAttempt:
        metadata = {
            "tmdb_id": self._generate_stable_id(context.title, context.year or 2077, media_type_hint),
            "title": context.title,
            "original_title": context.title,
            "year": context.year or 2077,
            "rating": 0,
            "description": "Scraping disabled (Local)" if not context.scrape_enabled else "Unidentified (Local)",
            "cover": "",
            "background_cover": "",
            "category": self._local_categories(media_type_hint),
            "director": "Unknown",
            "actors": [],
            "country": "Unknown",
            "scraper_source": "Local",
        }
        return ProviderAttempt(
            result=ScrapeResult(
                metadata=metadata,
                provider='local_fallback',
                confidence=0.0,
                raw={
                    "title": context.title,
                    "year": context.year,
                    "content_type": media_type_hint,
                },
            )
        )
