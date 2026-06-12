from __future__ import annotations

import sys
import unittest
from datetime import datetime

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import generate_password_hash

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Library, LibrarySource, MediaResource, Movie, StorageSource, User, UserFavorite, UserVaultSecret
from backend.app.services.login_rate_limit import clear_all_login_failures
from backend.app.services.users import set_user_password


class FavoritesLibraryTests(unittest.TestCase):
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
        self.admin = self._user("admin", role=User.ROLE_ADMIN)
        self._login("admin")

        self.source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        self.library = Library(name="电影库", slug="movies")
        db.session.add_all([self.source, self.library])
        db.session.commit()
        db.session.add(LibrarySource(library_id=self.library.id, source_id=self.source.id, root_path="movies"))
        db.session.commit()

    def tearDown(self):
        clear_all_login_failures()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _user(self, username, role=User.ROLE_USER, password="password-123"):
        user = User(username=username, display_name=username, role=role, is_enabled=True)
        set_user_password(user, password)
        db.session.add(user)
        db.session.commit()
        return user

    def _login(self, username, password="password-123"):
        response = self.client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response

    def _setup_vault(self, pin="123456"):
        response = self.client.post("/api/v1/user/vault/password", json={"pin": pin})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        data = response.get_json()["data"]
        self.assertTrue(data["configured"])
        self.assertTrue(data["unlocked"])
        return response

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

    def test_favorites_library_is_accessible_directly_but_never_listed_as_media_library(self):
        movie = self._movie("Favorite")

        libraries = self.client.get("/api/v1/libraries").get_json()["data"]
        self.assertNotIn("favorites", [item["id"] for item in libraries])
        self.assertEqual(403, self.client.get("/api/v1/libraries/favorites").status_code)

        self._setup_vault()
        self.assertEqual(404, self.client.get("/api/v1/libraries/favorites").status_code)

        add_response = self.client.post(f"/api/v1/user/favorites/{movie.id}")
        self.assertEqual(200, add_response.status_code)
        add_data = add_response.get_json()["data"]
        self.assertTrue(add_data["newly_added"])
        self.assertEqual("favorites", add_data["library"]["id"])
        self.assertFalse(add_data["library"]["actions"]["can_scan"])

        libraries = self.client.get("/api/v1/libraries").get_json()["data"]
        self.assertNotIn("favorites", [item["id"] for item in libraries])

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
        self._setup_vault()

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

    def test_vault_lock_requires_unlock_before_favorites_can_be_read(self):
        movie = self._movie("Locked")
        self._setup_vault()
        self.assertEqual(200, self.client.post(f"/api/v1/user/favorites/{movie.id}").status_code)

        lock_response = self.client.post("/api/v1/user/vault/lock")
        locked_list = self.client.get("/api/v1/user/favorites")
        wrong_unlock = self.client.post("/api/v1/user/vault/unlock", json={"pin": "654321"})
        unlock_response = self.client.post("/api/v1/user/vault/unlock", json={"pin": "123456"})
        unlocked_list = self.client.get("/api/v1/user/favorites")

        self.assertEqual(200, lock_response.status_code)
        self.assertFalse(lock_response.get_json()["data"]["unlocked"])
        self.assertEqual(403, locked_list.status_code)
        self.assertEqual(403, wrong_unlock.status_code)
        self.assertEqual(200, unlock_response.status_code)
        self.assertTrue(unlock_response.get_json()["data"]["unlocked"])
        self.assertEqual(200, unlocked_list.status_code)

    def test_vault_pin_must_be_six_digits_and_not_login_password(self):
        self.admin.password_hash = generate_password_hash("123456")
        db.session.commit()

        short_pin = self.client.post("/api/v1/user/vault/password", json={"pin": "12345"})
        login_password_pin = self.client.post("/api/v1/user/vault/password", json={"pin": "123456"})

        self.assertEqual(400, short_pin.status_code)
        self.assertEqual(400, login_password_pin.status_code)

    def test_vault_pin_change_limit_locks_after_ten_daily_changes(self):
        self._setup_vault()
        secret = UserVaultSecret.query.one()
        secret.pin_change_window_started_at = datetime.utcnow()
        secret.pin_change_count = 10
        db.session.commit()

        change_response = self.client.post("/api/v1/user/vault/password", json={
            "current_pin": "123456",
            "new_pin": "234567",
        })
        status_response = self.client.get("/api/v1/user/vault/status")
        unlock_response = self.client.post("/api/v1/user/vault/unlock", json={"pin": "123456"})

        self.assertEqual(423, change_response.status_code)
        status_data = status_response.get_json()["data"]
        self.assertTrue(status_data["locked"])
        self.assertEqual(0, status_data["pin_changes_remaining_today"])
        self.assertEqual(423, unlock_response.status_code)


class DefaultAdminVaultModeTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "USER_MANAGEMENT_ENABLED": False,
            "SECRET_KEY": "test-session-secret",
            "AUTH_ENABLED": False,
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

    def test_default_scope_is_temporary_admin_but_still_requires_pin(self):
        movie = Movie(
            tmdb_id="movie/default-vault",
            title="Default Vault",
            cover="https://img.example/default-vault.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        status = self.client.get("/api/v1/user/vault/status")
        before_pin = self.client.post(f"/api/v1/user/favorites/{movie.id}")
        setup = self.client.post("/api/v1/user/vault/password", json={"pin": "123456"})
        saved = self.client.post(f"/api/v1/user/favorites/{movie.id}")
        listed = self.client.get("/api/v1/user/favorites")
        libraries = self.client.get("/api/v1/libraries")

        self.assertEqual(200, status.status_code)
        self.assertFalse(status.get_json()["data"]["configured"])
        self.assertEqual(403, before_pin.status_code)
        self.assertEqual(200, setup.status_code)
        self.assertEqual(200, saved.status_code)
        self.assertEqual([movie.id], listed.get_json()["data"]["movie_ids"])
        self.assertNotIn("favorites", [item["id"] for item in libraries.get_json()["data"]])
        secret = UserVaultSecret.query.one()
        self.assertEqual("default", secret.scope_key)
        self.assertIsNone(secret.user_id)


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

    def _user(self, username, role=User.ROLE_USER):
        user = User(username=username, display_name=username, role=role, is_enabled=True)
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

    def test_vault_and_favorites_are_isolated_between_user_sessions(self):
        movie = self._movie()

        admin = self._user("admin", role=User.ROLE_ADMIN)
        alice = User.query.filter_by(username="alice").one()
        self._login("admin")
        self.assertEqual(200, self.client.post("/api/v1/user/vault/password", json={"pin": "123456"}).status_code)
        self.assertEqual(200, self.client.post(f"/api/v1/user/favorites/{movie.id}").status_code)
        self.assertEqual([], [
            item["id"]
            for item in self.client.get("/api/v1/libraries").get_json()["data"]
            if item["id"] == "favorites"
        ])
        self.client.post("/api/v1/auth/logout")

        self._login("alice")
        alice_status = self.client.get("/api/v1/user/vault/status")
        self.assertEqual([], [
            item["id"]
            for item in self.client.get("/api/v1/libraries").get_json()["data"]
            if item["id"] == "favorites"
        ])
        self.assertEqual(200, alice_status.status_code)
        self.assertFalse(alice_status.get_json()["data"]["configured"])
        self.assertEqual(403, self.client.get("/api/v1/user/favorites").status_code)
        self.assertEqual(403, self.client.post(f"/api/v1/user/favorites/{movie.id}").status_code)
        self.assertEqual(200, self.client.post("/api/v1/user/vault/password", json={"pin": "654321"}).status_code)
        self.assertEqual(200, self.client.post(f"/api/v1/user/favorites/{movie.id}").status_code)
        self.assertEqual([movie.id], self.client.get("/api/v1/user/favorites").get_json()["data"]["movie_ids"])
        secrets = {
            row.scope_key: row.user_id
            for row in UserVaultSecret.query.order_by(UserVaultSecret.scope_key.asc()).all()
        }
        self.assertEqual({
            f"user:{alice.id}": alice.id,
            f"user:{admin.id}": admin.id,
        }, secrets)


if __name__ == "__main__":
    unittest.main()
