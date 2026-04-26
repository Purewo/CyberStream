from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie
from backend.app.utils.genres import normalize_genres, normalize_tmdb_genres


class GenreNormalizationTests(unittest.TestCase):
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

    def test_normalizes_tmdb_tv_genre_aliases(self):
        self.assertEqual(
            ["科幻", "奇幻", "动作", "冒险", "战争", "政治"],
            normalize_genres(["Sci-Fi & Fantasy", "动作冒险", "War & Politics", "Local", "Movie", "TV"]),
        )
        self.assertEqual(
            ["科幻", "奇幻", "动作", "冒险"],
            normalize_tmdb_genres([
                {"id": 10765, "name": "Sci-Fi & Fantasy"},
                {"id": 10759, "name": "动作冒险"},
            ]),
        )

    def test_filters_and_movie_tags_return_public_genres(self):
        tv_movie = Movie(
            tmdb_id="tv/1",
            title="测试科幻剧",
            original_title="Test Sci-Fi Show",
            year=2024,
            cover="https://img.example/tv-1.jpg",
            category=["动画", "Sci-Fi & Fantasy", "动作冒险"],
            scraper_source="TMDB",
        )
        local_movie = Movie(
            tmdb_id="loc-test",
            title="本地占位",
            original_title="Local Placeholder",
            year=2077,
            category=["TV", "Local"],
            scraper_source="Local",
        )
        db.session.add_all([tv_movie, local_movie])
        db.session.commit()

        filters_response = self.client.get("/api/v1/filters?include=genres")
        filters_payload = filters_response.get_json()
        genre_names = [item["name"] for item in filters_payload["data"]["genres"]]

        self.assertEqual(200, filters_response.status_code)
        for expected in ["动画", "科幻", "奇幻", "动作", "冒险"]:
            self.assertIn(expected, genre_names)
        for unexpected in ["Local", "Movie", "TV", "Sci-Fi & Fantasy", "动作冒险"]:
            self.assertNotIn(unexpected, genre_names)

        movies_response = self.client.get("/api/v1/movies?genre=科幻&page_size=10")
        movies_payload = movies_response.get_json()
        items = movies_payload["data"]["items"]

        self.assertEqual(200, movies_response.status_code)
        self.assertEqual(1, len(items))
        self.assertEqual("测试科幻剧", items[0]["title"])
        self.assertEqual(["动画", "科幻", "奇幻", "动作", "冒险"], items[0]["tags"])


if __name__ == "__main__":
    unittest.main()
