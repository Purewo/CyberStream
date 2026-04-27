from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Library, LibraryMovieMembership, LibrarySource, MediaResource, Movie, StorageSource


class LibraryMovieMembershipTests(unittest.TestCase):
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

        self.source_a = StorageSource(name="AList A", type="local", config={"root_path": "/mnt/a"})
        self.source_b = StorageSource(name="AList B", type="local", config={"root_path": "/mnt/b"})
        self.library = Library(name="电影库", slug="movies")
        db.session.add_all([self.source_a, self.source_b, self.library])
        db.session.commit()

        db.session.add_all([
            LibrarySource(library_id=self.library.id, source_id=self.source_a.id, root_path="movies", scan_order=0),
            LibrarySource(library_id=self.library.id, source_id=self.source_b.id, root_path="extras", scan_order=1),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie(self, title, category=None, scraper_source="TMDB", cover=None):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            year=2026,
            cover=cover if cover is not None else f"https://img.example/{title}.jpg",
            category=category or ["动作"],
            scraper_source=scraper_source,
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def _resource(self, movie, source, path):
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            label="Movie - 1080P",
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def _library_movie_ids(self):
        response = self.client.get(f"/api/v1/libraries/{self.library.id}/movies")
        self.assertEqual(200, response.status_code)
        return {
            item["id"]: item["library_membership"]
            for item in response.get_json()["data"]["items"]
        }

    def test_library_api_does_not_accept_or_return_library_type(self):
        create_response = self.client.post(
            "/api/v1/libraries",
            json={"name": "新库", "slug": "new-library", "library_type": "anime"},
        )
        self.assertEqual(400, create_response.status_code)
        self.assertIn("library_type", create_response.get_json()["msg"])

        list_response = self.client.get("/api/v1/libraries")
        self.assertEqual(200, list_response.status_code)
        self.assertNotIn("library_type", list_response.get_json()["data"][0])

        update_response = self.client.patch(
            f"/api/v1/libraries/{self.library.id}",
            json={"library_type": "anime"},
        )
        self.assertEqual(400, update_response.status_code)
        self.assertIn("library_type", update_response.get_json()["msg"])

    def test_library_content_includes_multiple_bound_sources(self):
        movie_a = self._movie("Auto A")
        movie_b = self._movie("Auto B")
        outside = self._movie("Outside")
        self._resource(movie_a, self.source_a, "movies/auto-a.mkv")
        self._resource(movie_b, self.source_b, "extras/auto-b.mkv")
        self._resource(outside, self.source_a, "other/outside.mkv")

        movie_ids = self._library_movie_ids()

        self.assertEqual("auto", movie_ids[movie_a.id])
        self.assertEqual("auto", movie_ids[movie_b.id])
        self.assertNotIn(outside.id, movie_ids)

    def test_library_movies_support_pagination_and_sorting(self):
        titles = ["Charlie", "Bravo", "Alpha"]
        movies = [self._movie(title) for title in titles]
        for movie in movies:
            self._resource(movie, self.source_a, f"movies/{movie.title.lower()}.mkv")

        response = self.client.get(
            f"/api/v1/libraries/{self.library.id}/movies?page=1&page_size=2&sort_by=title&order=asc"
        )
        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]

        self.assertEqual(2, len(data["items"]))
        self.assertEqual(3, data["total"])
        self.assertEqual({
            "current_page": 1,
            "page_size": 2,
            "total_items": 3,
            "total_pages": 2,
        }, data["pagination"])
        self.assertEqual(["Alpha", "Bravo"], [item["title"] for item in data["items"]])

        response = self.client.get(
            f"/api/v1/libraries/{self.library.id}/movies?page=2&page_size=2&sort_by=title&order=asc"
        )
        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]

        self.assertEqual(["Charlie"], [item["title"] for item in data["items"]])
        self.assertEqual(3, data["total"])

    def test_media_resource_source_path_is_unique(self):
        first_movie = self._movie("Unique A")
        second_movie = self._movie("Unique B")
        self._resource(first_movie, self.source_a, "movies/unique.mkv")

        db.session.add(MediaResource(
            movie_id=second_movie.id,
            source_id=self.source_a.id,
            path="movies/unique.mkv",
            filename="unique.mkv",
        ))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_manual_include_adds_existing_movie_outside_bound_paths(self):
        manual = self._movie("Manual")

        response = self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "include", "movie_ids": [manual.id], "sort_order": 5},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, LibraryMovieMembership.query.count())

        movie_ids = self._library_movie_ids()
        self.assertEqual("manual", movie_ids[manual.id])

    def test_auto_binding_hides_attention_movie_until_manual_include(self):
        raw_movie = self._movie("Raw Bound", scraper_source="LOCAL_FALLBACK", cover="")
        self._resource(raw_movie, self.source_a, "movies/raw-bound.mkv")

        self.assertNotIn(raw_movie.id, self._library_movie_ids())

        response = self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "include", "movie_ids": [raw_movie.id]},
        )
        self.assertEqual(200, response.status_code)

        movie_ids = self._library_movie_ids()
        self.assertEqual("manual", movie_ids[raw_movie.id])

    def test_manual_exclude_hides_auto_movie_and_delete_restores_it(self):
        auto_movie = self._movie("Auto")
        self._resource(auto_movie, self.source_a, "movies/auto.mkv")

        response = self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "exclude", "movie_ids": [auto_movie.id]},
        )
        self.assertEqual(200, response.status_code)
        self.assertNotIn(auto_movie.id, self._library_movie_ids())

        response = self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships/delete",
            json={"movie_ids": [auto_movie.id]},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.get_json()["data"]["deleted_count"])
        self.assertEqual("auto", self._library_movie_ids()[auto_movie.id])

    def test_auto_and_manual_include_returns_both_without_duplicate(self):
        movie = self._movie("Both")
        self._resource(movie, self.source_a, "movies/both.mkv")

        response = self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "include", "movie_ids": [movie.id]},
        )
        self.assertEqual(200, response.status_code)

        movie_ids = self._library_movie_ids()
        self.assertEqual(1, list(movie_ids.keys()).count(movie.id))
        self.assertEqual("both", movie_ids[movie.id])

    def test_filter_counts_respect_manual_include_and_exclude(self):
        action = self._movie("Action", ["动作"])
        drama = self._movie("Drama", ["剧情"])
        manual = self._movie("Manual Sci-Fi", ["科幻"])
        self._resource(action, self.source_a, "movies/action.mkv")
        self._resource(drama, self.source_a, "movies/drama.mkv")

        self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "include", "movie_ids": [manual.id]},
        )
        self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "exclude", "movie_ids": [drama.id]},
        )

        response = self.client.get(f"/api/v1/libraries/{self.library.id}/filters?include=genres")
        self.assertEqual(200, response.status_code)
        genres = {
            item["name"]: item["count"]
            for item in response.get_json()["data"]["genres"]
        }

        self.assertEqual(1, genres["动作"])
        self.assertEqual(1, genres["科幻"])
        self.assertNotIn("剧情", genres)

    def test_recommendations_and_featured_use_manual_memberships(self):
        manual = self._movie("Manual Featured", ["动作"])
        manual.background_cover = "https://img.example/manual-featured-bg.jpg"
        db.session.commit()

        self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "include", "movie_ids": [manual.id]},
        )

        recommendations_response = self.client.get(
            f"/api/v1/libraries/{self.library.id}/recommendations?strategy=latest&limit=5"
        )
        featured_response = self.client.get(f"/api/v1/libraries/{self.library.id}/featured?limit=5")

        self.assertEqual(200, recommendations_response.status_code)
        self.assertEqual(200, featured_response.status_code)
        self.assertEqual([manual.id], [
            item["id"] for item in recommendations_response.get_json()["data"]
        ])
        self.assertEqual("manual", recommendations_response.get_json()["data"][0]["library_membership"])
        self.assertEqual([manual.id], [
            item["id"] for item in featured_response.get_json()["data"]
        ])
        self.assertEqual("manual", featured_response.get_json()["data"][0]["library_membership"])

    def test_membership_api_rejects_invalid_values(self):
        response = self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "invalid", "movie_ids": ["missing"]},
        )
        self.assertEqual(400, response.status_code)

        response = self.client.post(
            f"/api/v1/libraries/{self.library.id}/movie-memberships",
            json={"mode": "include", "movie_ids": ["missing"]},
        )
        self.assertEqual(404, response.status_code)

    def test_library_scan_route_rejects_when_scanner_lock_is_busy(self):
        with patch("backend.app.api.libraries_routes.scanner_engine") as scanner_mock:
            scanner_mock.try_start_scan.return_value = False

            response = self.client.post(f"/api/v1/libraries/{self.library.id}/scan")

        self.assertEqual(429, response.status_code)


if __name__ == "__main__":
    unittest.main()
