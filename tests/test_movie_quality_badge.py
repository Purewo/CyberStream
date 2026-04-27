from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie


class MovieQualityBadgeTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.counter = 0

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie_with_resources(self, tech_specs_list):
        self.counter += 1
        movie = Movie(
            tmdb_id=f"movie/quality-{self.counter}",
            title="Quality Movie",
            original_title="Quality Movie",
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.flush()
        for index, tech_specs in enumerate(tech_specs_list, start=1):
            db.session.add(MediaResource(
                movie_id=movie.id,
                path=f"movies/quality-{index}.mkv",
                filename=f"quality-{index}.mkv",
                label="Movie",
                tech_specs=tech_specs,
            ))
        db.session.commit()
        return movie

    def test_quality_badge_prefers_remux_over_4k(self):
        movie = self._movie_with_resources([
            {
                "resolution": "2160P",
                "resolution_rank": 2160,
                "source": "Blu-ray Remux",
                "features": {"is_4k": True, "is_remux": True},
                "tags": ["4K", "REMUX"],
            },
            {
                "resolution": "1080P",
                "resolution_rank": 1080,
            },
        ])

        self.assertEqual("Remux", movie.get_quality_badge())
        self.assertEqual("Remux", movie.to_simple_dict()["quality_badge"])

    def test_quality_badge_maps_2160p_to_4k(self):
        movie = self._movie_with_resources([{
            "resolution": "2160P",
            "resolution_rank": 2160,
            "features": {"is_4k": True},
        }])

        self.assertEqual("4K", movie.to_simple_dict()["quality_badge"])

    def test_quality_badge_maps_1080p_to_hd(self):
        movie = self._movie_with_resources([{
            "resolution": "1080P",
            "resolution_rank": 1080,
        }])

        self.assertEqual("HD", movie.to_simple_dict()["quality_badge"])

    def test_quality_badge_returns_none_for_other_quality(self):
        movie = self._movie_with_resources([{
            "resolution": "720P",
            "resolution_rank": 720,
        }])

        self.assertIsNone(movie.to_simple_dict()["quality_badge"])


if __name__ == "__main__":
    unittest.main()
