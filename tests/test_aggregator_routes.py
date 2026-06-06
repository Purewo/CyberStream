from __future__ import annotations

import sys
import unittest
from unittest import mock

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db


class AggregatorRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "AGGREGATOR_DEFAULT_SOURCE": "rarbt",
            "AGGREGATOR_BTBTLA_PROXY": "http://127.0.0.1:10808",
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

    # --- sources ---
    def test_sources_lists_registered_sources(self):
        response = self.client.get("/api/v1/aggregator/sources")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["code"], 200)
        data = payload["data"]
        self.assertIn("rarbt", data["sources"])
        self.assertEqual(data["default"], "rarbt")
        self.assertIn("priority", data)

    # --- search ---
    def test_search_requires_keyword(self):
        response = self.client.get("/api/v1/aggregator/search")
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["code"], 40000)
        self.assertIsNone(payload["data"])

    def test_search_calls_core_with_default_source_no_proxy(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            return_value=[{"title": "x", "link": "/y"}],
        ) as m:
            response = self.client.get("/api/v1/aggregator/search?keyword=foo")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["items"], [{"title": "x", "link": "/y"}])
        self.assertEqual(payload["data"]["source"], "rarbt")
        m.assert_called_once_with("foo", page=1, source="rarbt", proxy=None)

    def test_search_btbtla_passes_config_proxy(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            return_value=[],
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&source=btbtla"
            )
        self.assertEqual(response.status_code, 200)
        m.assert_called_once_with(
            "foo", page=1, source="btbtla", proxy="http://127.0.0.1:10808"
        )

    def test_search_unknown_source_returns_error_envelope(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            side_effect=ValueError("未知资源站: 'bogus'"),
        ):
            response = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&source=bogus"
            )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["code"], 40000)
        self.assertIn("bogus", payload["msg"])

    def test_search_scrape_failure_returns_500_envelope(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            side_effect=RuntimeError("boom"),
        ):
            response = self.client.get("/api/v1/aggregator/search?keyword=foo")
        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertEqual(payload["code"], 50000)

    # --- detail ---
    def test_detail_requires_link(self):
        response = self.client.get("/api/v1/aggregator/detail")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], 40000)

    def test_detail_returns_core_payload(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.get_detail",
            return_value={"director": "D"},
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/detail?link=/abc&source=4kzhinan"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["detail"], {"director": "D"})
        m.assert_called_once_with("/abc", source="4kzhinan", proxy=None)

    # --- magnet ---
    def test_magnet_requires_link(self):
        response = self.client.get("/api/v1/aggregator/magnet")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], 40000)

    def test_magnet_returns_core_payload(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.get_magnet",
            return_value={"magnet": "magnet:?xt=abc"},
        ) as m:
            response = self.client.get("/api/v1/aggregator/magnet?link=/abc")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["magnet"], {"magnet": "magnet:?xt=abc"})
        m.assert_called_once_with("/abc", source="rarbt", proxy=None)


if __name__ == "__main__":
    unittest.main()
