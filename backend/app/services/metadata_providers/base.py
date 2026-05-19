from backend.app.services.metadata_types import CandidateSearchResult, ProviderAttempt, ScrapeContext, ScrapeResult


class MetadataProviderBase:
    name = ''
    display_name = ''
    authoritative = False
    supports_search = False

    def scrape(self, context: ScrapeContext, media_type_hint: str | None) -> ProviderAttempt:
        raise NotImplementedError

    def search_candidates(
        self,
        query: str,
        *,
        year: int | None = None,
        limit: int = 8,
        media_type_hint: str | None = None,
    ) -> CandidateSearchResult:
        return CandidateSearchResult()

    def get_details(self, candidate_id: str, media_type_hint: str | None = None) -> ScrapeResult | None:
        return None

    def describe(self):
        return {
            "key": self.name,
            "name": self.display_name or self.name,
            "authoritative": bool(self.authoritative),
            "supports_search": bool(self.supports_search),
            "supports_scrape": True,
        }
