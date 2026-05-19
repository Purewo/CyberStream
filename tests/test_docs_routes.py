from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db


class DocumentationRoutesTests(unittest.TestCase):
    def _create_client(self, **overrides):
        config = {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
        config.update(overrides)
        app = create_app(config)
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

    def test_docs_index_lists_openapi_and_frontend_documents(self):
        client = self._create_client()

        response = client.get("/api/v1/docs")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("1.21.0-beta", data["openapi_version"])
        self.assertEqual("/api/v1/openapi.json", data["openapi"]["url"])
        keys = {item["key"] for item in data["documents"]}
        self.assertIn("release-notes", keys)
        self.assertIn("api-overview", keys)
        self.assertIn("frontend-review-workbench", keys)

    def test_openapi_json_is_served_raw_for_generators(self):
        client = self._create_client()

        response = client.get("/api/v1/openapi.json")

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/json", response.mimetype)
        payload = response.get_json()
        self.assertEqual("3.0.0", payload["openapi"])
        self.assertIn("/api/v1/docs", payload["paths"])
        self.assertIn("/api/v1/docs/openapi.json", payload["paths"])

    def test_markdown_document_is_served_raw(self):
        client = self._create_client()

        response = client.get("/api/v1/docs/release-notes")

        self.assertEqual(200, response.status_code)
        self.assertEqual("text/markdown", response.mimetype)
        self.assertIn("# 1.21.0-beta", response.get_data(as_text=True))

    def test_unknown_document_key_returns_404(self):
        client = self._create_client()

        response = client.get("/api/v1/docs/not-a-doc")

        self.assertEqual(404, response.status_code)
        self.assertEqual(40441, response.get_json()["code"])

    def test_documentation_routes_are_public_when_api_token_auth_is_enabled(self):
        client = self._create_client(API_TOKEN="secret-token", AUTH_ENABLED=True)

        index = client.get("/api/v1/docs")
        openapi = client.get("/api/v1/openapi.json")
        protected = client.get("/api/v1/storage/sources")

        self.assertEqual(200, index.status_code)
        self.assertEqual(200, openapi.status_code)
        self.assertEqual(401, protected.status_code)

    def test_documentation_routes_are_public_when_user_management_is_enabled(self):
        client = self._create_client(
            USER_MANAGEMENT_ENABLED=True,
            SESSION_SECRET="test-session-secret",
            SECRET_KEY="test-session-secret",
        )

        index = client.get("/api/v1/docs")
        openapi = client.get("/api/v1/openapi.json")
        protected = client.get("/api/v1/storage/sources")

        self.assertEqual(200, index.status_code)
        self.assertEqual(200, openapi.status_code)
        self.assertEqual(401, protected.status_code)


if __name__ == "__main__":
    unittest.main()
