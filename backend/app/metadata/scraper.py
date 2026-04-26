import logging
import time

from backend.app.db.database import scanner_adapter as db
from backend.app.services.tmdb import scraper as tmdb_scraper
from .ai import AIMetadataScraper
from .nfo import NFOMetadataResolver
from .types import MetadataResolution, ParsedMediaInfo

logger = logging.getLogger(__name__)


class MetadataScraper:
    """三层刮削中的后两层：

    1. structured: 规范格式 -> 直接 TMDB/已有库命中
    2. fallback: 经验兜底 -> TMDB 宽松搜索 / 本地占位
    3. ai: 预留接口，当前只输出 not_enabled
    """

    def __init__(self, parser):
        self.parser = parser
        self.tmdb_cache = {}
        self.ai_scraper = AIMetadataScraper()
        self.nfo_resolver = NFOMetadataResolver()

    def resolve(self, parsed_info: ParsedMediaInfo):
        if parsed_info.title.startswith("UNKNOWN_SHOW_"):
            return MetadataResolution(
                meta_data=self.parser.build_orphan_fallback(parsed_info.title),
                resolved_tmdb_id=None,
                scrape_layer='fallback',
                scrape_strategy='orphan_group',
                reason='garbage_title',
            )

        resolution = self._resolve_nfo(parsed_info)
        if resolution:
            return resolution

        resolution = self._resolve_structured(parsed_info)
        if resolution:
            return resolution

        resolution = self._resolve_fallback(parsed_info)
        if resolution:
            return resolution

        resolution = self._resolve_ai(parsed_info)
        if resolution:
            return resolution

        meta_data = self.parser.build_local_fallback(parsed_info.title, parsed_info.year)
        meta_data['scraper_source'] = 'LOCAL_FALLBACK'
        meta_data['scrape_layer'] = 'fallback'
        meta_data['scrape_strategy'] = 'local_placeholder'
        return MetadataResolution(
            meta_data=meta_data,
            resolved_tmdb_id=None,
            scrape_layer='fallback',
            scrape_strategy='local_placeholder',
            reason='local_placeholder',
        )

    def _resolve_structured(self, parsed_info: ParsedMediaInfo):
        title = parsed_info.title
        year = parsed_info.year
        media_type_hint = parsed_info.media_type_hint
        cache_key = (title, year, media_type_hint, 'structured')

        if parsed_info.parse_layer != 'strict':
            return None

        if cache_key in self.tmdb_cache:
            tmdb_id = self.tmdb_cache[cache_key]
        else:
            db_match = db.get_movie_by_title_year(title, year)
            if db_match:
                tmdb_id = db_match['tmdb_id']
            else:
                tmdb_id = tmdb_scraper.search_movie(title, year, strict=True, media_type_hint=media_type_hint)
            if tmdb_id:
                self.tmdb_cache[cache_key] = tmdb_id

        if not tmdb_id or tmdb_id.startswith('loc-'):
            return None

        meta_data = tmdb_scraper.get_movie_details(tmdb_id)
        if not meta_data:
            return None

        meta_data['scraper_source'] = 'TMDB_STRICT'
        meta_data['scrape_layer'] = 'structured'
        meta_data['scrape_strategy'] = parsed_info.parse_strategy
        return MetadataResolution(
            meta_data=meta_data,
            resolved_tmdb_id=tmdb_id,
            scrape_layer='structured',
            scrape_strategy=parsed_info.parse_strategy,
            reason='tmdb_match',
        )

    def _resolve_fallback(self, parsed_info: ParsedMediaInfo):
        title = parsed_info.title
        year = parsed_info.year
        media_type_hint = parsed_info.media_type_hint
        cache_key = (title, year, media_type_hint, 'fallback')

        if cache_key in self.tmdb_cache:
            tmdb_id = self.tmdb_cache[cache_key]
        else:
            db_match = db.get_movie_by_title_year(title, year)
            if db_match:
                tmdb_id = db_match['tmdb_id']
            else:
                time.sleep(0.1)
                tmdb_id = tmdb_scraper.search_movie(title, year, strict=False, media_type_hint=media_type_hint)
            if tmdb_id:
                self.tmdb_cache[cache_key] = tmdb_id

        if tmdb_id and not tmdb_id.startswith('loc-'):
            meta_data = tmdb_scraper.get_movie_details(tmdb_id)
            if meta_data:
                meta_data['scraper_source'] = 'TMDB_FALLBACK'
                meta_data['scrape_layer'] = 'fallback'
                meta_data['scrape_strategy'] = parsed_info.parse_strategy
                return MetadataResolution(
                    meta_data=meta_data,
                    resolved_tmdb_id=tmdb_id,
                    scrape_layer='fallback',
                    scrape_strategy=parsed_info.parse_strategy,
                    reason='tmdb_match',
                )

        return None

    def _resolve_ai(self, parsed_info: ParsedMediaInfo):
        return self.ai_scraper.resolve(parsed_info)

    def _resolve_nfo(self, parsed_info: ParsedMediaInfo):
        return self.nfo_resolver.resolve(parsed_info)
