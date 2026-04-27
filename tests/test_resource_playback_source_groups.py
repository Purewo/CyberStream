from __future__ import annotations

import sys
import unittest
from datetime import datetime

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import History, MediaResource, Movie, StorageSource


class ResourcePlaybackSourceGroupTests(unittest.TestCase):
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

        self.source_a = StorageSource(name="Disk A", type="local", config={"root_path": "/mnt/a"})
        self.source_b = StorageSource(name="Disk B", type="local", config={"root_path": "/mnt/b"})
        db.session.add_all([self.source_a, self.source_b])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie(self):
        movie = Movie(
            tmdb_id="movie/duplicate-sources",
            title="Duplicate Sources",
            original_title="Duplicate Sources",
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def _resource(self, movie, source, path, filename, size, season=None, episode=None):
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id,
            path=path,
            filename=filename,
            size=size,
            season=season,
            episode=episode,
            label="Movie - 2160P",
            tech_specs={
                "resolution": "2160P",
                "resolution_rank": 2160,
                "quality_tier": "reference",
                "quality_label": "4K Remux HDR",
            },
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def _history(self, resource):
        history = History(
            resource_id=resource.id,
            progress=300,
            duration=1000,
            last_watched=datetime.utcnow(),
        )
        db.session.add(history)
        db.session.commit()
        return history

    def test_duplicate_files_are_grouped_as_playback_sources(self):
        movie = self._movie()
        first = self._resource(
            movie,
            self.source_a,
            "movies/Duplicate.Sources.2026.2160p.mkv",
            "Duplicate.Sources.2026.2160p.mkv",
            50_000,
        )
        watched_backup = self._resource(
            movie,
            self.source_b,
            "backup/Duplicate.Sources.2026.2160p.mkv",
            "Duplicate.Sources.2026.2160p.mkv",
            50_000,
        )
        different_size = self._resource(
            movie,
            self.source_b,
            "backup/Duplicate.Sources.2026.1080p.mkv",
            "Duplicate.Sources.2026.1080p.mkv",
            20_000,
        )
        self._history(watched_backup)

        response = self.client.get(f"/api/v1/movies/{movie.id}/resources")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(3, data["summary"]["total_items"])
        self.assertEqual(2, data["summary"]["playback_source_count"])
        self.assertEqual(1, data["summary"]["duplicate_group_count"])
        self.assertEqual(1, data["summary"]["alternate_resource_count"])
        self.assertEqual(3, len(data["items"]))

        duplicate_group = next(
            item for item in data["groups"]["playback_sources"]
            if item["is_duplicate_group"]
        )
        self.assertEqual(watched_backup.id, duplicate_group["primary_resource_id"])
        self.assertEqual([first.id], duplicate_group["alternate_resource_ids"])
        self.assertEqual([watched_backup.id, first.id], duplicate_group["resource_ids"])
        self.assertEqual("same_filename_size", duplicate_group["match"]["type"])
        self.assertEqual(watched_backup.id, duplicate_group["user_data"]["resource_id"])

        standalone = data["groups"]["standalone"]
        self.assertEqual(3, standalone["count"])
        self.assertEqual(2, standalone["playback_source_count"])
        self.assertEqual(1, standalone["alternate_resource_count"])
        self.assertEqual({watched_backup.id, different_size.id}, set(standalone["primary_resource_ids"]))

    def test_episode_duplicate_groups_update_season_primary_ids(self):
        movie = self._movie()
        first = self._resource(
            movie,
            self.source_a,
            "shows/S01E01.mkv",
            "S01E01.mkv",
            10_000,
            season=1,
            episode=1,
        )
        backup = self._resource(
            movie,
            self.source_b,
            "backup/S01E01.mkv",
            "S01E01.mkv",
            10_000,
            season=1,
            episode=1,
        )
        self._history(backup)

        response = self.client.get(f"/api/v1/movies/{movie.id}/resources")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        season = data["groups"]["seasons"][0]
        self.assertEqual([backup.id], season["primary_resource_ids"])
        self.assertEqual(1, season["playback_source_count"])
        self.assertEqual(1, season["alternate_resource_count"])
        self.assertEqual(1, data["summary"]["playback_source_count"])
        self.assertEqual(1, data["summary"]["duplicate_group_count"])


if __name__ == "__main__":
    unittest.main()
