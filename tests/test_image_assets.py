from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import requests

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie


JPEG_BYTES = b"\xff\xd8\xff\xe0poster-data\xff\xd9"
ALT_JPEG_BYTES = b"\xff\xd8\xff\xe0poster-data-refetched\xff\xd9"


class FakeImageResponse:
    def __init__(self, body=JPEG_BYTES, content_type="image/jpeg", status_code=200):
        self.body = body
        self.status_code = status_code
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size=65536):
        yield self.body

    def close(self):
        pass


class FakeCDNResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self.payload = payload or {}
        self.status_code = status_code
        self.text = text
        self.content = b"{}"

    def json(self):
        return self.payload


class MovieImageAssetTests(unittest.TestCase):
    def setUp(self):
        self.cache_dir = tempfile.mkdtemp(prefix="cyber-image-assets-")
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "CACHE_DIR": self.cache_dir,
            "TMDB_PROXIES": None,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def _movie(self, cover="https://image.tmdb.org/t/p/w500/poster.jpg", background_cover=None, scraper_source="TMDB"):
        movie = Movie(
            tmdb_id="movie/image-assets",
            title="Image Assets",
            original_title="Image Assets",
            year=2026,
            cover=cover,
            background_cover=background_cover,
            category=["科幻"],
            scraper_source=scraper_source,
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def test_movie_payload_exposes_backend_image_asset_urls(self):
        movie = self._movie(background_cover="https://image.tmdb.org/t/p/original/backdrop.jpg")

        list_response = self.client.get("/api/v1/movies?page_size=10")
        list_item = list_response.get_json()["data"]["items"][0]
        detail_response = self.client.get(f"/api/v1/movies/{movie.id}")
        detail = detail_response.get_json()["data"]

        self.assertEqual(f"/api/v1/movies/{movie.id}/images/poster", list_item["poster_asset_url"])
        self.assertEqual(f"/api/v1/movies/{movie.id}/images/poster", detail["poster_asset_url"])
        self.assertEqual(f"/api/v1/movies/{movie.id}/images/backdrop", detail["backdrop_asset_url"])
        self.assertEqual("local", list_item["poster_asset_urls"]["source"])
        self.assertEqual(
            ["https://image.tmdb.org/t/p/w500/poster.jpg"],
            list_item["poster_asset_fallback_urls"],
        )
        self.assertEqual(
            f"/api/v1/movies/{movie.id}/images/poster",
            list_item["poster_asset_urls"]["local_url"],
        )
        self.assertEqual(
            "https://image.tmdb.org/t/p/w500/poster.jpg",
            list_item["poster_asset_urls"]["original_url"],
        )
        self.assertEqual("tmdb", list_item["poster_source_info"]["provider"])
        self.assertEqual("external_metadata", list_item["poster_source_info"]["source_type"])
        self.assertEqual("cover", list_item["poster_source_info"]["field"])
        self.assertEqual("tmdb", detail["backdrop_source_info"]["provider"])
        self.assertEqual("background_cover", detail["backdrop_source_info"]["field"])

    def test_movie_payload_uses_configured_image_asset_public_base_url(self):
        movie = self._movie(background_cover="https://image.tmdb.org/t/p/original/backdrop.jpg")
        self.app.config["IMAGE_ASSET_PUBLIC_BASE_URL"] = "https://cdn.example.test/assets/"

        list_response = self.client.get("/api/v1/movies?page_size=10")
        list_item = list_response.get_json()["data"]["items"][0]
        detail_response = self.client.get(f"/api/v1/movies/{movie.id}")
        detail = detail_response.get_json()["data"]
        status_response = self.client.get(f"/api/v1/movies/{movie.id}/images/status?kind=poster")
        status_item = status_response.get_json()["data"]["items"][0]

        self.assertEqual(
            f"https://cdn.example.test/assets/api/v1/movies/{movie.id}/images/poster",
            list_item["poster_asset_url"],
        )
        self.assertEqual(
            f"https://cdn.example.test/assets/api/v1/movies/{movie.id}/images/poster",
            detail["poster_asset_url"],
        )
        self.assertEqual(
            f"https://cdn.example.test/assets/api/v1/movies/{movie.id}/images/backdrop",
            detail["backdrop_asset_url"],
        )
        self.assertEqual(
            f"https://cdn.example.test/assets/api/v1/movies/{movie.id}/images/poster",
            status_item["asset_url"],
        )
        self.assertEqual(
            ["https://image.tmdb.org/t/p/w500/poster.jpg"],
            status_item["fallback_urls"],
        )
        self.assertEqual(
            f"https://cdn.example.test/assets/api/v1/movies/{movie.id}/images/poster",
            status_item["asset_urls"]["local_url"],
        )
        self.assertEqual("tmdb", status_item["source_info"]["provider"])

    def test_movie_payload_marks_locked_image_field_as_manual_source(self):
        movie = self._movie(cover="https://image.tmdb.org/t/p/w500/manual-poster.jpg")
        movie.set_locked_fields(["cover"])
        db.session.commit()

        detail_response = self.client.get(f"/api/v1/movies/{movie.id}")
        detail = detail_response.get_json()["data"]

        self.assertEqual("manual", detail["poster_source_info"]["provider"])
        self.assertEqual("manual_override", detail["poster_source_info"]["source_type"])
        self.assertTrue(detail["poster_source_info"]["locked"])
        self.assertIn("metadata_field_locked", detail["poster_source_info"]["evidence"])

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_endpoint_fetches_and_reuses_cached_poster(self, mock_get):
        movie = self._movie()
        mock_get.return_value = FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg")

        first = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")
        second = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")

        self.assertEqual(200, first.status_code)
        self.assertEqual(JPEG_BYTES, first.data)
        self.assertEqual("miss", first.headers.get("X-Cyber-Image-Cache"))
        self.assertEqual(200, second.status_code)
        self.assertEqual(JPEG_BYTES, second.data)
        self.assertEqual("hit", second.headers.get("X-Cyber-Image-Cache"))
        self.assertEqual(1, mock_get.call_count)
        first.close()
        second.close()

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_status_reports_cache_state(self, mock_get):
        movie = self._movie(background_cover="")
        mock_get.return_value = FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg")

        before = self.client.get(f"/api/v1/movies/{movie.id}/images/status")
        before_items = {
            item["kind"]: item
            for item in before.get_json()["data"]["items"]
        }
        self.assertEqual("missing", before_items["poster"]["cache_state"])
        self.assertFalse(before_items["poster"]["cached"])
        self.assertEqual("missing_source", before_items["backdrop"]["cache_state"])

        fetched = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")
        self.assertEqual(200, fetched.status_code)

        after = self.client.get(f"/api/v1/movies/{movie.id}/images/status?kind=poster")
        after_items = after.get_json()["data"]["items"]
        self.assertEqual(1, len(after_items))
        self.assertEqual("cached", after_items[0]["cache_state"])
        self.assertTrue(after_items[0]["cached"])
        self.assertEqual("tmdb", after_items[0]["source_info"]["provider"])
        self.assertEqual("poster.jpg", after_items[0]["cache"]["filename"])
        self.assertEqual("tmdb", after_items[0]["cache"]["source_info"]["provider"])
        fetched.close()

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_preload_fetches_available_images_and_skips_missing_sources(self, mock_get):
        movie = self._movie(background_cover="")
        mock_get.return_value = FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg")

        response = self.client.post(
            "/api/v1/images/preload",
            json={
                "movie_ids": [movie.id],
                "kinds": ["poster", "backdrop"],
            },
        )
        payload = response.get_json()
        items = {(item["movie_id"], item["kind"]): item for item in payload["data"]["items"]}

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, payload["data"]["summary"]["cached"])
        self.assertEqual(1, payload["data"]["summary"]["skipped"])
        self.assertEqual("cached", items[(movie.id, "poster")]["status"])
        self.assertEqual("miss", items[(movie.id, "poster")]["reason"])
        self.assertEqual("skipped", items[(movie.id, "backdrop")]["status"])
        self.assertEqual("missing_source", items[(movie.id, "backdrop")]["reason"])
        self.assertEqual(1, mock_get.call_count)

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_preload_accepts_string_false_refresh(self, mock_get):
        movie = self._movie()
        mock_get.return_value = FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg")

        first = self.client.post(
            "/api/v1/images/preload",
            json={"movie_ids": [movie.id], "kinds": ["poster"]},
        )
        second = self.client.post(
            "/api/v1/images/preload",
            json={"movie_ids": [movie.id], "kinds": ["poster"], "refresh": "false"},
        )

        self.assertEqual("miss", first.get_json()["data"]["items"][0]["reason"])
        self.assertEqual("hit", second.get_json()["data"]["items"][0]["reason"])
        self.assertEqual(1, mock_get.call_count)

    def test_movie_image_preload_reports_missing_movie(self):
        response = self.client.post(
            "/api/v1/images/preload",
            json={
                "movie_ids": ["00000000-0000-0000-0000-000000000000"],
                "kinds": ["poster"],
            },
        )
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, payload["data"]["summary"]["failed"])
        self.assertEqual("movie_not_found", payload["data"]["items"][0]["reason"])

    def test_movie_image_preload_rejects_unsupported_kind(self):
        response = self.client.post(
            "/api/v1/images/preload",
            json={
                "movie_ids": ["00000000-0000-0000-0000-000000000000"],
                "kinds": ["logo"],
            },
        )
        payload = response.get_json()

        self.assertEqual(400, response.status_code)
        self.assertEqual(40082, payload["code"])

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_refresh_plans_cdn_purge_and_preloads(self, mock_get):
        movie = self._movie()
        self.app.config["IMAGE_ASSET_PUBLIC_BASE_URL"] = "https://cdn.example.test"
        mock_get.return_value = FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg")

        response = self.client.post(
            "/api/v1/images/refresh",
            json={
                "movie_ids": [movie.id],
                "kinds": ["poster"],
            },
        )
        payload = response.get_json()
        data = payload["data"]
        item = data["items"][0]

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, data["summary"]["refreshed"])
        self.assertEqual("refreshed", item["status"])
        self.assertEqual("miss", item["reason"])
        self.assertEqual("planned", item["purge"]["status"])
        self.assertEqual("cdn_provider_not_configured", item["purge"]["reason"])
        self.assertEqual(
            [f"https://cdn.example.test/api/v1/movies/{movie.id}/images/poster"],
            item["purge"]["urls"],
        )
        self.assertEqual("cached", item["preload"]["status"])
        self.assertEqual("cached", item["after"]["cache_state"])
        self.assertEqual(1, mock_get.call_count)

    @patch("backend.app.services.cdn_assets.requests.get")
    @patch("backend.app.services.cdn_assets.requests.request")
    def test_movie_image_refresh_uploads_to_supercdn_china_all_bucket(self, mock_cdn_request, mock_get):
        movie = self._movie()
        self.app.config.update({
            "CDN_PROVIDER": "supercdn",
            "SUPERCDN_ENABLED": True,
            "SUPERCDN_URL": "https://qwk.ccwu.cc",
            "SUPERCDN_TOKEN": "root-token",
            "SUPERCDN_BUCKET": "cyberstream-cn-assets",
            "SUPERCDN_ROUTE_PROFILE": "china_all",
        })

        def get_request(url, **_kwargs):
            if str(url).startswith("https://image.tmdb.org/"):
                return FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg")
            if str(url).endswith("/api/v1/asset-buckets/cyberstream-cn-assets"):
                return FakeCDNResponse(status_code=404, text="not found")
            raise AssertionError(url)

        mock_get.side_effect = get_request

        def cdn_request(method, url, **kwargs):
            if url.endswith("/api/v1/asset-buckets"):
                self.assertEqual("china_all", kwargs["json"]["route_profile"])
                self.assertEqual("cyberstream-cn-assets", kwargs["json"]["slug"])
                self.assertEqual(["image", "document"], kwargs["json"]["allowed_types"])
                return FakeCDNResponse({
                    "slug": "cyberstream-cn-assets",
                    "route_profile": "china_all",
                }, status_code=201)

            self.assertIn("/api/v1/asset-buckets/cyberstream-cn-assets/objects", url)
            logical_path = kwargs["data"]["path"]
            self.assertTrue(logical_path.startswith(f"images/movies/{movie.id}/poster/"))
            self.assertEqual("image", kwargs["data"]["asset_type"])
            return FakeCDNResponse({
                "bucket": "cyberstream-cn-assets",
                "url": f"/a/cyberstream-cn-assets/{logical_path}",
                "public_url": f"https://qwk.ccwu.cc/a/cyberstream-cn-assets/{logical_path}",
                "urls": [f"https://qwk.ccwu.cc/a/cyberstream-cn-assets/{logical_path}"],
            }, status_code=201)

        mock_cdn_request.side_effect = cdn_request

        response = self.client.post(
            "/api/v1/images/refresh",
            json={
                "movie_ids": [movie.id],
                "kinds": ["poster"],
                "purge": False,
            },
        )
        item = response.get_json()["data"]["items"][0]

        self.assertEqual(200, response.status_code)
        self.assertEqual("refreshed", item["status"])
        self.assertEqual("cached", item["cdn"]["status"])
        self.assertEqual("uploaded", item["after"]["cdn"]["status"])
        self.assertEqual("cyberstream-cn-assets", item["after"]["cdn"]["bucket"])
        self.assertEqual("china_all", item["after"]["cdn"]["route_profile"])
        self.assertTrue(item["after"]["asset_url"].startswith("https://qwk.ccwu.cc/a/cyberstream-cn-assets/"))
        self.assertEqual("cdn", item["after"]["asset_urls"]["source"])
        self.assertEqual(
            [
                f"/api/v1/movies/{movie.id}/images/poster",
                "https://image.tmdb.org/t/p/w500/poster.jpg",
            ],
            item["after"]["fallback_urls"],
        )
        self.assertEqual({"cached": 1}, response.get_json()["data"]["summary"]["cdn_status_counts"])
        self.assertEqual(2, mock_get.call_count)

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_refresh_can_clear_local_cache_before_preload(self, mock_get):
        movie = self._movie()
        mock_get.side_effect = [
            FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg"),
            FakeImageResponse(body=ALT_JPEG_BYTES, content_type="image/jpeg"),
        ]

        first = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")
        self.assertEqual(200, first.status_code)
        first.close()

        response = self.client.post(
            "/api/v1/images/refresh",
            json={
                "movie_ids": [movie.id],
                "kinds": ["poster"],
                "clear_cache": True,
            },
        )
        item = response.get_json()["data"]["items"][0]
        refetched = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")

        self.assertEqual(200, response.status_code)
        self.assertEqual("refreshed", item["status"])
        self.assertEqual("cleared", item["clear_cache"]["status"])
        self.assertEqual("cached", item["preload"]["status"])
        self.assertEqual("missing", item["clear_cache"]["after"]["cache_state"])
        self.assertEqual("cached", item["after"]["cache_state"])
        self.assertEqual(200, refetched.status_code)
        self.assertEqual(ALT_JPEG_BYTES, refetched.data)
        self.assertEqual("hit", refetched.headers.get("X-Cyber-Image-Cache"))
        self.assertEqual(2, mock_get.call_count)
        refetched.close()

    def test_movie_image_refresh_reports_missing_movie(self):
        response = self.client.post(
            "/api/v1/images/refresh",
            json={
                "movie_ids": ["00000000-0000-0000-0000-000000000000"],
                "kinds": ["poster"],
            },
        )
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, payload["data"]["summary"]["failed"])
        self.assertEqual("movie_not_found", payload["data"]["items"][0]["reason"])

    def test_movie_image_refresh_rejects_unsupported_kind(self):
        response = self.client.post(
            "/api/v1/images/refresh",
            json={
                "movie_ids": ["00000000-0000-0000-0000-000000000000"],
                "kinds": ["logo"],
            },
        )
        payload = response.get_json()

        self.assertEqual(400, response.status_code)
        self.assertEqual(40082, payload["code"])

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_cache_delete_clears_local_cache(self, mock_get):
        movie = self._movie()
        mock_get.side_effect = [
            FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg"),
            FakeImageResponse(body=ALT_JPEG_BYTES, content_type="image/jpeg"),
        ]

        first = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")
        self.assertEqual(200, first.status_code)
        first.close()

        response = self.client.delete(f"/api/v1/movies/{movie.id}/images/poster")
        payload = response.get_json()
        data = payload["data"]

        self.assertEqual(200, response.status_code)
        self.assertEqual("cleared", data["status"])
        self.assertEqual("poster", data["kind"])
        self.assertTrue(data["deleted_metadata"])
        self.assertEqual(["poster.jpg"], [item["filename"] for item in data["deleted_files"]])
        self.assertTrue(data["deleted_files"][0]["relative_path"].endswith(f"{movie.id}/poster.jpg"))
        self.assertEqual("cached", data["before"]["cache_state"])
        self.assertEqual("missing", data["after"]["cache_state"])

        status = self.client.get(f"/api/v1/movies/{movie.id}/images/status?kind=poster")
        status_item = status.get_json()["data"]["items"][0]
        self.assertEqual("missing", status_item["cache_state"])

        refetched = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")
        self.assertEqual(200, refetched.status_code)
        self.assertEqual(ALT_JPEG_BYTES, refetched.data)
        self.assertEqual("miss", refetched.headers.get("X-Cyber-Image-Cache"))
        self.assertEqual(2, mock_get.call_count)
        refetched.close()

    def test_movie_image_cache_delete_reports_missing_when_no_cache(self):
        movie = self._movie()

        response = self.client.delete(f"/api/v1/movies/{movie.id}/images/poster")
        payload = response.get_json()
        data = payload["data"]

        self.assertEqual(200, response.status_code)
        self.assertEqual("missing", data["status"])
        self.assertEqual([], data["deleted_files"])
        self.assertFalse(data["deleted_metadata"])
        self.assertEqual("missing", data["before"]["cache_state"])
        self.assertEqual("missing", data["after"]["cache_state"])

    def test_movie_image_cache_delete_rejects_unsupported_kind(self):
        movie = self._movie()

        response = self.client.delete(f"/api/v1/movies/{movie.id}/images/logo")
        payload = response.get_json()

        self.assertEqual(400, response.status_code)
        self.assertEqual(40082, payload["code"])

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_endpoint_serves_stale_cache_when_refresh_fails(self, mock_get):
        movie = self._movie()
        mock_get.return_value = FakeImageResponse(body=JPEG_BYTES, content_type="image/jpeg")

        first = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")
        self.assertEqual(200, first.status_code)

        mock_get.side_effect = requests.RequestException("network down")
        refresh = self.client.get(f"/api/v1/movies/{movie.id}/images/poster?refresh=true")

        self.assertEqual(200, refresh.status_code)
        self.assertEqual(JPEG_BYTES, refresh.data)
        self.assertEqual("stale", refresh.headers.get("X-Cyber-Image-Cache"))
        first.close()
        refresh.close()

    def test_movie_image_endpoint_returns_404_when_source_missing(self):
        movie = self._movie(cover="")

        response = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")
        payload = response.get_json()

        self.assertEqual(404, response.status_code)
        self.assertEqual(40480, payload["code"])

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_endpoint_redirects_to_original_when_local_fetch_fails(self, mock_get):
        movie = self._movie()
        mock_get.side_effect = requests.RequestException("network down")

        response = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")

        self.assertEqual(302, response.status_code)
        self.assertEqual("https://image.tmdb.org/t/p/w500/poster.jpg", response.headers.get("Location"))
        self.assertEqual("fallback_original", response.headers.get("X-Cyber-Image-Cache"))
        self.assertEqual("original", response.headers.get("X-Cyber-Image-Fallback"))
        self.assertEqual("50282", response.headers.get("X-Cyber-Image-Error-Code"))

    @patch("backend.app.services.image_assets.requests.get")
    def test_movie_image_endpoint_redirects_to_original_when_source_returns_non_image_body(self, mock_get):
        movie = self._movie()
        mock_get.return_value = FakeImageResponse(body=b"<html>not an image</html>", content_type="image/jpeg")

        response = self.client.get(f"/api/v1/movies/{movie.id}/images/poster")

        self.assertEqual(302, response.status_code)
        self.assertEqual("https://image.tmdb.org/t/p/w500/poster.jpg", response.headers.get("Location"))
        self.assertEqual("fallback_original", response.headers.get("X-Cyber-Image-Cache"))
        self.assertEqual("50283", response.headers.get("X-Cyber-Image-Error-Code"))
