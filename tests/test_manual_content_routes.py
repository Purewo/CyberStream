from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Library, LibraryMovieMembership, MediaResource, Movie, StorageSource


class ManualContentRoutesTests(unittest.TestCase):
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

        self.source = StorageSource(name="课程盘", type="local", config={"root_path": "/media/courses"})
        self.library = Library(name="自建课程", slug="courses")
        db.session.add_all([self.source, self.library])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie(self, title, scraper_source="Local", cover=""):
        movie = Movie(
            tmdb_id=f"local/{title}",
            title=title,
            original_title=title,
            cover=cover,
            scraper_source=scraper_source,
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def _resource(self, movie, path, season=None, episode=None):
        resource = MediaResource(
            movie_id=movie.id,
            source_id=self.source.id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            season=season,
            episode=episode,
            label="Movie",
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def test_other_videos_can_create_manual_tv_and_include_library(self):
        raw_movie = self._movie("课反馈电路的计算")
        resource = self._resource(raw_movie, "电路课程/课反馈电路的计算.mp4")

        queue_response = self.client.get("/api/v1/other-videos?keyword=电路&page_size=20")
        self.assertEqual(200, queue_response.status_code)
        queue_ids = [item["resource_id"] for item in queue_response.get_json()["data"]["items"]]
        self.assertIn(resource.id, queue_ids)

        create_response = self.client.post(
            "/api/v1/movies/manual",
            json={
                "title": "电路课程",
                "description": "自己上传的电路基础课",
                "media_type": "tv",
                "resource_ids": [resource.id],
                "default_season": 1,
                "episode_start": 3,
                "library_ids": [self.library.id],
            },
        )
        self.assertEqual(201, create_response.status_code)
        data = create_response.get_json()["data"]
        movie_id = data["movie"]["id"]

        manual_movie = db.session.get(Movie, movie_id)
        moved_resource = db.session.get(MediaResource, resource.id)
        self.assertEqual(Movie.MANUAL_SOURCE_TV, manual_movie.scraper_source)
        self.assertEqual(Movie.CATALOG_VISIBILITY_HIDDEN, manual_movie.catalog_visibility_status)
        self.assertFalse(manual_movie.get_metadata_ui_state()["needs_attention"])
        issue_codes = {issue["code"] for issue in manual_movie.get_metadata_issues()}
        self.assertNotIn("poster_missing", issue_codes)
        self.assertNotIn("season_metadata_missing", issue_codes)
        self.assertEqual(movie_id, moved_resource.movie_id)
        self.assertEqual(1, moved_resource.season)
        self.assertEqual(3, moved_resource.episode)
        self.assertIsNone(db.session.get(Movie, raw_movie.id))

        memberships = LibraryMovieMembership.query.filter_by(movie_id=movie_id).all()
        self.assertEqual([self.library.id], [row.library_id for row in memberships])

        library_response = self.client.get(f"/api/v1/libraries/{self.library.id}/movies?page_size=20")
        self.assertEqual(200, library_response.status_code)
        library_ids = [item["id"] for item in library_response.get_json()["data"]["items"]]
        self.assertIn(movie_id, library_ids)

        default_response = self.client.get("/api/v1/movies?page_size=20")
        self.assertEqual(200, default_response.status_code)
        default_ids = [item["id"] for item in default_response.get_json()["data"]["items"]]
        self.assertNotIn(movie_id, default_ids)

        attention_response = self.client.get("/api/v1/metadata/work-items?needs_attention=true&page_size=20")
        self.assertEqual(200, attention_response.status_code)
        attention_ids = [item["id"] for item in attention_response.get_json()["data"]["items"]]
        self.assertNotIn(movie_id, attention_ids)

        queue_response = self.client.get("/api/v1/other-videos?keyword=电路&page_size=20")
        self.assertEqual(200, queue_response.status_code)
        queue_ids = [item["resource_id"] for item in queue_response.get_json()["data"]["items"]]
        self.assertNotIn(resource.id, queue_ids)

    def test_other_videos_excludes_episode_review_resources(self):
        standalone_movie = self._movie("未识别单片")
        standalone_resource = self._resource(standalone_movie, "散片/未识别单片.mp4")
        episode_movie = self._movie("本地剧集")
        episode_resource = self._resource(episode_movie, "本地剧集/S01E01.mkv", season=1, episode=1)

        queue_response = self.client.get("/api/v1/other-videos?page_size=20")
        self.assertEqual(200, queue_response.status_code)
        queue_items = queue_response.get_json()["data"]["items"]
        queue_resource_ids = {item["resource_id"] for item in queue_items}
        queue_movie_ids = {item["movie_id"] for item in queue_items}
        queue_issue_codes = {
            issue["code"]
            for item in queue_items
            for issue in item.get("metadata_issues", [])
        }

        self.assertIn(standalone_resource.id, queue_resource_ids)
        self.assertNotIn(episode_resource.id, queue_resource_ids)
        self.assertNotIn("season_metadata_missing", queue_issue_codes)

        review_response = self.client.get("/api/v1/metadata/episode-review-items?page_size=20")
        self.assertEqual(200, review_response.status_code)
        review_movie_ids = {
            item["movie_id"]
            for item in review_response.get_json()["data"]["items"]
        }
        self.assertIn(episode_movie.id, review_movie_ids)
        self.assertFalse(queue_movie_ids & review_movie_ids)

    def test_other_videos_exposes_metadata_match_actions(self):
        movie = self._movie("旧占位标题")
        resource = self._resource(movie, "电影合集/Star.Wars.1977.2160p.mkv")
        resource.tech_specs = {
            "analysis": {
                "path_cleaning": {
                    "title_hint": "Star Wars",
                    "year_hint": 1977,
                },
            },
            "metadata_trace": {
                "media_type_hint": "tv",
            },
        }
        db.session.commit()

        queue_response = self.client.get("/api/v1/other-videos?keyword=Star&page_size=20")
        self.assertEqual(200, queue_response.status_code)
        item = queue_response.get_json()["data"]["items"][0]

        self.assertEqual("match_metadata", item["recommended_resolution"])
        self.assertEqual({
            "suggested_query": "Star Wars",
            "suggested_year": 1977,
            "suggested_media_type_hint": "movie",
            "source_media_type_hint": "tv",
            "media_type_options": ["movie", "tv"],
            "title_hint_source": "path_cleaning",
        }, item["metadata_match_context"])

        match_action = item["actions"]["match_metadata"]
        self.assertEqual("GET", match_action["search"]["method"])
        self.assertEqual(f"/api/v1/movies/{movie.id}/metadata/search", match_action["search"]["endpoint"])
        self.assertEqual({
            "query": "Star Wars",
            "year": 1977,
            "media_type_hint": "movie",
        }, match_action["search"]["params"])
        self.assertEqual(f"/api/v1/movies/{movie.id}/metadata/match", match_action["preview"]["endpoint"])
        self.assertEqual(f"/api/v1/movies/{movie.id}/metadata/match", match_action["apply"]["endpoint"])
        self.assertTrue(match_action["apply"]["body_template"]["apply"])
        self.assertEqual([resource.id], item["actions"]["create_manual_movie"]["body"]["resource_ids"])

    def test_episode_review_excludes_manual_tv_content(self):
        manual_movie = Movie(
            tmdb_id="manual/tv/duplicate-episode",
            title="手工课程",
            original_title="手工课程",
            scraper_source=Movie.MANUAL_SOURCE_TV,
            catalog_visibility_status=Movie.CATALOG_VISIBILITY_HIDDEN,
        )
        db.session.add(manual_movie)
        db.session.commit()
        first_resource = self._resource(manual_movie, "手工课程/S01E01-a.mp4", season=1, episode=1)
        second_resource = self._resource(manual_movie, "手工课程/S01E01-b.mp4", season=1, episode=1)

        queue_response = self.client.get("/api/v1/other-videos?include_manual=true&page_size=20")
        self.assertEqual(200, queue_response.status_code)
        queue_resource_ids = {
            item["resource_id"]
            for item in queue_response.get_json()["data"]["items"]
        }
        self.assertIn(first_resource.id, queue_resource_ids)
        self.assertIn(second_resource.id, queue_resource_ids)

        review_response = self.client.get("/api/v1/metadata/episode-review-items?page_size=20")
        self.assertEqual(200, review_response.status_code)
        review_movie_ids = {
            item["movie_id"]
            for item in review_response.get_json()["data"]["items"]
        }
        self.assertNotIn(manual_movie.id, review_movie_ids)

    def test_attach_resources_can_turn_manual_movie_into_tv(self):
        raw_movie = self._movie("爬虫 01")
        resource = self._resource(raw_movie, "爬虫课程/第01课.mp4")
        manual_movie = Movie(
            tmdb_id="manual/movie/test",
            title="爬虫课程",
            original_title="爬虫课程",
            description="爬虫课程合集",
            scraper_source=Movie.MANUAL_SOURCE_MOVIE,
            catalog_visibility_status=Movie.CATALOG_VISIBILITY_HIDDEN,
        )
        db.session.add(manual_movie)
        db.session.commit()

        response = self.client.post(
            f"/api/v1/movies/{manual_movie.id}/resources/attach",
            json={
                "media_type": "tv",
                "library_ids": [str(self.library.id)],
                "resources": [
                    {
                        "id": resource.id,
                        "season": 1,
                        "episode": 1,
                        "title": "环境准备",
                        "overview": "爬虫环境安装",
                    }
                ],
            },
        )
        self.assertEqual(200, response.status_code)

        db.session.refresh(manual_movie)
        moved_resource = db.session.get(MediaResource, resource.id)
        self.assertEqual(Movie.MANUAL_SOURCE_TV, manual_movie.scraper_source)
        self.assertEqual(manual_movie.id, moved_resource.movie_id)
        self.assertEqual(1, moved_resource.season)
        self.assertEqual(1, moved_resource.episode)
        self.assertEqual("环境准备", moved_resource.title)
        self.assertEqual("爬虫环境安装", moved_resource.overview)
        self.assertEqual(1, LibraryMovieMembership.query.filter_by(movie_id=manual_movie.id).count())


if __name__ == "__main__":
    unittest.main()
