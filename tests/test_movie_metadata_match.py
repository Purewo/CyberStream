from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import (
    HomepageSetting,
    History,
    Library,
    LibraryMovieMembership,
    MediaResource,
    Movie,
    MovieMetadataLock,
    MovieSeasonMetadata,
    StorageSource,
    UserFavorite,
)


class MovieMetadataMatchTests(unittest.TestCase):
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

    def test_match_defaults_to_preview_and_does_not_apply_metadata(self):
        movie = Movie(
            tmdb_id="tv/old",
            title="旧标题",
            original_title="Old Title",
            year=2014,
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.commit()

        tmdb_payload = {
            "tmdb_id": "tv/67954",
            "title": "画江湖之不良人",
            "original_title": "Hua Jiang Hu Zhi Bu Liang Ren",
            "year": 2016,
            "rating": 8.6,
            "description": "test",
            "cover": "poster",
            "background_cover": "backdrop",
            "category": ["动画"],
            "director": "test director",
            "actors": ["甲", "乙"],
            "country": "中国大陆",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "tv/67954",
                    "media_type_hint": "tv",
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("Movie metadata match preview", payload["msg"])
        data = payload["data"]
        self.assertTrue(data["dry_run"])
        self.assertEqual("旧标题", data["current"]["title"])
        self.assertEqual("画江湖之不良人", data["preview"]["title"])
        self.assertEqual({"candidate_id": "tv/67954", "apply": True, "media_type_hint": "tv"}, data["apply_payload"])

        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("tv/old", refreshed.tmdb_id)
        self.assertEqual("旧标题", refreshed.title)

    def test_match_can_unlock_locked_fields_and_replace_metadata(self):
        movie = Movie(
            tmdb_id="tv/old",
            title="旧标题",
            original_title="Old Title",
            year=2014,
            country="中国",
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.commit()

        db.session.add(MovieMetadataLock(movie_id=movie.id, locked_fields=["title", "year"]))
        db.session.commit()

        tmdb_payload = {
            "tmdb_id": "tv/67954",
            "title": "画江湖之不良人",
            "original_title": "Hua Jiang Hu Zhi Bu Liang Ren",
            "year": 2016,
            "rating": 8.6,
            "description": "test",
            "cover": "poster",
            "background_cover": "backdrop",
            "category": ["动画"],
            "director": "test director",
            "actors": ["甲", "乙"],
            "country": "中国大陆",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "tv/67954",
                    "metadata_unlocked_fields": ["title", "year"],
                    "media_type_hint": "tv",
                    "apply": True,
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("Movie metadata matched", payload["msg"])

        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("tv/67954", refreshed.tmdb_id)
        self.assertEqual("画江湖之不良人", refreshed.title)
        self.assertEqual(2016, refreshed.year)
        self.assertEqual([], refreshed.get_locked_fields())

    def test_match_preserves_existing_category_year_and_rating_when_external_entry_is_sparse(self):
        movie = Movie(
            tmdb_id="tv/old-sparse",
            title="旧标题",
            original_title="Old Title",
            year=2016,
            rating=6.5,
            cover="existing-poster",
            category=["动作", "科幻"],
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        sparse_tmdb_payload = {
            "tmdb_id": "tv/302809",
            "title": "画江湖之不良人Ⅵ",
            "original_title": "画江湖之不良人Ⅵ",
            "year": None,
            "rating": 0.0,
            "description": "",
            "cover": "",
            "background_cover": "",
            "category": [],
            "director": "Unknown",
            "actors": [],
            "country": "China",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=sparse_tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "tv/302809",
                    "media_type_hint": "tv",
                    "apply": True,
                },
            )

        self.assertEqual(200, response.status_code)

        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("tv/302809", refreshed.tmdb_id)
        self.assertEqual("画江湖之不良人Ⅵ", refreshed.title)
        self.assertEqual(2016, refreshed.year)
        self.assertEqual(6.5, refreshed.rating)
        self.assertEqual("existing-poster", refreshed.cover)
        self.assertEqual(["动作", "科幻"], refreshed.category)

    def test_apply_rejects_missing_poster_without_explicit_override(self):
        movie = Movie(
            tmdb_id="loc-foundation",
            title="基地3",
            original_title="基地3",
            year=None,
            cover="",
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.commit()

        no_poster_payload = {
            "tmdb_id": "movie/1312801",
            "title": "Foundation",
            "original_title": "Foundation",
            "year": 2024,
            "rating": 0.0,
            "description": "",
            "cover": "",
            "background_cover": "",
            "category": [],
            "director": "",
            "actors": [],
            "country": "",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=no_poster_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "movie/1312801",
                    "media_type_hint": "movie",
                    "apply": True,
                },
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual(40920, response.get_json()["code"])
        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("loc-foundation", refreshed.tmdb_id)
        self.assertEqual("基地3", refreshed.title)

    def test_preview_reflects_final_values_when_sparse_candidate_preserves_current_poster(self):
        movie = Movie(
            tmdb_id="tv/93740",
            title="基地",
            original_title="Foundation",
            year=2021,
            cover="existing-poster",
            background_cover="existing-backdrop",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()

        sparse_payload = {
            "tmdb_id": "movie/1312801",
            "title": "Foundation",
            "original_title": "Foundation",
            "year": 2024,
            "rating": 0.0,
            "description": "An old hotel. A missing woman.",
            "cover": "",
            "background_cover": "",
            "category": [],
            "director": "",
            "actors": [],
            "country": "",
            "scraper_source": "TMDB",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=sparse_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={
                    "tmdb_id": "movie/1312801",
                    "media_type_hint": "movie",
                },
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("An old hotel. A missing woman.", data["preview"]["overview"])
        self.assertEqual("existing-poster", data["preview"]["poster_url"])
        self.assertEqual("existing-backdrop", data["preview"]["backdrop_url"])

        fields = {item["field"]: item for item in data["diff"]["fields"]}
        self.assertEqual("An old hotel. A missing woman.", fields["description"]["preview_value"])
        self.assertEqual("existing-poster", fields["cover"]["preview_value"])
        self.assertEqual("existing-backdrop", fields["background_cover"]["preview_value"])

    def test_match_existing_tmdb_movie_merges_orphan_relations_and_resources(self):
        target = Movie(
            tmdb_id="tv/67954",
            title="既有正确条目",
            cover="target-poster",
            scraper_source="TMDB",
        )
        orphan = Movie(
            tmdb_id="loc-tv-orphan",
            title="脏目录幽灵条目",
            cover="orphan-poster",
            scraper_source="LOCAL_FALLBACK",
        )
        library = Library(name="剧集", slug="tv")
        source = StorageSource(name="Cloud", type="local", config={"root_path": "/shows"})
        db.session.add_all([target, orphan, library, source])
        db.session.flush()
        old_target_resource = MediaResource(
            movie_id=target.id,
            source_id=source.id,
            path="shows/jackal/S01E01.AMZN.mkv",
            filename="S01E01.AMZN.mkv",
            season=1,
            episode=1,
        )
        orphan_resource = MediaResource(
            movie_id=orphan.id,
            source_id=source.id,
            path="shows/jackal/S01E01.NOW.mkv",
            filename="S01E01.NOW.mkv",
            season=1,
            episode=1,
        )
        db.session.add_all([old_target_resource, orphan_resource])
        db.session.flush()
        db.session.add_all([
            History(resource_id=orphan_resource.id, progress=120, duration=600),
            LibraryMovieMembership(library_id=library.id, movie_id=target.id, mode="include"),
            LibraryMovieMembership(library_id=library.id, movie_id=orphan.id, mode="include"),
            UserFavorite(scope_key="default", movie_id=target.id),
            UserFavorite(scope_key="default", movie_id=orphan.id),
            MovieMetadataLock(movie_id=orphan.id, locked_fields=["description"]),
            MovieSeasonMetadata(movie_id=orphan.id, season=1, title="幽灵季名"),
            HomepageSetting(
                id=1,
                hero_movie_id=orphan.id,
                sections=[{"key": "custom", "movie_ids": [orphan.id, target.id]}],
            ),
        ])
        db.session.commit()
        orphan_id = orphan.id
        resource_id = orphan_resource.id
        target_resource_id = old_target_resource.id

        tmdb_payload = {
            "tmdb_id": "tv/67954",
            "title": "豺狼的日子",
            "original_title": "The Day of the Jackal",
            "year": 2024,
            "rating": 8.2,
            "description": "new description",
            "cover": "new-poster",
            "background_cover": "new-backdrop",
            "category": ["剧情"],
            "director": "Creator",
            "actors": ["演员"],
            "country": "英国",
            "scraper_source": "TMDB",
            "season_metadata": [{"season": 1, "title": "Season 1", "episode_count": 10}],
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{orphan_id}/metadata/match",
                json={"tmdb_id": "tv/67954", "media_type_hint": "tv", "apply": True},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(target.id, response.get_json()["data"]["id"])
        self.assertIsNone(db.session.get(Movie, orphan_id))

        refreshed_target = db.session.get(Movie, target.id)
        self.assertEqual("豺狼的日子", refreshed_target.title)
        self.assertEqual("new-poster", refreshed_target.cover)
        self.assertEqual("", refreshed_target.description or "")
        self.assertIn("description", refreshed_target.get_locked_fields())
        self.assertIsNone(db.session.get(MediaResource, resource_id))
        merged_resource = db.session.get(MediaResource, target_resource_id)
        self.assertEqual(target.id, merged_resource.movie_id)
        self.assertEqual("shows/jackal/S01E01.NOW.mkv", merged_resource.path)
        self.assertEqual(target_resource_id, History.query.first().resource_id)
        self.assertEqual(1, LibraryMovieMembership.query.filter_by(library_id=library.id, movie_id=target.id).count())
        self.assertEqual(1, UserFavorite.query.filter_by(scope_key="default", movie_id=target.id).count())

        setting = db.session.get(HomepageSetting, 1)
        self.assertEqual(target.id, setting.hero_movie_id)
        self.assertEqual([target.id], setting.sections[0]["movie_ids"])
        season = MovieSeasonMetadata.query.filter_by(movie_id=target.id, season=1).first()
        self.assertEqual("Season 1", season.title)

    def test_applying_movie_match_clears_stale_episode_resources(self):
        movie = Movie(
            tmdb_id="loc-venom",
            title="Venom The Last Danc Blu ray 1 HDT",
            original_title="Venom The Last Danc Blu ray 1 HDT",
            year=2024,
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.flush()
        resource = MediaResource(
            movie_id=movie.id,
            path=(
                "Movies/Venom The Last Dance 2024 2160p UHD Blu-ray Remux HEVC DV TrueHD 7.1 Atmos-HDT/"
                "Venom The Last Dance 2024 2160p UHD Blu-ray Remux HEVC DV TrueHD 7.1 Atmos-HDT.mkv"
            ),
            filename="Venom The Last Dance 2024 2160p UHD Blu-ray Remux HEVC DV TrueHD 7.1 Atmos-HDT.mkv",
            season=3,
            episode=1,
            label="S03E01 - 2160P",
            tech_specs={
                "resolution": "2160P",
                "features": {"is_movie_feature": False},
                "metadata_trace": {"media_type_hint": "tv"},
            },
        )
        db.session.add(resource)
        db.session.commit()

        tmdb_payload = {
            "tmdb_id": "movie/912649",
            "title": "毒液：最后一舞",
            "original_title": "Venom: The Last Dance",
            "year": 2024,
            "rating": 6.7,
            "description": "movie",
            "cover": "poster",
            "background_cover": "",
            "category": ["动作"],
            "director": "Director",
            "actors": [],
            "country": "US",
            "scraper_source": "TMDB",
            "media_type_hint": "movie",
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={"tmdb_id": "movie/912649", "media_type_hint": "movie", "apply": True},
            )

        self.assertEqual(200, response.status_code)
        refreshed = db.session.get(MediaResource, resource.id)
        self.assertIsNone(refreshed.season)
        self.assertIsNone(refreshed.episode)
        self.assertEqual("Movie - 2160P", refreshed.label)
        self.assertTrue(refreshed.tech_specs["features"]["is_movie_feature"])
        self.assertEqual("movie", refreshed.tech_specs["metadata_trace"]["media_type_hint"])
        self.assertEqual("movie_filename_year", refreshed.tech_specs["metadata_trace"]["parse_strategy"])

    def test_applying_tv_match_repairs_parenthesized_episode_resources(self):
        movie = Movie(
            tmdb_id="loc-tang",
            title="Tang Changan",
            original_title="Tang Changan",
            year=2025,
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.flush()
        first = MediaResource(
            movie_id=movie.id,
            path="Shows/Tang Changan/tang.2025.2160p.WEB-DL.S03 (1).mkv",
            filename="tang.2025.2160p.WEB-DL.S03 (1).mkv",
            label="Movie - 2160P",
            tech_specs={
                "resolution": "2160P",
                "features": {"is_movie_feature": True},
                "metadata_trace": {"media_type_hint": "movie"},
            },
        )
        tenth = MediaResource(
            movie_id=movie.id,
            path="Shows/Tang Changan/tang.2025.2160p.WEB-DL.S03 (10).mkv",
            filename="tang.2025.2160p.WEB-DL.S03 (10).mkv",
            label="Movie - 2160P",
            tech_specs={
                "resolution": "2160P",
                "features": {"is_movie_feature": True},
                "metadata_trace": {"media_type_hint": "movie"},
            },
        )
        db.session.add_all([first, tenth])
        db.session.commit()

        tmdb_payload = {
            "tmdb_id": "tv/12345",
            "title": "Tang Changan",
            "original_title": "Tang Changan",
            "year": 2025,
            "rating": 8.0,
            "description": "series",
            "cover": "poster",
            "background_cover": "",
            "category": ["TV"],
            "director": "Director",
            "actors": [],
            "country": "CN",
            "scraper_source": "TMDB",
            "media_type_hint": "tv",
            "season_metadata": [{"season": 3, "title": "Season 3", "episode_count": 40}],
        }

        with patch("backend.app.api.library_routes.scraper.get_movie_details", return_value=tmdb_payload):
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={"tmdb_id": "tv/12345", "media_type_hint": "movie", "apply": True},
            )

        self.assertEqual(200, response.status_code)
        refreshed_first = db.session.get(MediaResource, first.id)
        refreshed_tenth = db.session.get(MediaResource, tenth.id)
        self.assertEqual((3, 1), (refreshed_first.season, refreshed_first.episode))
        self.assertEqual((3, 10), (refreshed_tenth.season, refreshed_tenth.episode))
        self.assertEqual("S03E01 - 2160P", refreshed_first.label)
        self.assertFalse(refreshed_first.tech_specs["features"]["is_movie_feature"])
        self.assertEqual("tv", refreshed_first.tech_specs["metadata_trace"]["media_type_hint"])

        season = MovieSeasonMetadata.query.filter_by(movie_id=movie.id, season=3).first()
        self.assertIsNotNone(season)
        self.assertEqual(40, season.episode_count)


if __name__ == "__main__":
    unittest.main()
