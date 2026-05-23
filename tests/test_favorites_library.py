from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Library, LibrarySource, MediaResource, Movie, StorageSource, User, UserFavorite
from backend.app.services.login_rate_limit import clear_all_login_failures
from backend.app.services.users import set_user_password


class FavoritesLibraryTests(unittest.TestCase):
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

        self.source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        self.library = Library(name="电影库", slug="movies")
        db.session.add_all([self.source, self.library])
        db.session.commit()
        db.session.add(LibrarySource(library_id=self.library.id, source_id=self.source.id, root_path="movies"))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie(self, title):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            cover=f"https://img.example/{title}.jpg",
            category=["科幻"],
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path=f"movies/{title}.mkv",
            filename=f"{title}.mkv",
        ))
        db.session.commit()
        return movie

    def test_favorites_library_appears_after_first_favorite_and_disappears_after_last_remove(self):
        movie = self._movie("Favorite")

        libraries = self.client.get("/api/v1/libraries").get_json()["data"]
        self.assertNotIn("favorites", [item["id"] for item in libraries])
        self.assertEqual(404, self.client.get("/api/v1/libraries/favorites").status_code)

        add_response = self.client.post(f"/api/v1/user/favorites/{movie.id}")
        self.assertEqual(200, add_response.status_code)
        add_data = add_response.get_json()["data"]
        self.assertTrue(add_data["newly_added"])
        self.assertEqual("favorites", add_data["library"]["id"])
        self.assertFalse(add_data["library"]["actions"]["can_scan"])

        libraries = self.client.get("/api/v1/libraries").get_json()["data"]
        self.assertEqual("favorites", libraries[0]["id"])
        self.assertEqual("我的收藏", libraries[0]["name"])

        movies_response = self.client.get("/api/v1/libraries/favorites/movies")
        self.assertEqual(200, movies_response.status_code)
        movies_data = movies_response.get_json()["data"]
        self.assertEqual([movie.id], [item["id"] for item in movies_data["items"]])
        self.assertEqual("favorite", movies_data["items"][0]["library_membership"])

        self.assertEqual(404, self.client.post("/api/v1/libraries/favorites/scan").status_code)

        remove_response = self.client.delete(f"/api/v1/user/favorites/{movie.id}")
        self.assertEqual(200, remove_response.status_code)
        self.assertTrue(remove_response.get_json()["data"]["removed"])
        libraries = self.client.get("/api/v1/libraries").get_json()["data"]
        self.assertNotIn("favorites", [item["id"] for item in libraries])

    def test_favorite_add_is_idempotent_and_list_endpoint_returns_movie_ids(self):
        movie = self._movie("Idempotent")

        first = self.client.post(f"/api/v1/user/favorites/{movie.id}")
        second = self.client.post(f"/api/v1/user/favorites/{movie.id}")
        list_response = self.client.get("/api/v1/user/favorites?include_movies=true")
        state_response = self.client.get(f"/api/v1/user/favorites/{movie.id}")

        self.assertEqual(200, first.status_code)
        self.assertTrue(first.get_json()["data"]["newly_added"])
        self.assertEqual(200, second.status_code)
        self.assertFalse(second.get_json()["data"]["newly_added"])
        self.assertEqual(1, UserFavorite.query.count())
        list_data = list_response.get_json()["data"]
        self.assertEqual([movie.id], list_data["movie_ids"])
        self.assertEqual(movie.id, list_data["items"][0]["movie"]["id"])
        self.assertTrue(state_response.get_json()["data"]["is_favorite"])


class FavoritesUserIsolationTests(unittest.TestCase):
    def setUp(self):
        clear_all_login_failures()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "USER_MANAGEMENT_ENABLED": True,
            "SESSION_SECRET": "test-session-secret",
            "SECRET_KEY": "test-session-secret",
            "API_TOKEN": "",
            "AUTH_ENABLED": False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        self._user("alice")
        self._user("bob")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        library = Library(name="电影库", slug="movies")
        db.session.add_all([source, library])
        db.session.commit()
        db.session.add(LibrarySource(library_id=library.id, source_id=source.id, root_path="movies"))
        db.session.commit()
        self.source = source

    def tearDown(self):
        clear_all_login_failures()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _user(self, username):
        user = User(username=username, display_name=username, role=User.ROLE_USER, is_enabled=True)
        set_user_password(user, "password-123")
        db.session.add(user)
        db.session.commit()
        return user

    def _login(self, username):
        response = self.client.post("/api/v1/auth/login", json={"username": username, "password": "password-123"})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))

    def _movie(self):
        movie = Movie(
            tmdb_id="movie/shared-favorite",
            title="Shared Favorite",
            original_title="Shared Favorite",
            cover="https://img.example/shared.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="movies/shared.mkv",
            filename="shared.mkv",
        ))
        db.session.commit()
        return movie

    def test_favorites_are_isolated_by_login_user(self):
        movie = self._movie()

        self._login("alice")
        self.assertEqual(200, self.client.post(f"/api/v1/user/favorites/{movie.id}").status_code)
        self.assertEqual(["favorites"], [
            item["id"]
            for item in self.client.get("/api/v1/libraries").get_json()["data"]
            if item["id"] == "favorites"
        ])
        self.client.post("/api/v1/auth/logout")

        self._login("bob")
        self.assertEqual([], [
            item["id"]
            for item in self.client.get("/api/v1/libraries").get_json()["data"]
            if item["id"] == "favorites"
        ])


if __name__ == "__main__":
    unittest.main()
