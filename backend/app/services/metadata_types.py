from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScrapeContext:
    title: str
    year: int | None
    source_id: int
    provider: Any | None = None
    scrape_enabled: bool = True
    content_type: str | None = None
    root_path: str | None = None
    library_id: int | None = None
    library_source_id: int | None = None
    scraper_policy: dict[str, Any] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ScrapeResult:
    metadata: dict[str, Any]
    provider: str
    confidence: float
    matched_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None


@dataclass
class ProviderAttempt:
    result: ScrapeResult | None = None
    warnings: list[str] = field(default_factory=list)
