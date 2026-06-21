from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, StorageSource, User
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


if __name__ == "__main__":
    unittest.main()
