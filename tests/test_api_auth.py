from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db


class ApiAuthTests(unittest.TestCase):
    def create_client(self, token="", enabled=False):
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "API_TOKEN": token,
            "AUTH_ENABLED": enabled,
        })
        ctx = app.app_context()
        ctx.push()
        db.drop_all()
        db.create_all()
        self.addCleanup(lambda: self._cleanup(ctx))
        return app.test_client()

    def _cleanup(self, ctx):
        db.session.remove()
        db.drop_all()
        ctx.pop()

    def test_auth_disabled_when_token_is_not_configured(self):
        client = self.create_client()

        response = client.get("/api/v1/storage/sources")

        self.assertEqual(200, response.status_code)

    def test_auth_disabled_when_enabled_but_token_is_blank(self):
        client = self.create_client(token="", enabled=True)

        response = client.get("/api/v1/storage/sources")

        self.assertEqual(200, response.status_code)

    def test_auth_requires_bearer_token_when_enabled(self):
        client = self.create_client(token="secret-token", enabled=True)

        missing = client.get("/api/v1/storage/sources")
        invalid = client.get("/api/v1/storage/sources", headers={"Authorization": "Bearer wrong"})
        valid = client.get("/api/v1/storage/sources", headers={"Authorization": "Bearer secret-token"})

        self.assertEqual(401, missing.status_code)
        self.assertEqual(40100, missing.get_json()["code"])
        self.assertEqual(403, invalid.status_code)
        self.assertEqual(40300, invalid.get_json()["code"])
        self.assertEqual(200, valid.status_code)

    def test_auth_accepts_cyber_api_token_header(self):
        client = self.create_client(token="secret-token", enabled=True)

        response = client.get("/api/v1/storage/sources", headers={"X-Cyber-API-Token": "secret-token"})

        self.assertEqual(200, response.status_code)

    def test_auth_me_is_public_probe_when_user_management_is_disabled(self):
        client = self.create_client(token="secret-token", enabled=True)

        response = client.get("/api/v1/auth/me")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertFalse(data["user_management_enabled"])
        self.assertFalse(data["authenticated"])

    def test_login_route_stays_hidden_when_user_management_is_disabled(self):
        client = self.create_client(token="secret-token", enabled=True)

        response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "password-123"})

        self.assertEqual(404, response.status_code)

    def test_health_options_and_media_gets_remain_public(self):
        client = self.create_client(token="secret-token", enabled=True)

        health = client.get("/")
        options = client.open("/api/v1/storage/sources", method="OPTIONS")
        stream = client.get("/api/v1/resources/11111111-1111-1111-1111-111111111111/stream")
        image = client.get("/api/v1/movies/11111111-1111-1111-1111-111111111111/images/poster")

        self.assertEqual(200, health.status_code)
        self.assertNotEqual(401, options.status_code)
        self.assertNotEqual(401, stream.status_code)
        self.assertNotEqual(401, image.status_code)


if __name__ == "__main__":
    unittest.main()
