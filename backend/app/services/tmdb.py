import requests
import re
import socket
import time
import logging
import threading
from urllib.parse import urlparse
from urllib3.util import connection as urllib3_connection
from backend import config
from backend.app.utils.genres import normalize_tmdb_genres

logger = logging.getLogger(__name__)

_TMDB_DNS_FAMILY_LOCK = threading.Lock()
_TMDB_DNS_FAMILY_CACHE = {}
_TMDB_DNS_FAMILY_CACHE_TTL = 300
_TMDB_DNS_PROBE_TIMEOUT = 0.8


def _tmdb_ipv4_gai_family():
    return socket.AF_INET


def _tmdb_ipv6_gai_family():
    return socket.AF_INET6


def _tmdb_gai_family_callback(family):
    return _tmdb_ipv6_gai_family if family == socket.AF_INET6 else _tmdb_ipv4_gai_family


def _tmdb_address_key(sockaddr):
    return str(sockaddr)


def _tmdb_probe_family(addresses, timeout):
    last_error = None
    seen = set()
    for family, socktype, proto, _canonname, sockaddr in addresses:
        key = _tmdb_address_key(sockaddr)
        if key in seen:
            continue
        seen.add(key)
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return family
        except OSError as e:
            last_error = e
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    if last_error:
        raise last_error
    raise OSError("No address available for family probe")


def _tmdb_cache_key(url):
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def _tmdb_cached_family(cache_key):
    now = time.monotonic()
    with _TMDB_DNS_FAMILY_LOCK:
        cached = _TMDB_DNS_FAMILY_CACHE.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]
        if cached:
            _TMDB_DNS_FAMILY_CACHE.pop(cache_key, None)
    return None


def _tmdb_store_family(cache_key, family):
    with _TMDB_DNS_FAMILY_LOCK:
        _TMDB_DNS_FAMILY_CACHE[cache_key] = (
            family,
            time.monotonic() + _TMDB_DNS_FAMILY_CACHE_TTL,
        )


def _tmdb_clear_family(cache_key, family=None):
    with _TMDB_DNS_FAMILY_LOCK:
        cached = _TMDB_DNS_FAMILY_CACHE.get(cache_key)
        if cached and (family is None or cached[0] == family):
            _TMDB_DNS_FAMILY_CACHE.pop(cache_key, None)


def _tmdb_race_dns_families(host, port):
    try:
        addrinfos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        logger.debug("TMDB DNS family probe skipped host=%s error=%s", host, e)
        return None

    grouped = {
        socket.AF_INET: [],
        socket.AF_INET6: [],
    }
    family_order = []
    for addrinfo in addrinfos:
        family = addrinfo[0]
        if family in grouped:
            grouped[family].append(addrinfo)
            if family not in family_order:
                family_order.append(family)

    families = [family for family in family_order if grouped[family]]
    if len(families) == 1:
        return families[0]
    if not families:
        return None

    result = {}
    done = threading.Event()

    def worker(family):
        try:
            _tmdb_probe_family(grouped[family], _TMDB_DNS_PROBE_TIMEOUT)
        except OSError as e:
            logger.debug("TMDB DNS family probe failed host=%s family=%s error=%s", host, family, e)
            return
        if not done.is_set():
            result["family"] = family
            done.set()

    threads = [
        threading.Thread(target=worker, args=(family,), daemon=True)
        for family in families
    ]
    for thread in threads:
        thread.start()

    done.wait(_TMDB_DNS_PROBE_TIMEOUT)
    for thread in threads:
        thread.join(timeout=0)
    return result.get("family")

class TMDBScraper:
    PRECISE_MATCH_SCORE_THRESHOLD = 400
    YEAR_HINT_MATCH_SCORE_THRESHOLD = 150

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.refresh_runtime_config(reset_session=False)

    def refresh_runtime_config(self, reset_session=False):
        self.headers = {
            "Authorization": f"Bearer {config.TMDB_TOKEN}",
            "accept": "application/json"
        }
        self.proxies = getattr(config, "TMDB_PROXIES", None)
        if reset_session:
            try:
                self.session.close()
            except Exception:
                logger.debug("TMDB session close failed during config refresh", exc_info=True)
            self.session = requests.Session()
            self.session.trust_env = False

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
        text = re.sub(r'\s+', ' ', text)
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
            year_delta = abs(result_year - year)
            score -= min(year_delta, 20) * 60
            if year_delta > 1:
                score -= 500
        elif year and result_year is None:
            score -= 1000

        return score

    def _search_variant_results(self, variant):
        data = self._get(variant["url"], variant["params"])
        if not data or not data.get('results'):
            return []
        return self._normalize_results(
            data['results'],
            forced_media_type=variant["forced_media_type"],
        )

    def _search_best_result(self, variants, clean_query, year=None, strict=False, media_type_hint=None):
        best_result = None
        best_score = None

        for variant in variants:
            results = self._search_variant_results(variant)
            for result in results:
                if media_type_hint in ['movie', 'tv'] and result.get('media_type') != media_type_hint:
                    continue
                score = self._score_result(result, clean_query, year=year, strict=strict)
                if score is None:
                    continue
                score += variant["bonus"]
                if best_score is None or score > best_score:
                    best_score = score
                    best_result = result

        return best_result, best_score

    def _pick_dns_family(self, url):
        cache_key = _tmdb_cache_key(url)
        if not cache_key:
            return None

        cached = _tmdb_cached_family(cache_key)
        if cached:
            return cached

        family = _tmdb_race_dns_families(*cache_key)
        if family:
            _tmdb_store_family(cache_key, family)
        return family

    def _clear_dns_family_cache(self, url, family=None):
        cache_key = _tmdb_cache_key(url)
        if cache_key:
            _tmdb_clear_family(cache_key, family=family)

    def _session_get(self, url, params=None, family=None, timeout=10):
        if family not in (socket.AF_INET, socket.AF_INET6):
            return self.session.get(
                url,
                headers=self.headers,
                params=params,
                proxies=self.proxies,
                timeout=timeout
            )

        with _TMDB_DNS_FAMILY_LOCK:
            original_gai_family = urllib3_connection.allowed_gai_family
            urllib3_connection.allowed_gai_family = _tmdb_gai_family_callback(family)
            try:
                return self.session.get(
                    url,
                    headers=self.headers,
                    params=params,
                    proxies=self.proxies,
                    timeout=timeout
                )
            finally:
                urllib3_connection.allowed_gai_family = original_gai_family

    def check_token_status(self):
        token = str(config.TMDB_TOKEN or "").strip()
        proxy_enabled = bool(getattr(config, "TMDB_PROXY_ENABLED", True))
        proxy_url = str(getattr(config, "TMDB_PROXY_URL", "") or "").strip()
        base_payload = {
            "ready": False,
            "token_set": bool(token),
            "token_valid": False,
            "status": "missing_token" if not token else "unknown",
            "message": "TMDB token is not configured" if not token else "",
            "http_status": None,
            "tmdb_status_code": None,
            "tmdb_status_message": "",
            "proxy_enabled": proxy_enabled,
            "proxy_configured": bool(proxy_url),
            "elapsed_ms": None,
        }
        if not token:
            return base_payload

        self.refresh_runtime_config(reset_session=False)
        url = "https://api.themoviedb.org/3/authentication"
        started = time.monotonic()
        family = None if self.proxies else self._pick_dns_family(url)

        try:
            response = self._session_get(url, family=family, timeout=6)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            try:
                data = response.json()
            except ValueError:
                data = {}

            tmdb_status_code = data.get("status_code")
            tmdb_status_message = data.get("status_message") or ""
            payload = {
                **base_payload,
                "http_status": response.status_code,
                "tmdb_status_code": tmdb_status_code,
                "tmdb_status_message": tmdb_status_message,
                "elapsed_ms": elapsed_ms,
            }

            if response.status_code == 200 and data.get("success") is True:
                return {
                    **payload,
                    "ready": True,
                    "token_valid": True,
                    "status": "ok",
                    "message": "TMDB token is valid",
                }

            if response.status_code in {401, 403}:
                return {
                    **payload,
                    "status": "invalid_token",
                    "message": tmdb_status_message or "TMDB rejected the configured token",
                }

            if response.status_code == 429:
                return {
                    **payload,
                    "status": "rate_limited",
                    "message": tmdb_status_message or "TMDB rate limit reached",
                }

            return {
                **payload,
                "status": "tmdb_error",
                "message": tmdb_status_message or f"TMDB returned HTTP {response.status_code}",
            }
        except requests.exceptions.ProxyError as e:
            status = "proxy_error"
            message = "TMDB proxy connection failed"
            error = e
        except requests.exceptions.Timeout as e:
            status = "timeout"
            message = "TMDB token check timed out"
            error = e
        except requests.exceptions.SSLError as e:
            status = "tls_error"
            message = "TMDB TLS verification failed"
            error = e
        except requests.exceptions.RequestException as e:
            status = "network_error"
            message = "TMDB token check request failed"
            error = e
        except OSError as e:
            status = "network_error"
            message = "TMDB network lookup failed"
            error = e

        if family:
            self._clear_dns_family_cache(url, family=family)
        logger.warning("TMDB token check failed status=%s error=%s", status, error)
        return {
            **base_payload,
            "status": status,
            "message": message,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    def _get(self, url, params=None):
        if not config.TMDB_TOKEN:
            logger.warning("TMDB_TOKEN is not configured; skipping TMDB request url=%s", url)
            return None
        self.refresh_runtime_config(reset_session=False)

        for _ in range(3):
            family = None if self.proxies else self._pick_dns_family(url)
            try:
                response = self._session_get(url, params=params, family=family)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                if family:
                    self._clear_dns_family_cache(url, family=family)
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

        if media_type_hint in ['movie', 'tv']:
            broad_result, broad_score = self._search_best_result(
                self._build_search_variants(clean_query, year=None, media_type_hint=None),
                clean_query,
                year=year,
                strict=strict,
                media_type_hint=media_type_hint,
            )
            if broad_result and (broad_score or 0) >= self.PRECISE_MATCH_SCORE_THRESHOLD:
                return f"{broad_result['media_type']}/{broad_result['id']}"

        best_result, best_score = self._search_best_result(
            self._build_search_variants(clean_query, year=year, media_type_hint=media_type_hint),
            clean_query,
            year=year,
            strict=strict,
            media_type_hint=media_type_hint,
        )

        if not best_result:
            return None
        if year and not strict and (best_score or 0) < self.YEAR_HINT_MATCH_SCORE_THRESHOLD:
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

    def _details_needs_language_fallback(self, data):
        if not isinstance(data, dict):
            return False
        title = data.get('title') or data.get('name')
        return not all([
            title,
            data.get('overview'),
            data.get('poster_path'),
            data.get('backdrop_path'),
        ])

    def _merge_missing_detail_fields(self, primary, fallback):
        if not isinstance(primary, dict) or not isinstance(fallback, dict):
            return primary

        merged = dict(primary)
        for field in (
            'title',
            'name',
            'original_title',
            'original_name',
            'overview',
            'poster_path',
            'backdrop_path',
            'release_date',
            'first_air_date',
        ):
            if not merged.get(field) and fallback.get(field):
                merged[field] = fallback.get(field)

        if not merged.get('genres') and fallback.get('genres'):
            merged['genres'] = fallback.get('genres')
        if not merged.get('production_countries') and fallback.get('production_countries'):
            merged['production_countries'] = fallback.get('production_countries')
        if not merged.get('credits') and fallback.get('credits'):
            merged['credits'] = fallback.get('credits')
        if not merged.get('created_by') and fallback.get('created_by'):
            merged['created_by'] = fallback.get('created_by')
        return merged

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
        if self._details_needs_language_fallback(data):
            fallback_data = self._get(url, {
                "language": "en-US",
                "append_to_response": "credits,videos"
            })
            data = self._merge_missing_detail_fields(data, fallback_data)

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
