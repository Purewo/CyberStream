from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, MovieSeasonMetadata


class TVSeasonPosterTests(unittest.TestCase):
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

    def test_movie_simple_dict_includes_season_cards(self):
        movie = Movie(
            tmdb_id="tv/100",
            title="赛博番剧",
            original_title="Cyber Anime",
            year=2024,
            cover="https://image.tmdb.org/t/p/w500/series-poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        db.session.add_all([
            MovieSeasonMetadata(
                movie_id=movie.id,
                season=1,
                title="第一季",
                overview="season one",
                air_date="2024-01-01",
                poster="https://image.tmdb.org/t/p/w500/season-1.jpg",
                episode_count=12,
            ),
            MovieSeasonMetadata(
                movie_id=movie.id,
                season=2,
                title="第二季",
                overview="season two",
                air_date="2025-01-01",
                poster="https://image.tmdb.org/t/p/w500/season-2.jpg",
                episode_count=12,
            ),
        ])
        db.session.add_all([
            MediaResource(movie_id=movie.id, path="anime/s1e01.mkv", filename="s1e01.mkv", season=1, episode=1),
            MediaResource(movie_id=movie.id, path="anime/s2e01.mkv", filename="s2e01.mkv", season=2, episode=1),
        ])
        db.session.commit()

        payload = movie.to_simple_dict()

        self.assertEqual(2, payload["season_count"])
        self.assertTrue(payload["has_multi_season_content"])
        self.assertEqual(2, len(payload["season_cards"]))
        self.assertEqual(1, payload["season_cards"][0]["season"])
        self.assertEqual("https://image.tmdb.org/t/p/w500/season-1.jpg", payload["season_cards"][0]["poster_url"])
        self.assertTrue(payload["season_cards"][0]["has_distinct_poster"])
        self.assertEqual(12, payload["season_cards"][0]["episode_count"])
        self.assertEqual(1, payload["season_cards"][0]["available_episode_count"])

    def test_match_syncs_season_metadata_and_seasons_endpoint_returns_posters(self):
        movie = Movie(
            tmdb_id="tv/old",
            title="旧番剧",
            original_title="Old Anime",
            year=2023,
            cover="https://image.tmdb.org/t/p/w500/old-series.jpg",
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.commit()

        db.session.add_all([
            MediaResource(movie_id=movie.id, path="anime/s1e01.mkv", filename="s1e01.mkv", season=1, episode=1),
            MediaResource(movie_id=movie.id, path="anime/s2e01.mkv", filename="s2e01.mkv", season=2, episode=1),
            MovieSeasonMetadata(
                movie_id=movie.id,
                season=3,
                title="旧第三季",
                poster="https://image.tmdb.org/t/p/w500/stale.jpg",
            ),
        ])
        db.session.commit()

        tmdb_payload = {
            "tmdb_id": "tv/67954",
            "title": "新番剧",
            "original_title": "New Anime",
            "year": 2024,
            "rating": 8.8,
            "description": "test",
            "cover": "https://image.tmdb.org/t/p/w500/series-new.jpg",
            "background_cover": "https://image.tmdb.org/t/p/original/backdrop.jpg",
            "category": ["动画"],
            "director": "Creator",
            "actors": ["甲"],
            "country": "JP",
            "scraper_source": "TMDB",
            "season_metadata": [
                {
                    "season": 1,
                    "title": "第一季",
                    "overview": "season one",
                    "air_date": "2024-01-01",
                    "poster": "https://image.tmdb.org/t/p/w500/season-1.jpg",
                    "episode_count": 12,
                },
                {
                    "season": 2,
                    "title": "第二季",
                    "overview": "season two",
                    "air_date": "2025-01-01",
                    "poster": "https://image.tmdb.org/t/p/w500/season-2.jpg",
                    "episode_count": 12,
                },
            ],
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "tv/67954",
                    "media_type_hint": "tv",
                },
            )

        self.assertEqual(200, response.status_code)
        refreshed = db.session.get(Movie, movie.id)
        seasons = MovieSeasonMetadata.query.filter_by(movie_id=movie.id).order_by(MovieSeasonMetadata.season.asc()).all()
        self.assertEqual("tv/67954", refreshed.tmdb_id)
        self.assertEqual([1, 2], [item.season for item in seasons])
        self.assertEqual("https://image.tmdb.org/t/p/w500/season-1.jpg", seasons[0].poster)

        detail_payload = response.get_json()["data"]
        self.assertNotIn("resources", detail_payload)
        self.assertEqual(2, len(detail_payload["season_cards"]))
        self.assertEqual("https://image.tmdb.org/t/p/w500/season-2.jpg", detail_payload["season_cards"][1]["poster_url"])

        resources_response = self.client.get(f"/api/v1/movies/{movie.id}/resources")
        self.assertEqual(200, resources_response.status_code)
        resources_payload = resources_response.get_json()["data"]
        self.assertEqual(2, len(resources_payload["items"]))
        self.assertNotIn("standalone_items", resources_payload)
        self.assertNotIn("season_groups", resources_payload)
        self.assertEqual([], resources_payload["groups"]["standalone"]["resource_ids"])
        self.assertEqual([1, 2], [item["season"] for item in resources_payload["groups"]["seasons"]])
        self.assertEqual(1, resources_payload["groups"]["seasons"][0]["episode_count"])
        self.assertNotIn("items", resources_payload["groups"]["seasons"][0])

        seasons_response = self.client.get(f"/api/v1/movies/{movie.id}/seasons")
        self.assertEqual(200, seasons_response.status_code)
        seasons_payload = seasons_response.get_json()["data"]
        self.assertEqual(2, len(seasons_payload["items"]))
        self.assertEqual("https://image.tmdb.org/t/p/w500/season-1.jpg", seasons_payload["items"][0]["poster_url"])
        self.assertEqual(2, seasons_payload["summary"]["season_metadata_count"])


if __name__ == "__main__":
    unittest.main()
