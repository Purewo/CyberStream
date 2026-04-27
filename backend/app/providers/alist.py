import logging
import posixpath
import ipaddress
import socket
import threading
import time
from urllib.parse import quote, urlencode, urljoin, urlparse

import requests

from .base import StorageProvider

logger = logging.getLogger(__name__)


class AListProvider(StorageProvider):
    ENDPOINT_CACHE_TTL_SECONDS = 1800
    ENDPOINT_PROBE_TIMEOUT_SECONDS = 1.5
    TOKEN_CACHE_TTL_SECONDS = 1800
    _endpoint_cache = {}
    _endpoint_cache_lock = threading.Lock()
    _token_cache = {}
    _token_cache_lock = threading.Lock()

    def __init__(self, config, platform='alist'):
        super().__init__(config)
        self.platform = str(platform or 'alist').strip().lower()
        self.base_url = self._resolve_base_url(config)
        self.request_base_url = self._resolve_request_base_url(self.base_url)
        self.root = self._clean_relative_path(config.get('root', '/'))
        self.token = config.get('token', '')
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.otp_code = config.get('otp_code', '')
        self.path_password = config.get('path_password', '')
        self.timeout = int(config.get('timeout', 30))
        self.verify_ssl = bool(config.get('verify_ssl', False))
        self.proxy_stream = bool(config.get('proxy_stream', False))
        self._resolved_token = None
        self._host_header = urlparse(self.base_url).netloc if self.request_base_url != self.base_url else None

        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            'User-Agent': f'CyberPlayer/1.0 {self.platform.capitalize()}Client',
            'Accept': 'application/json',
        })

    def _resolve_base_url(self, config):
        base_url = str(config.get('base_url') or '').strip().rstrip('/')
        if base_url:
            return base_url

        host = str(config.get('host') or '').strip()
        port = int(config.get('port', 5244))
        secure = bool(config.get('secure', False))
        base_path = str(config.get('base_path') or '').strip().strip('/')
        protocol = 'https' if secure else 'http'
        suffix = f"/{base_path}" if base_path else ''
        return f"{protocol}://{host}:{port}{suffix}"

    def _resolve_request_base_url(self, base_url):
        parsed = urlparse(base_url)
        if parsed.scheme not in {'http', 'https'}:
            return base_url

        host = parsed.hostname or ''
        if not host or self._looks_like_ip(host):
            return base_url

        cached_endpoint = self._get_cached_endpoint(base_url)
        if cached_endpoint:
            return cached_endpoint

        port = parsed.port or 80
        for family in (socket.AF_INET, socket.AF_INET6):
            for candidate in self._resolve_address_candidates(host, port, family):
                if not self._probe_candidate(candidate):
                    continue
                endpoint = self._build_candidate_base_url(parsed, candidate['address'])
                self._store_cached_endpoint(base_url, endpoint)
                return endpoint

        return base_url

    def _looks_like_ip(self, host):
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def _get_cached_endpoint(self, base_url):
        now = time.time()
        with self._endpoint_cache_lock:
            cached = self._endpoint_cache.get(base_url)
            if not cached:
                return None
            if cached['expires_at'] <= now:
                self._endpoint_cache.pop(base_url, None)
                return None
            return cached['endpoint']

    def _store_cached_endpoint(self, base_url, endpoint):
        with self._endpoint_cache_lock:
            self._endpoint_cache[base_url] = {
                'endpoint': endpoint,
                'expires_at': time.time() + self.ENDPOINT_CACHE_TTL_SECONDS,
            }

    def _build_candidate_base_url(self, parsed_base_url, address):
        if ':' in address:
            netloc = f'[{address}]'
        else:
            netloc = address
        if parsed_base_url.port:
            netloc = f"{netloc}:{parsed_base_url.port}"
        return parsed_base_url._replace(netloc=netloc).geturl()

    def _resolve_address_candidates(self, host, port, family):
        try:
            infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        except socket.gaierror:
            return []

        candidates = []
        seen = set()
        for family_value, socktype, proto, canonname, sockaddr in infos:
            if family_value not in {socket.AF_INET, socket.AF_INET6}:
                continue
            address = sockaddr[0]
            key = (family_value, address)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                'family': family_value,
                'sockaddr': sockaddr,
                'address': address,
            })
        return candidates

    def _probe_candidate(self, candidate):
        sock = None
        try:
            sock = socket.socket(candidate['family'], socket.SOCK_STREAM)
            sock.settimeout(self.ENDPOINT_PROBE_TIMEOUT_SECONDS)
            sock.connect(candidate['sockaddr'])
            return True
        except OSError:
            return False
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _clean_relative_path(self, value):
        raw = str(value or '').replace('\\', '/').strip().strip('/')
        if not raw:
            return ''
        normalized = posixpath.normpath('/' + raw).lstrip('/')
        return '' if normalized == '.' else normalized

    def _remote_path(self, relative_path):
        clean_path = self._clean_relative_path(relative_path)
        parts = [part for part in (self.root, clean_path) if part]
        if not parts:
            return '/'
        return '/' + posixpath.join(*parts)

    def _child_relative_path(self, relative_path, name):
        clean_path = self._clean_relative_path(relative_path)
        return posixpath.join(clean_path, name).strip('/') if clean_path else name

    def _api_url(self, path):
        return urljoin(self.request_base_url + '/', str(path or '').lstrip('/'))

    def _request_headers(self, headers=None, url=None):
        merged = dict(headers or {})
        if self._host_header and url:
            parsed_url = urlparse(url)
            parsed_request_base = urlparse(self.request_base_url)
            if (
                parsed_url.scheme == parsed_request_base.scheme
                and parsed_url.netloc == parsed_request_base.netloc
            ):
                merged['Host'] = self._host_header
        elif self._host_header:
            merged['Host'] = self._host_header
        return merged

    def _token_cache_key(self):
        return (
            self.platform,
            self.base_url,
            self.username,
            self.password,
            self.otp_code,
        )

    def _get_cached_token(self):
        cache_key = self._token_cache_key()
        now = time.time()
        with self._token_cache_lock:
            cached = self._token_cache.get(cache_key)
            if not cached:
                return None
            if cached['expires_at'] <= now:
                self._token_cache.pop(cache_key, None)
                return None
            return cached['token']

    def _store_cached_token(self, token):
        cache_key = self._token_cache_key()
        with self._token_cache_lock:
            self._token_cache[cache_key] = {
                'token': token,
                'expires_at': time.time() + self.TOKEN_CACHE_TTL_SECONDS,
            }

    def _clear_cached_token(self):
        cache_key = self._token_cache_key()
        with self._token_cache_lock:
            self._token_cache.pop(cache_key, None)

    def _resolve_url(self, raw_url):
        if not raw_url:
            return None

        parsed = urlparse(raw_url)
        if parsed.scheme and parsed.netloc:
            return raw_url

        base_parsed = urlparse(self.base_url)
        if str(raw_url).startswith('/'):
            return f"{base_parsed.scheme}://{base_parsed.netloc}{raw_url}"
        return urljoin(self.base_url + '/', str(raw_url))

    def _is_same_origin(self, raw_url):
        if not raw_url:
            return False
        parsed = urlparse(raw_url)
        if not parsed.netloc:
            return True
        base_parsed = urlparse(self.base_url)
        if parsed.scheme == base_parsed.scheme and parsed.netloc == base_parsed.netloc:
            return True
        request_base_parsed = urlparse(self.request_base_url)
        return parsed.scheme == request_base_parsed.scheme and parsed.netloc == request_base_parsed.netloc

    def _parse_api_response(self, response):
        try:
            payload = response.json()
        except ValueError as e:
            body = response.text[:200] if hasattr(response, 'text') else ''
            raise ValueError(
                f"{self.platform} api invalid response status={response.status_code} body={body}"
            ) from e

        code = payload.get('code')
        message = payload.get('message') or payload.get('msg') or 'unknown error'

        if response.status_code >= 400:
            raise ValueError(f"{self.platform} api http error {response.status_code}: {message}")
        if code != 200:
            raise ValueError(f"{self.platform} api error {code}: {message}")
        return payload.get('data')

    def _get_token(self):
        if self._resolved_token:
            return self._resolved_token

        token = str(self.token or '').strip()
        if token:
            self._resolved_token = token
            return token

        cached_token = self._get_cached_token()
        if cached_token:
            self._resolved_token = cached_token
            return cached_token

        if not (self.username and self.password):
            return ''

        payload = {
            'username': self.username,
            'password': self.password,
        }
        if self.otp_code:
            payload['otp_code'] = self.otp_code

        response = self.session.post(
            self._api_url('/api/auth/login'),
            json=payload,
            headers=self._request_headers(),
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        data = self._parse_api_response(response)
        token = str((data or {}).get('token') or '').strip()
        if not token:
            raise ValueError(f"{self.platform} login succeeded without token")
        self._resolved_token = token
        self._store_cached_token(token)
        return token

    def _normalize_base_path(self, value):
        if value in (None, '', '/'):
            return ''
        normalized = str(value).strip().replace('\\', '/').strip('/')
        return f"/{normalized}" if normalized else ''

    def _build_api_headers(self):
        headers = {}
        token = self._get_token()
        if token:
            headers['Authorization'] = token
        return headers

    def _build_download_headers(self, raw_url, range_header=None):
        headers = {
            'User-Agent': self.session.headers.get('User-Agent', 'CyberPlayer/1.0'),
        }
        if range_header:
            headers['Range'] = range_header
        token = self._resolved_token or str(self.token or '').strip()
        if token and self._is_same_origin(raw_url):
            headers['Authorization'] = token
        return headers

    def _api_post(self, path, payload):
        response = self.session.post(
            self._api_url(path),
            json=payload,
            headers=self._request_headers(self._build_api_headers()),
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        return self._parse_api_response(response)

    def _get_entry(self, relative_path):
        return self._api_post(
            '/api/fs/get',
            {
                'path': self._remote_path(relative_path),
                'password': self.path_password,
                'page': 1,
                'per_page': 0,
                'refresh': False,
            },
        )

    def list_items(self, relative_path):
        data = self._api_post(
            '/api/fs/list',
            {
                'path': self._remote_path(relative_path),
                'password': self.path_password,
                'page': 1,
                'per_page': 0,
                'refresh': False,
            },
        )

        items = []
        for entry in (data or {}).get('content') or []:
            name = str(entry.get('name') or '').strip()
            if not name or name in {'.', '..'} or name.startswith('.'):
                continue

            is_dir = bool(entry.get('is_dir', False))
            items.append({
                'path': self._child_relative_path(relative_path, name),
                'name': name,
                'isdir': is_dir,
                'size': 0 if is_dir else int(entry.get('size') or 0),
            })
        return items

    def path_exists(self, relative_path):
        try:
            entry = self._get_entry(relative_path)
            return bool((entry or {}).get('is_dir', False))
        except Exception:
            return False

    def health_check(self, relative_path=''):
        path = self._clean_relative_path(relative_path)
        version = None
        site_title = None

        try:
            response = self.session.get(
                self._api_url('/api/public/settings'),
                headers=self._request_headers(),
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            data = self._parse_api_response(response)
            version = (data or {}).get('version')
            site_title = (data or {}).get('site_title')
        except Exception:
            pass

        try:
            exists = self.path_exists(path)
            return {
                "status": "online" if exists else "offline",
                "path": path or "/",
                "path_exists": exists,
                "base_url": self.base_url,
                "root": "/" + self.root if self.root else "/",
                "platform": self.platform,
                "site_title": site_title,
                "version": version,
                "error": None if exists else "Path not found or unavailable",
            }
        except Exception as e:
            return {
                "status": "offline",
                "path": path or "/",
                "path_exists": False,
                "base_url": self.base_url,
                "root": "/" + self.root if self.root else "/",
                "platform": self.platform,
                "site_title": site_title,
                "version": version,
                "error": str(e),
            }

    def check_connection(self):
        result = self.health_check('')
        return {
            "status": result.get("status", "offline"),
            "reason": "ok" if result.get("status") == "online" else "request_failed",
            "message": f"{self.platform} reachable" if result.get("status") == "online" else result.get("error"),
            **result,
        }

    def _fetch_raw_url(self, relative_path):
        entry = self._get_entry(relative_path)
        raw_url = self._resolve_url((entry or {}).get('raw_url'))
        if not raw_url:
            raise ValueError(f"{self.platform} fs/get did not return raw_url")
        return raw_url

    def _build_download_url(self, relative_path, sign=None, base_url=None):
        remote_path = quote(self._remote_path(relative_path), safe='/')
        target_base_url = str(base_url or self.base_url).rstrip('/')
        url = f"{target_base_url}/d{remote_path}"
        if sign:
            return f"{url}?{urlencode({'sign': str(sign)})}"
        return url

    def _build_signed_download_urls(self, relative_path):
        entry = self._get_entry(relative_path)
        sign = (entry or {}).get('sign')
        return (
            self._build_download_url(relative_path, sign=sign, base_url=self.base_url),
            self._build_download_url(relative_path, sign=sign, base_url=self.request_base_url),
        )

    def _ensure_auth_token(self):
        if self._resolved_token or str(self.token or '').strip():
            return
        if self.username and self.password:
            self._get_token()

    def _open_stream_response(self, url, range_header=None, allow_redirects=False):
        return self.session.get(
            url,
            headers=self._request_headers(
                self._build_download_headers(url, range_header=range_header),
                url=url,
            ),
            stream=True,
            timeout=self.timeout,
            verify=self.verify_ssl,
            allow_redirects=allow_redirects,
        )

    def _close_response(self, response):
        close = getattr(response, 'close', None)
        if callable(close):
            close()

    def _to_stream_result(self, response, request_url):
        if response.status_code in [301, 302, 303, 307, 308]:
            location = response.headers.get('Location')
            self._close_response(response)
            if location:
                return None, 302, 0, urljoin(request_url, location)
            return None, response.status_code, 0, None

        if response.status_code >= 400:
            self._close_response(response)
            return None, response.status_code, 0, None

        return (
            response.iter_content(chunk_size=64 * 1024),
            response.status_code,
            response.headers.get('content-length'),
            response.headers.get('content-range'),
        )

    def read_text(self, path, max_bytes=262144, encoding=None):
        raw_url = self._fetch_raw_url(path)
        response = self.session.get(
            raw_url,
            headers=self._build_download_headers(raw_url),
            timeout=self.timeout,
            verify=self.verify_ssl,
            allow_redirects=True,
        )
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        text = response.text
        encoded = text.encode(response.encoding or 'utf-8', errors='ignore')
        if len(encoded) > max_bytes:
            return encoded[:max_bytes].decode(response.encoding or 'utf-8', errors='ignore')
        return text

    def get_stream_data(self, path, range_header=None):
        try:
            self._ensure_auth_token()
            public_download_url, _request_download_url = self._build_signed_download_urls(path)
            return None, 302, 0, public_download_url
        except Exception as e:
            logger.exception("%s stream failed path=%s error=%s", self.platform, path, e)
            return None, 500, 0, None

    def get_ffmpeg_input(self, path):
        try:
            public_download_url, _request_download_url = self._build_signed_download_urls(path)
            return public_download_url
        except Exception:
            try:
                return self._fetch_raw_url(path)
            except Exception:
                return self._build_download_url(path)
