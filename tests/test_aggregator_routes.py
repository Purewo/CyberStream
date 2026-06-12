from __future__ import annotations

import sys
import threading
import time
import unittest
from unittest import mock

import requests

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.services.aggregator import SourceBusyError
from backend.app.services.aggregator import film_resource_core
from backend.app.services.aggregator import sources as sources_module
from backend.app.services.aggregator.sources.bt7274 import BT7274Source
from backend.app.services.aggregator.sources.rarbt import RarbtSource


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

    def test_search_rarbt_passes_config_proxy(self):
        self.app.config["AGGREGATOR_RARBT_PROXY"] = "http://127.0.0.1:7890"
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            return_value=[],
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&source=rarbt"
            )
        self.assertEqual(response.status_code, 200)
        m.assert_called_once_with(
            "foo", page=1, source="rarbt", proxy="http://127.0.0.1:7890"
        )

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

    def test_search_btbtla_falls_back_to_shared_proxy(self):
        self.app.config["AGGREGATOR_BTBTLA_PROXY"] = None
        self.app.config["AGGREGATOR_PROXY_URL"] = "http://127.0.0.1:7890"
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            return_value=[],
        ) as m:
            response = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&source=btbtla"
            )
        self.assertEqual(response.status_code, 200)
        m.assert_called_once_with(
            "foo", page=1, source="btbtla", proxy="http://127.0.0.1:7890"
        )

    def test_search_unknown_source_returns_error_envelope(self):
        with mock.patch("backend.app.api.aggregator_routes.search_film") as search:
            response = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&source=bogus"
            )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["code"], 40000)
        self.assertIn("bogus", payload["msg"])
        search.assert_not_called()

    def test_search_rejects_invalid_page(self):
        with mock.patch("backend.app.api.aggregator_routes.search_film") as search:
            non_integer = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&page=nope"
            )
            zero = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&page=0"
            )
            too_large = self.client.get(
                "/api/v1/aggregator/search?keyword=foo&page=51"
            )

        self.assertEqual(400, non_integer.status_code)
        self.assertEqual(400, zero.status_code)
        self.assertEqual(400, too_large.status_code)
        search.assert_not_called()

    def test_search_rejects_oversized_keyword(self):
        with mock.patch("backend.app.api.aggregator_routes.search_film") as search:
            response = self.client.get(
                "/api/v1/aggregator/search",
                query_string={"keyword": "x" * 121},
            )

        self.assertEqual(400, response.status_code)
        search.assert_not_called()

    def test_search_scrape_failure_returns_500_envelope(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            side_effect=RuntimeError("secret upstream detail"),
        ):
            response = self.client.get("/api/v1/aggregator/search?keyword=foo")
        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertEqual(payload["code"], 50000)
        self.assertEqual("aggregator search failed", payload["msg"])
        self.assertNotIn("secret", payload["msg"])

    def test_search_busy_source_returns_429(self):
        with mock.patch(
            "backend.app.api.aggregator_routes.search_film",
            side_effect=SourceBusyError("source is busy: rarbt"),
        ):
            response = self.client.get("/api/v1/aggregator/search?keyword=foo")

        self.assertEqual(429, response.status_code)
        payload = response.get_json()
        self.assertEqual(42900, payload["code"])
        self.assertEqual("aggregator source is busy", payload["msg"])

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
        m.assert_called_once_with("http://www.rarbt.us/thread-123.html")

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

    def test_detail_rejects_oversized_link(self):
        with mock.patch("backend.app.api.aggregator_routes.get_detail") as detail:
            response = self.client.get(
                "/api/v1/aggregator/detail",
                query_string={"link": "x" * 2049},
            )

        self.assertEqual(400, response.status_code)
        detail.assert_not_called()

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

    def test_rarbt_explicit_proxy_disables_environment_proxy_lookup(self):
        source = RarbtSource()
        source.set_proxy("http://127.0.0.1:7890")

        session = source.session

        self.assertFalse(session.trust_env)
        self.assertEqual("http://127.0.0.1:7890", session.proxies["http"])
        self.assertEqual("http://127.0.0.1:7890", session.proxies["https"])

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

    def test_source_operations_are_serialized_per_source(self):
        state_lock = threading.Lock()
        state = {"active": 0, "max_active": 0}

        class FakeSource:
            request_lock = threading.RLock()

            def set_proxy(self, proxy):
                self.proxy = proxy

            def search(self, keyword, page=1):
                with state_lock:
                    state["active"] += 1
                    state["max_active"] = max(state["max_active"], state["active"])
                time.sleep(0.05)
                with state_lock:
                    state["active"] -= 1
                return []

        source = FakeSource()
        with mock.patch.object(film_resource_core, "get_source", return_value=source):
            threads = [
                threading.Thread(
                    target=film_resource_core.search_film,
                    kwargs={"keyword": f"query-{index}", "source": "rarbt"},
                )
                for index in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(1, state["max_active"])

    def test_source_operation_raises_busy_when_lock_timeout_expires(self):
        class BusyLock:
            def acquire(self, timeout=None):
                self.timeout = timeout
                return False

            def release(self):
                raise AssertionError("release should not be called")

        class FakeSource:
            request_lock = BusyLock()

            def set_proxy(self, proxy):
                raise AssertionError("set_proxy should not be called")

        source = FakeSource()
        with mock.patch.object(film_resource_core, "get_source", return_value=source):
            with self.assertRaises(SourceBusyError):
                film_resource_core.search_film(keyword="foo", source="rarbt")

        self.assertEqual(
            film_resource_core.SOURCE_LOCK_TIMEOUT_SECONDS,
            source.request_lock.timeout,
        )

    def test_source_registry_creates_singleton_under_concurrent_access(self):
        barrier = threading.Barrier(8)
        errors = []
        results = []
        result_lock = threading.Lock()

        class SlowSource:
            init_count = 0

            def __init__(self):
                type(self).init_count += 1
                time.sleep(0.02)

        def get_concurrent_source():
            try:
                barrier.wait(timeout=2)
                source = sources_module.get_source("concurrency-test")
                with result_lock:
                    results.append(source)
            except Exception as exc:  # noqa: BLE001
                with result_lock:
                    errors.append(exc)

        with mock.patch.dict(sources_module._REGISTRY, {"concurrency-test": SlowSource}):
            with sources_module._INSTANCES_LOCK:
                sources_module._INSTANCES.pop("concurrency-test", None)
            try:
                threads = [threading.Thread(target=get_concurrent_source) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=2)
            finally:
                with sources_module._INSTANCES_LOCK:
                    sources_module._INSTANCES.pop("concurrency-test", None)

        self.assertEqual([], errors)
        self.assertEqual(8, len(results))
        self.assertEqual(1, len({id(source) for source in results}))
        self.assertEqual(1, SlowSource.init_count)


if __name__ == "__main__":
    unittest.main()
