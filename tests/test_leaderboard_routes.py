from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Account, History, MediaResource, Movie
from backend.app.services.accounts import account_scope


class LeaderboardRoutesTests(unittest.TestCase):
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

    def _movie_with_resource(self, title, *, rating=0, added_at=None):
        timestamp = added_at or datetime.utcnow()
        movie = Movie(
            tmdb_id=f"movie/{title.lower().replace(' ', '-')}",
            title=title,
            original_title=title,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
            rating=rating,
            added_at=timestamp,
            updated_at=timestamp,
        )
        db.session.add(movie)
        db.session.flush()

        resource = MediaResource(
            movie_id=movie.id,
            path=f"movies/{title}.mkv",
            filename=f"{title}.mkv",
            label=title,
            tech_specs={"resolution": "1080P", "resolution_rank": 1080},
        )
        db.session.add(resource)
        db.session.flush()
        return movie, resource

    def _add_history(self, resource, *, view_count, last_watched):
        history = History(
            resource_id=resource.id,
            progress=120,
            duration=600,
            view_count=view_count,
            device_id=f"device-{resource.id}",
            last_watched=last_watched,
        )
        db.session.add(history)
        db.session.flush()
        return history

    def test_hot_leaderboard_orders_by_windowed_views(self):
        now = datetime.utcnow()
        evergreen, evergreen_resource = self._movie_with_resource(
            "Evergreen",
            rating=6.5,
            added_at=now - timedelta(days=100),
        )
        recent, recent_resource = self._movie_with_resource(
            "Recent",
            rating=9.0,
            added_at=now - timedelta(days=1),
        )
        _, old_resource = self._movie_with_resource(
            "Old Views",
            rating=10.0,
            added_at=now - timedelta(days=2),
        )
        self._add_history(evergreen_resource, view_count=5, last_watched=now - timedelta(days=1))
        self._add_history(recent_resource, view_count=2, last_watched=now - timedelta(hours=2))
        self._add_history(old_resource, view_count=9, last_watched=now - timedelta(days=40))
        db.session.commit()

        response = self.client.get("/api/v1/leaderboard?type=hot&window=weekly&page_size=10")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual({"type": "hot", "window": "weekly", "metric_name": "views"}, data["summary"])
        self.assertEqual([evergreen.id, recent.id], [item["id"] for item in data["items"]])
        self.assertEqual([1, 2], [item["rank"] for item in data["items"]])
        self.assertEqual([5, 2], [item["views"] for item in data["items"]])
        self.assertEqual([5, 2], [item["play_count"] for item in data["items"]])
        self.assertEqual(5, data["items"][0]["leaderboard"]["metric_value"])

    def test_rated_and_new_leaderboards_respect_type_and_window(self):
        now = datetime.utcnow()
        lower_rated, _ = self._movie_with_resource(
            "Lower Rated",
            rating=8.0,
            added_at=now - timedelta(days=1),
        )
        higher_rated, _ = self._movie_with_resource(
            "Higher Rated",
            rating=9.5,
            added_at=now - timedelta(days=2),
        )
        old_top_rated, _ = self._movie_with_resource(
            "Old Top Rated",
            rating=10.0,
            added_at=now - timedelta(days=40),
        )
        db.session.commit()

        rated = self.client.get("/api/v1/leaderboard?type=rated&window=monthly&page_size=10")
        self.assertEqual(200, rated.status_code)
        self.assertEqual(
            [higher_rated.id, lower_rated.id],
            [item["id"] for item in rated.get_json()["data"]["items"]],
        )
        self.assertNotIn(
            old_top_rated.id,
            [item["id"] for item in rated.get_json()["data"]["items"]],
        )

        newest = self.client.get("/api/v1/leaderboard?type=new&window=all_time&page_size=10")
        self.assertEqual(200, newest.status_code)
        self.assertEqual(
            [lower_rated.id, higher_rated.id, old_top_rated.id],
            [item["id"] for item in newest.get_json()["data"]["items"]],
        )
        self.assertEqual("added_at", newest.get_json()["data"]["summary"]["metric_name"])

    def test_movie_list_returns_total_play_count(self):
        movie, resource = self._movie_with_resource("Counted", rating=7.0)
        self._add_history(
            resource,
            view_count=4,
            last_watched=datetime.utcnow() - timedelta(days=2),
        )
        db.session.commit()

        response = self.client.get("/api/v1/movies?page=1&page_size=10")

        self.assertEqual(200, response.status_code)
        item = next(row for row in response.get_json()["data"]["items"] if row["id"] == movie.id)
        self.assertEqual(4, item["views"])
        self.assertEqual(4, item["play_count"])

    def test_leaderboard_play_counts_are_isolated_by_account(self):
        account_a = Account(name="Account A", slug="account-a")
        account_b = Account(name="Account B", slug="account-b")
        db.session.add_all([account_a, account_b])
        db.session.commit()

        with account_scope(account_a.id):
            movie_a, resource_a = self._movie_with_resource("Account A Movie", rating=7.0)
            self._add_history(resource_a, view_count=3, last_watched=datetime.utcnow())
            db.session.commit()

        with account_scope(account_b.id):
            movie_b, resource_b = self._movie_with_resource("Account B Movie", rating=8.0)
            self._add_history(resource_b, view_count=9, last_watched=datetime.utcnow())
            db.session.commit()

        with account_scope(account_a.id):
            response = self.client.get("/api/v1/leaderboard?type=hot&window=all_time")

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]["items"]
        self.assertEqual([movie_a.id], [item["id"] for item in items])
        self.assertEqual(3, items[0]["views"])
        self.assertNotEqual(movie_b.id, items[0]["id"])

    def test_invalid_leaderboard_parameters_return_api_errors(self):
        invalid_type = self.client.get("/api/v1/leaderboard?type=unknown")
        self.assertEqual(400, invalid_type.status_code)
        self.assertEqual(40093, invalid_type.get_json()["code"])

        invalid_window = self.client.get("/api/v1/leaderboard?window=yearly")
        self.assertEqual(400, invalid_window.status_code)
        self.assertEqual(40094, invalid_window.get_json()["code"])


if __name__ == "__main__":
    unittest.main()
