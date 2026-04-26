from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie, MovieMetadataLock


class MovieMetadataMatchTests(unittest.TestCase):
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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_match_can_unlock_locked_fields_and_replace_metadata(self):
        movie = Movie(
            tmdb_id="tv/old",
            title="旧标题",
            original_title="Old Title",
            year=2014,
            country="中国",
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.commit()

        db.session.add(MovieMetadataLock(movie_id=movie.id, locked_fields=["title", "year"]))
        db.session.commit()

        tmdb_payload = {
            "tmdb_id": "tv/67954",
            "title": "画江湖之不良人",
            "original_title": "Hua Jiang Hu Zhi Bu Liang Ren",
            "year": 2016,
            "rating": 8.6,
            "description": "test",
            "cover": "poster",
            "background_cover": "backdrop",
            "category": ["动画"],
            "director": "test director",
            "actors": ["甲", "乙"],
            "country": "中国大陆",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "tv/67954",
                    "metadata_unlocked_fields": ["title", "year"],
                    "media_type_hint": "tv",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("Movie metadata matched", payload["msg"])

        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("tv/67954", refreshed.tmdb_id)
        self.assertEqual("画江湖之不良人", refreshed.title)
        self.assertEqual(2016, refreshed.year)
        self.assertEqual([], refreshed.get_locked_fields())

    def test_match_preserves_existing_category_year_and_rating_when_external_entry_is_sparse(self):
        movie = Movie(
            tmdb_id="tv/old-sparse",
            title="旧标题",
            original_title="Old Title",
            year=2016,
            rating=6.5,
            category=["动作", "科幻"],
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        sparse_tmdb_payload = {
            "tmdb_id": "tv/302809",
            "title": "画江湖之不良人Ⅵ",
            "original_title": "画江湖之不良人Ⅵ",
            "year": None,
            "rating": 0.0,
            "description": "",
            "cover": "",
            "background_cover": "",
            "category": [],
            "director": "Unknown",
            "actors": [],
            "country": "China",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=sparse_tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "tv/302809",
                    "media_type_hint": "tv",
                },
            )

        self.assertEqual(200, response.status_code)

        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("tv/302809", refreshed.tmdb_id)
        self.assertEqual("画江湖之不良人Ⅵ", refreshed.title)
        self.assertEqual(2016, refreshed.year)
        self.assertEqual(6.5, refreshed.rating)
        self.assertEqual(["动作", "科幻"], refreshed.category)


if __name__ == "__main__":
    unittest.main()
