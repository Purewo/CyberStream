from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedMediaInfo:
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    media_type_hint: str | None = None
    parse_layer: str = 'fallback'
    parse_strategy: str = 'unknown'
    confidence: str = 'medium'
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "title": self.title,
            "year": self.year,
            "season": self.season,
            "episode": self.episode,
            "media_type_hint": self.media_type_hint,
            "parse_layer": self.parse_layer,
            "parse_strategy": self.parse_strategy,
            "confidence": self.confidence,
            **self.extras,
        }


@dataclass
class MetadataResolution:
    meta_data: dict[str, Any]
    resolved_tmdb_id: str | None = None
    scrape_layer: str = 'fallback'
    scrape_strategy: str = 'local_only'
    reason: str = 'unresolved'


@dataclass
class EntityMetadataContext:
    title: str
    year: int | None = None
    media_type_hint: str | None = None
    parse_layer: str = 'fallback'
    parse_strategy: str = 'unknown'
    confidence: str = 'medium'
    sample_path: str = ''
    nfo_candidates: list[str] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)

    def to_parsed_media_info(self) -> ParsedMediaInfo:
        sample_meta = self.files[0].get('_meta', {}) if self.files else {}
        return ParsedMediaInfo(
            title=self.title,
            year=self.year,
            season=sample_meta.get('season'),
            episode=sample_meta.get('episode'),
            media_type_hint=self.media_type_hint or sample_meta.get('media_type_hint'),
            parse_layer=self.parse_layer,
            parse_strategy=self.parse_strategy,
            confidence=self.confidence,
            extras={
                "sample_path": self.sample_path,
                "file_count": len(self.files),
                "nfo_candidates": list(self.nfo_candidates),
            },
        )
