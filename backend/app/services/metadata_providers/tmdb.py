import time

from backend.app.db.database import scanner_adapter as db
from backend.app.services.metadata_providers.base import MetadataProviderBase
from backend.app.services.metadata_types import CandidateSearchResult, ProviderAttempt, ScrapeContext, ScrapeResult
from backend.app.services.tmdb import scraper


class TmdbMetadataProvider(MetadataProviderBase):
    name = 'tmdb'
    display_name = 'TMDB'
    authoritative = True
    supports_search = True

    def __init__(self):
        self.tmdb_cache: dict[tuple[str, int | None, str | None], str] = {}

    def scrape(self, context: ScrapeContext, media_type_hint: str | None) -> ProviderAttempt:
        cache_key = (context.title, context.year, media_type_hint)
        tmdb_id = None
        matched_from = None

        if cache_key in self.tmdb_cache:
            tmdb_id = self.tmdb_cache[cache_key]
            matched_from = 'memory_cache'
        else:
            db_match = db.get_movie_by_title_year(context.title, context.year, media_type_hint)
            if db_match:
                tmdb_id = db_match['tmdb_id']
                matched_from = 'database'
            else:
                time.sleep(0.1)
                tmdb_id = scraper.search_movie(context.title, context.year, media_type_hint=media_type_hint)
                if tmdb_id:
                    self.tmdb_cache[cache_key] = tmdb_id
                    matched_from = 'tmdb_search'

        if not tmdb_id or tmdb_id.startswith('loc-'):
            return ProviderAttempt()

        metadata = scraper.get_movie_details(tmdb_id)
        if not metadata:
            return ProviderAttempt(warnings=[f'tmdb_details_failed:{tmdb_id}'])

        if matched_from == 'database':
            confidence = 0.95
        elif context.year:
            confidence = 0.85
        else:
            confidence = 0.7

        return ProviderAttempt(
            result=ScrapeResult(
                metadata=metadata,
                provider='tmdb',
                confidence=confidence,
                matched_id=tmdb_id,
                raw={
                    "title": context.title,
                    "year": context.year,
                    "content_type": media_type_hint,
                    "matched_from": matched_from,
                },
            )
        )

    def search_candidates(
        self,
        query: str,
        *,
        year: int | None = None,
        limit: int = 8,
        media_type_hint: str | None = None,
    ) -> CandidateSearchResult:
        candidates = scraper.search_movie_candidates(query, year=year, limit=limit)
        if media_type_hint:
            candidates = [item for item in candidates if item.get('media_type') == media_type_hint]

        items = []
        for item in candidates[:max(limit, 0)]:
            tmdb_id = item.get('tmdb_id')
            items.append({
                **item,
                "provider": self.name,
                "provider_name": self.display_name,
                "source_key": self.name,
                "candidate_id": tmdb_id,
                "external_id": tmdb_id,
            })
        return CandidateSearchResult(items=items)

    def get_details(self, candidate_id: str, media_type_hint: str | None = None) -> ScrapeResult | None:
        metadata = scraper.get_movie_details(candidate_id)
        if not metadata:
            return None
        return ScrapeResult(
            metadata=metadata,
            provider=self.name,
            confidence=1.0,
            matched_id=metadata.get("tmdb_id") or candidate_id,
            raw={
                "matched_from": "candidate_id",
                "content_type": media_type_hint,
            },
        )
