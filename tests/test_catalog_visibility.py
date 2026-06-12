from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie


class CatalogVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
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

    def _movie(self, title, scraper_source="TMDB", cover="poster", description="overview"):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            year=2026,
            cover=cover,
            description=description,
            category=["剧情"],
            scraper_source=scraper_source,
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def _list_movie_ids(self, query_string=None):
        response = self.client.get("/api/v1/movies", query_string=query_string or {})
        self.assertEqual(200, response.status_code)
        return [item["id"] for item in response.get_json()["data"]["items"]]

    def test_auto_visibility_keeps_existing_public_catalog_behavior(self):
        public_movie = self._movie("Public")
        local_movie = self._movie("Local", scraper_source="LOCAL_FALLBACK", cover="")

        movie_ids = self._list_movie_ids()

        self.assertIn(public_movie.id, movie_ids)
        self.assertNotIn(local_movie.id, movie_ids)

        detail_response = self.client.get(f"/api/v1/movies/{public_movie.id}")
        visibility = detail_response.get_json()["data"]["catalog_visibility"]
        self.assertEqual("auto", visibility["status"])
        self.assertTrue(visibility["is_visible"])
        self.assertEqual("auto_public", visibility["reason"])

    def test_hidden_visibility_removes_public_movie_from_global_catalog(self):
        movie = self._movie("Hidden")

        response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "hidden", "note": "not for homepage"},
        )

        self.assertEqual(200, response.status_code)
        visibility = response.get_json()["data"]["catalog_visibility"]
        self.assertEqual("hidden", visibility["status"])
        self.assertFalse(visibility["is_visible"])
        self.assertEqual("manual_hidden", visibility["reason"])
        self.assertNotIn(movie.id, self._list_movie_ids())
        self.assertNotIn(movie.id, self._list_movie_ids({"needs_attention": "true"}))

    def test_pending_review_keeps_ready_movie_out_of_public_catalog(self):
        movie = self._movie("Pending Ready")

        response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "pending_review", "note": "check before publish"},
        )

        self.assertEqual(200, response.status_code)
        visibility = response.get_json()["data"]["catalog_visibility"]
        self.assertEqual("pending_review", visibility["status"])
        self.assertEqual("pending_review", visibility["effective_status"])
        self.assertFalse(visibility["is_visible"])
        self.assertFalse(visibility["auto_visible"])
        self.assertEqual("pending_review", visibility["reason"])
        self.assertNotIn(movie.id, self._list_movie_ids())

    def test_catalog_visibility_force_field_is_strict_boolean(self):
        movie = self._movie("Strict Force")

        accepted_response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "hidden", "force": "false"},
        )
        invalid_response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "auto", "force": "not-a-bool"},
        )

        self.assertEqual(200, accepted_response.status_code)
        self.assertEqual(400, invalid_response.status_code)
        db.session.refresh(movie)
        self.assertEqual(Movie.CATALOG_VISIBILITY_HIDDEN, movie.catalog_visibility_status)

    def test_legacy_catalog_visibility_patch_cannot_publish(self):
        movie = self._movie("Raw", scraper_source="LOCAL_FALLBACK", cover="")

        response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "published", "force": True, "note": "manual catalog item"},
        )

        self.assertEqual(410, response.status_code)
        payload = response.get_json()
        self.assertEqual(41010, payload["code"])
        self.assertIn("/api/v1/metadata/pending-review/publish", payload["msg"])
        self.assertNotIn(movie.id, self._list_movie_ids())

    def test_auto_reset_returns_to_implicit_visibility_rules(self):
        movie = self._movie("Reset", scraper_source="LOCAL_FALLBACK", cover="")
        movie.catalog_visibility_status = Movie.CATALOG_VISIBILITY_PUBLISHED
        db.session.commit()
        self.assertIn(movie.id, self._list_movie_ids())

        response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "auto"},
        )

        self.assertEqual(200, response.status_code)
        visibility = response.get_json()["data"]["catalog_visibility"]
        self.assertEqual("auto", visibility["status"])
        self.assertFalse(visibility["is_visible"])
        self.assertNotIn(movie.id, self._list_movie_ids())


if __name__ == "__main__":
    unittest.main()
