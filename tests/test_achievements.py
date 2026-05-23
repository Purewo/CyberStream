from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import History, MediaResource, Movie, User, UserAchievement, UserFavorite
from backend.app.services.login_rate_limit import clear_all_login_failures
from backend.app.services.users import set_user_password


class AchievementRoutesTests(unittest.TestCase):
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

    def _movie_with_resource(self, title="Achievement Movie", tech_specs=None, added_at=None):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
            added_at=added_at or datetime.utcnow(),
        )
        db.session.add(movie)
        db.session.flush()
        resource = MediaResource(
            movie_id=movie.id,
            path=f"movies/{title}.mkv",
            filename=f"{title}.mkv",
            label="Movie",
            tech_specs=tech_specs or {},
        )
        db.session.add(resource)
        db.session.commit()
        return movie, resource

    def test_get_achievements_returns_defs_and_user_state(self):
        response = self.client.get("/api/v1/user/achievements")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        defs_by_id = {item["id"]: item for item in data["defs"]}
        user_by_id = {item["id"]: item for item in data["user"]}

        self.assertIn("network_legend", defs_by_id)
        self.assertEqual("milestone", defs_by_id["network_legend"]["category"])
        self.assertEqual("completed_movies_count", defs_by_id["network_legend"]["trigger"]["metric"])
        self.assertIn("overclock", defs_by_id)
        self.assertEqual("behavior", defs_by_id["overclock"]["category"])
        self.assertIsNone(user_by_id["overclock"]["unlocked_at"])

    def test_behavior_unlock_is_idempotent_and_rejects_milestone(self):
        first = self.client.post("/api/v1/user/achievements/unlock", json={"id": "overclock"})
        second = self.client.post("/api/v1/user/achievements/unlock", json={"id": "overclock"})
        milestone = self.client.post("/api/v1/user/achievements/unlock", json={"id": "network_legend"})

        self.assertEqual(200, first.status_code)
        self.assertTrue(first.get_json()["data"]["newly_unlocked"])
        self.assertEqual(200, second.status_code)
        self.assertFalse(second.get_json()["data"]["newly_unlocked"])
        self.assertEqual(400, milestone.status_code)
        self.assertEqual(1, UserAchievement.query.filter_by(achievement_id="overclock").count())

    def test_history_report_unlocks_quality_and_legacy_milestones(self):
        _movie, resource = self._movie_with_resource(
            title="Legacy DV Atmos",
            added_at=datetime.utcnow() - timedelta(days=400),
            tech_specs={
                "resolution": "2160P",
                "resolution_rank": 2160,
                "hdr_format": "Dolby Vision",
                "audio_codec": "Dolby TrueHD Atmos",
                "features": {"is_4k": True, "is_dolby_vision": True},
            },
        )

        response = self.client.post("/api/v1/user/history", json={
            "resource_id": resource.id,
            "position_sec": 120,
            "total_duration": 1000,
            "device_id": "browser-a",
        })
        self.assertEqual(200, response.status_code)

        achievements = self.client.get("/api/v1/user/achievements").get_json()["data"]["user"]
        unlocked = {
            item["id"]
            for item in achievements
            if item["unlocked_at"]
        }

        self.assertIn("quality_supreme", unlocked)
        self.assertIn("dolby_eye", unlocked)
        self.assertIn("surround_field", unlocked)
        self.assertIn("cold_archaeologist", unlocked)

    def test_clear_history_unlocks_ghost_even_after_history_is_deleted(self):
        _movie, resource = self._movie_with_resource()
        db.session.add(History(resource_id=resource.id, progress=10, duration=100, last_watched=datetime.utcnow()))
        db.session.commit()

        response = self.client.delete("/api/v1/user/history")

        self.assertEqual(200, response.status_code)
        self.assertEqual(0, History.query.count())
        achievements = self.client.get("/api/v1/user/achievements").get_json()["data"]["user"]
        ghost = next(item for item in achievements if item["id"] == "ghost")
        self.assertIsNotNone(ghost["unlocked_at"])

    def test_collector_is_a_server_calculated_milestone(self):
        for index in range(50):
            movie = Movie(
                tmdb_id=f"movie/favorite-{index}",
                title=f"Favorite {index}",
                scraper_source="TMDB",
            )
            db.session.add(movie)
            db.session.flush()
            db.session.add(UserFavorite(scope_key="default", movie_id=movie.id))
        db.session.commit()

        data = self.client.get("/api/v1/user/achievements").get_json()["data"]
        definition = next(item for item in data["defs"] if item["id"] == "collector")
        state = next(item for item in data["user"] if item["id"] == "collector")

        self.assertEqual("milestone", definition["category"])
        self.assertEqual("favorites_count", definition["trigger"]["metric"])
        self.assertIsNotNone(state["unlocked_at"])
        self.assertEqual(1, state["progress"])


class AchievementUserIsolationTests(unittest.TestCase):
    def setUp(self):
        clear_all_login_failures()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "USER_MANAGEMENT_ENABLED": True,
            "SESSION_SECRET": "test-session-secret",
            "SECRET_KEY": "test-session-secret",
            "API_TOKEN": "",
            "AUTH_ENABLED": False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        self._user("alice")
        self._user("bob")

    def tearDown(self):
        clear_all_login_failures()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _user(self, username):
        user = User(username=username, display_name=username, role=User.ROLE_USER, is_enabled=True)
        set_user_password(user, "password-123")
        db.session.add(user)
        db.session.commit()
        return user

    def _login(self, username):
        response = self.client.post("/api/v1/auth/login", json={"username": username, "password": "password-123"})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))

    def _achievement_state(self, achievement_id):
        response = self.client.get("/api/v1/user/achievements")
        self.assertEqual(200, response.status_code)
        return next(item for item in response.get_json()["data"]["user"] if item["id"] == achievement_id)

    def test_behavior_achievements_are_isolated_by_user(self):
        self._login("alice")
        response = self.client.post("/api/v1/user/achievements/unlock", json={"id": "overclock"})
        self.assertEqual(200, response.status_code)
        self.assertIsNotNone(self._achievement_state("overclock")["unlocked_at"])
        self.client.post("/api/v1/auth/logout")

        self._login("bob")
        self.assertIsNone(self._achievement_state("overclock")["unlocked_at"])


if __name__ == "__main__":
    unittest.main()
