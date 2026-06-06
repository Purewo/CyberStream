from __future__ import annotations

import sys
import unittest
from unittest import mock

import requests

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.services.aggregator.sources.bt7274 import BT7274Source


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

    def test_detail_normalizes_relative_source_link(self):
        with mock.patch(
            "backend.app.services.aggregator.sources.rarbt.RarbtSource.get_detail",
            return_value={"director": "D"},
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/detail",
                query_string={"link": "/thread-123.html", "source": "rarbt"},
            )
        self.assertEqual(response.status_code, 200)
        m.assert_called_once_with("https://www.rarbt.lol/thread-123.html")

    def test_detail_rejects_cross_source_link_before_fetch(self):
        with mock.patch(
            "backend.app.services.aggregator.sources.rarbt.RarbtSource.get_detail",
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/detail",
                query_string={"link": "http://127.0.0.1:5004/", "source": "rarbt"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], 40000)
        self.assertIn("not allowed", response.get_json()["msg"])
        m.assert_not_called()

    def test_detail_rejects_protocol_relative_cross_source_link(self):
        with mock.patch(
            "backend.app.services.aggregator.sources.rarbt.RarbtSource.get_detail",
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/detail",
                query_string={"link": "//example.com/internal", "source": "rarbt"},
            )
        self.assertEqual(response.status_code, 400)
        m.assert_not_called()

    def test_detail_rejects_non_http_scheme(self):
        with mock.patch(
            "backend.app.services.aggregator.sources.rarbt.RarbtSource.get_detail",
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/detail",
                query_string={"link": "file:///etc/passwd", "source": "rarbt"},
            )
        self.assertEqual(response.status_code, 400)
        m.assert_not_called()

    def test_detail_keeps_bt7274_numeric_identifier(self):
        with mock.patch(
            "backend.app.services.aggregator.sources.bt7274.BT7274Source.get_detail",
            return_value={"director": "D"},
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/detail",
                query_string={"link": "1295644", "source": "bt7274"},
            )
        self.assertEqual(response.status_code, 200)
        m.assert_called_once_with("1295644")

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

    def test_magnet_allows_direct_magnet_uri(self):
        magnet = "magnet:?xt=urn:btih:abcdef"
        with mock.patch(
            "backend.app.services.aggregator.sources.rarbt.RarbtSource.get_magnet",
            return_value={"magnet": magnet},
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/magnet",
                query_string={"link": magnet, "source": "rarbt"},
            )
        self.assertEqual(response.status_code, 200)
        m.assert_called_once_with(magnet)

    def test_magnet_rejects_cross_source_http_link_before_fetch(self):
        with mock.patch(
            "backend.app.services.aggregator.sources.rarbt.RarbtSource.get_magnet",
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/magnet",
                query_string={"link": "http://169.254.169.254/latest/meta-data/", "source": "rarbt"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], 40000)
        m.assert_not_called()


class AggregatorSourceSessionTests(unittest.TestCase):
    def test_session_blocks_cross_host_request_before_network_send(self):
        source = BT7274Source()
        request = requests.Request(
            "GET",
            "http://169.254.169.254/latest/meta-data/",
        ).prepare()

        with mock.patch.object(requests.Session, "send") as parent_send:
            with self.assertRaises(requests.exceptions.InvalidURL):
                source.session.send(request)

        parent_send.assert_not_called()

    def test_session_allows_source_host_request(self):
        source = BT7274Source()
        request = requests.Request(
            "GET",
            "https://www.bt7274.cc/detail/1295644",
        ).prepare()
        response = requests.Response()
        response.status_code = 200

        with mock.patch.object(requests.Session, "send", return_value=response) as parent_send:
            actual = source.session.send(request)

        self.assertIs(response, actual)
        parent_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
