from __future__ import annotations

import html
import json
import logging
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from backend import config
from backend.app.services.metadata_providers.base import MetadataProviderBase
from backend.app.services.metadata_types import CandidateSearchResult, ProviderAttempt, ScrapeResult

logger = logging.getLogger(__name__)


class _HeadMetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.meta_lists = {}
        self.ld_json = []
        self._in_ld_json = False
        self._ld_json_chunks = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        normalized_attrs = {
            str(key or "").lower(): value
            for key, value in attrs
        }

        if tag == "meta":
            key = (
                normalized_attrs.get("property")
                or normalized_attrs.get("name")
                or normalized_attrs.get("itemprop")
            )
            content = normalized_attrs.get("content")
            if key and content:
                key = str(key).strip()
                text = html.unescape(str(content)).strip()
                self.meta.setdefault(key, text)
                self.meta_lists.setdefault(key, []).append(text)
            return

        if tag == "script":
            script_type = str(normalized_attrs.get("type") or "").strip().lower()
            if script_type == "application/ld+json":
                self._in_ld_json = True
                self._ld_json_chunks = []

    def handle_data(self, data):
        if self._in_ld_json:
            self._ld_json_chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._in_ld_json:
            raw = "".join(self._ld_json_chunks).strip()
            if raw:
                self.ld_json.append(raw)
            self._in_ld_json = False
            self._ld_json_chunks = []


class TencentVideoMetadataProvider(MetadataProviderBase):
    name = "tencent_video"
    display_name = "Tencent Video"
    authoritative = True
    supports_search = True
    manual_only = True

    SEARCH_URL = "https://pbaccess.video.qq.com/trpc.videosearch.mobile_search.MultiTerminalSearch/MbSearch?vversion_platform=2"
    COVER_URL_TEMPLATE = "https://v.qq.com/x/cover/{cid}.html"
    SOURCE_ID_PREFIX = "tencent_video"
    APP_ID = "10718"
    DATA_VERSION = "26022601"
    FRONT_VERSION = "26041606"

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False

    def describe(self):
        data = super().describe()
        data.update({
            "supports_scrape": False,
            "manual_only": True,
            "manual_only_reason": "Tencent Video is available only for explicit manual metadata matching.",
        })
        return data

    def _timeout(self):
        return float(getattr(config, "TENCENT_VIDEO_TIMEOUT_SECONDS", 8))

    def _user_agent(self):
        return getattr(
            config,
            "TENCENT_VIDEO_USER_AGENT",
            "Purewo/CyberStream/1.21.0 metadata manual matcher",
        )

    def _headers(self):
        return {
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://v.qq.com",
            "Referer": "https://v.qq.com/",
            "User-Agent": self._user_agent(),
        }

    def _request_json(self, url, payload):
        for attempt in range(2):
            try:
                response = self.session.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self._timeout(),
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.warning("Tencent Video JSON request failed url=%s attempt=%s error=%s", url, attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.2)
        return None

    def _request_text(self, url):
        headers = self._headers()
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        headers.pop("Content-Type", None)
        for attempt in range(2):
            try:
                response = self.session.get(url, headers=headers, timeout=self._timeout())
                response.raise_for_status()
                return response.text
            except Exception as e:
                logger.warning("Tencent Video HTML request failed url=%s attempt=%s error=%s", url, attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.2)
        return None

    def _plain_text(self, value):
        if value is None:
            return ""
        text = html.unescape(str(value))
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _normalize_query(self, query):
        query = self._plain_text(query)
        query = re.sub(r"\b(19|20)\d{2}\b", "", query).strip()
        return query

    def _normalize_title(self, value):
        text = self._plain_text(value)
        if not text:
            return ""
        text = re.split(r"[_|]", text, maxsplit=1)[0].strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _year_from_date(self, value):
        text = str(value or "").strip()
        if len(text) >= 4 and text[:4].isdigit():
            year = int(text[:4])
            if 1800 <= year <= 2100:
                return year
        return None

    def _first_date(self, *values):
        for value in values:
            text = str(value or "").strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}", text):
                return text[:10]
        return None

    def _candidate_id(self, cid):
        return f"{self.SOURCE_ID_PREFIX}/{cid}"

    def _source_url(self, cid):
        return self.COVER_URL_TEMPLATE.format(cid=cid)

    def _parse_candidate_id(self, candidate_id):
        raw = str(candidate_id or "").strip()
        if not raw:
            return None, None

        prefixed = re.search(r"(?:tencent_video|qq)/([a-z0-9]+)(?:/([a-z0-9]+))?\b", raw, flags=re.IGNORECASE)
        if prefixed:
            return prefixed.group(1), prefixed.group(2)

        url_match = re.search(r"/x/cover/([a-z0-9]+)(?:/([a-z0-9]+))?\.html", raw, flags=re.IGNORECASE)
        if url_match:
            return url_match.group(1), url_match.group(2)

        parsed = urlparse(raw)
        if parsed.query:
            query_cid = re.search(r"(?:^|&)cid=([a-z0-9]+)", parsed.query, flags=re.IGNORECASE)
            query_vid = re.search(r"(?:^|&)vid=([a-z0-9]+)", parsed.query, flags=re.IGNORECASE)
            if query_cid:
                return query_cid.group(1), query_vid.group(1) if query_vid else None

        if re.match(r"^[a-z0-9]{10,}$", raw, flags=re.IGNORECASE):
            return raw, None
        return None, None

    def _season_number_from_title(self, title):
        text = self._plain_text(title)
        match = re.search(r"\u7b2c\s*(\d{1,2})\s*\u5b63", text)
        if match:
            return int(match.group(1))

        match = re.search(r"\bS(\d{1,2})\b", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

        numerals = {
            "\u4e00": 1, "\u4e8c": 2, "\u4e09": 3, "\u56db": 4, "\u4e94": 5,
            "\u516d": 6, "\u4e03": 7, "\u516b": 8, "\u4e5d": 9, "\u5341": 10,
        }
        match = re.search(r"\u7b2c\s*([\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]{1,3})\s*\u5b63", text)
        if not match:
            return None
        raw = match.group(1)
        if raw == "\u5341":
            return 10
        if raw.startswith("\u5341"):
            return 10 + numerals.get(raw[-1], 0)
        if raw.endswith("\u5341"):
            return numerals.get(raw[0], 1) * 10
        if "\u5341" in raw:
            left, right = raw.split("\u5341", 1)
            return numerals.get(left, 1) * 10 + numerals.get(right, 0)
        return numerals.get(raw)

    def _rating_from_tags(self, tags):
        for tag in tags or []:
            text = self._plain_text(tag.get("text") if isinstance(tag, dict) else tag)
            match = re.search(r"\u8bc4\u5206\s*([0-9]+(?:\.[0-9]+)?)", text)
            if not match:
                continue
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _episode_count_from_img_tag(self, raw_img_tag):
        values = []
        if isinstance(raw_img_tag, str) and raw_img_tag.strip():
            try:
                raw_img_tag = json.loads(raw_img_tag)
            except (TypeError, ValueError):
                values.append(raw_img_tag)
        if isinstance(raw_img_tag, dict):
            stack = list(raw_img_tag.values())
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)
                else:
                    values.append(item)

        for value in values:
            text = self._plain_text(value)
            match = re.search(r"\u5168\s*(\d{1,4})\s*\u96c6", text)
            if match:
                return int(match.group(1))
        return None

    def _episode_count_from_video_info(self, video_info):
        if not isinstance(video_info, dict):
            return None

        from_img_tag = self._episode_count_from_img_tag(video_info.get("imgTag"))
        if from_img_tag:
            return from_img_tag

        subject_doc = video_info.get("subjectDoc")
        if isinstance(subject_doc, dict):
            try:
                count = int(subject_doc.get("videoNum") or 0)
                if count > 0:
                    return count
            except (TypeError, ValueError):
                pass

        numbered = set()
        for site in video_info.get("episodeSites") or []:
            for episode in site.get("episodeInfoList") or []:
                title = self._plain_text(episode.get("title"))
                if title.isdigit():
                    numbered.add(int(title))
        if numbered:
            return max(numbered)
        return None

    def _search_payload(self, query, *, limit):
        page_size = min(max(limit * 4, 8), 30)
        return {
            "version": self.DATA_VERSION,
            "clientType": 1,
            "filterValue": "",
            "uuid": "cyberstream-manual-search",
            "retry": 0,
            "query": query,
            "pagenum": 0,
            "isPrefetch": True,
            "pagesize": page_size,
            "queryFrom": 0,
            "searchDatakey": "",
            "transInfo": "",
            "isneedQc": True,
            "preQid": "",
            "adClientInfo": "",
            "extraInfo": {
                "isNewMarkLabel": "1",
                "multi_terminal_pc": "1",
                "themeType": "0",
                "sugRelatedIds": "{}",
                "appVersion": "",
                "frontVersion": self.FRONT_VERSION,
            },
            "featureList": [
                "DEFAULT_FEFEATURE",
                "PC_SHORT_VIDEOS_WATERFALL",
                "PC_WANT_EPISODE_V2",
                "PC_WANT_EPISODE",
            ],
        }

    def _image_from_video_info(self, video_info):
        for key in ("imgUrl", "dynamicImgUrl", "playCover"):
            value = self._plain_text(video_info.get(key))
            if value:
                return value
        return ""

    def _category_from_video_info(self, video_info, actors):
        categories = []
        type_name = self._plain_text(video_info.get("typeName"))
        if type_name:
            categories.append(type_name)

        rich_tags = (video_info.get("coverDoc") or {}).get("richTags") or []
        actor_set = {actor.strip() for actor in actors or []}
        for raw_tag in rich_tags:
            text = self._plain_text(raw_tag.get("text") if isinstance(raw_tag, dict) else raw_tag)
            if not text or text in actor_set or text.startswith("\u8bc4\u5206"):
                continue
            if text not in categories:
                categories.append(text)
        return categories[:8]

    def _candidate_from_search_item(self, item, media_type_hint=None):
        doc = item.get("doc") if isinstance(item, dict) else None
        video_info = item.get("videoInfo") if isinstance(item, dict) else None
        if not isinstance(doc, dict) or not isinstance(video_info, dict):
            return None
        if int(doc.get("dataType") or 0) != 2:
            return None

        cid = self._plain_text(doc.get("id"))
        title = self._normalize_title(video_info.get("title"))
        if not cid or not title:
            return None

        actors = [
            self._plain_text(actor)
            for actor in (video_info.get("actors") or [])
            if self._plain_text(actor)
        ]
        episode_count = self._episode_count_from_video_info(video_info)
        media_type = media_type_hint if media_type_hint in {"movie", "tv"} else ("tv" if episode_count and episode_count > 1 else "movie")
        cover_doc = video_info.get("coverDoc") or {}
        rating = self._rating_from_tags(cover_doc.get("richTags") or [])

        return {
            "provider": self.name,
            "provider_name": self.display_name,
            "source_key": self.name,
            "candidate_id": self._candidate_id(cid),
            "external_id": self._candidate_id(cid),
            "tmdb_id": self._candidate_id(cid),
            "tencent_video_cid": cid,
            "source_url": self._source_url(cid),
            "media_type": media_type,
            "episode_count": episode_count,
            "season": self._season_number_from_title(title),
            "title": title,
            "original_title": title,
            "overview": self._plain_text(video_info.get("descrip")),
            "year": self._safe_int(video_info.get("year")),
            "poster_url": self._image_from_video_info(video_info),
            "backdrop_url": self._plain_text((video_info.get("ipRichInfo") or {}).get("richBgUrl")),
            "popularity": self._plain_text(cover_doc.get("chaseNum")),
            "vote_average": rating,
            "rating": rating,
            "category": self._category_from_video_info(video_info, actors),
        }

    def _safe_int(self, value):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if 1800 <= number <= 2100 else None

    def search_candidates(
        self,
        query: str,
        *,
        year: int | None = None,
        limit: int = 8,
        media_type_hint: str | None = None,
    ) -> CandidateSearchResult:
        cid, _ = self._parse_candidate_id(query)
        if cid:
            result = self.get_details(self._candidate_id(cid), media_type_hint=media_type_hint)
            if not result:
                return CandidateSearchResult(warnings=[f"tencent_video_direct_lookup_failed:{cid}"])
            metadata = result.metadata
            return CandidateSearchResult(items=[self._candidate_from_metadata(metadata, cid)])

        clean_query = self._normalize_query(query)
        if not clean_query:
            return CandidateSearchResult()

        data = self._request_json(self.SEARCH_URL, self._search_payload(clean_query, limit=max(limit, 1)))
        if not isinstance(data, dict):
            return CandidateSearchResult(warnings=["tencent_video_search_failed"])

        item_list = (
            data.get("data", {})
            .get("normalList", {})
            .get("itemList", [])
        )
        candidates = []
        for item in item_list:
            candidate = self._candidate_from_search_item(item, media_type_hint=media_type_hint)
            if candidate:
                candidates.append(candidate)
            if len(candidates) >= max(limit, 0):
                break
        return CandidateSearchResult(items=candidates)

    def _candidate_from_metadata(self, metadata, cid):
        return {
            "provider": self.name,
            "provider_name": self.display_name,
            "source_key": self.name,
            "candidate_id": self._candidate_id(cid),
            "external_id": self._candidate_id(cid),
            "tmdb_id": self._candidate_id(cid),
            "tencent_video_cid": cid,
            "source_url": metadata.get("source_url") or self._source_url(cid),
            "media_type": metadata.get("media_type_hint") or "tv",
            "episode_count": self._first_season_episode_count(metadata.get("season_metadata")),
            "season": self._first_season_number(metadata.get("season_metadata")),
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

    def _first_season_number(self, season_items):
        if not isinstance(season_items, list) or not season_items:
            return None
        return season_items[0].get("season")

    def _parse_page_metadata(self, html_text):
        parser = _HeadMetadataParser()
        parser.feed(html_text or "")

        ld_payloads = []
        for raw in parser.ld_json:
            try:
                ld_payloads.append(json.loads(html.unescape(raw)))
            except (TypeError, ValueError):
                continue

        video_node = {}
        series_node = {}
        for payload in ld_payloads:
            nodes = payload.get("@graph") if isinstance(payload, dict) else None
            if not isinstance(nodes, list):
                nodes = [payload]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_type = node.get("@type")
                if node_type == "VideoObject" and not video_node:
                    video_node = node
                    if isinstance(node.get("partOfSeries"), dict):
                        series_node = node["partOfSeries"]
                elif node_type == "TVSeries" and not series_node:
                    series_node = node

        return parser, video_node, series_node

    def _extract_description(self, meta_description, fallback):
        text = self._plain_text(fallback) or self._plain_text(meta_description)
        if not text:
            return ""
        match = re.search(r"\u5267\u60c5\u7b80\u4ecb[:\uff1a]\s*(.+)$", text)
        if match:
            return match.group(1).strip()
        return text

    def _extract_actors(self, video_node, meta_description):
        actors = []
        for actor in video_node.get("actor") or []:
            if isinstance(actor, dict):
                name = self._plain_text(actor.get("name"))
            else:
                name = self._plain_text(actor)
            if name and name not in actors:
                actors.append(name)

        if actors:
            return actors

        match = re.search(r"\u9886\u8854\u4e3b\u6f14[:\uff1a]\s*([^,\uff0c]+(?:[,，][^,\uff0c]+)*)", self._plain_text(meta_description))
        if not match:
            return actors
        for value in re.split(r"[,，]", match.group(1)):
            name = self._plain_text(value)
            if name and name not in actors:
                actors.append(name)
        return actors

    def _extract_categories(self, parser, video_node, series_node, title, actors):
        categories = []
        actor_set = set(actors or [])
        title_set = {self._plain_text(title), self._normalize_title(title)}

        for genre in (series_node.get("genre") or video_node.get("genre") or []):
            text = self._plain_text(genre)
            if text and text not in categories:
                categories.append(text)

        meta_title = self._plain_text(parser.meta.get("title") or parser.meta.get("og:title"))
        title_parts = [part.strip() for part in meta_title.split("_") if part.strip()]
        if len(title_parts) >= 2 and title_parts[1] not in categories:
            categories.insert(0, title_parts[1])

        for tag in parser.meta_lists.get("og:video:tag", []):
            text = self._plain_text(tag)
            if not text or text in actor_set or text in title_set:
                continue
            if re.search(r"_\d{1,4}$", text):
                continue
            if text not in categories:
                categories.append(text)
        return categories[:8]

    def _image_url(self, value):
        if isinstance(value, list):
            for item in value:
                text = self._plain_text(item)
                if text:
                    return text
            return ""
        return self._plain_text(value)

    def _country_from_series(self, series_node):
        country = series_node.get("countryOfOrigin") if isinstance(series_node, dict) else None
        if isinstance(country, dict):
            return self._plain_text(country.get("name"))
        return self._plain_text(country)

    def _metadata_from_page(self, cid, html_text, media_type_hint=None):
        parser, video_node, series_node = self._parse_page_metadata(html_text)
        meta = parser.meta

        title = self._normalize_title(
            series_node.get("name")
            or video_node.get("name")
            or meta.get("og:title")
            or meta.get("title")
        )
        if not title:
            return None

        source_url = self._source_url(cid)
        description = self._extract_description(
            meta.get("description") or meta.get("og:description"),
            series_node.get("description") or video_node.get("description"),
        )
        actors = self._extract_actors(video_node, meta.get("description") or "")
        date_published = self._first_date(
            series_node.get("datePublished"),
            video_node.get("datePublished"),
            video_node.get("uploadDate"),
            meta.get("datePublished"),
        )
        year = self._year_from_date(date_published)
        episode_count = self._safe_positive_int(series_node.get("numberOfEpisodes"))
        season = self._season_number_from_title(title)
        media_type = media_type_hint if media_type_hint in {"movie", "tv"} else ("tv" if episode_count and episode_count > 1 else "movie")
        cover = self._image_url(series_node.get("image")) or self._plain_text(meta.get("image") or meta.get("og:image"))
        backdrop = self._image_url(video_node.get("thumbnailUrl"))
        country = self._country_from_series(series_node) or self._plain_text(meta.get("contentLocation"))

        season_metadata = []
        if media_type == "tv" and season:
            season_metadata.append({
                "season": season,
                "title": title,
                "overview": description,
                "air_date": date_published,
                "poster": cover,
                "episode_count": episode_count,
            })

        return {
            "tmdb_id": self._candidate_id(cid),
            "title": title,
            "original_title": title,
            "year": year,
            "rating": 0,
            "description": description or "",
            "cover": cover,
            "background_cover": backdrop if backdrop != cover else "",
            "source_url": source_url,
            "category": self._extract_categories(parser, video_node, series_node, title, actors),
            "director": "",
            "actors": actors,
            "country": country or "",
            "scraper_source": "TENCENT_VIDEO",
            "media_type_hint": media_type,
            "season_metadata": season_metadata,
        }

    def _safe_positive_int(self, value):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def get_details(self, candidate_id: str, media_type_hint: str | None = None) -> ScrapeResult | None:
        cid, _ = self._parse_candidate_id(candidate_id)
        if not cid:
            return None

        source_url = self._source_url(cid)
        html_text = self._request_text(source_url)
        if not html_text:
            return None

        metadata = self._metadata_from_page(cid, html_text, media_type_hint=media_type_hint)
        if not metadata:
            return None

        return ScrapeResult(
            metadata=metadata,
            provider=self.name,
            confidence=0.85,
            matched_id=metadata["tmdb_id"],
            raw={
                "matched_from": "candidate_id",
                "manual_only": True,
                "tencent_video_cid": cid,
                "source_url": source_url,
                "content_type": metadata.get("media_type_hint"),
            },
        )

    def scrape(self, context, media_type_hint: str | None) -> ProviderAttempt:
        return ProviderAttempt(warnings=["tencent_video_manual_only"])
