from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.providers.alist import AListProvider


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None, text=''):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.encoding = None

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f"http {self.status_code}")

    def close(self):
        pass

    def iter_content(self, chunk_size=65536):
        yield b'chunk-1'
        yield b'chunk-2'


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None, verify=None):
        self.calls.append(("POST", url, json, headers))
        if url.endswith('/api/auth/login'):
            return FakeResponse({"code": 200, "data": {"token": "login-token"}})
        if url.endswith('/api/fs/list'):
            return FakeResponse(
                {
                    "code": 200,
                    "data": {
                        "content": [
                            {"name": "电影", "is_dir": True, "size": 0},
                            {"name": "README.txt", "is_dir": False, "size": 12},
                            {"name": ".hidden", "is_dir": True, "size": 0},
                        ]
                    },
                }
            )
        if url.endswith('/api/fs/get'):
            path = (json or {}).get("path")
            if path in {"/library", "/library/电影"}:
                return FakeResponse(
                    {
                        "code": 200,
                        "data": {"name": path.rsplit("/", 1)[-1] or "library", "is_dir": True},
                    }
                )
            if path == "/library/电影/movie.nfo":
                return FakeResponse(
                    {
                        "code": 200,
                        "data": {"name": "movie.nfo", "is_dir": False, "raw_url": "/d/library/%E7%94%B5%E5%BD%B1/movie.nfo"},
                    }
                )
            if path == "/library/电影/movie.mkv":
                return FakeResponse(
                    {
                        "code": 200,
                        "data": {
                            "name": "movie.mkv",
                            "is_dir": False,
                            "raw_url": "https://cdn.example.com/raw/movie.mkv",
                            "sign": "signed-token",
                        },
                    }
                )
            return FakeResponse({"code": 500, "message": "not found"}, status_code=200)
        raise AssertionError(url)

    def get(self, url, headers=None, timeout=None, verify=None, stream=False, allow_redirects=True):
        self.calls.append(("GET", url, headers, {"stream": stream, "allow_redirects": allow_redirects}))
        if url.endswith('/api/public/settings'):
            return FakeResponse({"code": 200, "data": {"site_title": "OpenList", "version": "4.0.0"}})
        if url.endswith('/d/library/%E7%94%B5%E5%BD%B1/movie.nfo'):
            return FakeResponse({}, text='nfo text')
        if '/d/library/%E7%94%B5%E5%BD%B1/movie.mkv' in url:
            return FakeResponse({}, status_code=302, headers={"Location": "https://cdn.example.com/raw/movie.mkv?fresh=1"})
        if url == 'https://cdn.example.com/raw/movie.mkv?fresh=1':
            return FakeResponse({}, headers={"content-length": "100", "content-range": "bytes 0-99/100"})
        raise AssertionError(url)


class AListProviderTests(unittest.TestCase):
    def setUp(self):
        AListProvider._endpoint_cache.clear()
        AListProvider._token_cache.clear()

    def tearDown(self):
        AListProvider._endpoint_cache.clear()
        AListProvider._token_cache.clear()

    def create_provider(self, **config):
        provider = AListProvider(
            {
                "host": "alist.local",
                "port": 5244,
                "root": "/library",
                "username": "demo",
                "password": "secret",
                **config,
            },
            platform=config.pop("platform", "alist") if "platform" in config else "alist",
        )
        provider.session = FakeSession()
        return provider

    def test_session_does_not_inherit_environment_proxy(self):
        provider = AListProvider(
            {
                "host": "alist.local",
                "port": 5244,
                "root": "/library",
                "username": "demo",
                "password": "secret",
            }
        )

        self.assertFalse(provider.session.trust_env)

    def test_http_domain_prefers_reachable_ipv4_endpoint(self):
        with patch.object(
            AListProvider,
            "_resolve_base_url",
            return_value="http://alist.local:5244",
        ), patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("192.0.2.10", 5244)),
            (10, 1, 6, "", ("2001:db8::10", 5244, 0, 0)),
        ]), patch.object(AListProvider, "_probe_candidate", side_effect=[True]):
            provider = AListProvider(
                {
                    "host": "alist.local",
                    "port": 5244,
                    "root": "/library",
                    "username": "demo",
                    "password": "secret",
                }
            )

        self.assertEqual("http://192.0.2.10:5244", provider.request_base_url)
        self.assertEqual("alist.local:5244", provider._host_header)

    def test_http_domain_falls_back_to_ipv6_when_ipv4_is_unreachable(self):
        with patch.object(
            AListProvider,
            "_resolve_base_url",
            return_value="http://alist.local:5244",
        ), patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("192.0.2.10", 5244)),
            (10, 1, 6, "", ("2001:db8::10", 5244, 0, 0)),
        ]), patch.object(AListProvider, "_probe_candidate", side_effect=[False, True]):
            provider = AListProvider(
                {
                    "host": "alist.local",
                    "port": 5244,
                    "root": "/library",
                    "username": "demo",
                    "password": "secret",
                }
            )

        self.assertEqual("http://[2001:db8::10]:5244", provider.request_base_url)
        self.assertEqual("alist.local:5244", provider._host_header)

    def test_https_ip_keeps_original_endpoint(self):
        with patch.object(
            AListProvider,
            "_resolve_base_url",
            return_value="https://192.0.2.10:5244",
        ), patch("socket.getaddrinfo") as getaddrinfo:
            provider = AListProvider(
                {
                    "host": "192.0.2.10",
                    "port": 5244,
                    "secure": True,
                    "root": "/library",
                    "username": "demo",
                    "password": "secret",
                }
            )

        self.assertEqual("https://192.0.2.10:5244", provider.request_base_url)
        self.assertIsNone(provider._host_header)
        getaddrinfo.assert_not_called()

    def test_https_domain_prefers_reachable_ipv4_endpoint_with_host_header(self):
        with patch.object(
            AListProvider,
            "_resolve_base_url",
            return_value="https://alist.local:5244",
        ), patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("192.0.2.10", 5244)),
            (10, 1, 6, "", ("2001:db8::10", 5244, 0, 0)),
        ]), patch.object(AListProvider, "_probe_candidate", side_effect=[True]):
            provider = AListProvider(
                {
                    "host": "alist.local",
                    "port": 5244,
                    "secure": True,
                    "root": "/library",
                    "username": "demo",
                    "password": "secret",
                }
            )

        self.assertEqual("https://192.0.2.10:5244", provider.request_base_url)
        self.assertEqual("alist.local:5244", provider._host_header)

    def test_list_items_uses_api_and_filters_hidden_entries(self):
        provider = self.create_provider()
        items = provider.list_items("")

        self.assertEqual(["README.txt", "电影"], sorted(item["name"] for item in items))
        self.assertEqual("电影", [item["path"] for item in items if item["name"] == "电影"][0])
        list_calls = [call for call in provider.session.calls if call[0] == "POST" and call[1].endswith('/api/fs/list')]
        self.assertEqual("/library", list_calls[-1][2]["path"])

    def test_list_items_prefixes_child_path_with_config_root(self):
        provider = self.create_provider()
        provider.list_items("电影")

        list_calls = [call for call in provider.session.calls if call[0] == "POST" and call[1].endswith('/api/fs/list')]
        self.assertEqual("/library/电影", list_calls[-1][2]["path"])

    def test_path_exists_only_accepts_directories(self):
        provider = self.create_provider()

        self.assertTrue(provider.path_exists(""))
        self.assertTrue(provider.path_exists("电影"))
        self.assertFalse(provider.path_exists("电影/movie.mkv"))

    def test_read_text_fetches_raw_url(self):
        provider = self.create_provider(token="static-token")
        text = provider.read_text("电影/movie.nfo")

        self.assertEqual("nfo text", text)

    def test_stream_returns_redirect_by_default(self):
        provider = self.create_provider(token="static-token")
        stream, status, length, location = provider.get_stream_data("电影/movie.mkv")

        self.assertIsNone(stream)
        self.assertEqual(302, status)
        self.assertEqual(0, length)
        self.assertEqual(
            "http://alist.local:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            location,
        )

    def test_stream_default_returns_alist_domain_url(self):
        provider = self.create_provider(token="static-token")
        provider._fetch_raw_url = lambda path: (_ for _ in ()).throw(AssertionError("should not fetch raw url"))

        stream, status, length, location = provider.get_stream_data("电影/movie.mkv")

        self.assertIsNone(stream)
        self.assertEqual(302, status)
        self.assertEqual(0, length)
        self.assertEqual(
            "http://alist.local:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            location,
        )
        get_calls = [call for call in provider.session.calls if call[0] == "GET"]
        self.assertFalse(get_calls)

    def test_stream_default_returns_download_url_without_network_probe(self):
        provider = self.create_provider(token="static-token")
        provider.session.get = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not request remote /d"))
        stream, status, length, location = provider.get_stream_data("电影/movie.mkv")

        self.assertIsNone(stream)
        self.assertEqual(302, status)
        self.assertEqual(0, length)
        self.assertEqual(
            "http://alist.local:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            location,
        )

    def test_stream_default_preserves_http_scheme(self):
        provider = self.create_provider(base_url="http://alist.example.com:5244", root="/library", token="static-token")

        self.assertEqual(
            "http://alist.example.com:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv",
            provider._build_download_url("电影/movie.mkv"),
        )
        self.assertEqual(
            "http://alist.example.com:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            provider._build_download_url("电影/movie.mkv", sign="signed-token"),
        )

    def test_request_headers_only_attach_host_for_request_base_url(self):
        provider = self.create_provider(token="static-token")
        provider.base_url = "http://alist.example.com:5244"
        provider.request_base_url = "http://192.0.2.10:5244"
        provider._host_header = "alist.example.com:5244"

        request_headers = provider._request_headers({"Authorization": "token"}, url="http://192.0.2.10:5244/d/a.mkv")
        public_headers = provider._request_headers({"Authorization": "token"}, url="http://alist.example.com:5244/d/a.mkv")

        self.assertEqual("alist.example.com:5244", request_headers.get("Host"))
        self.assertNotIn("Host", public_headers)

    def test_build_signed_download_urls_uses_public_and_request_base_url(self):
        provider = self.create_provider(token="static-token")
        provider.base_url = "http://alist.example.com:5244"
        provider.request_base_url = "http://192.0.2.10:5244"

        public_url, request_url = provider._build_signed_download_urls("电影/movie.mkv")

        self.assertEqual(
            "http://alist.example.com:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            public_url,
        )
        self.assertEqual(
            "http://192.0.2.10:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            request_url,
        )

    def test_ffmpeg_input_prefers_public_signed_download_url(self):
        provider = self.create_provider(token="static-token")
        provider._fetch_raw_url = lambda path: (_ for _ in ()).throw(AssertionError("should not use raw url first"))

        self.assertEqual(
            "http://alist.local:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            provider.get_ffmpeg_input("电影/movie.mkv"),
        )

    def test_build_download_url_keeps_base_path(self):
        provider = self.create_provider(base_url="https://alist.example.com/base", root="/movies", token="static-token")

        self.assertEqual(
            "https://alist.example.com/base/d/movies/Folder%20A/%E7%A4%BA%E4%BE%8B.mkv",
            provider._build_download_url("Folder A/示例.mkv"),
        )

    def test_stream_can_proxy_when_enabled(self):
        provider = self.create_provider(token="static-token", proxy_stream=True)
        stream, status, length, location = provider.get_stream_data("电影/movie.mkv", "bytes=0-99")

        self.assertIsNone(stream)
        self.assertEqual(302, status)
        self.assertEqual(0, length)
        self.assertEqual(
            "http://alist.local:5244/d/library/%E7%94%B5%E5%BD%B1/movie.mkv?sign=signed-token",
            location,
        )

    def test_login_token_is_requested_when_token_missing(self):
        provider = self.create_provider()
        provider.list_items("")

        post_urls = [call[1] for call in provider.session.calls if call[0] == "POST"]
        self.assertTrue(any(url.endswith('/api/auth/login') for url in post_urls))

    def test_login_token_is_cached_across_preview_instances(self):
        first = self.create_provider()
        first.list_items("")

        second = self.create_provider()
        second.list_items("")

        second_post_urls = [call[1] for call in second.session.calls if call[0] == "POST"]
        self.assertFalse(any(url.endswith('/api/auth/login') for url in second_post_urls))
        self.assertTrue(any(url.endswith('/api/fs/list') for url in second_post_urls))


if __name__ == "__main__":
    unittest.main()
