from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.providers.webdav import WebDAVProvider


class FakeWebDAVResponse:
    def __init__(self, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.body = body
        self.text = body.decode("utf-8", errors="replace")
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield self.body

    def close(self):
        self.closed = True


class FakeWebDAVSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.verify = True
        self.trust_env = True
        self.calls = []

    def get(self, url, stream=False, timeout=None, allow_redirects=True, headers=None, auth=None):
        self.calls.append(
            {
                "url": url,
                "stream": stream,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
                "headers": headers,
                "auth": auth,
            }
        )
        return self.response


class FakeWebDAVClient:
    def __init__(self, options, response):
        self.options = options
        self.verify = True
        self.session = FakeWebDAVSession(response)


class WebDAVProviderTests(unittest.TestCase):
    def test_stream_redirect_resolves_relative_location(self):
        response = FakeWebDAVResponse(
            status_code=302,
            headers={"Location": "../download/Movie.mkv"},
        )

        def fake_client(options):
            return FakeWebDAVClient(options, response)

        with patch("backend.app.providers.webdav.Client", side_effect=fake_client):
            provider = WebDAVProvider(
                {
                    "host": "dav.example",
                    "port": 443,
                    "secure": True,
                    "root": "/media",
                    "username": "alice",
                    "password": "secret",
                }
            )
            stream, status, length, location = provider.get_stream_data("Movies/Movie.mkv")

        self.assertIsNone(stream)
        self.assertEqual(302, status)
        self.assertEqual(0, length)
        self.assertEqual("https://dav.example:443/media/download/Movie.mkv", location)
        self.assertTrue(response.closed)
        self.assertEqual(1, len(provider.client.session.calls))
        self.assertFalse(provider.client.session.calls[0]["allow_redirects"])


if __name__ == "__main__":
    unittest.main()
