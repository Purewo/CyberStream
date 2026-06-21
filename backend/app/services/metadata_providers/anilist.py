from __future__ import annotations

import html
import logging
import re
import time

import requests

from backend import config
from backend.app.services.metadata_providers.base import MetadataProviderBase
from backend.app.services.metadata_types import CandidateSearchResult, ProviderAttempt, ScrapeContext, ScrapeResult


logger = logging.getLogger(__name__)


MEDIA_FIELDS = """
id
idMal
title {
  romaji
  english
  native
  userPreferred
}
description(asHtml: false)
startDate {
  year
  month
  day
}
coverImage {
  extraLarge
  large
}
bannerImage
episodes
averageScore
popularity
genres
format
siteUrl
countryOfOrigin
"""


SEARCH_QUERY = f"""
query ($search: String, $perPage: Int) {{
  Page(page: 1, perPage: $perPage) {{
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {{
      {MEDIA_FIELDS}
    }}
  }}
}}
"""


DETAIL_QUERY = f"""
query ($id: Int) {{
  Media(id: $id, type: ANIME) {{
    {MEDIA_FIELDS}
  }}
}}
"""


class AniListMetadataProvider(MetadataProviderBase):
    name = "anilist"
    display_name = "AniList"
    authoritative = True
    supports_search = True

    SOURCE_ID_PREFIX = "anilist"

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False

    def describe(self):
        data = super().describe()
        data.update({
            "manual_only": False,
            "default_enabled": False,
            "default_enabled_reason": "AniList is available only when explicitly selected or configured in provider_order.",
        })
        return data

    def _api_url(self):
        return str(getattr(config, "ANILIST_API_URL", "https://graphql.anilist.co") or "").strip()

    def _timeout(self):
        return float(getattr(config, "ANILIST_TIMEOUT_SECONDS", 10))

    def _headers(self):
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": getattr(
                config,
                "ANILIST_USER_AGENT",
                "Purewo/CyberStream/1.22.0 metadata matcher",
            ),
        }

    def _request(self, query, variables):
        for attempt in range(2):
            try:
                response = self.session.post(
                    self._api_url(),
                    headers=self._headers(),
                    json={"query": query, "variables": variables},
                    timeout=self._timeout(),
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("errors"):
                    logger.warning("AniList GraphQL errors variables=%s errors=%s", variables, payload.get("errors"))
                    return None
                return payload if isinstance(payload, dict) else None
            except Exception as e:
                logger.warning("AniList request failed attempt=%s error=%s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.5)
        return None

    def _normalize_query(self, query):
        text = self._plain_text(query)
        text = re.sub(r"\b(19|20)\d{2}\b", "", text).strip()
        return text

    def _plain_text(self, value):
        if value is None:
            return ""
        text = html.unescape(str(value))
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _contains_cjk(self, value):
        return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))

    def _preferred_title(self, media, query_hint=None):
        title = media.get("title") if isinstance(media, dict) else {}
        if not isinstance(title, dict):
            title = {}
        native = self._plain_text(title.get("native"))
        english = self._plain_text(title.get("english"))
        romaji = self._plain_text(title.get("romaji"))
        user_preferred = self._plain_text(title.get("userPreferred"))

        if str(media.get("countryOfOrigin") or "").strip().upper() == "CN" and native:
            return native
        if self._contains_cjk(query_hint) and self._contains_cjk(native):
            return native
        return english or romaji or user_preferred or native

    def _original_title(self, media, fallback=""):
        title = media.get("title") if isinstance(media, dict) else {}
        if not isinstance(title, dict):
            title = {}
        return (
            self._plain_text(title.get("romaji"))
            or self._plain_text(title.get("native"))
            or fallback
        )

    def _date_string(self, media):
        start_date = media.get("startDate") if isinstance(media, dict) else None
        if not isinstance(start_date, dict):
            return None
        year = start_date.get("year")
        month = start_date.get("month")
        day = start_date.get("day")
        if not year:
            return None
        try:
            year = int(year)
            month = int(month or 1)
            day = int(day or 1)
        except (TypeError, ValueError):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _year(self, media):
        start_date = media.get("startDate") if isinstance(media, dict) else None
        if not isinstance(start_date, dict):
            return None
        try:
            year = int(start_date.get("year") or 0)
        except (TypeError, ValueError):
            return None
        return year if 1800 <= year <= 2100 else None

    def _rating(self, media):
        try:
            score = float(media.get("averageScore") or 0)
        except (TypeError, ValueError):
            return 0.0
        if score <= 0:
            return 0.0
        return round(score / 10, 1)

    def _image_url(self, media):
        cover = media.get("coverImage") if isinstance(media, dict) else None
        if not isinstance(cover, dict):
            return ""
        return self._plain_text(cover.get("extraLarge")) or self._plain_text(cover.get("large"))

    def _media_type(self, media, media_type_hint=None):
        if media_type_hint in {"movie", "tv"}:
            return media_type_hint
        media_format = str(media.get("format") or "").strip().upper()
        if media_format == "MOVIE":
            return "movie"
        return "tv"

    def _season_number_from_title(self, title):
        text = self._plain_text(title)
        match = re.search(r"\b(?:season|s)\s*(\d{1,2})\b", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\s+season\b", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"\u7b2c\s*(\d{1,2})\s*(?:\u5b63|\u671f)", text)
        if match:
            return int(match.group(1))
        return 1

    def _candidate_id(self, anilist_id):
        return f"{self.SOURCE_ID_PREFIX}/{anilist_id}"

    def _parse_candidate_id(self, candidate_id):
        raw = str(candidate_id or "").strip()
        if not raw:
            return None
        match = re.search(r"(?:anilist|ani)/(\d+)\b", raw, flags=re.IGNORECASE)
        if not match:
            match = re.search(r"anilist\.co/anime/(\d+)\b", raw, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        if raw.isdigit():
            return int(raw)
        return None

    def _candidate_from_media(self, media, media_type_hint=None, query_hint=None):
        if not isinstance(media, dict) or media.get("id") is None:
            return None
        title = self._preferred_title(media, query_hint=query_hint)
        if not title:
            return None
        original_title = self._original_title(media, fallback=title)
        media_type = self._media_type(media, media_type_hint=media_type_hint)
        anilist_id = media.get("id")
        score = self._rating(media)

        return {
            "provider": self.name,
            "provider_name": self.display_name,
            "source_key": self.name,
            "candidate_id": self._candidate_id(anilist_id),
            "external_id": self._candidate_id(anilist_id),
            "tmdb_id": self._candidate_id(anilist_id),
            "anilist_id": self._candidate_id(anilist_id),
            "mal_id": media.get("idMal"),
            "source_url": self._plain_text(media.get("siteUrl")) or f"https://anilist.co/anime/{anilist_id}",
            "media_type": media_type,
            "episode_count": media.get("episodes"),
            "title": title,
            "original_title": original_title,
            "overview": self._plain_text(media.get("description")),
            "year": self._year(media),
            "poster_url": self._image_url(media),
            "backdrop_url": self._plain_text(media.get("bannerImage")),
            "popularity": media.get("popularity") or 0,
            "vote_average": score,
            "rating": score,
            "category": self._categories(media),
            "format": media.get("format"),
        }

    def _categories(self, media):
        categories = ["动画"]
        for genre in media.get("genres") or []:
            text = self._plain_text(genre)
            if text and text not in categories:
                categories.append(text)
        return categories[:8]

    def _search_media(self, query, limit):
        clean_query = self._normalize_query(query)
        if not clean_query:
            return []
        payload = self._request(SEARCH_QUERY, {"search": clean_query, "perPage": max(limit, 1)})
        if not isinstance(payload, dict):
            return None
        return (
            payload.get("data", {})
            .get("Page", {})
            .get("media", [])
        )

    def search_candidates(
        self,
        query: str,
        *,
        year: int | None = None,
        limit: int = 8,
        media_type_hint: str | None = None,
    ) -> CandidateSearchResult:
        anilist_id = self._parse_candidate_id(query)
        if anilist_id:
            result = self.get_details(self._candidate_id(anilist_id), media_type_hint=media_type_hint)
            if not result:
                return CandidateSearchResult(warnings=[f"anilist_direct_lookup_failed:{anilist_id}"])
            return CandidateSearchResult(items=[self._candidate_from_metadata(result.metadata, anilist_id)])

        media_items = self._search_media(query, limit=limit)
        if media_items is None:
            return CandidateSearchResult(warnings=["anilist_search_failed"])

        candidates = []
        for media in media_items:
            candidate = self._candidate_from_media(media, media_type_hint=media_type_hint, query_hint=query)
            if not candidate:
                continue
            candidates.append(candidate)
        return CandidateSearchResult(items=candidates[:max(limit, 0)])

    def _candidate_from_metadata(self, metadata, anilist_id):
        return {
            "provider": self.name,
            "provider_name": self.display_name,
            "source_key": self.name,
            "candidate_id": self._candidate_id(anilist_id),
            "external_id": self._candidate_id(anilist_id),
            "tmdb_id": self._candidate_id(anilist_id),
            "anilist_id": self._candidate_id(anilist_id),
            "mal_id": metadata.get("mal_id"),
            "source_url": metadata.get("source_url") or f"https://anilist.co/anime/{anilist_id}",
            "media_type": metadata.get("media_type_hint") or "tv",
            "episode_count": self._first_season_episode_count(metadata.get("season_metadata")),
            "title": metadata.get("title") or "",
            "original_title": metadata.get("original_title") or metadata.get("title") or "",
            "overview": metadata.get("description") or "",
            "year": metadata.get("year"),
            "poster_url": metadata.get("cover") or "",
            "backdrop_url": metadata.get("background_cover") or "",
            "vote_average": metadata.get("rating") or 0,
            "rating": metadata.get("rating") or 0,
            "category": metadata.get("category") or [],
        }

    def _first_season_episode_count(self, season_items):
        if not isinstance(season_items, list) or not season_items:
            return None
        return season_items[0].get("episode_count")

    def _metadata_from_media(self, media, media_type_hint=None, query_hint=None):
        candidate = self._candidate_from_media(media, media_type_hint=media_type_hint, query_hint=query_hint)
        if not candidate:
            return None

        media_type = candidate["media_type"]
        air_date = self._date_string(media)
        season_metadata = []
        if media_type == "tv":
            season_metadata.append({
                "season": self._season_number_from_title(candidate["title"] or candidate["original_title"]),
                "title": candidate["title"],
                "overview": candidate["overview"],
                "air_date": air_date,
                "poster": candidate["poster_url"],
                "episode_count": candidate["episode_count"],
            })

        return {
            "tmdb_id": candidate["candidate_id"],
            "title": candidate["title"],
            "original_title": candidate["original_title"],
            "year": candidate["year"],
            "rating": candidate["rating"],
            "description": candidate["overview"],
            "cover": candidate["poster_url"],
            "background_cover": candidate["backdrop_url"],
            "source_url": candidate["source_url"],
            "category": candidate["category"],
            "director": "",
            "actors": [],
            "country": self._plain_text(media.get("countryOfOrigin")),
            "scraper_source": "ANILIST",
            "media_type_hint": media_type,
            "mal_id": candidate.get("mal_id"),
            "season_metadata": season_metadata,
        }

    def get_details(self, candidate_id: str, media_type_hint: str | None = None) -> ScrapeResult | None:
        anilist_id = self._parse_candidate_id(candidate_id)
        if not anilist_id:
            return None

        payload = self._request(DETAIL_QUERY, {"id": anilist_id})
        media = payload.get("data", {}).get("Media") if isinstance(payload, dict) else None
        metadata = self._metadata_from_media(media, media_type_hint=media_type_hint)
        if not metadata:
            return None

        return ScrapeResult(
            metadata=metadata,
            provider=self.name,
            confidence=0.88,
            matched_id=metadata["tmdb_id"],
            raw={
                "matched_from": "candidate_id",
                "anilist_id": anilist_id,
                "mal_id": metadata.get("mal_id"),
                "source_url": metadata.get("source_url"),
                "content_type": metadata.get("media_type_hint"),
            },
        )

    def scrape(self, context: ScrapeContext, media_type_hint: str | None) -> ProviderAttempt:
        result = self.search_candidates(
            context.title,
            year=context.year,
            limit=5,
            media_type_hint=media_type_hint,
        )
        if result.warnings:
            return ProviderAttempt(warnings=result.warnings)
        if not result.items:
            return ProviderAttempt(warnings=["anilist_no_match"])

        candidates = result.items
        if context.year:
            exact_year = [item for item in candidates if item.get("year") == context.year]
            if exact_year:
                candidates = exact_year

        candidate_id = candidates[0].get("candidate_id")
        details = self.get_details(candidate_id, media_type_hint=media_type_hint)
        if not details:
            return ProviderAttempt(warnings=[f"anilist_detail_failed:{candidate_id}"])
        return ProviderAttempt(result=details)
