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
        self.assertEqual("/api/v1/openapi/modules", data["openapi"]["modules_url"])
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

    def test_openapi_module_index_lists_small_contracts(self):
        client = self._create_client()

        response = client.get("/api/v1/openapi/modules")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        modules = {item["key"]: item for item in data["modules"]}
        self.assertIn("catalog", modules)
        self.assertIn("metadata", modules)
        self.assertEqual("/api/v1/openapi/modules/catalog.json", modules["catalog"]["url"])
        self.assertGreater(modules["catalog"]["path_count"], 0)

    def test_openapi_module_json_is_pruned_raw_contract(self):
        client = self._create_client()

        response = client.get("/api/v1/openapi/modules/metadata.json")

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/json", response.mimetype)
        payload = response.get_json()
        self.assertEqual("3.0.0", payload["openapi"])
        self.assertIn("/api/v1/metadata/providers", payload["paths"])
        self.assertIn("/api/v1/movies/{id}/metadata/search", payload["paths"])
        self.assertNotIn("/api/v1/movies", payload["paths"])
        self.assertIn("schemas", payload["components"])
        full_payload = client.get("/api/v1/openapi.json").get_json()
        self.assertLess(
            len(payload["components"]["schemas"]),
            len(full_payload["components"]["schemas"]),
        )

    def test_unknown_openapi_module_returns_404(self):
        client = self._create_client()

        response = client.get("/api/v1/openapi/modules/not-a-module.json")

        self.assertEqual(404, response.status_code)
        self.assertEqual(40442, response.get_json()["code"])

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
        modules = client.get("/api/v1/openapi/modules")
        module_json = client.get("/api/v1/openapi/modules/catalog.json")
        protected = client.get("/api/v1/storage/sources")

        self.assertEqual(200, index.status_code)
        self.assertEqual(200, openapi.status_code)
        self.assertEqual(200, modules.status_code)
        self.assertEqual(200, module_json.status_code)
        self.assertEqual(401, protected.status_code)

    def test_documentation_routes_are_public_when_user_management_is_enabled(self):
        client = self._create_client(
            USER_MANAGEMENT_ENABLED=True,
            SESSION_SECRET="test-session-secret",
            SECRET_KEY="test-session-secret",
        )

        index = client.get("/api/v1/docs")
        openapi = client.get("/api/v1/openapi.json")
        modules = client.get("/api/v1/openapi/modules")
        module_json = client.get("/api/v1/openapi/modules/catalog.json")
        protected = client.get("/api/v1/storage/sources")

        self.assertEqual(200, index.status_code)
        self.assertEqual(200, openapi.status_code)
        self.assertEqual(200, modules.status_code)
        self.assertEqual(200, module_json.status_code)
        self.assertEqual(401, protected.status_code)


if __name__ == "__main__":
    unittest.main()
