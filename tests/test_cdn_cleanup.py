from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.services.cdn_assets import delete_file_from_supercdn
from backend.app.services.cdn_cleanup import execute_cdn_cleanup_assets


class FakeCDNResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self.payload = payload or {}
        self.status_code = status_code
        self.text = text
        self.content = b"{}"

    def json(self):
        return self.payload


class CDNCleanupTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SUPERCDN_URL": "http://127.0.0.1:8080",
            "SUPERCDN_TOKEN": "test-token",
            "SUPERCDN_BUCKET": "cyberstream-cn-assets",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch("backend.app.services.cdn_assets.requests.request")
    def test_delete_file_calls_object_delete_without_deleting_bucket(self, mock_request):
        mock_request.return_value = FakeCDNResponse({
            "bucket": "cyberstream-cn-assets",
            "logical_path": "images/movies/movie-1/poster/hash.jpg",
            "deleted_local": True,
            "remote": [{"target": "china_all", "status": "deleted"}],
        })

        result = delete_file_from_supercdn(
            "images/movies/movie-1/poster/hash.jpg",
            bucket="cyberstream-cn-assets",
        )

        self.assertEqual("deleted", result["status"])
        method, url = mock_request.call_args.args
        self.assertEqual("DELETE", method)
        self.assertEqual(
            "http://127.0.0.1:8080/api/v1/asset-buckets/cyberstream-cn-assets/objects",
            url,
        )
        self.assertEqual({
            "path": "images/movies/movie-1/poster/hash.jpg",
            "delete_remote": "true",
        }, mock_request.call_args.kwargs["params"])

    @patch("backend.app.services.cdn_assets.requests.request")
    def test_delete_file_treats_missing_object_as_idempotent(self, mock_request):
        mock_request.return_value = FakeCDNResponse(
            {"error": "bucket object not found"},
            status_code=404,
            text="not found",
        )

        result = delete_file_from_supercdn(
            "subtitles/resources/resource-1/subtitle-1/original/hash.srt",
            bucket="cyberstream-cn-assets",
        )

        self.assertEqual("not_found", result["status"])
        self.assertIsNone(result["error"])

    @patch("backend.app.services.cdn_assets.requests.request")
    def test_delete_file_can_use_recorded_bucket_when_default_bucket_missing(self, mock_request):
        self.app.config["SUPERCDN_BUCKET"] = ""
        mock_request.return_value = FakeCDNResponse({
            "bucket": "old-bucket",
            "logical_path": "images/movies/movie-1/poster/hash.jpg",
            "deleted_local": True,
        })

        result = delete_file_from_supercdn(
            "images/movies/movie-1/poster/hash.jpg",
            bucket="old-bucket",
        )

        self.assertEqual("deleted", result["status"])
        self.assertEqual(
            "http://127.0.0.1:8080/api/v1/asset-buckets/old-bucket/objects",
            mock_request.call_args.args[1],
        )

    @patch("backend.app.services.cdn_cleanup.delete_file_from_supercdn")
    def test_execute_cleanup_deduplicates_exact_bucket_paths(self, mock_delete):
        mock_delete.return_value = {
            "provider": "supercdn",
            "bucket": "cyberstream-cn-assets",
            "logical_path": "images/movies/movie-1/poster/hash.jpg",
            "status": "deleted",
        }

        result = execute_cdn_cleanup_assets([
            {
                "provider": "supercdn",
                "bucket": "cyberstream-cn-assets",
                "logical_path": "images/movies/movie-1/poster/hash.jpg",
                "references": [{"kind": "movie_image"}],
            },
            {
                "provider": "supercdn",
                "bucket": "cyberstream-cn-assets",
                "logical_path": "images/movies/movie-1/poster/hash.jpg",
                "references": [{"kind": "movie_image"}],
            },
        ])

        self.assertEqual("completed", result["status"])
        self.assertEqual(1, result["summary"]["total"])
        self.assertEqual(1, mock_delete.call_count)


if __name__ == "__main__":
    unittest.main()
