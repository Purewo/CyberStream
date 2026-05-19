from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import (
    AuditLog,
    Library,
    LibrarySource,
    MediaResource,
    Movie,
    StorageSource,
    User,
    UserLibraryRule,
    UserSubtitleSetting,
)
from backend.app.services.login_rate_limit import clear_all_login_failures
from backend.app.services.users import set_user_password


class UserManagementTests(unittest.TestCase):
    def create_enabled_app(self, **overrides):
        clear_all_login_failures()
        config = {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "USER_MANAGEMENT_ENABLED": True,
            "SESSION_SECRET": "test-session-secret",
            "SECRET_KEY": "test-session-secret",
            "API_TOKEN": "",
            "AUTH_ENABLED": False,
        }
        config.update(overrides)
        app = create_app(config)
        ctx = app.app_context()
        ctx.push()
        self.addCleanup(lambda: self._cleanup(ctx))
        return app

    def _cleanup(self, ctx):
        clear_all_login_failures()
        db.session.remove()
        db.drop_all()
        ctx.pop()

    def _user(self, username, role=User.ROLE_USER, password="password-123"):
        user = User(username=username, display_name=username, role=role, is_enabled=True)
        set_user_password(user, password)
        db.session.add(user)
        db.session.commit()
        return user

    def _login(self, client, username, password="password-123"):
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response

    def _movie_with_resource(self, title, source, path):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            cover=f"https://img.example/{title}.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.flush()
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            label="Movie",
        )
        db.session.add(resource)
        db.session.commit()
        return movie, resource

    def _library(self, name, source, root_path):
        library = Library(name=name, slug=name.lower())
        db.session.add(library)
        db.session.commit()
        db.session.add(LibrarySource(library_id=library.id, source_id=source.id, root_path=root_path))
        db.session.commit()
        return library

    def test_bootstrap_admin_is_created_when_enabled(self):
        app = self.create_enabled_app(
            BOOTSTRAP_ADMIN_USERNAME="owner",
            BOOTSTRAP_ADMIN_PASSWORD="password-123",
            BOOTSTRAP_ADMIN_DISPLAY_NAME="Owner",
        )
        client = app.test_client()

        response = self._login(client, "owner")
        me_response = client.get("/api/v1/auth/me")

        data = response.get_json()["data"]
        self.assertEqual("owner", data["user"]["username"])
        self.assertEqual("admin", data["role"])
        self.assertEqual("owner", me_response.get_json()["data"]["user"]["username"])

    def test_normal_user_is_read_only_and_admin_can_manage(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)
        self._user("viewer", role=User.ROLE_USER)

        self._login(client, "viewer")
        self.assertEqual(403, client.get("/api/v1/storage/sources").status_code)
        self.assertEqual(403, client.post("/api/v1/scan").status_code)
        self.assertEqual(200, client.get("/api/v1/movies").status_code)

        client.post("/api/v1/auth/logout")
        self._login(client, "admin")
        self.assertEqual(200, client.get("/api/v1/storage/sources").status_code)

    def test_api_token_remains_admin_backdoor_when_user_management_is_enabled(self):
        app = self.create_enabled_app(API_TOKEN="break-glass", AUTH_ENABLED=True)
        client = app.test_client()

        response = client.get("/api/v1/storage/sources", headers={"Authorization": "Bearer break-glass"})

        self.assertEqual(200, response.status_code)

    def test_admin_can_create_user_and_assign_library_rules(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        library = self._library("Kids", source, "kids")

        self._login(client, "admin")
        create_response = client.post("/api/v1/admin/users", json={
            "username": "viewer",
            "password": "password-123",
            "role": "user",
        })
        self.assertEqual(201, create_response.status_code)
        user_id = create_response.get_json()["data"]["id"]

        rules_response = client.put(f"/api/v1/admin/users/{user_id}/library-rules", json={
            "rules": [{"library_id": library.id, "mode": "allow"}],
        })

        self.assertEqual(200, rules_response.status_code)
        rules = rules_response.get_json()["data"]["library_rules"]
        self.assertEqual([{"library_id": library.id, "mode": "allow"}], [
            {"library_id": item["library_id"], "mode": item["mode"]}
            for item in rules
        ])

    def test_admin_can_preview_user_visibility(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)
        viewer = self._user("viewer")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        allowed_library = self._library("Allowed", source, "allowed")
        denied_library = self._library("Denied", source, "denied")
        open_library = self._library("Open", source, "open")
        allowed_movie, _allowed_resource = self._movie_with_resource("Allowed Movie", source, "allowed/a.mkv")
        denied_movie, _denied_resource = self._movie_with_resource("Denied Movie", source, "denied/b.mkv")
        open_movie, _open_resource = self._movie_with_resource("Open Movie", source, "open/c.mkv")
        db.session.add(UserLibraryRule(
            user_id=viewer.id,
            library_id=allowed_library.id,
            mode=UserLibraryRule.MODE_ALLOW,
        ))
        db.session.add(UserLibraryRule(
            user_id=viewer.id,
            library_id=denied_library.id,
            mode=UserLibraryRule.MODE_DENY,
        ))
        db.session.commit()

        self._login(client, "admin")
        response = client.get(f"/api/v1/admin/users/{viewer.id}/visibility-preview?sample_limit=10")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("allow_libraries", data["default_scope"])
        self.assertEqual([allowed_library.id], data["allow_library_ids"])
        self.assertEqual([denied_library.id], data["deny_library_ids"])
        self.assertEqual([allowed_library.id], data["visible_library_ids"])
        self.assertEqual(1, data["visible_movie_count"])
        self.assertEqual([allowed_movie.id], [item["id"] for item in data["sample_movies"]])
        library_map = {item["id"]: item for item in data["libraries"]}
        self.assertTrue(library_map[allowed_library.id]["visible"])
        self.assertEqual("allow", library_map[allowed_library.id]["rule_mode"])
        self.assertFalse(library_map[denied_library.id]["visible"])
        self.assertEqual("deny", library_map[denied_library.id]["rule_mode"])
        self.assertFalse(library_map[open_library.id]["visible"])
        self.assertEqual("implicit", library_map[open_library.id]["rule_mode"])
        self.assertEqual(0, library_map[denied_library.id]["visible_movie_count"])
        self.assertNotIn(denied_movie.id, [item["id"] for item in data["sample_movies"]])
        self.assertNotIn(open_movie.id, [item["id"] for item in data["sample_movies"]])

    def test_last_enabled_admin_cannot_be_disabled_or_demoted(self):
        app = self.create_enabled_app()
        client = app.test_client()
        admin = self._user("admin", role=User.ROLE_ADMIN)

        self._login(client, "admin")

        demote_response = client.patch(f"/api/v1/admin/users/{admin.id}", json={"role": "user"})
        disable_response = client.patch(f"/api/v1/admin/users/{admin.id}", json={"is_enabled": False})

        self.assertEqual(409, demote_response.status_code)
        self.assertEqual(409, disable_response.status_code)
        db.session.refresh(admin)
        self.assertEqual(User.ROLE_ADMIN, admin.role)
        self.assertTrue(admin.is_enabled)

    def test_admin_password_reset_invalidates_existing_user_session(self):
        app = self.create_enabled_app()
        admin_client = app.test_client()
        user_client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)
        viewer = self._user("viewer")

        self._login(user_client, "viewer")
        self._login(admin_client, "admin")
        reset_response = admin_client.post(
            f"/api/v1/admin/users/{viewer.id}/password",
            json={"password": "new-password-123"},
        )

        self.assertEqual(200, reset_response.status_code)
        self.assertEqual(401, user_client.get("/api/v1/movies").status_code)
        self.assertEqual(401, user_client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "password-123",
        }).status_code)
        self.assertEqual(200, user_client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "new-password-123",
        }).status_code)

    def test_user_can_change_own_password_and_keep_current_session(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("viewer")

        self._login(client, "viewer")
        response = client.post("/api/v1/user/password", json={
            "current_password": "password-123",
            "new_password": "new-password-123",
        })

        self.assertEqual(200, response.status_code)
        self.assertEqual(200, client.get("/api/v1/user/profile").status_code)
        client.post("/api/v1/auth/logout")
        self.assertEqual(401, client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "password-123",
        }).status_code)
        self.assertEqual(200, client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "new-password-123",
        }).status_code)

    def test_login_rate_limit_and_audit_logs(self):
        app = self.create_enabled_app(
            LOGIN_RATE_LIMIT_MAX_ATTEMPTS=2,
            LOGIN_RATE_LIMIT_WINDOW_SECONDS=300,
            LOGIN_RATE_LIMIT_LOCK_SECONDS=60,
        )
        client = app.test_client()
        self._user("viewer")

        first_response = client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "wrong-password",
        })
        second_response = client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "wrong-password",
        })
        locked_response = client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "password-123",
        })

        self.assertEqual(401, first_response.status_code)
        self.assertEqual(429, second_response.status_code)
        self.assertEqual(429, locked_response.status_code)
        self.assertEqual("60", second_response.headers.get("Retry-After"))
        outcomes = [row.outcome for row in AuditLog.query.filter_by(action="auth.login").all()]
        self.assertIn("failure", outcomes)
        self.assertIn("rate_limited", outcomes)

    def test_admin_can_query_audit_logs(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)

        self._login(client, "admin")
        create_response = client.post("/api/v1/admin/users", json={
            "username": "viewer",
            "password": "password-123",
            "role": "user",
        })
        audit_response = client.get("/api/v1/admin/audit-logs?limit=10")

        self.assertEqual(201, create_response.status_code)
        self.assertEqual(200, audit_response.status_code)
        actions = [item["action"] for item in audit_response.get_json()["data"]["items"]]
        self.assertIn("admin.user.create", actions)
        self.assertIn("auth.login", actions)

    def test_library_rules_filter_catalog_and_block_direct_playback(self):
        app = self.create_enabled_app()
        client = app.test_client()
        user = self._user("viewer")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        allowed_library = self._library("Allowed", source, "allowed")
        denied_library = self._library("Denied", source, "denied")
        allowed_movie, _allowed_resource = self._movie_with_resource("Allowed Movie", source, "allowed/a.mkv")
        denied_movie, denied_resource = self._movie_with_resource("Denied Movie", source, "denied/b.mkv")
        db.session.add(UserLibraryRule(user_id=user.id, library_id=allowed_library.id, mode=UserLibraryRule.MODE_ALLOW))
        db.session.commit()

        self._login(client, "viewer")
        movies = client.get("/api/v1/movies?page=1&page_size=10").get_json()["data"]["items"]
        library_items = client.get("/api/v1/libraries").get_json()["data"]

        self.assertEqual([allowed_movie.id], [item["id"] for item in movies])
        self.assertEqual([allowed_library.id], [item["id"] for item in library_items])
        self.assertEqual(200, client.get(f"/api/v1/movies/{allowed_movie.id}").status_code)
        self.assertEqual(403, client.get(f"/api/v1/movies/{denied_movie.id}").status_code)
        self.assertEqual(403, client.get(f"/api/v1/resources/{denied_resource.id}/stream").status_code)
        self.assertNotEqual(denied_library.id, allowed_library.id)

    def test_history_is_isolated_by_user(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("alice")
        self._user("bob")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        _movie, resource = self._movie_with_resource("Shared", source, "shared.mkv")

        self._login(client, "alice")
        self.assertEqual(200, client.post("/api/v1/user/history", json={
            "resource_id": resource.id,
            "position_sec": 100,
            "total_duration": 1000,
        }).status_code)
        client.post("/api/v1/auth/logout")

        self._login(client, "bob")
        self.assertEqual(200, client.post("/api/v1/user/history", json={
            "resource_id": resource.id,
            "position_sec": 300,
            "total_duration": 1000,
        }).status_code)
        bob_item = client.get("/api/v1/user/history").get_json()["data"]["items"][0]
        self.assertEqual(300, bob_item["progress"])
        client.post("/api/v1/auth/logout")

        self._login(client, "alice")
        alice_item = client.get("/api/v1/user/history").get_json()["data"]["items"][0]
        self.assertEqual(100, alice_item["progress"])

    def test_subtitle_settings_are_isolated_by_user(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("alice")
        self._user("bob")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        _movie, resource = self._movie_with_resource("Subtitle", source, "subtitle.mkv")

        self._login(client, "alice")
        response = client.patch(f"/api/v1/resources/{resource.id}/subtitle-settings", json={"offset": 120})
        self.assertEqual(200, response.status_code)
        self.assertEqual("user", response.get_json()["data"]["source"])
        self.assertEqual(1, UserSubtitleSetting.query.count())
        client.post("/api/v1/auth/logout")

        self._login(client, "bob")
        bob_settings = client.get(f"/api/v1/resources/{resource.id}/subtitle-settings").get_json()["data"]
        self.assertEqual("default", bob_settings["source"])
        self.assertEqual(72, bob_settings["settings"]["offset"])


if __name__ == "__main__":
    unittest.main()
