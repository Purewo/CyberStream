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

    def test_publish_requires_force_when_movie_is_not_public_ready(self):
        movie = self._movie("Raw", scraper_source="LOCAL_FALLBACK", cover="")

        blocked_response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "published"},
        )

        self.assertEqual(409, blocked_response.status_code)
        blocked_payload = blocked_response.get_json()
        self.assertEqual(40901, blocked_payload["code"])
        self.assertTrue(blocked_payload["data"]["required_force"])
        blockers = blocked_payload["data"]["catalog_visibility"]["blockers"]
        self.assertIn("metadata_needs_attention", blockers)
        self.assertIn("poster_missing", blockers)
        self.assertNotIn(movie.id, self._list_movie_ids())

        published_response = self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "published", "force": True, "note": "manual catalog item"},
        )

        self.assertEqual(200, published_response.status_code)
        visibility = published_response.get_json()["data"]["catalog_visibility"]
        self.assertEqual("published", visibility["status"])
        self.assertTrue(visibility["is_visible"])
        self.assertEqual("manual_published", visibility["reason"])
        self.assertIn(movie.id, self._list_movie_ids())

    def test_auto_reset_returns_to_implicit_visibility_rules(self):
        movie = self._movie("Reset", scraper_source="LOCAL_FALLBACK", cover="")
        self.client.patch(
            f"/api/v1/movies/{movie.id}/catalog-visibility",
            json={"status": "published", "force": True},
        )
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
