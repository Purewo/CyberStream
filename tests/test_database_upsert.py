from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.db.database import MovieDatabaseAdapter
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, StorageSource


class DatabaseUpsertTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

        self.source = StorageSource(name="NAS", type="local", config={"root_path": "/media"})
        db.session.add(self.source)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_upsert_movie_updates_existing_source_path_without_duplicate(self):
        adapter = MovieDatabaseAdapter()
        meta_data = {
            "tmdb_id": "movie/upsert",
            "title": "Upsert Movie",
            "original_title": "Upsert Movie",
            "year": 2026,
            "scraper_source": "TMDB",
        }
        resource_info = {
            "path": "movies/Upsert.Movie.mkv",
            "tech_specs": {"size": 100, "resolution": "1080p"},
            "season": None,
            "episode": None,
            "label": "Movie - 1080p",
        }

        first = adapter.upsert_movie(meta_data, resource_info, self.source.id)
        resource_info["tech_specs"] = {"size": 200, "resolution": "2160p"}
        resource_info["label"] = "Movie - 2160p"
        second = adapter.upsert_movie(meta_data, resource_info, self.source.id)

        resources = MediaResource.query.filter_by(source_id=self.source.id, path=resource_info["path"]).all()
        self.assertEqual("Saved", first["msg"])
        self.assertEqual("Saved", second["msg"])
        self.assertEqual(1, len(resources))
        self.assertEqual(200, resources[0].size)
        self.assertEqual("Movie - 2160p", resources[0].label)

    def test_duplicate_race_recovery_updates_existing_resource(self):
        adapter = MovieDatabaseAdapter()
        movie = Movie(tmdb_id="movie/race", title="Race Movie", original_title="Race Movie", year=2026)
        db.session.add(movie)
        db.session.commit()

        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path="movies/Race.Movie.mkv",
            filename="Race.Movie.mkv",
            size=100,
            tech_specs={"size": 100},
        )
        db.session.add(resource)
        db.session.commit()

        result = adapter._retry_upsert_existing_resource_after_integrity_error(
            {
                "tmdb_id": "movie/race",
                "title": "Race Movie",
                "original_title": "Race Movie",
                "year": 2026,
                "scraper_source": "TMDB",
            },
            {
                "path": "movies/Race.Movie.mkv",
                "tech_specs": {"size": 300, "resolution": "2160p"},
                "season": None,
                "episode": None,
                "label": "Movie - 2160p",
            },
            self.source.id,
            "movies/Race.Movie.mkv",
        )

        resources = MediaResource.query.filter_by(source_id=self.source.id, path="movies/Race.Movie.mkv").all()
        self.assertEqual("Saved", result["msg"])
        self.assertTrue(result["deduped"])
        self.assertEqual(1, len(resources))
        self.assertEqual(300, resources[0].size)
        self.assertEqual("Movie - 2160p", resources[0].label)


if __name__ == "__main__":
    unittest.main()
