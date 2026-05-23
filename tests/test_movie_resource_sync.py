from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, StorageSource


class _ImmediateThread:
    def __init__(self, target=None, args=None, kwargs=None):
        self.target = target
        self.args = args or ()
        self.kwargs = kwargs or {}

    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)


class MovieResourceSyncTests(unittest.TestCase):
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
            name="Episodes AList",
            type="alist",
            config={
                "host": "alist.local",
                "port": 5244,
                "root": "/",
            },
        )
        self.movie = Movie(
            tmdb_id="tv/100",
            title="Test Series",
            scraper_source="TMDB",
        )
        db.session.add_all([self.source, self.movie])
        db.session.flush()
        db.session.add_all([
            MediaResource(
                movie_id=self.movie.id,
                source_id=self.source.id,
                path="shows/Test Series/S01/Test.Series.S01E01.mkv",
                filename="Test.Series.S01E01.mkv",
                season=1,
                episode=1,
            ),
            MediaResource(
                movie_id=self.movie.id,
                source_id=self.source.id,
                path="shows/Test Series/S02/Test.Series.S02E01.mkv",
                filename="Test.Series.S02E01.mkv",
                season=2,
                episode=1,
            ),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_sync_refreshes_common_show_directory_and_scans_it(self):
        provider = MagicMock()
        with patch("backend.app.api.library_routes.threading.Thread", _ImmediateThread), \
             patch("backend.app.api.library_routes.scanner_engine") as scanner_mock, \
             patch("backend.app.api.library_routes.provider_factory.get_provider", return_value=provider):
            scanner_mock.try_start_scan.return_value = True

            response = self.client.post(f"/api/v1/movies/{self.movie.id}/resources/sync")

        payload = response.get_json()
        target = payload["data"]["targets"][0]

        self.assertEqual(202, response.status_code)
        self.assertEqual("tv", payload["data"]["content_type"])
        self.assertTrue(payload["data"]["refresh"])
        self.assertEqual(["shows/Test Series"], target["root_paths"])
        self.assertEqual(["shows/Test Series"], target["display_root_paths"])
        self.assertTrue(target["refresh_supported"])
        provider.refresh_directory.assert_called_once_with("shows/Test Series")
        scanner_mock.scan_source.assert_called_once()
        _, kwargs = scanner_mock.scan_source.call_args
        self.assertEqual("shows/Test Series", kwargs["root_path"])
        self.assertEqual("tv", kwargs["content_type"])
        self.assertTrue(kwargs["scrape_enabled"])
        self.assertEqual({}, kwargs["scraper_policy"])
        scanner_mock.finish_scan.assert_called_once()

    def test_sync_does_not_collapse_unrelated_directories_to_source_root(self):
        separate_movie = Movie(tmdb_id="tv/200", title="Split Series", scraper_source="TMDB")
        db.session.add(separate_movie)
        db.session.flush()
        db.session.add_all([
            MediaResource(
                movie_id=separate_movie.id,
                source_id=self.source.id,
                path="disk-a/Split Series/E01.mkv",
                filename="E01.mkv",
                season=1,
                episode=1,
            ),
            MediaResource(
                movie_id=separate_movie.id,
                source_id=self.source.id,
                path="disk-b/Split Series/E02.mkv",
                filename="E02.mkv",
                season=1,
                episode=2,
            ),
        ])
        db.session.commit()

        with patch("backend.app.api.library_routes.threading.Thread", _ImmediateThread), \
             patch("backend.app.api.library_routes.scanner_engine") as scanner_mock, \
             patch("backend.app.api.library_routes.provider_factory.get_provider") as provider_factory_mock:
            scanner_mock.try_start_scan.return_value = True
            response = self.client.post(
                f"/api/v1/movies/{separate_movie.id}/resources/sync",
                json={"refresh": False},
            )

        payload = response.get_json()
        target = payload["data"]["targets"][0]
        called_roots = [call.kwargs["root_path"] for call in scanner_mock.scan_source.call_args_list]

        self.assertEqual(202, response.status_code)
        self.assertEqual(["disk-a/Split Series", "disk-b/Split Series"], target["root_paths"])
        self.assertEqual(["disk-a/Split Series", "disk-b/Split Series"], called_roots)
        provider_factory_mock.assert_not_called()

    def test_sync_returns_validation_error_for_movie_without_resources(self):
        empty_movie = Movie(tmdb_id="movie/300", title="No Resources", scraper_source="TMDB")
        db.session.add(empty_movie)
        db.session.commit()

        with patch("backend.app.api.library_routes.scanner_engine") as scanner_mock:
            response = self.client.post(f"/api/v1/movies/{empty_movie.id}/resources/sync")

        payload = response.get_json()
        self.assertEqual(400, response.status_code)
        self.assertEqual(40026, payload["code"])
        scanner_mock.try_start_scan.assert_not_called()

    def test_sync_rejects_when_scanner_lock_is_busy(self):
        with patch("backend.app.api.library_routes.scanner_engine") as scanner_mock:
            scanner_mock.try_start_scan.return_value = False
            response = self.client.post(f"/api/v1/movies/{self.movie.id}/resources/sync")

        self.assertEqual(429, response.status_code)
        scanner_mock.scan_source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
