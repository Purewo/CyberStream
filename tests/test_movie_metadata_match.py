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

    def test_match_defaults_to_preview_and_does_not_apply_metadata(self):
        movie = Movie(
            tmdb_id="tv/old",
            title="旧标题",
            original_title="Old Title",
            year=2014,
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
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
                    "media_type_hint": "tv",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("Movie metadata match preview", payload["msg"])
        data = payload["data"]
        self.assertTrue(data["dry_run"])
        self.assertEqual("旧标题", data["current"]["title"])
        self.assertEqual("画江湖之不良人", data["preview"]["title"])
        self.assertEqual({"candidate_id": "tv/67954", "apply": True, "media_type_hint": "tv"}, data["apply_payload"])

        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("tv/old", refreshed.tmdb_id)
        self.assertEqual("旧标题", refreshed.title)

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
                    "apply": True,
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
            cover="existing-poster",
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
                    "apply": True,
                },
            )

        self.assertEqual(200, response.status_code)

        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("tv/302809", refreshed.tmdb_id)
        self.assertEqual("画江湖之不良人Ⅵ", refreshed.title)
        self.assertEqual(2016, refreshed.year)
        self.assertEqual(6.5, refreshed.rating)
        self.assertEqual("existing-poster", refreshed.cover)
        self.assertEqual(["动作", "科幻"], refreshed.category)

    def test_apply_rejects_missing_poster_without_explicit_override(self):
        movie = Movie(
            tmdb_id="loc-foundation",
            title="基地3",
            original_title="基地3",
            year=None,
            cover="",
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.commit()

        no_poster_payload = {
            "tmdb_id": "movie/1312801",
            "title": "Foundation",
            "original_title": "Foundation",
            "year": 2024,
            "rating": 0.0,
            "description": "",
            "cover": "",
            "background_cover": "",
            "category": [],
            "director": "",
            "actors": [],
            "country": "",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=no_poster_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "movie/1312801",
                    "media_type_hint": "movie",
                    "apply": True,
                },
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual(40920, response.get_json()["code"])
        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("loc-foundation", refreshed.tmdb_id)
        self.assertEqual("基地3", refreshed.title)

    def test_preview_reflects_final_values_when_sparse_candidate_preserves_current_poster(self):
        movie = Movie(
            tmdb_id="tv/93740",
            title="基地",
            original_title="Foundation",
            year=2021,
            cover="existing-poster",
            background_cover="existing-backdrop",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        sparse_payload = {
            "tmdb_id": "movie/1312801",
            "title": "Foundation",
            "original_title": "Foundation",
            "year": 2024,
            "rating": 0.0,
            "description": "An old hotel. A missing woman.",
            "cover": "",
            "background_cover": "",
            "category": [],
            "director": "",
            "actors": [],
            "country": "",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=sparse_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "movie/1312801",
                    "media_type_hint": "movie",
                },
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("An old hotel. A missing woman.", data["preview"]["overview"])
        self.assertEqual("existing-poster", data["preview"]["poster_url"])
        self.assertEqual("existing-backdrop", data["preview"]["backdrop_url"])

        fields = {item["field"]: item for item in data["diff"]["fields"]}
        self.assertEqual("An old hotel. A missing woman.", fields["description"]["preview_value"])
        self.assertEqual("existing-poster", fields["cover"]["preview_value"])
        self.assertEqual("existing-backdrop", fields["background_cover"]["preview_value"])


if __name__ == "__main__":
    unittest.main()
