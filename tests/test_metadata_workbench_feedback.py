from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.metadata.types import EntityMetadataContext, MetadataResolution
from backend.app.models import MediaResource, Movie


class MetadataWorkbenchFeedbackTests(unittest.TestCase):
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

    def _add_movie(self, title="旧标题", scraper_source="LOCAL_FALLBACK", cover="poster"):
        movie = Movie(
            tmdb_id=f"loc-{title}",
            title=title,
            original_title=title,
            year=2020,
            cover=cover,
            scraper_source=scraper_source,
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def _add_resource(self, movie, path="shows/Old.Title.S01E01.mkv"):
        resource = MediaResource(
            movie_id=movie.id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            season=1,
            episode=1,
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def _entity_context(self, resource):
        return EntityMetadataContext(
            title="New Title",
            year=2024,
            media_type_hint="tv",
            parse_layer="fallback",
            parse_strategy="dirty_release_group",
            confidence="medium",
            sample_path=resource.path,
            nfo_candidates=[],
            files=[{"path": resource.path, "name": resource.filename, "_meta": {}}],
        )

    def _tmdb_resolution(self):
        return MetadataResolution(
            meta_data={
                "tmdb_id": "tv/100",
                "title": "New Title",
                "original_title": "New Title",
                "year": 2024,
                "rating": 8.1,
                "description": "updated",
                "cover": "new-poster",
                "background_cover": "new-backdrop",
                "category": ["剧情"],
                "director": "Creator",
                "actors": ["Actor"],
                "country": "JP",
                "scraper_source": "TMDB_FALLBACK",
            },
            resolved_tmdb_id="tv/100",
            scrape_layer="fallback",
            scrape_strategy="dirty_release_group",
            reason="tmdb_match",
        )

    def test_batch_re_scrape_reports_apply_status_and_error_category(self):
        updated_movie = self._add_movie()
        failed_movie = self._add_movie(title="空资源")
        resource = self._add_resource(updated_movie)
        entity_context = self._entity_context(resource)
        resolution = self._tmdb_resolution()

        def resolve_movie(movie, media_type_hint=None):
            if movie.id == updated_movie.id:
                return {
                    "resources": [resource],
                    "entity_context": entity_context,
                    "resolution": resolution,
                    "resource_count": 1,
                }
            raise ValueError("Movie has no resources")

        with patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.resolve_movie",
            side_effect=resolve_movie,
        ), patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.apply_resource_traces",
        ):
            response = self.client.post(
                "/api/v1/metadata/re-scrape",
                json={
                    "items": [
                        {"id": updated_movie.id, "media_type_hint": "tv"},
                        {"id": failed_movie.id},
                    ]
                },
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        data = payload["data"]
        items = {item["movie_id"]: item for item in data["items"]}

        updated_item = items[updated_movie.id]
        self.assertEqual("updated", updated_item["status"])
        self.assertTrue(updated_item["changed"])
        self.assertIn("title", updated_item["updated_fields"])
        self.assertEqual(
            "external_match_needs_review",
            updated_item["explanation"]["classification"]["code"],
        )
        self.assertEqual("tv/100", updated_item["explanation"]["candidate"]["tmdb_id"])

        failed_item = items[failed_movie.id]
        self.assertEqual("failed", failed_item["status"])
        self.assertEqual("no_resources", failed_item["error"]["category"])
        self.assertFalse(failed_item["error"]["retryable"])

        self.assertEqual(2, data["summary"]["total"])
        self.assertEqual(1, data["summary"]["updated"])
        self.assertEqual(1, data["summary"]["failed"])
        self.assertEqual(1, data["summary"]["status_counts"]["updated"])
        self.assertEqual(1, data["summary"]["status_counts"]["failed"])

    def test_preview_explains_placeholder_metadata_result(self):
        movie = self._add_movie(title="Unknown Raw", cover="")
        resource = self._add_resource(movie, path="raw/Unknown.Raw.2024.mkv")
        entity_context = self._entity_context(resource)
        resolution = MetadataResolution(
            meta_data={
                "tmdb_id": "loc-unknown-raw",
                "title": "Unknown Raw",
                "original_title": "Unknown Raw",
                "year": 2024,
                "rating": 0,
                "description": "Unidentified (Local)",
                "cover": "",
                "background_cover": "",
                "category": ["Local"],
                "director": "Unknown",
                "actors": [],
                "country": "Unknown",
                "scraper_source": "LOCAL_FALLBACK",
            },
            resolved_tmdb_id=None,
            scrape_layer="fallback",
            scrape_strategy="local_placeholder",
            reason="local_placeholder",
        )

        with patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.resolve_movie",
            return_value={
                "resources": [resource],
                "entity_context": entity_context,
                "resolution": resolution,
                "resource_count": 1,
            },
        ):
            response = self.client.post(f"/api/v1/movies/{movie.id}/metadata/preview", json={})

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        data = payload["data"]
        self.assertEqual(
            "placeholder_metadata",
            data["preview"]["explanation"]["classification"]["code"],
        )
        self.assertEqual(
            "placeholder_metadata",
            data["explanation"]["classification"]["code"],
        )
        self.assertEqual(resource.path, data["preview"]["parse"]["sample_path"])

    def test_search_candidates_include_match_explanation(self):
        movie = self._add_movie(title="Deep Sea", scraper_source="TMDB")
        candidates = [
            {
                "tmdb_id": "movie/667717",
                "media_type": "movie",
                "title": "Deep Sea",
                "original_title": "深海",
                "overview": "",
                "year": 2023,
                "poster_url": "poster",
                "backdrop_url": "",
                "popularity": 20,
                "vote_average": 7.1,
            }
        ]

        with patch(
            "backend.app.api.library_routes.scraper.search_movie_candidates",
            return_value=candidates,
        ):
            response = self.client.get(
                f"/api/v1/movies/{movie.id}/metadata/search"
                "?query=Deep%20Sea&year=2023&media_type_hint=movie"
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        item = payload["data"]["items"][0]
        self.assertEqual(1, item["rank"])
        self.assertEqual("high", item["match_explanation"]["confidence"])
        self.assertIn("title_exact", item["match_explanation"]["reason_codes"])
        self.assertIn("year_match", item["match_explanation"]["reason_codes"])
        self.assertIn("media_type_match", item["match_explanation"]["reason_codes"])


if __name__ == "__main__":
    unittest.main()
