import hashlib
import re
import xml.etree.ElementTree as ET

from backend.app.services.metadata_providers.base import MetadataProviderBase
from backend.app.services.metadata_types import ProviderAttempt, ScrapeContext, ScrapeResult
from backend.app.utils.genres import normalize_genres


class NfoMetadataProvider(MetadataProviderBase):
    name = 'nfo'

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

    def _build_tmdb_combined_id(self, raw_tmdb_id, media_type_hint, default_media_type='movie'):
        raw_tmdb_id = str(raw_tmdb_id or '').strip()
        if not raw_tmdb_id:
            return None
        if '/' in raw_tmdb_id:
            return raw_tmdb_id

        media_type = media_type_hint or default_media_type
        if media_type not in {'movie', 'tv'}:
            media_type = default_media_type
        return f"{media_type}/{raw_tmdb_id}"

    def _safe_int(self, value, default=None):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_date_year(self, value, default=None):
        value = (value or '').strip()
        if len(value) >= 4:
            return self._safe_int(value[:4], default)
        return default

    def _first_text(self, root, *tags):
        if root is None:
            return None
        for tag in tags:
            node = root.find(tag)
            if node is not None and node.text:
                text = node.text.strip()
                if text:
                    return text
        return None

    def _multi_text(self, root, tag):
        values = []
        if root is None:
            return values
        for node in root.findall(tag):
            if node is not None and node.text:
                text = node.text.strip()
                if text and text not in values:
                    values.append(text)
        return values

    def _split_text_values(self, value):
        values = []
        if not value:
            return values
        for part in re.split(r'[/,|，、]', value):
            part = part.strip()
            if part and part not in values:
                values.append(part)
        return values

    def _extract_nfo_candidates(self, context):
        if not context.files:
            return []

        candidates = []
        seen_paths = set()
        for file_item in context.files:
            for candidate in file_item.get('_nfo_candidates', []):
                candidate_path = candidate.get('path')
                if candidate_path and candidate_path not in seen_paths:
                    candidates.append(candidate)
                    seen_paths.add(candidate_path)
        return candidates

    def _resolve_nfo_media_type(self, root_tag, media_type_hint):
        root_tag = (root_tag or '').strip().lower()
        if root_tag == 'movie':
            return 'movie'
        if root_tag in {'tvshow', 'episodedetails'}:
            return 'tv'
        return media_type_hint

    def _find_series_nfo_info(self, context):
        if not context.provider:
            return None
        candidates = [
            candidate for candidate in self._extract_nfo_candidates(context)
            if candidate.get('kind') == 'tvshow'
        ]
        if not candidates:
            return None

        for candidate in candidates:
            candidate_path = candidate.get('path')
            if not candidate_path:
                continue
            try:
                content = context.provider.read_text(candidate_path)
                if not content:
                    continue
                root = ET.fromstring(content)
                if root.tag.lower() != 'tvshow':
                    continue
                return {
                    "root": root,
                    "path": candidate_path,
                }
            except Exception:
                continue
        return None

    def _build_nfo_unique_id(self, root, resolved_media_type, title, year):
        return (
            self._build_tmdb_combined_id(self._first_text(root, 'tmdbid'), resolved_media_type, default_media_type='movie')
            or self._build_tmdb_combined_id(
                next(
                    (
                        node.text.strip()
                        for node in root.findall('uniqueid')
                        if node.text and (node.get('type') or '').strip().lower() == 'tmdb'
                    ),
                    None,
                ),
                resolved_media_type,
                default_media_type='movie',
            )
            or self._generate_stable_id(title, year or 2077, resolved_media_type)
        )

    def _extract_nfo_actors(self, *roots):
        actors = []
        for root in roots:
            if root is None:
                continue
            for actor_node in root.findall('actor'):
                name_node = actor_node.find('name')
                if name_node is not None and name_node.text:
                    actor_name = name_node.text.strip()
                    if actor_name and actor_name not in actors:
                        actors.append(actor_name)
        return actors

    def _extract_nfo_genres(self, *roots):
        genres = []
        for root in roots:
            if root is None:
                continue
            for genre in self._multi_text(root, 'genre'):
                for item in self._split_text_values(genre):
                    if item not in genres:
                        genres.append(item)
        return genres

    def _extract_nfo_image(self, root, *tags):
        image = self._first_text(root, *tags)
        if image and image.startswith(('http://', 'https://')):
            return image
        return ""

    def _build_episode_nfo_metadata(self, root, context, candidate_path):
        series_info = self._find_series_nfo_info(context)
        series_root = series_info['root'] if series_info else None

        show_title = (
            self._first_text(root, 'showtitle')
            or self._first_text(series_root, 'title')
            or context.title
        )
        episode_title = self._first_text(root, 'title')
        original_title = (
            self._first_text(series_root, 'originaltitle')
            or self._first_text(root, 'originaltitle')
            or show_title
        )
        year = (
            self._safe_int(self._first_text(series_root, 'year'))
            or self._safe_date_year(self._first_text(series_root, 'premiered'))
            or self._safe_date_year(self._first_text(root, 'aired'))
            or context.year
            or 2077
        )
        matched_id = self._build_nfo_unique_id(series_root or root, 'tv', show_title, year)
        season = self._safe_int(self._first_text(root, 'season'))
        episode = self._safe_int(self._first_text(root, 'episode'))
        genres = self._extract_nfo_genres(root, series_root)
        actors = self._extract_nfo_actors(root, series_root)

        metadata = {
            "tmdb_id": matched_id,
            "title": show_title,
            "original_title": original_title,
            "year": year,
            "rating": self._safe_float(
                self._first_text(series_root, 'rating') or self._first_text(root, 'rating'),
                0.0,
            ),
            "description": (
                self._first_text(series_root, 'plot')
                or self._first_text(root, 'plot')
                or 'Episode NFO metadata'
            ),
            "cover": self._extract_nfo_image(series_root or root, 'thumb'),
            "background_cover": self._extract_nfo_image(series_root or root, 'fanart/thumb', 'fanart'),
            "category": normalize_genres(genres) or self._local_categories('tv'),
            "director": self._first_text(root, 'director') or self._first_text(series_root, 'director') or "Unknown",
            "actors": actors,
            "country": self._first_text(series_root, 'country') or self._first_text(root, 'country') or "Unknown",
            "scraper_source": "NFO",
        }
        return metadata, 'tv', matched_id, {
            "root_tag": root.tag.lower(),
            "path": candidate_path,
            "series_nfo_path": series_info['path'] if series_info else None,
            "episode": {
                "title": episode_title,
                "season": season,
                "episode": episode,
                "aired": self._first_text(root, 'aired'),
            },
        }

    def _build_nfo_metadata(self, root, context, candidate_path, media_type_hint):
        root_tag = root.tag.lower()
        resolved_media_type = self._resolve_nfo_media_type(root_tag, media_type_hint)

        if root_tag == 'episodedetails':
            return self._build_episode_nfo_metadata(root, context, candidate_path)

        title = self._first_text(root, 'title') or context.title
        original_title = self._first_text(root, 'originaltitle') or title
        year = self._safe_int(self._first_text(root, 'year'))
        if year is None:
            year = self._safe_date_year(self._first_text(root, 'premiered'), context.year or 2077)

        matched_id = self._build_nfo_unique_id(root, resolved_media_type, title, year)
        genres = self._extract_nfo_genres(root)
        actors = self._extract_nfo_actors(root)

        metadata = {
            "tmdb_id": matched_id,
            "title": title,
            "original_title": original_title,
            "year": year or context.year or 2077,
            "rating": self._safe_float(self._first_text(root, 'rating'), 0.0),
            "description": self._first_text(root, 'plot') or 'NFO metadata',
            "cover": self._extract_nfo_image(root, 'thumb'),
            "background_cover": self._extract_nfo_image(root, 'fanart/thumb', 'fanart'),
            "category": normalize_genres(genres) or self._local_categories(resolved_media_type),
            "director": self._first_text(root, 'director') or "Unknown",
            "actors": actors,
            "country": self._first_text(root, 'country') or "Unknown",
            "scraper_source": "NFO",
        }
        return metadata, resolved_media_type, matched_id, {
            "root_tag": root_tag,
            "path": candidate_path,
        }

    def scrape(self, context: ScrapeContext, media_type_hint: str | None) -> ProviderAttempt:
        if not context.provider:
            return ProviderAttempt()

        for candidate in self._extract_nfo_candidates(context):
            candidate_path = candidate.get('path')
            if not candidate_path:
                continue
            try:
                content = context.provider.read_text(candidate_path)
                if not content:
                    continue
                root = ET.fromstring(content)
                metadata, resolved_media_type, matched_id, raw_info = self._build_nfo_metadata(
                    root,
                    context,
                    candidate_path,
                    media_type_hint,
                )
                confidence = 0.95 if matched_id and not str(matched_id).startswith('loc-') else 0.8
                return ProviderAttempt(
                    result=ScrapeResult(
                        metadata=metadata,
                        provider='nfo',
                        confidence=confidence,
                        matched_id=matched_id,
                        raw={
                            "title": context.title,
                            "year": context.year,
                            "content_type": resolved_media_type,
                            "matched_from": "nfo",
                            "path": candidate_path,
                            "root_tag": raw_info['root_tag'],
                            "series_nfo_path": raw_info.get('series_nfo_path'),
                            "episode": raw_info.get('episode'),
                        },
                    )
                )
            except Exception:
                continue

        return ProviderAttempt()
