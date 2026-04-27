from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import History, Library, LibraryMovieMembership, MediaResource, Movie, StorageSource


class RecommendationReasonsTests(unittest.TestCase):
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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie(self, title, rating=7.0, category=None, added_days_ago=0):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            year=2026,
            rating=rating,
            cover=f"https://img.example/{title}.jpg",
            category=category or ["动作"],
            scraper_source="TMDB",
            added_at=datetime.utcnow() - timedelta(days=added_days_ago),
        )
        db.session.add(movie)
        db.session.flush()
        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path=f"movies/{title}.mkv",
            filename=f"{title}.mkv",
            label="Movie - 2160P",
            tech_specs={"resolution": "2160P", "resolution_rank": 2160},
        )
        db.session.add(resource)
        db.session.commit()
        return movie, resource

    def _history(self, resource, progress=300, duration=1000):
        history = History(
            resource_id=resource.id,
            progress=progress,
            duration=duration,
            last_watched=datetime.utcnow(),
        )
        db.session.add(history)
        db.session.commit()
        return history

    def test_default_recommendations_return_ranked_reasons(self):
        continue_movie, continue_resource = self._movie(
            "Continue Movie",
            rating=7.2,
            category=["剧情"],
            added_days_ago=10,
        )
        self._history(continue_resource, progress=250, duration=1000)
        self._movie("Fresh Action", rating=8.2, category=["动作"], added_days_ago=1)
        self._movie("Old Classic", rating=9.0, category=["科幻"], added_days_ago=90)

        response = self.client.get("/api/v1/recommendations?strategy=default&limit=3")

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]
        self.assertEqual(3, len(items))
        self.assertEqual(continue_movie.id, items[0]["id"])
        recommendation = items[0]["recommendation"]
        self.assertEqual("default", recommendation["strategy"])
        self.assertEqual(1, recommendation["rank"])
        self.assertEqual("continue_watching", recommendation["primary_reason"]["code"])
        self.assertIn("score", recommendation)
        self.assertGreater(recommendation["signals"]["resource_count"], 0)

    def test_library_recommendations_keep_membership_and_add_reason_payload(self):
        library = Library(name="精选库", slug="picked")
        movie, _ = self._movie("Manual Pick", rating=8.4, category=["科幻"], added_days_ago=2)
        db.session.add(library)
        db.session.commit()
        db.session.add(LibraryMovieMembership(library_id=library.id, movie_id=movie.id, mode="include"))
        db.session.commit()

        response = self.client.get(f"/api/v1/libraries/{library.id}/recommendations?strategy=latest&limit=5")

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]
        self.assertEqual([movie.id], [item["id"] for item in items])
        self.assertEqual("manual", items[0]["library_membership"])
        self.assertEqual("latest", items[0]["recommendation"]["strategy"])
        reason_codes = [reason["code"] for reason in items[0]["recommendation"]["reasons"]]
        self.assertIn("recently_added", reason_codes)

    def test_context_recommendations_prioritize_same_series_before_same_genre(self):
        anchor, _ = self._movie("Avatar: Fire and Ash", rating=7.2, category=["科幻"], added_days_ago=2)
        same_series, _ = self._movie("Avatar: The Way of Water", rating=6.8, category=["科幻"], added_days_ago=50)
        same_genre, _ = self._movie("Interstellar", rating=9.0, category=["科幻"], added_days_ago=1)
        anime, _ = self._movie("Cyber Anime", rating=9.8, category=["动画", "科幻"], added_days_ago=0)

        response = self.client.get(f"/api/v1/movies/{anchor.id}/recommendations?limit=3")

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]
        item_ids = [item["id"] for item in items]
        self.assertEqual(same_series.id, item_ids[0])
        self.assertIn(same_genre.id, item_ids)
        self.assertNotIn(anime.id, item_ids)
        self.assertEqual("context", items[0]["recommendation"]["strategy"])
        self.assertEqual("same_title_family", items[0]["recommendation"]["primary_reason"]["code"])
        reason_codes = [reason["code"] for reason in items[0]["recommendation"]["reasons"]]
        self.assertIn("same_title_family", reason_codes)
        self.assertIn("live_action_partition", reason_codes)

    def test_context_recommendations_prefer_current_library_then_fill_global(self):
        library = Library(name="科幻小库", slug="sci-fi-library")
        db.session.add(library)
        db.session.commit()

        anchor, _ = self._movie("Avatar: Fire and Ash", rating=7.2, category=["科幻"], added_days_ago=2)
        library_pick, _ = self._movie("Dune", rating=7.5, category=["科幻"], added_days_ago=20)
        outside_same_series, _ = self._movie("Avatar: The Way of Water", rating=9.4, category=["科幻"], added_days_ago=0)
        self._movie("Cyber Anime", rating=9.8, category=["动画", "科幻"], added_days_ago=0)
        db.session.add(LibraryMovieMembership(library_id=library.id, movie_id=anchor.id, mode="include"))
        db.session.add(LibraryMovieMembership(library_id=library.id, movie_id=library_pick.id, mode="include"))
        db.session.commit()

        response = self.client.get(
            f"/api/v1/movies/{anchor.id}/recommendations?library_id={library.id}&limit=2"
        )

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]
        self.assertEqual([library_pick.id, outside_same_series.id], [item["id"] for item in items])
        first_reason_codes = [reason["code"] for reason in items[0]["recommendation"]["reasons"]]
        second_reason_codes = [reason["code"] for reason in items[1]["recommendation"]["reasons"]]
        self.assertIn("same_library", first_reason_codes)
        self.assertIn("outside_library_fill", second_reason_codes)
        self.assertEqual("same_genre", items[0]["recommendation"]["primary_reason"]["code"])
        self.assertEqual("same_title_family", items[1]["recommendation"]["primary_reason"]["code"])

    def test_context_recommendations_do_not_mix_anime_and_live_action(self):
        anchor, _ = self._movie("Galaxy Anime", rating=8.0, category=["动画", "科幻"], added_days_ago=1)
        anime_candidate, _ = self._movie("Future Anime", rating=7.0, category=["动画", "科幻"], added_days_ago=4)
        live_action_candidate, _ = self._movie("Future Live Action", rating=9.9, category=["科幻"], added_days_ago=0)

        response = self.client.get(f"/api/v1/movies/{anchor.id}/recommendations?limit=5")

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]
        item_ids = [item["id"] for item in items]
        self.assertEqual([anime_candidate.id], item_ids)
        self.assertNotIn(live_action_candidate.id, item_ids)
        reason_codes = [reason["code"] for reason in items[0]["recommendation"]["reasons"]]
        self.assertIn("anime_partition", reason_codes)


if __name__ == "__main__":
    unittest.main()
