from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import StorageSource
from backend.app.services.scanner import CyberScanner


class _ImmediateThread:
    def __init__(self, target=None, args=None, kwargs=None):
        self.target = target
        self.args = args or ()
        self.kwargs = kwargs or {}

    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)


class StorageSourceScanScopeTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.source = StorageSource(
            name="Test AList",
            type="alist",
            config={
                "host": "alist.local",
                "port": 5244,
                "root": "/",
            },
        )
        db.session.add(self.source)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_scan_source_route_passes_selected_root_path_to_scanner(self):
        with patch("backend.app.api.storage_routes.threading.Thread", _ImmediateThread), \
             patch("backend.app.api.storage_routes.scanner_engine") as scanner_mock:
            scanner_mock.try_start_scan.return_value = True

            response = self.client.post(
                f"/api/v1/storage/sources/{self.source.id}/scan",
                json={
                    "root_path": "/电影/华语",
                    "content_type": "movie",
                    "scrape_enabled": False,
                },
            )

        payload = response.get_json()

        self.assertEqual(202, response.status_code)
        self.assertEqual("电影/华语", payload["data"]["root_path"])
        scanner_mock.scan.assert_called_once_with(
            self.source.id,
            root_path="电影/华语",
            content_type="movie",
            scrape_enabled=False,
            lock_acquired=True,
        )

    def test_scan_source_route_accepts_target_path_alias(self):
        with patch("backend.app.api.storage_routes.threading.Thread", _ImmediateThread), \
             patch("backend.app.api.storage_routes.scanner_engine") as scanner_mock:
            scanner_mock.try_start_scan.return_value = True

            response = self.client.post(
                f"/api/v1/storage/sources/{self.source.id}/scan",
                json={"target_path": "/剧集/美剧"},
            )

        payload = response.get_json()

        self.assertEqual(202, response.status_code)
        self.assertEqual("剧集/美剧", payload["data"]["root_path"])
        scanner_mock.scan.assert_called_once_with(
            self.source.id,
            root_path="剧集/美剧",
            content_type=None,
            scrape_enabled=True,
            lock_acquired=True,
        )

    def test_scan_source_route_rejects_when_scanner_lock_is_busy(self):
        with patch("backend.app.api.storage_routes.scanner_engine") as scanner_mock:
            scanner_mock.try_start_scan.return_value = False

            response = self.client.post(f"/api/v1/storage/sources/{self.source.id}/scan")

        self.assertEqual(429, response.status_code)
        scanner_mock.scan.assert_not_called()

    def test_global_scan_route_rejects_when_scanner_lock_is_busy(self):
        with patch("backend.app.api.system_routes.scanner_engine") as scanner_mock:
            scanner_mock.try_start_scan.return_value = False

            response = self.client.post("/api/v1/scan")

        self.assertEqual(429, response.status_code)
        scanner_mock.scan.assert_not_called()

    def test_scanner_scan_passes_scope_for_specific_source(self):
        scanner = CyberScanner()

        with patch("backend.app.services.scanner.db.get_all_sources", return_value=[self.source]), \
             patch.object(scanner, "scan_source") as scan_source_mock:
            scanner.scan(
                specific_source_id=self.source.id,
                root_path="电影/欧美",
                content_type="movie",
                scrape_enabled=False,
            )

        scan_source_mock.assert_called_once()
        args, kwargs = scan_source_mock.call_args
        self.assertEqual(self.source, args[0])
        self.assertEqual("电影/欧美", kwargs["root_path"])
        self.assertEqual("movie", kwargs["content_type"])
        self.assertFalse(kwargs["scrape_enabled"])

    def test_scanner_scan_does_not_run_when_lock_is_busy(self):
        scanner = CyberScanner()
        self.assertTrue(scanner.try_start_scan())

        try:
            with patch.object(scanner, "scan_source") as scan_source_mock:
                result = scanner.scan(specific_source_id=self.source.id)
            self.assertFalse(result)
            scan_source_mock.assert_not_called()
        finally:
            scanner.finish_scan()


if __name__ == "__main__":
    unittest.main()
