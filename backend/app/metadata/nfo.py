import logging
import re
from xml.etree import ElementTree

from backend.app.services.tmdb import scraper as tmdb_scraper
from .types import MetadataResolution, ParsedMediaInfo

logger = logging.getLogger(__name__)


class NFOMetadataResolver:
    """NFO 解析预处理层。

    当前阶段只做轻量解析和留痕：
    - 识别同组是否存在 NFO
    - 尝试从 NFO 文本中提取 tmdb/tvdb/imdb 等外部 ID
    - 解析基础标题/年份/类型提示

    这一层先不直接读远端文件内容，只有在 scanner 已经把 NFO 文本塞进 extras 时才消费。
    后续接 provider 文件读取能力时，只需要扩这里。
    """

    def resolve(self, parsed_info: ParsedMediaInfo):
        nfo_payloads = parsed_info.extras.get('nfo_payloads') or []
        nfo_candidates = parsed_info.extras.get('nfo_candidates') or []
        if nfo_candidates and not nfo_payloads:
            logger.info(
                "Metadata NFO layer deferred title=%r year=%s candidates=%s reason=content_not_loaded",
                parsed_info.title,
                parsed_info.year,
                len(nfo_candidates),
            )
        if not nfo_payloads:
            return None

        for payload in nfo_payloads:
            meta_data = self._parse_nfo_payload(payload)
            if not meta_data:
                continue

            tmdb_id = meta_data.get('tmdb_id')
            if not self._is_tmdb_id(tmdb_id):
                external_tmdb_id = tmdb_scraper.find_by_external_id(
                    tmdb_id,
                    media_type_hint=meta_data.get('media_type_hint') or parsed_info.media_type_hint,
                )
                if external_tmdb_id:
                    tmdb_id = external_tmdb_id
                    meta_data['tmdb_id'] = external_tmdb_id
            if self._is_tmdb_id(tmdb_id):
                tmdb_meta = tmdb_scraper.get_movie_details(tmdb_id)
                if tmdb_meta:
                    merged_meta = self._merge_tmdb_with_nfo(tmdb_meta, meta_data)
                    merged_meta['scraper_source'] = 'NFO_TMDB'
                    merged_meta['scrape_layer'] = 'structured'
                    merged_meta['scrape_strategy'] = 'nfo_tmdb_id'
                    return MetadataResolution(
                        meta_data=merged_meta,
                        resolved_tmdb_id=tmdb_id,
                        scrape_layer='structured',
                        scrape_strategy='nfo_tmdb_id',
                        reason='nfo_tmdb_match',
                    )

            meta_data.setdefault('scraper_source', 'NFO_LOCAL')
            meta_data['scrape_layer'] = 'structured'
            meta_data['scrape_strategy'] = 'nfo_sidecar'
            return MetadataResolution(
                meta_data=meta_data,
                resolved_tmdb_id=tmdb_id,
                scrape_layer='structured',
                scrape_strategy='nfo_sidecar',
                reason='nfo_match',
            )

        logger.info(
            "Metadata NFO layer skipped title=%r year=%s reason=no_structured_nfo_match",
            parsed_info.title,
            parsed_info.year,
        )
        return None

    def _parse_nfo_payload(self, payload):
        content = (payload or {}).get('content')
        if not content:
            return None

        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            logger.warning("Metadata NFO parse failed path=%s", (payload or {}).get('path'))
            return None

        node_name = (root.tag or '').lower()
        media_type_hint = 'tv' if node_name in {'tvshow', 'episodedetails'} else 'movie'
        tmdb_id = self._extract_tmdb_id(root, media_type_hint)
        title = self._find_text(root, ['title', 'name']) or self._find_text(root, ['originaltitle'])
        original_title = self._find_text(root, ['originaltitle']) or title
        year = self._parse_year(self._find_text(root, ['year', 'premiered', 'aired']))
        plot = self._find_text(root, ['plot', 'outline'])
        director = self._find_text(root, ['director']) or "Unknown"
        country = self._find_text(root, ['country']) or "Unknown"

        categories = []
        for genre in root.findall('genre'):
            if genre.text and genre.text.strip():
                categories.append(genre.text.strip())

        actors = []
        for actor in root.findall('actor'):
            name = actor.findtext('name')
            if name and name.strip():
                actors.append(name.strip())

        if not tmdb_id and not title:
            return None

        safe_title = title or original_title or 'Unknown'
        fallback_tmdb_id = self._build_fallback_external_id(root, media_type_hint)
        return {
            "tmdb_id": tmdb_id or fallback_tmdb_id,
            "title": safe_title,
            "original_title": original_title or safe_title,
            "year": year or 2077,
            "rating": 0,
            "description": plot or "Imported from NFO",
            "cover": "",
            "background_cover": "",
            "category": categories or ["Local"],
            "director": director,
            "actors": actors,
            "country": country,
            "media_type_hint": media_type_hint,
        }

    def _find_text(self, root, names):
        for name in names:
            text = root.findtext(name)
            if text and text.strip():
                return text.strip()
        return None

    def _parse_year(self, value):
        if not value:
            return None
        match = re.search(r'(?:19|20)\d{2}', value)
        return int(match.group(0)) if match else None

    def _extract_tmdb_id(self, root, media_type_hint):
        known_fields = ['tmdbid', 'tmdb_id', 'id']
        for field in known_fields:
            value = self._find_text(root, [field])
            if not value:
                continue
            normalized = value.strip()
            if field == 'id' and not normalized.isdigit():
                continue
            if normalized.isdigit():
                return f"{media_type_hint}/{normalized}"
            if normalized.startswith('movie/') or normalized.startswith('tv/'):
                return normalized

        unique_id = self._extract_unique_id(root, 'tmdb')
        if unique_id and unique_id.isdigit():
            return f"{media_type_hint}/{unique_id}"
        return None

    def _build_fallback_external_id(self, root, media_type_hint):
        for field_name, prefix in [('imdbid', 'imdb'), ('tvdbid', 'tvdb')]:
            value = self._find_text(root, [field_name])
            if value:
                return f"{prefix}/{value.strip()}"

        for unique_type, prefix in [('imdb', 'imdb'), ('tvdb', 'tvdb')]:
            unique_id = self._extract_unique_id(root, unique_type)
            if unique_id:
                return f"{prefix}/{unique_id}"
        return f"nfo/{media_type_hint}/{abs(hash(ElementTree.tostring(root, encoding='unicode')))}"

    def _extract_unique_id(self, root, target_type):
        for node in root.findall('uniqueid'):
            node_type = (node.attrib.get('type') or '').strip().lower()
            if node_type != target_type:
                continue
            value = (node.text or '').strip()
            if value:
                return value
        return None

    def _is_tmdb_id(self, tmdb_id):
        return isinstance(tmdb_id, str) and (tmdb_id.startswith('movie/') or tmdb_id.startswith('tv/'))

    def _merge_tmdb_with_nfo(self, tmdb_meta, nfo_meta):
        merged = dict(tmdb_meta or {})
        merged.setdefault('media_type_hint', nfo_meta.get('media_type_hint'))

        preferred_fields = (
            'title',
            'original_title',
            'year',
            'description',
            'category',
            'director',
            'actors',
            'country',
        )
        for field in preferred_fields:
            nfo_value = nfo_meta.get(field)
            current_value = merged.get(field)
            if current_value in (None, '', [], 'Unknown', '暂无简介') and nfo_value not in (None, '', []):
                merged[field] = nfo_value

        return merged
