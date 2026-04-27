import requests
import re
import time
import logging
from backend import config
from backend.app.utils.genres import normalize_tmdb_genres

logger = logging.getLogger(__name__)

class TMDBScraper:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {config.TMDB_TOKEN}",
            "accept": "application/json"
        }
        self.session = requests.Session()
        self.session.trust_env = False
        self.proxies = getattr(config, "TMDB_PROXIES", None)

    def _normalize_search_query(self, query):
        clean_query = re.sub(r'\b(19|20)\d{2}\b', '', query or '').strip()
        return clean_query or (query or '').strip()

    def _search_endpoint(self, media_type_hint=None):
        if media_type_hint in ['movie', 'tv']:
            return f"https://api.themoviedb.org/3/search/{media_type_hint}", media_type_hint
        return "https://api.themoviedb.org/3/search/multi", None

    def _normalize_compare_text(self, value):
        text = re.sub(r'\s+', ' ', (value or '').strip().lower())
        text = re.sub(r'[-_.:]+', ' ', text)
        return text.strip()

    def _looks_ascii_query(self, query):
        compact = re.sub(r'[\W_]+', '', query or '')
        return bool(compact) and compact.isascii()

    def _build_search_params(self, clean_query, language, year=None, forced_media_type=None):
        params = {
            "query": clean_query,
            "language": language,
            "include_adult": "false",
            "page": 1,
        }
        if year:
            if forced_media_type == 'movie':
                params["year"] = year
            elif forced_media_type == 'tv':
                params["first_air_date_year"] = year
        return params

    def _build_search_variants(self, clean_query, year=None, media_type_hint=None):
        url, forced_media_type = self._search_endpoint(media_type_hint)
        languages = ['zh-CN']
        if self._looks_ascii_query(clean_query):
            languages.append('en-US')

        variants = []
        seen = set()
        for language in languages:
            if year and forced_media_type in {'movie', 'tv'}:
                params = self._build_search_params(
                    clean_query,
                    language,
                    year=year,
                    forced_media_type=forced_media_type,
                )
                key = (url, tuple(sorted(params.items())))
                if key not in seen:
                    seen.add(key)
                    variants.append({
                        "url": url,
                        "forced_media_type": forced_media_type,
                        "params": params,
                        "bonus": 30 if language == 'en-US' else 20,
                    })

            params = self._build_search_params(
                clean_query,
                language,
                forced_media_type=forced_media_type,
            )
            key = (url, tuple(sorted(params.items())))
            if key in seen:
                continue
            seen.add(key)
            variants.append({
                "url": url,
                "forced_media_type": forced_media_type,
                "params": params,
                "bonus": 10 if language == 'en-US' else 0,
            })

        return variants

    def _normalize_results(self, results, forced_media_type=None):
        normalized = []
        for result in results or []:
            media_type = forced_media_type or result.get('media_type')
            if media_type not in ['movie', 'tv']:
                continue
            normalized.append({
                **result,
                "media_type": media_type,
            })
        return normalized

    def _pick_result_by_hint(self, results, media_type_hint=None):
        if not results:
            return None
        if media_type_hint in ['movie', 'tv']:
            for result in results:
                if result.get('media_type') == media_type_hint:
                    return result
        return results[0]

    def _result_year(self, result):
        date_value = result.get('release_date') or result.get('first_air_date') or ''
        if len(date_value) >= 4 and date_value[:4].isdigit():
            return int(date_value[:4])
        return None

    def _score_result(self, result, clean_query, year=None, strict=False):
        normalized_query = self._normalize_compare_text(clean_query)
        candidate_title = self._normalize_compare_text(result.get('title') or result.get('name'))
        candidate_original = self._normalize_compare_text(
            result.get('original_title') or result.get('original_name')
        )
        result_year = self._result_year(result)

        title_exact = candidate_title == normalized_query
        original_exact = candidate_original == normalized_query
        if strict and not (title_exact or original_exact):
            return None
        if strict and year and result_year != year:
            return None

        score = float(result.get('popularity') or 0)
        if title_exact:
            score += 600
        if original_exact:
            score += 520

        if normalized_query:
            if candidate_title.startswith(normalized_query) and not title_exact:
                score += 120
            if candidate_original.startswith(normalized_query) and not original_exact:
                score += 100
            if normalized_query in candidate_title and not title_exact:
                score += 60
            if normalized_query in candidate_original and not original_exact:
                score += 50

        if year and result_year == year:
            score += 350
        elif year and result_year is not None:
            score -= min(abs(result_year - year), 20) * 12

        return score

    def _search_variant_results(self, variant):
        data = self._get(variant["url"], variant["params"])
        if not data or not data.get('results'):
            return []
        return self._normalize_results(
            data['results'],
            forced_media_type=variant["forced_media_type"],
        )

    def _get(self, url, params=None):
        for _ in range(3):
            try:
                response = self.session.get(
                    url,
                    headers=self.headers,
                    params=params,
                    proxies=self.proxies,
                    timeout=10
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.warning("TMDB request failed url=%s attempt=%s error=%s", url, _ + 1, e)
                time.sleep(1)
        return None

    def search_movie(self, query, year=None, strict=False, media_type_hint=None):
        clean_query = self._normalize_search_query(query)

        logger.info(
            "TMDB search query=%r year_hint=%s strict=%s media_type_hint=%s",
            clean_query,
            year,
            strict,
            media_type_hint,
        )

        best_result = None
        best_score = None

        for variant in self._build_search_variants(clean_query, year=year, media_type_hint=media_type_hint):
            results = self._search_variant_results(variant)
            for result in results:
                score = self._score_result(result, clean_query, year=year, strict=strict)
                if score is None:
                    continue
                score += variant["bonus"]
                if best_score is None or score > best_score:
                    best_score = score
                    best_result = result

        if not best_result:
            return None
        return f"{best_result['media_type']}/{best_result['id']}"

    def search_movie_candidates(self, query, year=None, limit=8):
        clean_query = self._normalize_search_query(query)
        if not clean_query:
            return []

        logger.info("TMDB candidate search query=%r year_hint=%s limit=%s", clean_query, year, limit)

        merged_results = {}
        for variant in self._build_search_variants(clean_query, year=None, media_type_hint=None):
            results = self._search_variant_results(variant)
            for result in results:
                result_key = f"{result.get('media_type')}/{result.get('id')}"
                existing = merged_results.get(result_key)
                if existing and existing["_bonus"] >= variant["bonus"]:
                    continue
                merged_results[result_key] = {
                    **result,
                    "_bonus": variant["bonus"],
                }

        if not merged_results:
            return []

        candidates = []
        for result in merged_results.values():
            media_type = result['media_type']
            release_date = result.get('release_date') or result.get('first_air_date') or ""
            result_year = int(release_date[:4]) if release_date[:4].isdigit() else None
            title = result.get('title') or result.get('name') or ""
            original_title = result.get('original_title') or result.get('original_name') or ""
            tmdb_combined_id = f"{media_type}/{result['id']}"

            score = self._score_result(result, clean_query, year=year, strict=False) or 0
            score += result.get("_bonus", 0)

            candidates.append({
                "tmdb_id": tmdb_combined_id,
                "media_type": media_type,
                "title": title,
                "original_title": original_title,
                "overview": result.get('overview') or "",
                "year": result_year,
                "poster_url": config.TMDB_IMAGE_BASE + result.get('poster_path') if result.get('poster_path') else "",
                "backdrop_url": config.TMDB_BACKDROP_BASE + result.get('backdrop_path') if result.get('backdrop_path') else "",
                "popularity": result.get('popularity') or 0,
                "vote_average": round(result.get('vote_average') or 0, 1),
                "_score": score,
            })

        candidates.sort(key=lambda item: (item["_score"], item["popularity"]), reverse=True)
        trimmed = candidates[:max(limit, 0)]
        for item in trimmed:
            item.pop("_score", None)
        return trimmed

    def find_by_external_id(self, external_id, media_type_hint=None):
        if not isinstance(external_id, str):
            return None

        raw = external_id.strip()
        if not raw:
            return None
        if raw.startswith('movie/') or raw.startswith('tv/'):
            return raw

        if '/' not in raw:
            return None

        prefix, value = raw.split('/', 1)
        prefix = prefix.strip().lower()
        value = value.strip()
        if not value:
            return None

        source_map = {
            'imdb': 'imdb_id',
            'tvdb': 'tvdb_id',
        }
        external_source = source_map.get(prefix)
        if not external_source:
            return None

        logger.info(
            "TMDB external id lookup external_id=%r media_type_hint=%s",
            raw,
            media_type_hint,
        )

        url = f"https://api.themoviedb.org/3/find/{value}"
        data = self._get(url, {
            "external_source": external_source,
            "language": "zh-CN",
        })
        if not data:
            return None

        results = []
        results.extend(self._normalize_results(data.get('movie_results') or [], forced_media_type='movie'))
        results.extend(self._normalize_results(data.get('tv_results') or [], forced_media_type='tv'))
        target = self._pick_result_by_hint(results, media_type_hint=media_type_hint)
        if not target:
            return None
        return f"{target['media_type']}/{target['id']}"

    def get_movie_details(self, tmdb_combined_id):
        try:
            media_type, tmdb_id = tmdb_combined_id.split('/')
        except Exception:
            media_type = 'movie'
            tmdb_id = tmdb_combined_id

        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        params = {
            "language": "zh-CN",
            "append_to_response": "credits,videos"
        }

        data = self._get(url, params)
        if not data: return None

        title = data.get('title') or data.get('name')
        original_title = data.get('original_title') or data.get('original_name')
        date = data.get('release_date') or data.get('first_air_date')
        year = int(date[:4]) if date and date[:4].isdigit() else None

        cast = []
        if 'credits' in data and 'cast' in data['credits']:
            cast = [p['name'] for p in data['credits']['cast'][:6]]

        director = "Unknown"
        if media_type == 'movie' and 'credits' in data:
            for crew in data['credits']['crew']:
                if crew['job'] == 'Director':
                    director = crew['name'];
                    break
        elif media_type == 'tv' and data.get('created_by'):
            director = data['created_by'][0]['name']

        genres = normalize_tmdb_genres(data.get('genres', []))
        countries = [c['name'] for c in data.get('production_countries', [])]
        country_str = countries[0] if countries else "Unknown"
        season_metadata = []
        if media_type == 'tv':
            for season in data.get('seasons', []) or []:
                season_number = season.get('season_number')
                try:
                    season_number = int(season_number)
                except (TypeError, ValueError):
                    continue
                if season_number <= 0:
                    continue

                season_metadata.append({
                    "season": season_number,
                    "title": (season.get('name') or '').strip() or None,
                    "overview": (season.get('overview') or '').strip() or None,
                    "air_date": season.get('air_date') or None,
                    "poster": config.TMDB_IMAGE_BASE + season.get('poster_path') if season.get('poster_path') else "",
                    "episode_count": season.get('episode_count'),
                })

        return {
            "tmdb_id": tmdb_combined_id,
            "title": title,
            "original_title": original_title,
            "year": year,
            "rating": round(data.get('vote_average', 0), 1),
            "description": data.get('overview', '暂无简介'),
            "cover": config.TMDB_IMAGE_BASE + data.get('poster_path') if data.get('poster_path') else "",
            "background_cover": config.TMDB_BACKDROP_BASE + data.get('backdrop_path') if data.get(
                'backdrop_path') else "",
            "category": genres,
            "director": director,
            "actors": cast,
            "country": country_str,
            "scraper_source": "TMDB",
            "season_metadata": season_metadata,
        }

scraper = TMDBScraper()
