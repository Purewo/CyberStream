from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.api import libraries_routes, library_helpers
from backend.app.extensions import db
from backend.app.models import Library, LibrarySource, MediaResource, Movie, StorageSource
from backend.app.services.filter_options_cache import clear_filter_options_cache


class FilterOptionsCacheTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "FILTER_OPTIONS_CACHE_TTL_SECONDS": 600,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        clear_filter_options_cache()
        self.client = self.app.test_client()

    def tearDown(self):
        clear_filter_options_cache()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie(self, title, category, year=2026, country="中国", scraper_source="TMDB"):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            year=year,
            country=country,
            category=category,
            cover=f"https://img.example/{title}.jpg",
            scraper_source=scraper_source,
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def _library_setup(self):
        source = StorageSource(name="Local", type="local", config={"root_path": "/mnt"})
        library = Library(name="电影库", slug="movies")
        db.session.add_all([source, library])
        db.session.commit()
        db.session.add(LibrarySource(library_id=library.id, source_id=source.id, root_path="movies", scan_order=0))
        db.session.commit()
        return source, library

    def _resource(self, movie, source, path):
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            label="Movie",
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def test_global_filters_are_cached_and_invalidated_on_movie_commit(self):
        self._movie("Action", ["动作"])
        build_calls = []
        original = library_helpers._build_global_filter_options

        def wrapped(includes):
            build_calls.append(list(includes))
            return original(includes)

        with patch("backend.app.api.library_helpers._build_global_filter_options", side_effect=wrapped):
            first = self.client.get("/api/v1/filters?include=genres,years,countries")
            second = self.client.get("/api/v1/filters?include=genres,years,countries")
            self._movie("Sci-Fi", ["科幻"])
            third = self.client.get("/api/v1/filters?include=genres,years,countries")

        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual(200, third.status_code)
        self.assertEqual(2, len(build_calls))
        self.assertEqual(["动作"], [item["name"] for item in first.get_json()["data"]["genres"]])
        self.assertCountEqual(["动作", "科幻"], [item["name"] for item in third.get_json()["data"]["genres"]])

    def test_library_filters_are_cached_and_invalidated_on_resource_commit(self):
        source, library = self._library_setup()
        action = self._movie("Action", ["动作"])
        self._resource(action, source, "movies/action.mkv")
        build_calls = []
        original = libraries_routes._build_library_filter_options

        def wrapped(library_arg, includes):
            build_calls.append((library_arg.id, list(includes)))
            return original(library_arg, includes)

        with patch("backend.app.api.libraries_routes._build_library_filter_options", side_effect=wrapped):
            first = self.client.get(f"/api/v1/libraries/{library.id}/filters?include=genres,years,countries")
            second = self.client.get(f"/api/v1/libraries/{library.id}/filters?include=genres,years,countries")
            sci_fi = self._movie("Sci-Fi", ["科幻"])
            self._resource(sci_fi, source, "movies/sci-fi.mkv")
            third = self.client.get(f"/api/v1/libraries/{library.id}/filters?include=genres,years,countries")

        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual(200, third.status_code)
        self.assertEqual(2, len(build_calls))
        self.assertEqual(["动作"], [item["name"] for item in first.get_json()["data"]["genres"]])
        self.assertCountEqual(["动作", "科幻"], [item["name"] for item in third.get_json()["data"]["genres"]])


if __name__ == "__main__":
    unittest.main()
