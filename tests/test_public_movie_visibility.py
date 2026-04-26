from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie


class PublicMovieVisibilityTests(unittest.TestCase):
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

    def _movie(
        self,
        title,
        scraper_source="TMDB",
        cover="https://img.example/poster.jpg",
        category=None,
        year=2026,
        country="中国",
    ):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            year=year,
            country=country,
            cover=cover,
            category=category or ["动作"],
            scraper_source=scraper_source,
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def test_movies_default_hides_attention_rows_but_explicit_queue_can_show_them(self):
        public_movie = self._movie("Public Movie")
        raw_movie = self._movie(
            "Raw No Poster",
            scraper_source="Local",
            cover="",
            category=["恐怖"],
            year=2077,
            country="本地",
        )
        no_poster_tmdb = self._movie(
            "Matched No Poster",
            scraper_source="TMDB",
            cover="",
            category=["科幻"],
        )
        fallback_movie = self._movie(
            "Fallback Needs Review",
            scraper_source="LOCAL_FALLBACK",
            category=["剧情"],
        )

        default_response = self.client.get("/api/v1/movies?page_size=20")
        self.assertEqual(200, default_response.status_code)
        default_ids = [item["id"] for item in default_response.get_json()["data"]["items"]]

        self.assertIn(public_movie.id, default_ids)
        self.assertNotIn(raw_movie.id, default_ids)
        self.assertNotIn(no_poster_tmdb.id, default_ids)
        self.assertNotIn(fallback_movie.id, default_ids)

        attention_response = self.client.get("/api/v1/movies?needs_attention=true&page_size=20")
        self.assertEqual(200, attention_response.status_code)
        attention_ids = [item["id"] for item in attention_response.get_json()["data"]["items"]]

        self.assertNotIn(public_movie.id, attention_ids)
        self.assertIn(raw_movie.id, attention_ids)
        self.assertIn(no_poster_tmdb.id, attention_ids)
        self.assertIn(fallback_movie.id, attention_ids)

    def test_public_filters_exclude_attention_rows(self):
        self._movie("Public Movie", category=["动作"], year=2026, country="中国")
        self._movie(
            "Raw No Poster",
            scraper_source="LOCAL_ORPHAN",
            cover="",
            category=["恐怖"],
            year=2077,
            country="本地",
        )
        self._movie(
            "Matched No Poster",
            scraper_source="TMDB",
            cover="",
            category=["科幻"],
            year=2025,
            country="美国",
        )

        response = self.client.get("/api/v1/filters?include=genres,years,countries")
        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]

        self.assertEqual(["动作"], [item["name"] for item in data["genres"]])
        self.assertEqual([2026], [item["year"] for item in data["years"]])
        self.assertEqual(["中国"], [item["name"] for item in data["countries"]])

    def test_can_filter_missing_poster_issue_for_metadata_workbench(self):
        public_movie = self._movie("Public Movie")
        no_poster_movie = self._movie("Matched No Poster", scraper_source="TMDB", cover="")

        response = self.client.get("/api/v1/movies?metadata_issue_code=poster_missing&page_size=20")
        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]["items"]
        item_ids = [item["id"] for item in items]

        self.assertNotIn(public_movie.id, item_ids)
        self.assertIn(no_poster_movie.id, item_ids)
        self.assertEqual(["poster_missing"], items[0]["metadata_state"]["issue_codes"])


if __name__ == "__main__":
    unittest.main()
