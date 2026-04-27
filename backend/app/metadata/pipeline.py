from .parser import PathMetadataParser
from .scraper import MetadataScraper
from .types import EntityMetadataContext


class MetadataPipeline:
    def __init__(self):
        self.parser = PathMetadataParser()
        self.scraper = MetadataScraper(self.parser)

    def parse_path(self, file_path):
        return self.parser.parse(file_path)

    def optimize_entities(self, raw_entities):
        return self.parser.optimize_entities(raw_entities)

    def build_entity_context(self, key, files):
        title, year = key
        sample_meta = files[0].get('_meta', {}) if files else {}
        return EntityMetadataContext(
            title=title,
            year=year,
            media_type_hint=sample_meta.get('media_type_hint'),
            parse_layer=sample_meta.get('parse_layer', 'fallback'),
            parse_strategy=sample_meta.get('parse_strategy', 'unknown'),
            confidence=sample_meta.get('confidence', 'medium'),
            sample_path=files[0].get('path', '') if files else '',
            nfo_candidates=[
                candidate
                for item in files
                for candidate in item.get('_meta', {}).get('nfo_candidates', [])
            ],
            files=files,
        )

    def resolve_metadata(self, parsed_info):
        return self.scraper.resolve(parsed_info)

    def build_orphan_fallback(self, title):
        return self.parser.build_orphan_fallback(title)


metadata_pipeline = MetadataPipeline()
