from __future__ import annotations

import sys
import unittest
from datetime import datetime
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import History, MediaResource, Movie


class HistoryRoutesTests(unittest.TestCase):
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

    def _movie_with_resource(self, title="History Movie", season=None, episode=None):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            cover="https://img.example/poster.jpg",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.flush()

        resource = MediaResource(
            movie_id=movie.id,
            path=f"movies/{title}.mkv",
            filename=f"{title}.mkv",
            label="Movie",
            season=season,
            episode=episode,
            tech_specs={"resolution": "1080P", "resolution_rank": 1080},
        )
        db.session.add(resource)
        db.session.commit()
        return movie, resource

    def _add_history(self, resource, progress=120, duration=600):
        history = History(
            resource_id=resource.id,
            progress=progress,
            duration=duration,
            view_count=1,
            device_id="test-device",
            device_name="Test Device",
            last_watched=datetime.utcnow(),
        )
        db.session.add(history)
        db.session.commit()
        return history

    def test_report_and_get_history_keeps_progress_without_is_played(self):
        _, resource = self._movie_with_resource()

        post_response = self.client.post("/api/v1/user/history", json={
            "resource_id": resource.id,
            "position_sec": 240,
            "total_duration": 1000,
            "device_id": "browser",
            "device_name": "Chrome",
        })
        self.assertEqual(200, post_response.status_code)

        response = self.client.get("/api/v1/user/history?page=1&page_size=10")
        self.assertEqual(200, response.status_code)
        item = response.get_json()["data"]["items"][0]

        self.assertEqual(resource.id, item["resource_id"])
        self.assertEqual(240, item["progress"])
        self.assertEqual(1000, item["duration"])
        self.assertNotIn("is_played", item)

    @patch("backend.app.api.history_routes.record_audio_transcode_history_heartbeat")
    def test_report_progress_notifies_audio_transcode_watchdog(self, record_heartbeat):
        _, resource = self._movie_with_resource()

        response = self.client.post("/api/v1/user/history", json={
            "resource_id": resource.id,
            "position_sec": 120,
            "total_duration": 1000,
            "session_id": "playback_01",
        })

        self.assertEqual(200, response.status_code)
        record_heartbeat.assert_called_once_with(
            resource.id,
            session_id="playback_01",
            inactive_timeout_seconds=180,
        )

    def test_movie_list_and_detail_return_user_data_without_is_played(self):
        movie, resource = self._movie_with_resource()
        self._add_history(resource, progress=300, duration=900)

        list_response = self.client.get("/api/v1/movies?page=1&page_size=10")
        self.assertEqual(200, list_response.status_code)
        items = list_response.get_json()["data"]["items"]
        item = next(row for row in items if row["id"] == movie.id)
        self.assertEqual(resource.id, item["user_data"]["resource_id"])
        self.assertEqual(300, item["user_data"]["progress"])
        self.assertNotIn("is_played", item["user_data"])

        detail_response = self.client.get(f"/api/v1/movies/{movie.id}")
        self.assertEqual(200, detail_response.status_code)
        detail = detail_response.get_json()["data"]
        self.assertEqual(resource.id, detail["user_data"]["resource_id"])
        self.assertNotIn("is_played", detail["user_data"])

    def test_resource_groups_return_user_data_without_is_played(self):
        movie, resource = self._movie_with_resource(season=1, episode=1)
        self._add_history(resource, progress=60, duration=600)

        response = self.client.get(f"/api/v1/movies/{movie.id}/resources")
        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]

        resource_item = data["items"][0]
        season_group = data["groups"]["seasons"][0]
        self.assertEqual(resource.id, resource_item["user_data"]["resource_id"])
        self.assertNotIn("is_played", resource_item["user_data"])
        self.assertEqual(resource.id, season_group["user_data"]["resource_id"])
        self.assertNotIn("is_played", season_group["user_data"])


if __name__ == "__main__":
    unittest.main()
