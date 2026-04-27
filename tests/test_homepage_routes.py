from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import HomepageSetting, MediaResource, Movie


class HomepageRoutesTests(unittest.TestCase):
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
        category,
        added_offset=0,
        cover="https://img.example/poster.jpg",
        background_cover=None,
        scraper_source="TMDB",
    ):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            year=2026,
            cover=cover,
            background_cover=background_cover,
            category=category,
            scraper_source=scraper_source,
            added_at=datetime.utcnow() + timedelta(seconds=added_offset),
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def test_default_homepage_creates_four_default_sections(self):
        response = self.client.get("/api/v1/homepage")
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, HomepageSetting.query.count())
        self.assertEqual(["科幻", "动作", "剧情", "动画"], [
            section["genre"] for section in payload["data"]["sections"]
        ])
        self.assertEqual([15, 15, 15, 15], [
            section["limit"] for section in payload["data"]["sections"]
        ])

    def test_existing_default_limit_ten_is_upgraded_to_fifteen(self):
        db.session.add(HomepageSetting(
            id=1,
            sections=[
                {"key": "sci_fi", "title": "科幻", "genre": "科幻", "mode": "latest", "limit": 10, "movie_ids": [], "enabled": True, "sort_order": 0},
                {"key": "action", "title": "动作", "genre": "动作", "mode": "latest", "limit": 10, "movie_ids": [], "enabled": True, "sort_order": 1},
                {"key": "drama", "title": "剧情", "genre": "剧情", "mode": "latest", "limit": 10, "movie_ids": [], "enabled": True, "sort_order": 2},
                {"key": "animation", "title": "动画", "genre": "动画", "mode": "latest", "limit": 10, "movie_ids": [], "enabled": True, "sort_order": 3},
            ],
        ))
        db.session.commit()

        response = self.client.get("/api/v1/homepage/config")
        sections = response.get_json()["data"]["sections"]

        self.assertEqual([15, 15, 15, 15], [section["limit"] for section in sections])

    def test_config_patch_and_get_roundtrip(self):
        hero = self._movie("Hero", ["科幻"], background_cover="https://img.example/hero.jpg")

        response = self.client.patch("/api/v1/homepage/config", json={
            "hero_movie_id": hero.id,
            "sections": [{
                "key": "sci_fi_custom",
                "title": "科幻精选",
                "genre": "Sci-Fi",
                "mode": "custom",
                "limit": 4,
                "movie_ids": [hero.id],
                "enabled": True,
                "sort_order": 0,
            }],
        })
        self.assertEqual(200, response.status_code)

        config_response = self.client.get("/api/v1/homepage/config")
        config = config_response.get_json()["data"]

        self.assertEqual(hero.id, config["hero_movie_id"])
        self.assertEqual("科幻精选", config["sections"][0]["title"])
        self.assertEqual("科幻", config["sections"][0]["genre"])
        self.assertEqual([hero.id], config["sections"][0]["movie_ids"])

    def test_custom_section_does_not_auto_fill_when_under_limit(self):
        custom_movie = self._movie("Manual Sci-Fi", ["科幻"])
        self._movie("Auto Sci-Fi", ["科幻"], added_offset=10)

        self.client.patch("/api/v1/homepage/config", json={
            "sections": [{
                "key": "sci_fi",
                "title": "科幻",
                "genre": "科幻",
                "mode": "custom",
                "limit": 4,
                "movie_ids": [custom_movie.id],
                "enabled": True,
                "sort_order": 0,
            }],
        })

        response = self.client.get("/api/v1/homepage")
        items = response.get_json()["data"]["sections"][0]["items"]

        self.assertEqual(1, len(items))
        self.assertEqual(custom_movie.id, items[0]["id"])

    def test_hero_movie_is_excluded_from_sections(self):
        hero = self._movie("Hero Sci-Fi", ["科幻"], added_offset=20, background_cover="https://img.example/hero.jpg")
        other = self._movie("Other Sci-Fi", ["科幻"], added_offset=10)

        self.client.patch("/api/v1/homepage/config", json={
            "hero_movie_id": hero.id,
            "sections": [{
                "key": "sci_fi",
                "title": "科幻",
                "genre": "科幻",
                "mode": "latest",
                "limit": 4,
                "enabled": True,
                "sort_order": 0,
            }],
        })

        response = self.client.get("/api/v1/homepage")
        data = response.get_json()["data"]
        section_ids = [item["id"] for item in data["sections"][0]["items"]]

        self.assertEqual(hero.id, data["hero"]["movie"]["id"])
        self.assertNotIn(hero.id, section_ids)
        self.assertIn(other.id, section_ids)

    def test_animation_section_excludes_animation_from_other_sections(self):
        animated_action = self._movie("Animated Action", ["动画", "动作"], added_offset=20)
        pure_action = self._movie("Pure Action", ["动作"], added_offset=10)

        self.client.patch("/api/v1/homepage/config", json={
            "sections": [
                {
                    "key": "action",
                    "title": "动作",
                    "genre": "动作",
                    "mode": "latest",
                    "limit": 4,
                    "enabled": True,
                    "sort_order": 0,
                },
                {
                    "key": "animation",
                    "title": "动画",
                    "genre": "动画",
                    "mode": "latest",
                    "limit": 4,
                    "enabled": True,
                    "sort_order": 1,
                },
            ],
        })

        response = self.client.get("/api/v1/homepage")
        sections = response.get_json()["data"]["sections"]
        action_ids = [item["id"] for item in sections[0]["items"]]
        animation_ids = [item["id"] for item in sections[1]["items"]]

        self.assertIn(pure_action.id, action_ids)
        self.assertNotIn(animated_action.id, action_ids)
        self.assertIn(animated_action.id, animation_ids)

    def test_latest_section_filters_low_quality_movies(self):
        good = self._movie("Good Action", ["动作"], added_offset=0)
        self._movie("No Poster Action", ["动作"], added_offset=20, cover="")
        self._movie("Medium Review Action", ["动作"], added_offset=15, scraper_source="NFO_LOCAL")
        self._movie("High Review Action", ["动作"], added_offset=10, scraper_source="LOCAL_FALLBACK")

        self.client.patch("/api/v1/homepage/config", json={
            "sections": [{
                "key": "action",
                "title": "动作",
                "genre": "动作",
                "mode": "latest",
                "limit": 3,
                "enabled": True,
                "sort_order": 0,
            }],
        })

        response = self.client.get("/api/v1/homepage")
        items = response.get_json()["data"]["sections"][0]["items"]

        self.assertEqual([good.id], [item["id"] for item in items])

    def test_homepage_sections_do_not_return_season_cards(self):
        movie = self._movie("Multi Season Animation", ["动画"])
        db.session.add(MediaResource(
            movie_id=movie.id,
            path="animation/s01e01.mkv",
            filename="s01e01.mkv",
            season=1,
            episode=1,
            label="S01E01",
        ))
        db.session.add(MediaResource(
            movie_id=movie.id,
            path="animation/s02e01.mkv",
            filename="s02e01.mkv",
            season=2,
            episode=1,
            label="S02E01",
        ))
        db.session.commit()

        self.client.patch("/api/v1/homepage/config", json={
            "sections": [{
                "key": "animation",
                "title": "动画",
                "genre": "动画",
                "mode": "latest",
                "limit": 15,
                "enabled": True,
                "sort_order": 0,
            }],
        })

        response = self.client.get("/api/v1/homepage")
        item = response.get_json()["data"]["sections"][0]["items"][0]

        self.assertEqual(movie.id, item["id"])
        self.assertEqual([], item["season_cards"])
        self.assertEqual(2, item["season_count"])

    def test_config_validation_rejects_invalid_values(self):
        missing_movie_response = self.client.patch("/api/v1/homepage/config", json={
            "hero_movie_id": "missing-movie",
        })
        self.assertEqual(400, missing_movie_response.status_code)

        invalid_mode_response = self.client.patch("/api/v1/homepage/config", json={
            "sections": [{
                "key": "bad",
                "genre": "动作",
                "mode": "random",
                "limit": 4,
            }],
        })
        self.assertEqual(400, invalid_mode_response.status_code)

        invalid_limit_response = self.client.patch("/api/v1/homepage/config", json={
            "sections": [{
                "key": "bad",
                "genre": "动作",
                "mode": "latest",
                "limit": 0,
            }],
        })
        self.assertEqual(400, invalid_limit_response.status_code)


if __name__ == "__main__":
    unittest.main()
