import logging
import os
from collections import defaultdict

from backend.app.metadata import metadata_pipeline
from backend.app.providers.factory import provider_factory

logger = logging.getLogger(__name__)


class MovieMetadataRescrapeService:
    """针对单条影片的定点重刮服务。

    目标：
    - 不触发全量扫描
    - 只使用当前影片已入库资源
    - 按需读取同目录 sidecar NFO
    - 复用 metadata pipeline 的 strict/fallback/nfo/tmdb/ai 规则
    """

    def resolve_movie(self, movie, media_type_hint=None):
        resources = movie.resources.all()
        if not resources:
            raise ValueError("Movie has no resources")

        source, scoped_resources = self._select_primary_source_resources(resources)
        provider = provider_factory.get_provider(source) if source else None
        files = self._build_file_items(scoped_resources, provider)
        if not files:
            raise ValueError("No readable resources available for re-scrape")

        raw_entities = defaultdict(list)
        for item in files:
            meta = item['_meta']
            raw_entities[(meta['title'], meta['year'])].append(item)

        optimized_entities = metadata_pipeline.optimize_entities(raw_entities)
        key, resolved_files = self._pick_best_entity(optimized_entities, movie)
        entity_context = metadata_pipeline.build_entity_context(key, resolved_files)
        parsed_info = entity_context.to_parsed_media_info()

        if media_type_hint in ('movie', 'tv'):
            parsed_info.media_type_hint = media_type_hint

        if provider:
            parsed_info.extras['nfo_payloads'] = self._load_nfo_payloads(provider, entity_context)

        resolution = metadata_pipeline.resolve_metadata(parsed_info)
        return {
            "source": source,
            "provider": provider,
            "resources": scoped_resources,
            "entity_context": entity_context,
            "resolution": resolution,
            "resource_count": len(scoped_resources),
        }

    def apply_resource_traces(self, resources, entity_context, resolution):
        parsed_info = entity_context.to_parsed_media_info()
        for resource in resources:
            specs = dict(resource.tech_specs or {})
            specs['metadata_trace'] = {
                "parse_layer": entity_context.parse_layer,
                "parse_strategy": entity_context.parse_strategy,
                "confidence": entity_context.confidence,
                "media_type_hint": parsed_info.media_type_hint,
                "has_nfo_candidates": bool(entity_context.nfo_candidates),
                "scrape_layer": resolution.scrape_layer,
                "scrape_strategy": resolution.scrape_strategy,
                "scrape_reason": resolution.reason,
            }
            resource.tech_specs = specs

    def _select_primary_source_resources(self, resources):
        grouped = defaultdict(list)
        without_source = []

        for resource in resources:
            if resource.source_id and resource.source:
                grouped[resource.source_id].append(resource)
            else:
                without_source.append(resource)

        if grouped:
            source_id, scoped_resources = max(grouped.items(), key=lambda item: len(item[1]))
            return scoped_resources[0].source, sorted(scoped_resources, key=self._resource_sort_key)

        return None, sorted(without_source, key=self._resource_sort_key)

    def _resource_sort_key(self, resource):
        return (
            resource.season is None,
            resource.season if resource.season is not None else 0,
            resource.episode is None,
            resource.episode if resource.episode is not None else 0,
            resource.filename or resource.path or "",
        )

    def _build_file_items(self, resources, provider):
        directory_cache = {}
        files = []

        for resource in resources:
            path = resource.path or ''
            filename = resource.filename or os.path.basename(path)
            parsed = metadata_pipeline.parse_path(path)
            nfo_candidates = self._find_sidecar_nfo(provider, path, filename, directory_cache) if provider else []

            trace = {}
            if isinstance(resource.tech_specs, dict):
                trace = resource.tech_specs.get('metadata_trace') or {}

            files.append({
                "path": path,
                "name": filename,
                "_resource": resource,
                "_meta": {
                    "title": parsed.title,
                    "year": parsed.year,
                    "season": resource.season if resource.season is not None else parsed.season,
                    "episode": resource.episode if resource.episode is not None else parsed.episode,
                    "media_type_hint": trace.get('media_type_hint') or parsed.media_type_hint,
                    "parse_layer": trace.get('parse_layer') or parsed.parse_layer,
                    "parse_strategy": trace.get('parse_strategy') or parsed.parse_strategy,
                    "confidence": trace.get('confidence') or parsed.confidence,
                    "nfo_candidates": nfo_candidates,
                },
            })

        return files

    def _find_sidecar_nfo(self, provider, video_path, filename, directory_cache):
        if provider is None:
            return []

        directory = os.path.dirname(video_path).replace('\\', '/').strip('/')
        if directory not in directory_cache:
            try:
                directory_cache[directory] = provider.list_items(directory or '')
            except Exception as e:
                logger.warning("Rescrape list sidecar NFO failed dir=%s error=%s", directory or '/', e)
                directory_cache[directory] = []

        video_base = os.path.splitext(filename or '')[0].lower()
        candidates = []
        for item in directory_cache[directory]:
            name = item.get('name', '')
            if not name.lower().endswith('.nfo'):
                continue
            base = os.path.splitext(name)[0].lower()
            if base == video_base or base in {'movie', 'tvshow', 'index'}:
                candidates.append(item.get('path', ''))
        return candidates

    def _load_nfo_payloads(self, provider, entity_context):
        payloads = []
        seen = set()
        for path in entity_context.nfo_candidates:
            clean_path = (path or '').strip()
            if not clean_path or clean_path in seen:
                continue
            seen.add(clean_path)
            content = provider.read_text(clean_path)
            if not content:
                continue
            payloads.append({
                "path": clean_path,
                "content": content,
            })
        return payloads

    def _pick_best_entity(self, optimized_entities, movie):
        if not optimized_entities:
            raise ValueError("Unable to infer entity from current resources")

        def _score(item):
            (title, year), files = item
            score = len(files)
            if title == movie.title or title == movie.original_title:
                score += 10
            if year and movie.year and year == movie.year:
                score += 5
            return score

        return max(optimized_entities.items(), key=_score)


movie_metadata_rescrape_service = MovieMetadataRescrapeService()
