from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import AccountMembership, MediaResource, Movie, StorageSource, User
from backend.app.services.login_rate_limit import clear_all_login_failures
from backend.app.services.users import set_user_password


class PlaybackTicketTests(unittest.TestCase):
    def create_app(self, **overrides):
        clear_all_login_failures()
        config = {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "USER_MANAGEMENT_ENABLED": True,
            "SESSION_SECRET": "test-session-secret",
            "SECRET_KEY": "test-session-secret",
            "PLAYBACK_TICKET_TTL_SECONDS": 43200,
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

    def _create_user_and_resource(self):
        user = User(username="viewer", display_name="Viewer", role=User.ROLE_USER, is_enabled=True)
        set_user_password(user, "password-123")
        source = StorageSource(name="Local", type="local", config={"root_path": "/tmp"})
        movie = Movie(
            tmdb_id="playback-ticket-movie",
            title="Playback Ticket",
            original_title="Playback Ticket",
            cover="https://img.example/ticket.jpg",
            scraper_source="TMDB",
        )
        db.session.add_all([user, source, movie])
        db.session.flush()
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id,
            path="ticket.mp4",
            filename="ticket.mp4",
            label="Movie",
        )
        db.session.add(resource)
        db.session.commit()
        return user, resource

    def _issue_user_ticket(self, app):
        _user, resource = self._create_user_and_resource()
        client = app.test_client()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "password-123"},
        )
        self.assertEqual(200, login.status_code)
        issued = client.post("/api/v1/auth/playback-ticket")
        self.assertEqual(200, issued.status_code, issued.get_data(as_text=True))
        data = issued.get_json()["data"]
        self.assertEqual(43200, data["ttl"])
        self.assertTrue(data["ticket"])
        return resource, data

    def test_ticket_endpoint_requires_authentication(self):
        app = self.create_app()
        response = app.test_client().post("/api/v1/auth/playback-ticket")

        self.assertEqual(401, response.status_code)
        self.assertEqual(40100, response.get_json()["code"])

    def test_user_ticket_authenticates_playback_without_cookie(self):
        app = self.create_app()
        resource, ticket_data = self._issue_user_ticket(app)

        response = app.test_client().get(
            f"/api/v1/resources/{resource.id}/streaming-qualities",
            query_string={"ticket": ticket_data["ticket"]},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual(40074, response.get_json()["code"])

    def test_user_ticket_authenticates_online_subtitle_search_and_download_without_cookie(self):
        app = self.create_app()
        resource, ticket_data = self._issue_user_ticket(app)
        client = app.test_client()

        with patch(
            "backend.app.api.player_routes.search_online_subtitles",
            return_value={"items": [], "count": 0},
        ) as search:
            search_response = client.get(
                f"/api/v1/resources/{resource.id}/subtitles/online/search",
                query_string={"keyword": "ticket subtitle", "ticket": ticket_data["ticket"]},
            )
        with patch(
            "backend.app.api.player_routes.download_online_subtitle",
            return_value={
                "filename": "ticket.srt",
                "mime_type": "text/plain; charset=utf-8",
                "content": b"1\n00:00:00,000 --> 00:00:01,000\nTicket\n",
                "meta": {"provider_id": "subhd"},
            },
        ) as download:
            download_response = client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/download",
                query_string={"ticket": ticket_data["ticket"]},
                json={"candidate_id": "subhd:ticket", "download_index": 0},
            )

        self.assertEqual(200, search_response.status_code)
        search.assert_called_once()
        self.assertEqual(200, download_response.status_code)
        self.assertEqual("subhd", download_response.headers.get("X-Cyber-Subtitle-Provider"))
        self.assertIn(b"Ticket", download_response.data)
        download.assert_called_once()

    def test_admin_ticket_authenticates_online_subtitle_bind_and_delete_without_cookie(self):
        app = self.create_app(API_TOKEN="api-secret", AUTH_ENABLED=True)
        _user, resource = self._create_user_and_resource()
        issued = app.test_client().post(
            "/api/v1/auth/playback-ticket",
            headers={"Authorization": "Bearer api-secret"},
        )
        self.assertEqual(200, issued.status_code)
        ticket = issued.get_json()["data"]["ticket"]
        client = app.test_client()

        with patch(
            "backend.app.api.player_routes.bind_online_subtitle",
            return_value={"id": "subtitle-bound", "source": "online_bound"},
        ) as bind:
            bind_response = client.post(
                f"/api/v1/resources/{resource.id}/subtitles/online/bind",
                query_string={"ticket": ticket},
                json={"candidate_id": "subhd:ticket", "download_index": 0, "confirm": True},
            )
        with patch(
            "backend.app.api.player_routes.delete_bound_resource_subtitle",
            return_value={"id": "subtitle-bound", "deleted": True},
        ) as delete:
            delete_response = client.delete(
                f"/api/v1/resources/{resource.id}/subtitles/subtitle-bound",
                query_string={"ticket": ticket},
            )

        self.assertEqual(200, bind_response.status_code)
        self.assertEqual("subtitle-bound", bind_response.get_json()["data"]["id"])
        bind.assert_called_once()
        self.assertEqual(200, delete_response.status_code)
        self.assertTrue(delete_response.get_json()["data"]["deleted"])
        delete.assert_called_once()

    def test_user_ticket_authenticates_history_routes_without_cookie(self):
        app = self.create_app()
        resource, ticket_data = self._issue_user_ticket(app)
        client = app.test_client()

        post_response = client.post(
            "/api/v1/user/history",
            query_string={"ticket": ticket_data["ticket"]},
            json={
                "resource_id": resource.id,
                "position_sec": 120,
                "total_duration": 1800,
                "device_id": "pc-native",
                "device_name": "PC Native",
            },
        )
        get_response = client.get(
            "/api/v1/user/history",
            query_string={"ticket": ticket_data["ticket"]},
        )
        delete_item_response = client.delete(
            f"/api/v1/user/history/{resource.id}",
            query_string={"ticket": ticket_data["ticket"]},
        )
        post_again_response = client.post(
            "/api/v1/user/history",
            query_string={"ticket": ticket_data["ticket"]},
            json={
                "resource_id": resource.id,
                "position_sec": 240,
                "total_duration": 1800,
            },
        )
        clear_response = client.delete(
            "/api/v1/user/history",
            query_string={"ticket": ticket_data["ticket"]},
        )

        self.assertEqual(200, post_response.status_code)
        self.assertEqual(200, get_response.status_code)
        items = get_response.get_json()["data"]["items"]
        self.assertEqual(1, len(items))
        self.assertEqual(120, items[0]["progress"])
        self.assertEqual(200, delete_item_response.status_code)
        self.assertEqual(200, post_again_response.status_code)
        self.assertEqual(200, clear_response.status_code)

    def test_user_ticket_authenticates_preferences_without_cookie(self):
        app = self.create_app()
        _resource, ticket_data = self._issue_user_ticket(app)
        client = app.test_client()
        prefs = {
            "theme": {"themeName": "NEON", "accent": "#00ffaa"},
            "scanlines": True,
            "glitch": False,
            "homepage": {
                "defaultLanding": "library",
                "libraryDefaults": {"type": "grid", "sort": "recent"},
            },
        }

        initial = client.get(
            "/api/v1/user/preferences",
            query_string={"ticket": ticket_data["ticket"]},
        )
        saved = client.put(
            "/api/v1/user/preferences",
            query_string={"ticket": ticket_data["ticket"]},
            json=prefs,
        )
        loaded = client.get(
            "/api/v1/user/preferences",
            query_string={"ticket": ticket_data["ticket"]},
        )
        invalid = client.put(
            "/api/v1/user/preferences",
            query_string={"ticket": ticket_data["ticket"]},
            json=["not", "an", "object"],
        )

        self.assertEqual(200, initial.status_code)
        self.assertEqual({}, initial.get_json()["data"])
        self.assertEqual(200, saved.status_code)
        self.assertEqual(prefs, saved.get_json()["data"])
        self.assertEqual(200, loaded.status_code)
        self.assertEqual(prefs, loaded.get_json()["data"])
        self.assertEqual(400, invalid.status_code)
        self.assertEqual(40090, invalid.get_json()["code"])

    def test_invalid_and_expired_tickets_return_40130(self):
        app = self.create_app()
        resource, ticket_data = self._issue_user_ticket(app)
        client = app.test_client()

        invalid = client.get(
            f"/api/v1/resources/{resource.id}/streaming-qualities",
            query_string={"ticket": f"{ticket_data['ticket']}tampered"},
        )
        with patch(
            "backend.app.services.playback_tickets.time.time",
            return_value=ticket_data["expires_at"] + 1,
        ):
            expired = client.get(
                f"/api/v1/resources/{resource.id}/streaming-qualities",
                query_string={"ticket": ticket_data["ticket"]},
            )

        self.assertEqual(401, invalid.status_code)
        self.assertEqual(40130, invalid.get_json()["code"])
        self.assertEqual(401, expired.status_code)
        self.assertEqual(40130, expired.get_json()["code"])

    def test_api_token_can_issue_admin_playback_ticket(self):
        app = self.create_app(API_TOKEN="api-secret", AUTH_ENABLED=True)
        issued = app.test_client().post(
            "/api/v1/auth/playback-ticket",
            headers={"Authorization": "Bearer api-secret"},
        )
        self.assertEqual(200, issued.status_code)

        response = app.test_client().get(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/streaming-qualities",
            query_string={"ticket": issued.get_json()["data"]["ticket"]},
        )
        self.assertEqual(404, response.status_code)

    def test_hosted_ticket_restores_account_and_cannot_read_other_account_resource(self):
        app = self.create_app(
            HOSTED_MANAGED_MODE=True,
            MULTI_TENANT_ENABLED=True,
            REGISTRATION_ENABLED=True,
        )
        client_a = app.test_client()
        client_b = app.test_client()

        register_a = client_a.post(
            "/api/v1/auth/register",
            json={"username": "account_a", "password": "password-123"},
        )
        register_b = client_b.post(
            "/api/v1/auth/register",
            json={"username": "account_b", "password": "password-123"},
        )
        self.assertEqual(201, register_a.status_code)
        self.assertEqual(201, register_b.status_code)

        user_a = User.query.filter_by(username="account_a").first()
        user_b = User.query.filter_by(username="account_b").first()
        account_a_id = AccountMembership.query.filter_by(user_id=user_a.id).first().account_id
        account_b_id = AccountMembership.query.filter_by(user_id=user_b.id).first().account_id

        source_a = StorageSource(
            account_id=account_a_id,
            name="A",
            type="local",
            config={"root_path": "/tmp/a"},
        )
        source_b = StorageSource(
            account_id=account_b_id,
            name="B",
            type="local",
            config={"root_path": "/tmp/b"},
        )
        movie_a = Movie(
            account_id=account_a_id,
            tmdb_id="ticket-account-a",
            title="A",
            original_title="A",
            cover="https://img.example/a.jpg",
            scraper_source="TMDB",
        )
        movie_b = Movie(
            account_id=account_b_id,
            tmdb_id="ticket-account-b",
            title="B",
            original_title="B",
            cover="https://img.example/b.jpg",
            scraper_source="TMDB",
        )
        db.session.add_all([source_a, source_b, movie_a, movie_b])
        db.session.flush()
        resource_a = MediaResource(
            account_id=account_a_id,
            movie_id=movie_a.id,
            source_id=source_a.id,
            path="a.mp4",
            filename="a.mp4",
            label="Movie",
        )
        resource_b = MediaResource(
            account_id=account_b_id,
            movie_id=movie_b.id,
            source_id=source_b.id,
            path="b.mp4",
            filename="b.mp4",
            label="Movie",
        )
        db.session.add_all([resource_a, resource_b])
        db.session.commit()

        ticket = client_a.post("/api/v1/auth/playback-ticket").get_json()["data"]["ticket"]
        no_cookie_client = app.test_client()
        own = no_cookie_client.get(
            f"/api/v1/resources/{resource_a.id}/streaming-qualities",
            query_string={"ticket": ticket},
        )
        other = no_cookie_client.get(
            f"/api/v1/resources/{resource_b.id}/streaming-qualities",
            query_string={"ticket": ticket},
        )
        own_history = no_cookie_client.post(
            "/api/v1/user/history",
            query_string={"ticket": ticket},
            json={
                "resource_id": resource_a.id,
                "position_sec": 60,
                "total_duration": 600,
            },
        )
        other_history = no_cookie_client.post(
            "/api/v1/user/history",
            query_string={"ticket": ticket},
            json={
                "resource_id": resource_b.id,
                "position_sec": 60,
                "total_duration": 600,
            },
        )
        with patch(
            "backend.app.api.player_routes.bind_online_subtitle",
            return_value={"id": "subtitle-a", "source": "online_bound"},
        ) as bind:
            own_bind = no_cookie_client.post(
                f"/api/v1/resources/{resource_a.id}/subtitles/online/bind",
                query_string={"ticket": ticket},
                json={"candidate_id": "subhd:ticket", "confirm": True},
            )
            other_bind = no_cookie_client.post(
                f"/api/v1/resources/{resource_b.id}/subtitles/online/bind",
                query_string={"ticket": ticket},
                json={"candidate_id": "subhd:ticket", "confirm": True},
            )
        with patch(
            "backend.app.api.player_routes.delete_bound_resource_subtitle",
            return_value={"id": "subtitle-a", "deleted": True},
        ) as delete:
            own_delete = no_cookie_client.delete(
                f"/api/v1/resources/{resource_a.id}/subtitles/subtitle-a",
                query_string={"ticket": ticket},
            )
            other_delete = no_cookie_client.delete(
                f"/api/v1/resources/{resource_b.id}/subtitles/subtitle-b",
                query_string={"ticket": ticket},
            )

        self.assertEqual(400, own.status_code)
        self.assertEqual(40074, own.get_json()["code"])
        self.assertEqual(404, other.status_code)
        self.assertEqual(40403, other.get_json()["code"])
        self.assertEqual(200, own_history.status_code)
        self.assertEqual(404, other_history.status_code)
        self.assertEqual(40402, other_history.get_json()["code"])
        self.assertEqual(200, own_bind.status_code)
        self.assertEqual(404, other_bind.status_code)
        bind.assert_called_once()
        self.assertEqual(200, own_delete.status_code)
        self.assertEqual(404, other_delete.status_code)
        delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
