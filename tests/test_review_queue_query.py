from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, StorageSource


class ReviewQueueQueryTests(unittest.TestCase):
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

        self.source = StorageSource(name="Test Source", type="local", config={"root_path": "/tmp"})
        db.session.add(self.source)
        db.session.commit()

        review_movie = Movie(
            tmdb_id="movie/1",
            title="The Green Planet",
            original_title="The Green Planet",
            year=2022,
        )
        normal_movie = Movie(
            tmdb_id="movie/2",
            title="Interstellar",
            original_title="Interstellar",
            year=2014,
        )
        db.session.add_all([review_movie, normal_movie])
        db.session.commit()

        review_resource = MediaResource(
            movie_id=review_movie.id,
            source_id=self.source.id,
            path="我的视频/绿色星球/Green Planet 1.m2ts",
            filename="Green Planet 1.m2ts",
            label="EP01 - 1080P",
            tech_specs={
                "analysis": {
                    "path_cleaning": {
                        "title_hint": "Green Planet",
                        "year_hint": None,
                        "parse_mode": "fallback",
                        "parse_strategy": "dirty_release_group",
                        "needs_review": True,
                    },
                    "scraping": {
                        "provider": "tmdb",
                        "confidence": 0.85,
                        "matched_id": "tv/1",
                        "warnings": ["title_hint_overridden:Green Planet->The Green Planet"],
                        "final_title_source": "tmdb",
                        "final_year_source": "tmdb",
                        "provider_order": ["tmdb", "local"],
                    },
                }
            },
        )
        normal_resource = MediaResource(
            movie_id=normal_movie.id,
            source_id=self.source.id,
            path="我的视频/星际穿越/Interstellar.2014.mkv",
            filename="Interstellar.2014.mkv",
            label="Movie - 4K",
            tech_specs={
                "analysis": {
                    "path_cleaning": {
                        "title_hint": "Interstellar",
                        "year_hint": 2014,
                        "parse_mode": "standard",
                        "parse_strategy": "movie_filename_year",
                        "needs_review": False,
                    },
                    "scraping": {
                        "provider": "tmdb",
                        "confidence": 0.95,
                        "matched_id": "movie/2",
                        "warnings": [],
                        "final_title_source": "tmdb",
                        "final_year_source": "tmdb",
                        "provider_order": ["tmdb", "local"],
                    },
                }
            },
        )
        db.session.add_all([review_resource, normal_resource])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_review_queue_returns_only_needs_review_resources(self):
        response = self.client.get("/api/v1/reviews/resources?page=1&page_size=10")
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(payload["data"]["items"]))
        item = payload["data"]["items"][0]
        self.assertEqual("Green Planet 1.m2ts", item["resource_info"]["file"]["filename"])
        self.assertTrue(item["metadata"]["path_cleaning"]["needs_review"])
        self.assertEqual("tmdb", item["metadata"]["scraping"]["provider"])

    def test_review_queue_supports_provider_filter(self):
        response = self.client.get("/api/v1/reviews/resources?provider=tmdb")
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(payload["data"]["items"]))

        response = self.client.get("/api/v1/reviews/resources?provider=nfo")
        payload = response.get_json()
        self.assertEqual(0, len(payload["data"]["items"]))


if __name__ == "__main__":
    unittest.main()
