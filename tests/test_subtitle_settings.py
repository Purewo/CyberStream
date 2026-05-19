from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, ResourceSubtitleSetting


class SubtitleSettingsRouteTests(unittest.TestCase):
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

    def _resource(self, title="Subtitle Settings Movie"):
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
            tech_specs={"resolution": "1080P", "resolution_rank": 1080},
        )
        db.session.add(resource)
        db.session.commit()
        return movie, resource

    def test_get_subtitle_settings_returns_resource_defaults(self):
        _movie, resource = self._resource()

        response = self.client.get(f"/api/v1/resources/{resource.id}/subtitle-settings")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(resource.id, data["resource_id"])
        self.assertFalse(data["customized"])
        self.assertEqual("default", data["source"])
        self.assertEqual({
            "zhSize": 28,
            "zhColor": "#FFFFFF",
            "enSize": 22,
            "enColor": "#FFFFFF",
            "gap": 6,
            "offset": 72,
        }, data["settings"])

    def test_patch_subtitle_settings_persists_per_resource_and_embeds_in_playback(self):
        movie, resource = self._resource()

        response = self.client.patch(f"/api/v1/resources/{resource.id}/subtitle-settings", json={
            "settings": {
                "zhSize": 32,
                "zhColor": "#f80",
                "enSize": 24,
                "enColor": "#00ffcc",
                "gap": 10,
                "offset": -24,
            }
        })

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["customized"])
        self.assertEqual("resource", data["source"])
        self.assertEqual({
            "zhSize": 32,
            "zhColor": "#FF8800",
            "enSize": 24,
            "enColor": "#00FFCC",
            "gap": 10,
            "offset": -24,
        }, data["settings"])

        row = ResourceSubtitleSetting.query.filter_by(resource_id=resource.id).one()
        self.assertEqual(32, row.zh_size)
        self.assertEqual("#FF8800", row.zh_color)

        resources_response = self.client.get(f"/api/v1/movies/{movie.id}/resources")
        self.assertEqual(200, resources_response.status_code)
        subtitles = resources_response.get_json()["data"]["items"][0]["playback"]["subtitles"]
        self.assertEqual(data["settings"], subtitles["settings"])
        self.assertTrue(subtitles["settings_customized"])
        self.assertEqual("resource", subtitles["settings_source"])

    def test_put_accepts_top_level_partial_payload_and_keeps_other_fields(self):
        _movie, resource = self._resource()
        first = self.client.put(f"/api/v1/resources/{resource.id}/subtitle-settings", json={
            "zhSize": 30,
            "offset": 100,
        })
        self.assertEqual(200, first.status_code)

        second = self.client.patch(f"/api/v1/resources/{resource.id}/subtitle-settings", json={
            "enColor": "#abc",
        })

        self.assertEqual(200, second.status_code)
        settings = second.get_json()["data"]["settings"]
        self.assertEqual(30, settings["zhSize"])
        self.assertEqual(100, settings["offset"])
        self.assertEqual("#AABBCC", settings["enColor"])
        self.assertEqual(22, settings["enSize"])

        third = self.client.patch(f"/api/v1/resources/{resource.id}/subtitle-settings", json={
            "settings": {},
            "gap": 12,
        })
        self.assertEqual(200, third.status_code)
        self.assertEqual(12, third.get_json()["data"]["settings"]["gap"])

    def test_settings_are_isolated_by_resource(self):
        _movie_a, resource_a = self._resource("Resource A")
        _movie_b, resource_b = self._resource("Resource B")

        response = self.client.patch(f"/api/v1/resources/{resource_a.id}/subtitle-settings", json={
            "offset": 120,
        })
        self.assertEqual(200, response.status_code)

        data_a = self.client.get(f"/api/v1/resources/{resource_a.id}/subtitle-settings").get_json()["data"]
        data_b = self.client.get(f"/api/v1/resources/{resource_b.id}/subtitle-settings").get_json()["data"]
        self.assertEqual(120, data_a["settings"]["offset"])
        self.assertEqual(72, data_b["settings"]["offset"])
        self.assertTrue(data_a["customized"])
        self.assertFalse(data_b["customized"])

    def test_invalid_subtitle_settings_are_rejected(self):
        _movie, resource = self._resource()

        bad_color = self.client.patch(f"/api/v1/resources/{resource.id}/subtitle-settings", json={
            "zhColor": "white",
        })
        bad_size = self.client.patch(f"/api/v1/resources/{resource.id}/subtitle-settings", json={
            "zhSize": 200,
        })
        unsupported = self.client.patch(f"/api/v1/resources/{resource.id}/subtitle-settings", json={
            "fontWeight": 700,
        })

        self.assertEqual(400, bad_color.status_code)
        self.assertEqual(40080, bad_color.get_json()["code"])
        self.assertEqual(400, bad_size.status_code)
        self.assertEqual(40080, bad_size.get_json()["code"])
        self.assertEqual(400, unsupported.status_code)
        self.assertEqual(40080, unsupported.get_json()["code"])
        self.assertEqual(0, ResourceSubtitleSetting.query.filter_by(resource_id=resource.id).count())

    def test_unknown_resource_settings_return_not_found(self):
        response = self.client.get("/api/v1/resources/11111111-1111-1111-1111-111111111111/subtitle-settings")

        self.assertEqual(404, response.status_code)
        self.assertEqual(40403, response.get_json()["code"])


if __name__ == "__main__":
    unittest.main()
