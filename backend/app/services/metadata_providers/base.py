from backend.app.services.metadata_types import ProviderAttempt, ScrapeContext


class MetadataProviderBase:
    name = ''

    def scrape(self, context: ScrapeContext, media_type_hint: str | None) -> ProviderAttempt:
        raise NotImplementedError
