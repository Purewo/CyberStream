from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import (
    Account,
    AccountMembership,
    AuditLog,
    History,
    Library,
    LibrarySource,
    MediaResource,
    Movie,
    StorageSource,
    User,
    UserLibraryRule,
    UserSubtitleSetting,
)
from backend.app.api.history_routes import clear_all_history
from backend.app.services.accounts import account_scope
from backend.app.services import login_rate_limit
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

    def test_login_rejects_non_object_json_without_server_error(self):
        app = self.create_enabled_app()
        client = app.test_client()

        response = client.post("/api/v1/auth/login", json=["unexpected"])

        self.assertEqual(401, response.status_code)
        self.assertEqual(40110, response.get_json()["code"])

    def test_cross_site_session_cookie_and_cors_allowlist(self):
        app = self.create_enabled_app(
            CORS_ORIGINS=["http://localhost:3000"],
            CORS_SUPPORTS_CREDENTIALS=True,
            SESSION_COOKIE_SAMESITE="None",
            SESSION_COOKIE_SECURE=True,
        )
        client = app.test_client()
        self._user("viewer")

        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "password-123"},
            headers={"Origin": "http://localhost:3000"},
        )
        blocked_preflight = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )

        set_cookie = login_response.headers.get("Set-Cookie", "")
        self.assertEqual(200, login_response.status_code)
        self.assertEqual("http://localhost:3000", login_response.headers.get("Access-Control-Allow-Origin"))
        self.assertEqual("true", login_response.headers.get("Access-Control-Allow-Credentials"))
        self.assertIn("SameSite=None", set_cookie)
        self.assertIn("Secure", set_cookie)
        self.assertIsNone(blocked_preflight.headers.get("Access-Control-Allow-Origin"))

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

    def test_hosted_managed_mode_blocks_server_config_mutations(self):
        app = self.create_enabled_app(
            HOSTED_MANAGED_MODE=True,
            API_TOKEN="break-glass",
            AUTH_ENABLED=True,
        )
        client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)

        self._login(client, "admin")
        storage_response = client.post("/api/v1/storage/sources", json={
            "name": "Local",
            "type": "local",
            "config": {"root_path": "/media"},
        })
        blocked_requests = [
            client.put("/api/v1/system/tmdb-config", json={"token": "tmdb-token"}),
            client.post("/api/v1/images/refresh", json={"limit": 1}),
            client.delete("/api/v1/movies/11111111-1111-1111-1111-111111111111/images/poster"),
            client.get("/api/v1/movies/11111111-1111-1111-1111-111111111111/images/poster?refresh=true"),
        ]
        image_read = client.get("/api/v1/movies/11111111-1111-1111-1111-111111111111/images/poster")
        resource_sync = client.post("/api/v1/movies/11111111-1111-1111-1111-111111111111/resources/sync", json={})
        client.post("/api/v1/auth/logout")
        token_response = client.put(
            "/api/v1/system/tmdb-config",
            json={"token": "tmdb-token"},
            headers={"Authorization": "Bearer break-glass"},
        )

        for response in [*blocked_requests, token_response]:
            self.assertEqual(403, response.status_code, response.get_data(as_text=True))
            self.assertEqual(40390, response.get_json()["code"])
        self.assertEqual(200, storage_response.status_code)
        source_data = storage_response.get_json()["data"]
        self.assertTrue(source_data["account_id"])
        default_library = Library.query.execution_options(include_all_accounts=True).filter_by(account_id=source_data["account_id"]).first()
        self.assertIsNotNone(default_library)
        self.assertIsNotNone(
            LibrarySource.query.execution_options(include_all_accounts=True).filter_by(
                account_id=source_data["account_id"],
                library_id=default_library.id,
                source_id=source_data["id"],
                root_path="/",
            ).first()
        )
        self.assertEqual(404, image_read.status_code)
        self.assertNotEqual(40390, image_read.get_json()["code"])
        self.assertEqual(404, resource_sync.status_code)
        self.assertNotEqual(40390, resource_sync.get_json()["code"])

    def test_hosted_managed_mode_reports_server_config_permission(self):
        hosted_app = self.create_enabled_app(HOSTED_MANAGED_MODE=True)
        hosted_client = hosted_app.test_client()
        self._user("hosted-admin", role=User.ROLE_ADMIN)

        self._login(hosted_client, "hosted-admin")
        hosted_status = hosted_client.get("/api/v1/auth/me").get_json()["data"]

        self.assertTrue(hosted_status["permissions"]["admin"])
        self.assertTrue(hosted_status["hosted_managed_mode"])
        self.assertFalse(hosted_status["permissions"]["manage_server_config"])
        self.assertTrue(hosted_status["permissions"]["manage_storage"])
        self.assertEqual("owner", hosted_status["account_role"])
        self.assertIsNotNone(hosted_status["current_account"])

    def test_hosted_registration_creates_account_owner_and_default_library(self):
        app = self.create_enabled_app(HOSTED_MANAGED_MODE=True)
        client = app.test_client()

        response = client.post("/api/v1/auth/register", json={
            "username": "new-owner",
            "password": "password-123",
            "display_name": "New Owner",
        })
        source_response = client.post("/api/v1/storage/sources", json={
            "name": "Owner Local",
            "type": "local",
            "config": {"root_path": "/media/new-owner"},
        })

        self.assertEqual(201, response.status_code, response.get_data(as_text=True))
        data = response.get_json()["data"]
        self.assertEqual("user", data["role"])
        self.assertEqual("owner", data["account_role"])
        self.assertFalse(data["permissions"]["admin"])
        self.assertTrue(data["permissions"]["manage_catalog"])
        self.assertTrue(data["permissions"]["manage_storage"])
        self.assertFalse(data["permissions"]["manage_server_config"])
        account_id = data["current_account"]["id"]
        membership = AccountMembership.query.execution_options(include_all_accounts=True).filter_by(
            account_id=account_id,
            user_id=data["user"]["id"],
        ).first()
        self.assertIsNotNone(membership)
        self.assertEqual(AccountMembership.ROLE_OWNER, membership.role)
        default_library = Library.query.execution_options(include_all_accounts=True).filter_by(account_id=account_id, slug="default").first()
        self.assertIsNotNone(default_library)
        self.assertEqual(200, source_response.status_code, source_response.get_data(as_text=True))
        source_data = source_response.get_json()["data"]
        self.assertEqual(account_id, source_data["account_id"])
        self.assertIsNotNone(
            LibrarySource.query.execution_options(include_all_accounts=True).filter_by(
                account_id=account_id,
                library_id=default_library.id,
                source_id=source_data["id"],
                root_path="/",
            ).first()
        )

    def test_hosted_accounts_are_isolated_for_storage_and_movies(self):
        app = self.create_enabled_app(HOSTED_MANAGED_MODE=True)
        alpha_client = app.test_client()
        beta_client = app.test_client()

        alpha_register = alpha_client.post("/api/v1/auth/register", json={
            "username": "alpha-owner",
            "password": "password-123",
        })
        beta_register = beta_client.post("/api/v1/auth/register", json={
            "username": "beta-owner",
            "password": "password-123",
        })
        self.assertEqual(201, alpha_register.status_code)
        self.assertEqual(201, beta_register.status_code)
        alpha_account_id = alpha_register.get_json()["data"]["current_account"]["id"]
        beta_account_id = beta_register.get_json()["data"]["current_account"]["id"]

        alpha_source_response = alpha_client.post("/api/v1/storage/sources", json={
            "name": "Alpha Local",
            "type": "local",
            "config": {"root_path": "/media/alpha"},
        })
        beta_source_response = beta_client.post("/api/v1/storage/sources", json={
            "name": "Beta Local",
            "type": "local",
            "config": {"root_path": "/media/beta"},
        })
        self.assertEqual(200, alpha_source_response.status_code)
        self.assertEqual(200, beta_source_response.status_code)
        alpha_source_id = alpha_source_response.get_json()["data"]["id"]
        beta_source_id = beta_source_response.get_json()["data"]["id"]

        alpha_movie = Movie(
            account_id=alpha_account_id,
            tmdb_id="movie/shared-tmdb",
            title="Alpha Movie",
            original_title="Alpha Movie",
            cover="https://img.example/alpha.jpg",
            scraper_source="TMDB_STRICT",
        )
        beta_movie = Movie(
            account_id=beta_account_id,
            tmdb_id="movie/shared-tmdb",
            title="Beta Movie",
            original_title="Beta Movie",
            cover="https://img.example/beta.jpg",
            scraper_source="TMDB_STRICT",
        )
        db.session.add_all([alpha_movie, beta_movie])
        db.session.flush()
        alpha_movie_id = alpha_movie.id
        beta_movie_id = beta_movie.id
        db.session.add(MediaResource(
            account_id=alpha_account_id,
            movie_id=alpha_movie_id,
            source_id=alpha_source_id,
            path="alpha.mkv",
            filename="alpha.mkv",
            label="Alpha",
        ))
        db.session.add(MediaResource(
            account_id=beta_account_id,
            movie_id=beta_movie_id,
            source_id=beta_source_id,
            path="beta.mkv",
            filename="beta.mkv",
            label="Beta",
        ))
        db.session.commit()

        alpha_sources = alpha_client.get("/api/v1/storage/sources").get_json()["data"]
        beta_sources = beta_client.get("/api/v1/storage/sources").get_json()["data"]
        alpha_movies = alpha_client.get("/api/v1/movies?page=1&page_size=20").get_json()["data"]["items"]
        beta_movies = beta_client.get("/api/v1/movies?page=1&page_size=20").get_json()["data"]["items"]

        self.assertEqual([alpha_source_id], [item["id"] for item in alpha_sources])
        self.assertEqual([beta_source_id], [item["id"] for item in beta_sources])
        self.assertIn(alpha_movie_id, [item["id"] for item in alpha_movies])
        self.assertNotIn(beta_movie_id, [item["id"] for item in alpha_movies])
        self.assertIn(beta_movie_id, [item["id"] for item in beta_movies])
        self.assertNotIn(alpha_movie_id, [item["id"] for item in beta_movies])
        self.assertEqual(404, alpha_client.get(f"/api/v1/storage/sources/{beta_source_id}").status_code)
        self.assertEqual(404, beta_client.get(f"/api/v1/movies/{alpha_movie_id}").status_code)

    def test_self_hosted_admin_reports_server_config_permission(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)

        self._login(client, "admin")
        status = client.get("/api/v1/auth/me").get_json()["data"]

        self.assertFalse(status["hosted_managed_mode"])
        self.assertTrue(status["permissions"]["manage_server_config"])

    def test_api_token_backdoor_respects_auth_enabled_switch(self):
        app = self.create_enabled_app(API_TOKEN="disabled-token", AUTH_ENABLED=False)
        client = app.test_client()

        protected = client.get(
            "/api/v1/storage/sources",
            headers={"Authorization": "Bearer disabled-token"},
        )
        auth_probe = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer disabled-token"},
        )

        self.assertEqual(401, protected.status_code)
        self.assertFalse(auth_probe.get_json()["data"]["authenticated"])
        self.assertIsNone(auth_probe.get_json()["data"]["auth_via"])

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

    def test_admin_user_enabled_field_accepts_string_false(self):
        app = self.create_enabled_app()
        admin_client = app.test_client()
        viewer_client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)
        viewer = self._user("viewer")

        self._login(admin_client, "admin")
        create_response = admin_client.post("/api/v1/admin/users", json={
            "username": "disabled-viewer",
            "password": "password-123",
            "role": "user",
            "is_enabled": "false",
        })
        update_response = admin_client.patch(
            f"/api/v1/admin/users/{viewer.id}",
            json={"is_enabled": "false"},
        )

        self.assertEqual(201, create_response.status_code)
        self.assertFalse(create_response.get_json()["data"]["is_enabled"])
        self.assertEqual(200, update_response.status_code)
        self.assertFalse(update_response.get_json()["data"]["is_enabled"])
        self.assertEqual(401, viewer_client.post("/api/v1/auth/login", json={
            "username": "disabled-viewer",
            "password": "password-123",
        }).status_code)
        self.assertEqual(401, viewer_client.post("/api/v1/auth/login", json={
            "username": "viewer",
            "password": "password-123",
        }).status_code)

    def test_admin_user_enabled_field_rejects_invalid_bool(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("admin", role=User.ROLE_ADMIN)
        viewer = self._user("viewer")

        self._login(client, "admin")
        create_response = client.post("/api/v1/admin/users", json={
            "username": "bad-bool",
            "password": "password-123",
            "is_enabled": "not-a-bool",
        })
        update_response = client.patch(
            f"/api/v1/admin/users/{viewer.id}",
            json={"is_enabled": "not-a-bool"},
        )

        self.assertEqual(400, create_response.status_code)
        self.assertEqual(40094, create_response.get_json()["code"])
        self.assertEqual(400, update_response.status_code)
        self.assertEqual(40094, update_response.get_json()["code"])

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

    def test_login_rate_limit_caps_unique_attempt_buckets(self):
        app = self.create_enabled_app(
            LOGIN_RATE_LIMIT_MAX_ATTEMPTS=100,
            LOGIN_RATE_LIMIT_WINDOW_SECONDS=300,
            LOGIN_RATE_LIMIT_LOCK_SECONDS=60,
            LOGIN_RATE_LIMIT_MAX_BUCKETS=2,
        )
        client = app.test_client()

        for username in ("missing-one", "missing-two", "missing-three"):
            response = client.post("/api/v1/auth/login", json={
                "username": username,
                "password": "wrong-password",
            })
            self.assertEqual(401, response.status_code)

        self.assertLessEqual(len(login_rate_limit._ATTEMPTS), 2)

    def test_login_rate_limit_uses_remote_addr_not_raw_forwarded_for(self):
        app = self.create_enabled_app(
            TRUST_PROXY_HEADERS=False,
            LOGIN_RATE_LIMIT_MAX_ATTEMPTS=2,
            LOGIN_RATE_LIMIT_WINDOW_SECONDS=300,
            LOGIN_RATE_LIMIT_LOCK_SECONDS=60,
        )
        client = app.test_client()
        self._user("viewer")

        first_response = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "wrong-password"},
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
        second_response = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "wrong-password"},
            headers={"X-Forwarded-For": "198.51.100.2"},
        )

        self.assertEqual(401, first_response.status_code)
        self.assertEqual(429, second_response.status_code)

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

    def test_normal_user_can_use_visible_resource_playback_helpers(self):
        app = self.create_enabled_app()
        client = app.test_client()
        user = self._user("viewer")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        allowed_library = self._library("Allowed", source, "allowed")
        _denied_library = self._library("Denied", source, "denied")
        _allowed_movie, allowed_resource = self._movie_with_resource(
            "Allowed Movie",
            source,
            "allowed/a.mkv",
        )
        _denied_movie, denied_resource = self._movie_with_resource(
            "Denied Movie",
            source,
            "denied/b.mkv",
        )
        db.session.add(UserLibraryRule(
            user_id=user.id,
            library_id=allowed_library.id,
            mode=UserLibraryRule.MODE_ALLOW,
        ))
        db.session.commit()

        self._login(client, "viewer")

        allowed_qualities = client.get(
            f"/api/v1/resources/{allowed_resource.id}/streaming-qualities"
        )
        allowed_transcoded = client.get(
            f"/api/v1/resources/{allowed_resource.id}/stream-transcoded"
        )
        allowed_subtitle_download = client.post(
            f"/api/v1/resources/{allowed_resource.id}/subtitles/online/download",
            json={},
        )
        allowed_audio_diagnostics = client.get(
            f"/api/v1/resources/{allowed_resource.id}/audio-transcode/diagnostics"
        )
        allowed_audio_stop = client.delete(
            f"/api/v1/resources/{allowed_resource.id}/audio-transcode?session_id=test-session"
        )

        self.assertEqual(400, allowed_qualities.status_code)
        self.assertEqual(400, allowed_transcoded.status_code)
        self.assertEqual(400, allowed_subtitle_download.status_code)
        self.assertEqual(200, allowed_audio_diagnostics.status_code)
        self.assertEqual(200, allowed_audio_stop.status_code)
        self.assertEqual(
            403,
            client.get(
                f"/api/v1/resources/{denied_resource.id}/streaming-qualities"
            ).status_code,
        )
        self.assertEqual(
            403,
            client.get(
                f"/api/v1/resources/{denied_resource.id}/stream-transcoded"
            ).status_code,
        )
        self.assertEqual(
            403,
            client.post(
                f"/api/v1/resources/{denied_resource.id}/subtitles/online/download",
                json={},
            ).status_code,
        )
        self.assertEqual(
            403,
            client.get(
                f"/api/v1/resources/{denied_resource.id}/audio-transcode/diagnostics"
            ).status_code,
        )
        self.assertEqual(
            403,
            client.delete(
                f"/api/v1/resources/{denied_resource.id}/audio-transcode?session_id=test-session"
            ).status_code,
        )

    def test_normal_user_cannot_modify_shared_resource_subtitles(self):
        app = self.create_enabled_app()
        client = app.test_client()
        self._user("viewer")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        _movie, resource = self._movie_with_resource("Shared", source, "shared.mkv")

        self._login(client, "viewer")

        self.assertEqual(
            403,
            client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/bind",
                json={},
            ).status_code,
        )
        self.assertEqual(
            403,
            client.post(
                f"/api/v1/resources/{resource.id}/subtitles/upload",
                data={},
            ).status_code,
        )

    def test_normal_user_can_manage_own_favorites_and_vault_for_visible_movies(self):
        app = self.create_enabled_app()
        client = app.test_client()
        user = self._user("viewer")
        source = StorageSource(name="Local", type="local", config={"root_path": "/media"})
        db.session.add(source)
        db.session.commit()
        allowed_library = self._library("Allowed", source, "allowed")
        _denied_library = self._library("Denied", source, "denied")
        allowed_movie, _allowed_resource = self._movie_with_resource(
            "Allowed Movie",
            source,
            "allowed/a.mkv",
        )
        denied_movie, _denied_resource = self._movie_with_resource(
            "Denied Movie",
            source,
            "denied/b.mkv",
        )
        db.session.add(UserLibraryRule(
            user_id=user.id,
            library_id=allowed_library.id,
            mode=UserLibraryRule.MODE_ALLOW,
        ))
        db.session.commit()

        self._login(client, "viewer")

        self.assertEqual(200, client.get("/api/v1/user/vault/status").status_code)
        self.assertEqual(
            200,
            client.post("/api/v1/user/vault/password", json={"pin": "654321"}).status_code,
        )
        self.assertEqual(
            200,
            client.post(f"/api/v1/user/favorites/{allowed_movie.id}").status_code,
        )
        self.assertEqual(
            200,
            client.get(f"/api/v1/user/favorites/{allowed_movie.id}").status_code,
        )
        self.assertEqual(200, client.get("/api/v1/user/favorites").status_code)
        self.assertEqual(
            403,
            client.post(f"/api/v1/user/favorites/{denied_movie.id}").status_code,
        )

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

    def test_clear_history_bulk_delete_is_scoped_by_account(self):
        self.create_enabled_app(MULTI_TENANT_ENABLED=True)
        account_a = Account(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            name="Account A",
            slug="account-a",
            status=Account.STATUS_ACTIVE,
            settings={},
        )
        account_b = Account(
            id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            name="Account B",
            slug="account-b",
            status=Account.STATUS_ACTIVE,
            settings={},
        )
        db.session.add_all([
            account_a,
            account_b,
            History(account_id=account_a.id, user_id=None, progress=10, duration=100),
            History(account_id=account_b.id, user_id=None, progress=20, duration=100),
        ])
        db.session.commit()

        with account_scope(account_a.id):
            response = clear_all_history()

        self.assertEqual(200, response[1])
        remaining = (
            History.query.execution_options(include_all_accounts=True)
            .order_by(History.id.asc())
            .all()
        )
        self.assertEqual(1, len(remaining))
        self.assertEqual(account_b.id, remaining[0].account_id)

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
