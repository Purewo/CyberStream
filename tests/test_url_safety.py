from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.url_safety import UnsafePublicUrlError, validate_public_http_url


class PublicHttpUrlSafetyTests(unittest.TestCase):
    def test_allows_public_http_url(self):
        self.assertEqual(
            "https://cdn.example.com/video.m3u8?token=abc",
            validate_public_http_url(" https://cdn.example.com/video.m3u8?token=abc "),
        )

    def test_rejects_relative_url(self):
        with self.assertRaises(UnsafePublicUrlError) as ctx:
            validate_public_http_url("/internal/video.m3u8")

        self.assertEqual("invalid", ctx.exception.reason)

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(UnsafePublicUrlError) as ctx:
            validate_public_http_url("file:///etc/passwd")

        self.assertEqual("invalid", ctx.exception.reason)

    def test_rejects_localhost_with_trailing_dot(self):
        with self.assertRaises(UnsafePublicUrlError) as ctx:
            validate_public_http_url("http://localhost./internal")

        self.assertEqual("blocked_host", ctx.exception.reason)

    def test_rejects_legacy_ipv4_loopback(self):
        with self.assertRaises(UnsafePublicUrlError) as ctx:
            validate_public_http_url("http://2130706433/internal")

        self.assertEqual("blocked_host", ctx.exception.reason)

    def test_rejects_link_local_ipv4(self):
        with self.assertRaises(UnsafePublicUrlError) as ctx:
            validate_public_http_url("http://169.254.169.254/latest/meta-data/")

        self.assertEqual("blocked_host", ctx.exception.reason)


if __name__ == "__main__":
    unittest.main()
