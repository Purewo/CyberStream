import logging
import re
import time
from urllib.parse import urljoin

import requests

from backend import config
from backend.app.services.metadata_providers.base import MetadataProviderBase
from backend.app.services.metadata_types import CandidateSearchResult, ProviderAttempt, ScrapeContext, ScrapeResult

logger = logging.getLogger(__name__)


class BangumiMetadataProvider(MetadataProviderBase):
    name = 'bangumi'
    display_name = 'Bangumi'
    authoritative = True
    supports_search = True
    ANIME_SUBJECT_TYPE = 2
    SUBJECT_URL_TEMPLATE = "https://bgm.tv/subject/{subject_id}"

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False

    def _api_base(self):
        return str(getattr(config, "BANGUMI_API_BASE", "https://api.bgm.tv")).rstrip("/")

    def _headers(self):
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": getattr(config, "BANGUMI_USER_AGENT", "pureworld/cyber-media/1.19.0"),
        }

    def _request(self, method, path, **kwargs):
        url = urljoin(f"{self._api_base()}/", path.lstrip("/"))
        timeout = float(getattr(config, "BANGUMI_TIMEOUT_SECONDS", 10))
        for attempt in range(2):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    timeout=timeout,
                    **kwargs,
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.warning("Bangumi request failed method=%s path=%s attempt=%s error=%s", method, path, attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.5)
        return None

    def _normalize_query(self, query):
        query = re.sub(r'\b(19|20)\d{2}\b', '', query or '').strip()
        return query or ""

    def _year_from_date(self, date_value):
        date_value = str(date_value or "")
        if len(date_value) >= 4 and date_value[:4].isdigit():
            return int(date_value[:4])
        return None

    def _image_url(self, subject):
        images = subject.get("images") if isinstance(subject, dict) else None
        if not isinstance(images, dict):
            return ""
        for key in ("large", "common", "medium", "small", "grid"):
            value = images.get(key)
            if value:
                return value
        return ""

    def _rating_score(self, subject):
        rating = subject.get("rating") if isinstance(subject, dict) else None
        if isinstance(rating, dict):
            return float(rating.get("score") or 0)
        try:
            return float(subject.get("score") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _collection_total(self, subject):
        collection = subject.get("collection") if isinstance(subject, dict) else None
        if isinstance(collection, dict):
            return int(collection.get("total") or 0)
        try:
            return int(subject.get("collection_total") or 0)
        except (TypeError, ValueError):
            return 0

    def _episode_count(self, subject):
        for key in ("eps", "total_episodes"):
            try:
                value = int(subject.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        return None

    def _subject_url(self, subject_id):
        return self.SUBJECT_URL_TEMPLATE.format(subject_id=subject_id)

    def _infer_media_type(self, subject, media_type_hint=None):
        if media_type_hint in {"movie", "tv"}:
            return media_type_hint

        platform = str(subject.get("platform") or "").strip().lower()
        title = f"{subject.get('name') or ''} {subject.get('name_cn') or ''}".lower()
        movie_markers = {"剧场版", "劇場版", "映画", "movie", "the movie"}
        if any(marker in platform or marker in title for marker in movie_markers):
            return "movie"

        eps = subject.get("eps") or subject.get("total_episodes")
        try:
            if int(eps or 0) == 1 and platform in {"剧场版", "movie"}:
                return "movie"
        except (TypeError, ValueError):
            pass
        return "tv"

    def _candidate_from_subject(self, subject, media_type_hint=None):
        subject_id = subject.get("id")
        if subject_id is None:
            return None

        bangumi_id = f"bangumi/{subject_id}"
        title = subject.get("name_cn") or subject.get("name") or ""
        original_title = subject.get("name") or title
        year = self._year_from_date(subject.get("date"))
        score = round(self._rating_score(subject), 1)
        collection_total = self._collection_total(subject)
        media_type = self._infer_media_type(subject, media_type_hint=media_type_hint)

        return {
            "provider": self.name,
            "provider_name": self.display_name,
            "source_key": self.name,
            "candidate_id": bangumi_id,
            "external_id": bangumi_id,
            "bangumi_id": bangumi_id,
            "tmdb_id": bangumi_id,
            "source_url": self._subject_url(subject_id),
            "subject_type": subject.get("type"),
            "episode_count": self._episode_count(subject),
            "media_type": media_type,
            "title": title,
            "original_title": original_title,
            "overview": subject.get("short_summary") or subject.get("summary") or "",
            "year": year,
            "poster_url": self._image_url(subject),
            "backdrop_url": "",
            "popularity": collection_total,
            "vote_average": score,
            "rating": score,
            "rank": subject.get("rank"),
        }

    def _search_subjects(self, query, limit=8):
        clean_query = self._normalize_query(query)
        if not clean_query:
            return []
        payload = {
            "keyword": clean_query,
            "sort": "match",
            "filter": {
                "type": [self.ANIME_SUBJECT_TYPE],
            },
        }
        data = self._request("POST", f"/v0/search/subjects?limit={max(limit, 0)}&offset=0", json=payload)
        if data is None:
            return None
        if isinstance(data, dict):
            items = data.get("data") or data.get("results") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        return [item for item in items if isinstance(item, dict)]

    def search_candidates(
        self,
        query: str,
        *,
        year: int | None = None,
        limit: int = 8,
        media_type_hint: str | None = None,
    ) -> CandidateSearchResult:
        direct_subject_id = self._subject_id_from_candidate(query)
        if direct_subject_id:
            subject = self._request("GET", f"/v0/subjects/{direct_subject_id}")
            if not isinstance(subject, dict):
                return CandidateSearchResult(warnings=[f"bangumi_direct_lookup_failed:{direct_subject_id}"])
            candidate = self._candidate_from_subject(subject, media_type_hint=media_type_hint)
            return CandidateSearchResult(items=[candidate] if candidate else [])

        subjects = self._search_subjects(query, limit=limit)
        if subjects is None:
            return CandidateSearchResult(warnings=["bangumi_search_failed"])
        candidates = []
        for subject in subjects:
            candidate = self._candidate_from_subject(subject, media_type_hint=media_type_hint)
            if not candidate:
                continue
            candidates.append(candidate)
        return CandidateSearchResult(items=candidates[:max(limit, 0)])

    def _subject_id_from_candidate(self, candidate_id):
        raw = str(candidate_id or "").strip()
        match = re.search(r'(?:bangumi|bgm)/(\d+)\b', raw, flags=re.IGNORECASE)
        if not match:
            match = re.search(r'/subject/(\d+)\b', raw, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        if raw.isdigit():
            return raw
        return None

    def _infobox_values(self, subject, keys):
        wanted = {key.strip().lower() for key in keys}
        values = []
        infobox = subject.get("infobox") if isinstance(subject, dict) else []
        if not isinstance(infobox, list):
            return values
        for item in infobox:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip().lower()
            if key not in wanted:
                continue
            value = item.get("value")
            if isinstance(value, str):
                values.append(value.strip())
            elif isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        text = entry.get("v") or entry.get("value")
                    else:
                        text = entry
                    text = str(text or "").strip()
                    if text:
                        values.append(text)
        return [value for value in values if value]

    def _metadata_from_subject(self, subject, media_type_hint=None):
        subject_id = subject.get("id")
        bangumi_id = f"bangumi/{subject_id}"
        title = subject.get("name_cn") or subject.get("name") or ""
        original_title = subject.get("name") or title
        year = self._year_from_date(subject.get("date"))
        score = round(self._rating_score(subject), 1)
        director_values = self._infobox_values(subject, {"导演", "监督", "監督"})
        country_values = self._infobox_values(subject, {"国家", "地区", "製作国家"})
        tags = subject.get("tags") if isinstance(subject.get("tags"), list) else []
        tag_names = [
            item.get("name")
            for item in tags[:5]
            if isinstance(item, dict) and item.get("name")
        ]
        category = ["动画"]
        for tag_name in tag_names:
            if tag_name not in category:
                category.append(tag_name)

        return {
            "tmdb_id": bangumi_id,
            "title": title,
            "original_title": original_title,
            "year": year,
            "rating": score,
            "description": subject.get("summary") or subject.get("short_summary") or "暂无简介",
            "cover": self._image_url(subject),
            "background_cover": "",
            "source_url": self._subject_url(subject_id),
            "category": category,
            "director": director_values[0] if director_values else "Unknown",
            "actors": [],
            "country": country_values[0] if country_values else "Unknown",
            "scraper_source": "BANGUMI",
            "media_type_hint": self._infer_media_type(subject, media_type_hint=media_type_hint),
            "season_metadata": [],
        }

    def get_details(self, candidate_id: str, media_type_hint: str | None = None) -> ScrapeResult | None:
        subject_id = self._subject_id_from_candidate(candidate_id)
        if not subject_id:
            return None
        subject = self._request("GET", f"/v0/subjects/{subject_id}")
        if not isinstance(subject, dict):
            return None
        metadata = self._metadata_from_subject(subject, media_type_hint=media_type_hint)
        return ScrapeResult(
            metadata=metadata,
            provider=self.name,
            confidence=0.9,
            matched_id=metadata["tmdb_id"],
            raw={
                "matched_from": "candidate_id",
                "content_type": metadata.get("media_type_hint"),
                "bangumi_subject_id": subject_id,
                "subject_url": self._subject_url(subject_id),
            },
        )

    def scrape(self, context: ScrapeContext, media_type_hint: str | None) -> ProviderAttempt:
        search_result = self.search_candidates(
            context.title,
            year=context.year,
            limit=3,
            media_type_hint=media_type_hint,
        )
        candidates = search_result.items
        if not candidates:
            return ProviderAttempt(warnings=search_result.warnings)

        candidate = candidates[0]
        result = self.get_details(candidate.get("candidate_id"), media_type_hint=media_type_hint)
        if not result:
            return ProviderAttempt(warnings=[*search_result.warnings, f"bangumi_details_failed:{candidate.get('candidate_id')}"])

        if context.year and result.metadata.get("year") and context.year == result.metadata.get("year"):
            result.confidence = 0.9
        elif context.year and result.metadata.get("year"):
            result.confidence = 0.75
        else:
            result.confidence = 0.8
        result.raw = {
            **(result.raw or {}),
            "title": context.title,
            "year": context.year,
            "matched_from": "bangumi_search",
        }
        return ProviderAttempt(result=result, warnings=search_result.warnings)
