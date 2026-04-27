import hashlib

from backend.app.services.metadata_providers import build_default_metadata_providers
from backend.app.services.metadata_types import ProviderAttempt, ScrapeContext, ScrapeResult

DEFAULT_PROVIDER_ORDER = ['nfo', 'tmdb', 'local']
AUTHORITATIVE_METADATA_PROVIDERS = {'nfo', 'tmdb'}
PROVIDER_ALIASES = {
    'nfo': 'nfo',
    'local_nfo': 'nfo',
    'tmdb': 'tmdb',
    'themoviedb': 'tmdb',
    'local': 'local',
    'fallback': 'local',
    'local_fallback': 'local',
}


class MetadataScraper:
    def __init__(self):
        self.providers = build_default_metadata_providers()

    def _normalize_content_type_hint(self, content_type):
        content_type = (content_type or '').strip().lower()
        if content_type in {'movie', 'tv'}:
            return content_type
        return None

    def _normalize_provider_name(self, value):
        if not isinstance(value, str):
            return None
        return PROVIDER_ALIASES.get(value.strip().lower())

    def _resolve_provider_order(self, context):
        policy = context.scraper_policy if isinstance(context.scraper_policy, dict) else {}
        raw_order = policy.get('provider_order') or policy.get('providers')
        warnings = []

        if isinstance(raw_order, str):
            raw_items = [item.strip() for item in raw_order.split(',')]
        elif isinstance(raw_order, list):
            raw_items = raw_order
        else:
            raw_items = list(DEFAULT_PROVIDER_ORDER)

        provider_order = []
        for raw_item in raw_items:
            provider_name = self._normalize_provider_name(raw_item)
            if provider_name:
                if provider_name not in provider_order:
                    provider_order.append(provider_name)
                continue
            if raw_item:
                warnings.append(f'unsupported_provider:{raw_item}')

        if not provider_order:
            provider_order = list(DEFAULT_PROVIDER_ORDER)

        if not context.scrape_enabled and 'tmdb' in provider_order:
            provider_order = [item for item in provider_order if item != 'tmdb']
            warnings.append('tmdb_skipped_scrape_disabled')

        if 'local' not in provider_order:
            provider_order.append('local')

        return provider_order, warnings

    def generate_stable_id(self, title, year, content_type=None):
        media_type = self._normalize_content_type_hint(content_type)
        if media_type:
            raw = f"{media_type}|{title.strip().lower()}|{year}"
            return f"loc-{media_type}-" + hashlib.md5(raw.encode()).hexdigest()[:12]

        raw = f"{title.strip().lower()}|{year}"
        return "loc-" + hashlib.md5(raw.encode()).hexdigest()[:12]

    def _build_unknown_series(self, context, media_type_hint):
        return {
            "tmdb_id": self.generate_stable_id(context.title, 0, media_type_hint),
            "title": "Unknown Series",
            "original_title": context.title,
            "year": 2077,
            "rating": 0,
            "description": "Auto-grouped orphan files. Please rename folders.",
            "cover": "",
            "background_cover": "",
            "category": ["Misc"],
            "director": "Scanner",
            "actors": [],
            "country": "Local",
            "scraper_source": "Local",
        }

    def _merge_attempt(self, attempt, warnings, provider_order):
        warnings.extend(attempt.warnings)
        if not attempt.result:
            return None

        result = attempt.result
        result.warnings = [*warnings, *result.warnings]
        result.raw = dict(result.raw or {})
        result.raw['provider_order'] = provider_order
        return result

    def _normalize_year_value(self, value):
        try:
            year = int(value)
        except (TypeError, ValueError):
            return None
        if year < 1800 or year > 2100:
            return None
        return year

    def _normalize_text_value(self, value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _resolve_metadata_value(self, path_value, scraped_value, provider_name, authoritative=False):
        if authoritative and scraped_value is not None:
            return scraped_value, provider_name
        if path_value is not None:
            return path_value, 'path_hint'
        if scraped_value is not None:
            return scraped_value, provider_name or 'scraper'
        return None, provider_name or 'scraper'

    def _apply_metadata_policy(self, context: ScrapeContext, result: ScrapeResult):
        path_title = self._normalize_text_value(context.title)
        scraped_title = self._normalize_text_value(result.metadata.get('title'))
        final_title, final_title_source = self._resolve_metadata_value(
            path_title,
            scraped_title,
            result.provider,
            authoritative=result.provider in AUTHORITATIVE_METADATA_PROVIDERS,
        )

        scraped_original_title = self._normalize_text_value(result.metadata.get('original_title'))
        final_original_title, final_original_title_source = self._resolve_metadata_value(
            None,
            scraped_original_title,
            result.provider,
            authoritative=result.provider in AUTHORITATIVE_METADATA_PROVIDERS,
        )
        if final_original_title is None and final_title is not None:
            final_original_title = final_title
            final_original_title_source = final_title_source

        path_year = self._normalize_year_value(context.year)
        scraped_year = self._normalize_year_value(result.metadata.get('year'))

        result.raw = dict(result.raw or {})
        result.raw.setdefault('path_title_hint', context.title)
        result.raw.setdefault('path_year_hint', path_year)
        result.raw['scraped_title'] = scraped_title
        result.raw['scraped_original_title'] = scraped_original_title
        result.raw['scraped_year'] = scraped_year

        if (
            result.provider in AUTHORITATIVE_METADATA_PROVIDERS
            and scraped_year is not None
        ):
            final_year = scraped_year
            final_year_source = result.provider
        elif path_year is not None:
            final_year = path_year
            final_year_source = 'path_hint'
        elif scraped_year is not None:
            final_year = scraped_year
            final_year_source = result.provider or 'scraper'
        else:
            final_year = result.metadata.get('year')
            final_year_source = result.provider or 'scraper'

        if (
            path_year is not None
            and scraped_year is not None
            and path_year != scraped_year
            and final_year_source == result.provider
        ):
            result.warnings.append(f'year_hint_overridden:{path_year}->{scraped_year}')

        if (
            path_title is not None
            and scraped_title is not None
            and path_title != scraped_title
            and final_title_source == result.provider
        ):
            result.warnings.append(f'title_hint_overridden:{path_title}->{scraped_title}')

        result.metadata['title'] = final_title or result.metadata.get('title') or context.title
        result.metadata['original_title'] = (
            final_original_title
            or result.metadata.get('original_title')
            or result.metadata['title']
        )
        result.metadata['year'] = final_year
        result.raw['final_title'] = result.metadata['title']
        result.raw['final_title_source'] = final_title_source
        result.raw['final_original_title'] = result.metadata['original_title']
        result.raw['final_original_title_source'] = final_original_title_source
        result.raw['final_year'] = final_year
        result.raw['final_year_source'] = final_year_source
        return result

    def scrape(self, context: ScrapeContext) -> ScrapeResult:
        media_type_hint = self._normalize_content_type_hint(context.content_type)

        if context.title.startswith("UNKNOWN_SHOW_"):
            return ScrapeResult(
                metadata=self._build_unknown_series(context, media_type_hint),
                provider='scanner_unknown',
                confidence=0.0,
                raw={"title": context.title, "year": context.year, "content_type": media_type_hint},
            )

        provider_order, warnings = self._resolve_provider_order(context)

        for provider_name in provider_order:
            provider = self.providers.get(provider_name)
            if not provider:
                warnings.append(f'provider_missing:{provider_name}')
                continue

            try:
                attempt = provider.scrape(context, media_type_hint)
            except Exception as e:
                warnings.append(f'provider_error:{provider_name}:{type(e).__name__}:{e}')
                continue
            result = self._merge_attempt(attempt, warnings, provider_order)
            if result:
                return self._apply_metadata_policy(context, result)

        # This should not happen because local is always appended, but keep a safe fallback.
        local_provider = self.providers.get('local')
        if local_provider:
            result = self._merge_attempt(local_provider.scrape(context, media_type_hint), warnings, provider_order)
            if result:
                return self._apply_metadata_policy(context, result)

        return ScrapeResult(
            metadata=self._build_unknown_series(context, media_type_hint),
            provider='scanner_unknown',
            confidence=0.0,
            warnings=warnings,
            raw={"title": context.title, "year": context.year, "content_type": media_type_hint},
        )


metadata_scraper = MetadataScraper()
