from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.metadata.parser import PathMetadataParser
from backend.app.metadata.rescrape import MovieMetadataRescrapeService
from backend.app.metadata.scraper import MetadataScraper as LegacyMetadataScraper
from backend.app.metadata.types import EntityMetadataContext, MetadataResolution
from backend.app.metadata.types import ParsedMediaInfo
from backend.app.models import MediaResource, Movie, MovieSeasonMetadata, StorageSource
from backend.app.services.jobs import job_manager


class MetadataWorkbenchFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "BACKGROUND_JOBS_INLINE": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        job_manager.clear()
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

    def _add_source(self):
        source = StorageSource(name="Local", type="local", config={"root_path": "/tmp/media"})
        db.session.add(source)
        db.session.commit()
        return source

    def _add_resource(self, movie, path="shows/Old.Title.S01E01.mkv", source=None):
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id if source else None,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            season=1,
            episode=1,
        )
        db.session.add(resource)
        db.session.commit()
        return resource

    def _assert_snapshot_meta(self, data):
        self.assertIn("revision", data)
        self.assertIn("updated_at", data)
        self.assertIn("rebuilding", data)
        self.assertIn("stale", data)
        self.assertFalse(data["rebuilding"])
        self.assertFalse(data["stale"])

    def _work_item_titles(self, issue_code):
        response = self.client.get(
            "/api/v1/metadata/work-items",
            query_string={"metadata_issue_code": issue_code, "page_size": 20},
        )
        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        return [item["title"] for item in payload["data"]["items"]]

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

    def test_work_items_can_filter_pending_review_catalog_status(self):
        pending = self._add_movie(title="Pending Review", scraper_source="TMDB", cover="poster")
        pending.catalog_visibility_status = Movie.CATALOG_VISIBILITY_PENDING_REVIEW
        public = self._add_movie(title="Public Ready", scraper_source="TMDB", cover="poster")
        db.session.commit()

        response = self.client.get(
            "/api/v1/metadata/work-items",
            query_string={"effective_status": "pending_review", "page_size": 20},
        )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self._assert_snapshot_meta(data)
        items = data["items"]
        ids = [item["id"] for item in items]
        self.assertIn(pending.id, ids)
        self.assertNotIn(public.id, ids)
        item = next(item for item in items if item["id"] == pending.id)
        self.assertEqual("pending_review", item["catalog_visibility"]["effective_status"])

    def test_pending_review_publish_batch_requires_force_for_blockers(self):
        pending = self._add_movie(title="Raw Pending", scraper_source="LOCAL_FALLBACK", cover="")
        pending.catalog_visibility_status = Movie.CATALOG_VISIBILITY_PENDING_REVIEW
        public = self._add_movie(title="Already Public", scraper_source="TMDB", cover="poster")
        db.session.commit()

        blocked_response = self.client.post(
            "/api/v1/metadata/pending-review/publish",
            json={"movie_ids": [pending.id, public.id]},
        )

        self.assertEqual(200, blocked_response.status_code)
        blocked_data = blocked_response.get_json()["data"]
        self.assertEqual([], blocked_data["published"])
        failed = {item["movie_id"]: item for item in blocked_data["failed"]}
        self.assertEqual("requires_force", failed[pending.id]["reason"])
        self.assertIn("metadata_needs_attention", failed[pending.id]["blockers"])
        self.assertEqual("not_pending_review", failed[public.id]["reason"])

        publish_response = self.client.post(
            "/api/v1/metadata/pending-review/publish",
            json={"movie_ids": [pending.id], "force": True},
        )

        self.assertEqual(200, publish_response.status_code)
        data = publish_response.get_json()["data"]
        self.assertEqual([pending.id], [item["movie_id"] for item in data["published"]])
        self.assertEqual([], data["failed"])
        refreshed = db.session.get(Movie, pending.id)
        self.assertEqual(Movie.CATALOG_VISIBILITY_PUBLISHED, refreshed.catalog_visibility_status)

    def test_pending_review_backfill_promotes_historical_auto_hidden_candidates(self):
        legacy = self._add_movie(title="Legacy Raw", scraper_source="LOCAL_FALLBACK", cover="")
        self._add_resource(legacy, path="movies/Legacy.Raw.S01E01.mkv")
        ready = self._add_movie(title="Ready Public", scraper_source="TMDB", cover="poster")
        self._add_resource(ready, path="movies/Ready.Public.S01E01.mkv")

        dry_run_response = self.client.post(
            "/api/v1/metadata/pending-review/backfill",
            json={"dry_run": True, "limit": 10},
        )

        self.assertEqual(200, dry_run_response.status_code)
        dry_run_data = dry_run_response.get_json()["data"]
        self.assertTrue(dry_run_data["dry_run"])
        self.assertEqual([legacy.id], [item["movie_id"] for item in dry_run_data["candidates"]])
        self.assertEqual(0, dry_run_data["summary"]["updated"])
        self.assertEqual(Movie.CATALOG_VISIBILITY_AUTO, db.session.get(Movie, legacy.id).catalog_visibility_status)

        apply_response = self.client.post(
            "/api/v1/metadata/pending-review/backfill",
            json={"dry_run": False, "limit": 10},
        )

        self.assertEqual(200, apply_response.status_code)
        data = apply_response.get_json()["data"]
        self.assertFalse(data["dry_run"])
        self.assertEqual([legacy.id], [item["movie_id"] for item in data["updated"]])
        self.assertEqual(1, data["summary"]["updated"])
        refreshed = db.session.get(Movie, legacy.id)
        self.assertEqual(Movie.CATALOG_VISIBILITY_PENDING_REVIEW, refreshed.catalog_visibility_status)
        self.assertEqual(Movie.CATALOG_VISIBILITY_AUTO, db.session.get(Movie, ready.id).catalog_visibility_status)

        pending_response = self.client.get(
            "/api/v1/metadata/work-items",
            query_string={"effective_status": "pending_review", "page_size": 20},
        )
        self.assertEqual(200, pending_response.status_code)
        pending_ids = [item["id"] for item in pending_response.get_json()["data"]["items"]]
        self.assertIn(legacy.id, pending_ids)
        self.assertNotIn(ready.id, pending_ids)

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

    def test_single_re_scrape_merges_local_placeholder_into_existing_external_movie(self):
        target = Movie(
            tmdb_id="tv/100",
            title="已有条目",
            original_title="Existing Title",
            year=2020,
            cover="target-poster",
            scraper_source="TMDB",
        )
        source = self._add_movie(title="本地占位")
        db.session.add(target)
        db.session.commit()
        resource = self._add_resource(source)

        with patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.resolve_movie",
            return_value={
                "resources": [resource],
                "entity_context": self._entity_context(resource),
                "resolution": self._tmdb_resolution(),
                "resource_count": 1,
            },
        ):
            response = self.client.post(f"/api/v1/movies/{source.id}/metadata/re-scrape", json={"media_type_hint": "tv"})

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["merged"])
        self.assertTrue(data["changed"])
        self.assertEqual(source.id, data["merged_from_movie_id"])
        self.assertEqual(target.id, data["movie"]["id"])
        self.assertIsNone(db.session.get(Movie, source.id))
        refreshed_target = db.session.get(Movie, target.id)
        self.assertEqual("New Title", refreshed_target.title)
        self.assertEqual(target.id, db.session.get(MediaResource, resource.id).movie_id)

    def test_batch_re_scrape_merges_local_placeholder_into_existing_external_movie(self):
        target = Movie(
            tmdb_id="tv/100",
            title="已有条目",
            original_title="Existing Title",
            year=2020,
            cover="target-poster",
            scraper_source="TMDB",
        )
        source = self._add_movie(title="待批量修复")
        db.session.add(target)
        db.session.commit()
        resource = self._add_resource(source)

        with patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.resolve_movie",
            return_value={
                "resources": [resource],
                "entity_context": self._entity_context(resource),
                "resolution": self._tmdb_resolution(),
                "resource_count": 1,
            },
        ):
            response = self.client.post(
                "/api/v1/metadata/re-scrape",
                json={"items": [{"id": source.id, "media_type_hint": "tv"}]},
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        item = data["items"][0]
        self.assertTrue(item["merged"])
        self.assertEqual(source.id, item["merged_from_movie_id"])
        self.assertEqual(target.id, item["target_movie_id"])
        self.assertEqual(target.id, item["movie_id"])
        self.assertEqual([target.id], data["summary"]["updated_movie_ids"])
        self.assertIsNone(db.session.get(Movie, source.id))
        self.assertEqual(target.id, db.session.get(MediaResource, resource.id).movie_id)

    def test_re_scrape_rebuilds_title_from_clean_filename_when_parent_is_dirty(self):
        movie = self._add_movie(title="【高清影视之家发布 www SSDSSE com】阿丽塔：战斗天使 USA TrueHD7 1")
        path = (
            "来自：云添加/【高清影视之家发布 www.SSDSSE.com】阿丽塔：战斗天使"
            "[HDR+杜比视界双版本][国英多音轨+特效中文字幕].2019.USA.BluRay.Remux.UHD.DoVi.HDR10."
            "2160p.Atmos.TrueHD7.1-DreamHD/Alita Battle Angel 2019 USA BluRay Remux UHD DoVi "
            "HDR 2160p Atmos TrueHD7.1-DreamHD.mkv"
        )
        resource = MediaResource(
            movie_id=movie.id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
        )
        db.session.add(resource)
        db.session.commit()

        captured = {}

        def fake_resolve(parsed_info):
            captured["title"] = parsed_info.title
            captured["year"] = parsed_info.year
            return MetadataResolution(
                meta_data={
                    "tmdb_id": "movie/399579",
                    "title": "阿丽塔：战斗天使",
                    "original_title": "Alita: Battle Angel",
                    "year": 2019,
                    "rating": 7.2,
                    "description": "updated",
                    "cover": "poster",
                    "background_cover": "backdrop",
                    "category": ["动作"],
                    "director": "Robert Rodriguez",
                    "actors": [],
                    "country": "US",
                    "scraper_source": "TMDB_FALLBACK",
                },
                resolved_tmdb_id="movie/399579",
                scrape_layer="structured",
                scrape_strategy="movie_filename_year",
                reason="tmdb_match",
            )

        with patch("backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata", side_effect=fake_resolve):
            result = MovieMetadataRescrapeService().resolve_movie(movie, media_type_hint="movie")

        self.assertEqual("Alita Battle Angel", captured["title"])
        self.assertEqual(2019, captured["year"])
        self.assertEqual("Alita Battle Angel", result["entity_context"].title)

    def test_re_scrape_search_override_replaces_path_keyword_for_pipeline(self):
        movie = self._add_movie(title="错误标题")
        resource = MediaResource(
            movie_id=movie.id,
            path="downloads/Wrong.Keyword.2017.1080p.mkv",
            filename="Wrong.Keyword.2017.1080p.mkv",
        )
        db.session.add(resource)
        db.session.commit()

        captured = {}

        def fake_resolve(parsed_info):
            captured["title"] = parsed_info.title
            captured["year"] = parsed_info.year
            captured["search_query"] = parsed_info.extras["search_query"]
            return MetadataResolution(
                meta_data={
                    "tmdb_id": "movie/999",
                    "title": "Correct Movie",
                    "original_title": "Correct Movie",
                    "year": 2024,
                    "scraper_source": "TMDB_FALLBACK",
                },
                resolved_tmdb_id="movie/999",
                scrape_layer="fallback",
                scrape_strategy="manual_search_override",
                reason="tmdb_match",
            )

        with patch("backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata", side_effect=fake_resolve):
            result = MovieMetadataRescrapeService().resolve_movie(
                movie,
                media_type_hint="movie",
                search_title="Correct Movie",
                search_year=2024,
            )

        self.assertEqual("Correct Movie", captured["title"])
        self.assertEqual(2024, captured["year"])
        self.assertEqual("Wrong Keyword", result["entity_context"].title)
        self.assertEqual(2017, result["entity_context"].year)
        self.assertEqual("Correct Movie", result["search_query"]["search_title"])
        self.assertEqual(2024, result["search_query"]["search_year"])
        self.assertTrue(result["search_query"]["title_overridden"])
        self.assertTrue(result["search_query"]["year_overridden"])
        self.assertEqual("user_override", captured["search_query"]["source"])

    def test_re_scrape_search_year_null_clears_path_year_hint(self):
        movie = self._add_movie(title="年份误判")
        resource = MediaResource(
            movie_id=movie.id,
            path="downloads/Correct.Title.2077.1080p.mkv",
            filename="Correct.Title.2077.1080p.mkv",
        )
        db.session.add(resource)
        db.session.commit()

        captured = {}

        def fake_resolve(parsed_info):
            captured["title"] = parsed_info.title
            captured["year"] = parsed_info.year
            return MetadataResolution(
                meta_data={"tmdb_id": "movie/888", "title": "Correct Title", "scraper_source": "TMDB_FALLBACK"},
                resolved_tmdb_id="movie/888",
                scrape_layer="fallback",
                scrape_strategy="manual_search_override",
                reason="tmdb_match",
            )

        with patch("backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata", side_effect=fake_resolve):
            result = MovieMetadataRescrapeService().resolve_movie(
                movie,
                media_type_hint="movie",
                search_title="Correct Title",
                search_year=None,
            )

        self.assertEqual("Correct Title", captured["title"])
        self.assertIsNone(captured["year"])
        self.assertEqual(2077, result["search_query"]["path_year"])
        self.assertIsNone(result["search_query"]["search_year"])
        self.assertTrue(result["search_query"]["year_overridden"])

    def test_re_scrape_search_plan_is_local_only(self):
        movie = self._add_movie(title="待识别")
        source = self._add_source()
        resource = self._add_resource(movie, path="movies/Fast.Plan.2024.1080p.mkv", source=source)

        with patch(
            "backend.app.metadata.rescrape.provider_factory.get_provider",
            side_effect=AssertionError("plan must not initialize storage provider"),
        ), patch(
            "backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata",
            side_effect=AssertionError("plan must not call metadata providers"),
        ):
            result = MovieMetadataRescrapeService().build_search_plan(movie, media_type_hint="movie")

        self.assertEqual(source.id, result["source"].id)
        self.assertIsNone(result["provider"])
        self.assertEqual(resource.path, result["entity_context"].sample_path)
        self.assertEqual("Fast Plan", result["search_query"]["search_title"])
        self.assertEqual(2024, result["search_query"]["search_year"])
        self.assertEqual("movie", result["search_query"]["media_type_hint"])

    def test_re_scrape_skips_sidecar_nfo_provider_by_default(self):
        movie = self._add_movie(title="慢挂载")
        source = self._add_source()
        self._add_resource(movie, path="movies/Slow.Mount.2024.1080p.mkv", source=source)

        def fake_resolve(parsed_info):
            return MetadataResolution(
                meta_data={"tmdb_id": "movie/100", "title": parsed_info.title, "scraper_source": "TMDB_STRICT"},
                resolved_tmdb_id="movie/100",
                scrape_layer="structured",
                scrape_strategy=parsed_info.parse_strategy,
                reason="tmdb_match",
            )

        with patch(
            "backend.app.metadata.rescrape.provider_factory.get_provider",
            side_effect=AssertionError("default re-scrape must not initialize storage provider for sidecar NFO"),
        ), patch(
            "backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata",
            side_effect=fake_resolve,
        ):
            result = MovieMetadataRescrapeService().resolve_movie(movie, media_type_hint="movie")

        self.assertFalse(result["sidecar_nfo_enabled"])
        self.assertEqual("movie", result["search_query"]["media_type_hint"])

    def test_re_scrape_allow_nfo_opts_into_sidecar_provider_lookup(self):
        movie = self._add_movie(title="允许 NFO")
        source = self._add_source()
        self._add_resource(movie, path="movies/Nfo.Movie.2024.1080p.mkv", source=source)
        provider_calls = {"list_items": 0}

        class FakeProvider:
            def list_items(self, directory):
                provider_calls["list_items"] += 1
                return []

        def fake_resolve(parsed_info):
            return MetadataResolution(
                meta_data={"tmdb_id": "movie/101", "title": parsed_info.title, "scraper_source": "TMDB_STRICT"},
                resolved_tmdb_id="movie/101",
                scrape_layer="structured",
                scrape_strategy=parsed_info.parse_strategy,
                reason="tmdb_match",
            )

        with patch("backend.app.metadata.rescrape.provider_factory.get_provider", return_value=FakeProvider()), patch(
            "backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata",
            side_effect=fake_resolve,
        ):
            result = MovieMetadataRescrapeService().resolve_movie(
                movie,
                media_type_hint="movie",
                include_sidecar_nfo=True,
            )

        self.assertTrue(result["sidecar_nfo_enabled"])
        self.assertEqual(1, provider_calls["list_items"])

    def test_legacy_pipeline_ignores_current_local_placeholder_title_match(self):
        movie = Movie(
            tmdb_id="loc-911c3d266e2b",
            title="Transformers Age of Extinction",
            original_title="Transformers Age of Extinction",
            year=2014,
            scraper_source="LOCAL_FALLBACK",
        )
        db.session.add(movie)
        db.session.commit()

        parsed_info = ParsedMediaInfo(
            title="Transformers Age of Extinction",
            year=2014,
            media_type_hint="movie",
            parse_layer="strict",
            parse_strategy="movie_filename_year",
            confidence="high",
        )
        details = {
            "tmdb_id": "movie/91314",
            "title": "变形金刚4：绝迹重生",
            "original_title": "Transformers: Age of Extinction",
            "year": 2014,
            "rating": 6.0,
            "description": "updated",
            "cover": "poster",
            "background_cover": "backdrop",
            "category": ["动作"],
            "director": "Michael Bay",
            "actors": [],
            "country": "US",
            "scraper_source": "TMDB",
        }

        resolver = LegacyMetadataScraper(PathMetadataParser())
        with patch("backend.app.metadata.scraper.tmdb_scraper.search_movie", return_value="movie/91314") as search, \
             patch("backend.app.metadata.scraper.tmdb_scraper.get_movie_details", return_value=details):
            resolution = resolver.resolve(parsed_info)

        search.assert_called_once_with(
            "Transformers Age of Extinction",
            2014,
            strict=True,
            media_type_hint="movie",
        )
        self.assertEqual("movie/91314", resolution.resolved_tmdb_id)
        self.assertEqual("TMDB_STRICT", resolution.meta_data["scraper_source"])

    def test_batch_re_scrape_job_tracks_status_and_result(self):
        movie = self._add_movie()
        resource = self._add_resource(movie)
        entity_context = self._entity_context(resource)
        resolution = self._tmdb_resolution()
        captured = {}

        def resolve_movie(target_movie, media_type_hint=None, search_title=None, search_year=None):
            captured["media_type_hint"] = media_type_hint
            captured["search_title"] = search_title
            captured["search_year"] = search_year
            return {
                "resources": [resource],
                "entity_context": entity_context,
                "search_query": {
                    "search_title": search_title,
                    "search_year": search_year,
                    "path_title": entity_context.title,
                    "path_year": entity_context.year,
                    "title_overridden": True,
                    "year_overridden": True,
                    "media_type_hint": media_type_hint,
                    "source": "user_override",
                },
                "resolution": resolution,
                "resource_count": 1,
            }

        with patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.resolve_movie",
            side_effect=resolve_movie,
        ), patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.apply_resource_traces",
        ):
            response = self.client.post(
                "/api/v1/metadata/re-scrape/jobs",
                json={"items": [{"id": movie.id, "media_type_hint": "tv", "search_title": "Correct Title", "search_year": 2025}]},
            )

        self.assertEqual(202, response.status_code)
        response_data = response.get_json()["data"]
        job = response_data["job"]
        self.assertEqual(job["id"], response_data["job_id"])
        self.assertEqual(f"/api/v1/jobs/{job['id']}", response_data["progress_endpoint"])
        self.assertEqual(f"/api/v1/jobs/{job['id']}", response_data["status_endpoint"])
        self.assertEqual(1000, response_data["poll_interval_ms"])
        self.assertEqual("metadata_re_scrape", job["type"])
        self.assertEqual("succeeded", job["status"])
        self.assertEqual(1, job["result"]["summary"]["updated"])
        self.assertEqual("Correct Title", captured["search_title"])
        self.assertEqual(2025, captured["search_year"])
        self.assertEqual("Correct Title", job["result"]["items"][0]["search_title"])
        self.assertEqual(2025, job["result"]["items"][0]["search_year"])
        self.assertEqual(1, job["progress"]["current"])
        db.session.expire_all()
        self.assertEqual("New Title", db.session.get(Movie, movie.id).title)

        detail = self.client.get(f"/api/v1/jobs/{job['id']}")
        self.assertEqual(200, detail.status_code)
        self.assertEqual("succeeded", detail.get_json()["data"]["status"])

        listing = self.client.get("/api/v1/jobs", query_string={"type": "metadata_re_scrape"})
        self.assertEqual(200, listing.status_code)
        self.assertEqual([job["id"]], [item["id"] for item in listing.get_json()["data"]["items"]])

    def test_batch_re_scrape_allow_nfo_is_explicit_opt_in(self):
        movie = self._add_movie()
        resource = self._add_resource(movie)
        captured = {}

        def resolve_movie(target_movie, media_type_hint=None, include_sidecar_nfo=False):
            captured["include_sidecar_nfo"] = include_sidecar_nfo
            return {
                "resources": [resource],
                "entity_context": self._entity_context(resource),
                "resolution": self._tmdb_resolution(),
                "resource_count": 1,
            }

        with patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.resolve_movie",
            side_effect=resolve_movie,
        ), patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.apply_resource_traces",
        ):
            response = self.client.post(
                "/api/v1/metadata/re-scrape",
                json={"items": [{"id": movie.id, "media_type_hint": "movie", "allow_nfo": True}]},
            )

        self.assertEqual(200, response.status_code)
        self.assertTrue(captured["include_sidecar_nfo"])

    def test_re_scrape_resource_trace_preserves_nfo_candidate_summary(self):
        movie = self._add_movie(title="NFO Trace", scraper_source="TMDB")
        resource = self._add_resource(movie, path="movies/Nfo.Trace.2024.1080p.mkv")
        context = self._entity_context(resource)
        context.nfo_candidates = [
            "movies/Nfo.Trace.2024/movie.nfo",
            "movies/Nfo.Trace.2024/movie.nfo",
            {"path": "movies/Nfo.Trace.2024/index.nfo", "name": "index.nfo", "kind": "index"},
        ]

        MovieMetadataRescrapeService().apply_resource_traces([resource], context, self._tmdb_resolution())

        trace = resource.tech_specs["metadata_trace"]
        self.assertTrue(trace["has_nfo_candidates"])
        self.assertEqual(2, trace["nfo_candidate_count"])
        self.assertEqual(
            [
                {"path": "movies/Nfo.Trace.2024/movie.nfo", "name": "movie.nfo"},
                {"path": "movies/Nfo.Trace.2024/index.nfo", "name": "index.nfo", "kind": "index"},
            ],
            trace["nfo_candidates"],
        )

    def test_quality_summary_returns_issue_samples_and_actions(self):
        movie = self._add_movie(title="质量汇总", scraper_source="TMDB", cover="")
        resource = self._add_resource(movie)
        resource.tech_specs = {
            "metadata_trace": {
                "confidence": "low",
                "scrape_layer": "fallback",
            }
        }
        db.session.commit()

        response = self.client.get("/api/v1/metadata/quality-summary", query_string={"sample_size": 1})

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self._assert_snapshot_meta(data)
        issues = {item["code"]: item for item in data["issues"]}
        self.assertEqual(1, issues["poster_missing"]["movie_count"])
        self.assertEqual(1, issues["fallback_pipeline_match"]["movie_count"])
        self.assertEqual("质量汇总", issues["poster_missing"]["samples"][0]["title"])
        actions = {item["id"]: item for item in data["actions"]}
        self.assertTrue(actions["bulk_reidentify"]["enabled"])
        self.assertEqual("/api/v1/metadata/re-scrape/plan", actions["bulk_reidentify"]["endpoint"])

    def test_published_fallback_matches_are_not_pending_metadata_issues(self):
        reviewed = self._add_movie(title="已审核兜底", scraper_source="TMDB", cover="poster")
        reviewed.catalog_visibility_status = Movie.CATALOG_VISIBILITY_PUBLISHED
        reviewed.catalog_visibility_note = "reviewed:fallback_pipeline_match:manual_pass"
        reviewed_resource = self._add_resource(reviewed, path="movies/Reviewed.Match.2024.1080p.mkv")
        reviewed_resource.tech_specs = {
            "metadata_trace": {
                "confidence": "high",
                "scrape_layer": "fallback",
            }
        }

        pending = self._add_movie(title="未审核兜底", scraper_source="TMDB", cover="poster")
        pending_resource = self._add_resource(pending, path="movies/Pending.Match.2024.1080p.mkv")
        pending_resource.tech_specs = {
            "metadata_trace": {
                "confidence": "high",
                "scrape_layer": "fallback",
            }
        }
        db.session.commit()

        reviewed_issue_codes = {item["code"] for item in reviewed.get_metadata_issues()}
        self.assertNotIn("fallback_pipeline_match", reviewed_issue_codes)
        self.assertEqual(["未审核兜底"], self._work_item_titles("fallback_pipeline_match"))

    def test_review_taxonomy_returns_frontend_contract_dictionary(self):
        response = self.client.get("/api/v1/metadata/review-taxonomy")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        bucket_ids = [item["id"] for item in data["buckets"]]
        issue_codes = {item["code"]: item for item in data["issue_codes"]}
        self.assertIn("metadata_review", bucket_ids)
        self.assertIn("episode_review", bucket_ids)
        self.assertIn("resource_governance", bucket_ids)
        self.assertIn("placeholder_metadata", issue_codes)
        self.assertEqual("metadata_review", issue_codes["placeholder_metadata"]["bucket"])
        self.assertEqual("batch_reidentify_plan", issue_codes["placeholder_metadata"]["bulk_action"])
        self.assertEqual("batch_reidentify_plan", issue_codes["local_only_metadata"]["bulk_action"])
        self.assertEqual("/api/v1/metadata/work-items", issue_codes["poster_missing"]["list"]["endpoint"])
        self.assertEqual("/api/v1/resources/governance-items", issue_codes["invalid_path"]["list"]["endpoint"])
        self.assertIn("BANGUMI", [item["code"] for item in data["metadata_sources"]])

    def test_metadata_review_priority_none_includes_bangumi(self):
        movie = self._add_movie(title="番组来源", scraper_source="BANGUMI")

        response = self.client.get(
            "/api/v1/movies",
            query_string={"metadata_review_priority": "none", "page_size": 20},
        )

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]["items"]
        self.assertIn(movie.id, [item["id"] for item in items])

    def test_batch_re_scrape_plan_is_dry_run_and_does_not_apply_metadata(self):
        movie = self._add_movie(title="旧标题", scraper_source="LOCAL_FALLBACK", cover="")
        failed_movie = self._add_movie(title="空资源", scraper_source="LOCAL_FALLBACK", cover="")
        resource = self._add_resource(movie)

        with patch(
            "backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata",
            side_effect=AssertionError("plan must not call metadata providers"),
        ), patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.apply_resource_traces",
        ) as apply_resource_traces:
            response = self.client.post(
                "/api/v1/metadata/re-scrape/plan",
                json={"movie_ids": [movie.id, failed_movie.id], "media_type_hint": "tv"},
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["dry_run"])
        self.assertEqual("keyword_preview", data["plan_mode"])
        self.assertFalse(data["provider_search"])
        self.assertEqual("/api/v1/metadata/re-scrape/jobs", data["apply_endpoint"])
        self.assertEqual("/api/v1/metadata/re-scrape", data["sync_apply_endpoint"])
        self.assertEqual("/api/v1/jobs/{job_id}", data["progress_endpoint_template"])
        planned = {item["movie_id"]: item for item in data["items"]}
        self.assertEqual("planned", planned[movie.id]["status"])
        self.assertEqual("keyword_preview", planned[movie.id]["plan_mode"])
        self.assertEqual(resource.path, planned[movie.id]["entity_context"]["sample_path"])
        self.assertEqual(planned[movie.id]["search_title"], data["apply_payload"]["items"][0]["search_title"])
        self.assertEqual(planned[movie.id]["search_year"], data["apply_payload"]["items"][0]["search_year"])
        self.assertEqual("path_parser", planned[movie.id]["search_query"]["source"])
        self.assertIsNone(planned[movie.id]["preview"])
        self.assertIsNone(planned[movie.id]["diff"])
        self.assertIsNone(planned[movie.id]["resolution"])
        self.assertIsNone(planned[movie.id]["explanation"])
        self.assertEqual("failed", planned[failed_movie.id]["status"])
        self.assertEqual("no_resources", planned[failed_movie.id]["error"]["category"])
        self.assertEqual("旧标题", db.session.get(Movie, movie.id).title)
        apply_resource_traces.assert_not_called()

    def test_batch_re_scrape_plan_defaults_include_local_metadata_failures(self):
        placeholder = self._add_movie(title="本地占位", scraper_source="LOCAL_FALLBACK", cover="")
        local_only = self._add_movie(title="本地 NFO", scraper_source="NFO_LOCAL", cover="")
        self._add_resource(placeholder, path="shows/Placeholder.S01E01.mkv")
        self._add_resource(local_only, path="shows/Nfo.Local.S01E01.mkv")

        with patch(
            "backend.app.metadata.rescrape.metadata_pipeline.resolve_metadata",
            side_effect=AssertionError("plan must not call metadata providers"),
        ):
            response = self.client.post("/api/v1/metadata/re-scrape/plan", json={"limit": 10})

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertIn("placeholder_metadata", data["selection"]["issue_codes"])
        self.assertIn("local_only_metadata", data["selection"]["issue_codes"])
        self.assertEqual({placeholder.id, local_only.id}, {item["movie_id"] for item in data["items"]})
        self.assertEqual(2, data["summary"]["planned"])

    def test_episode_review_items_returns_queue_with_dry_run_payload(self):
        movie = self._add_movie(title="剧集队列", scraper_source="TMDB")
        source = self._add_source()
        db.session.add(MovieSeasonMetadata(movie_id=movie.id, season=1, title="第一季", episode_count=3))
        first = self._add_resource(movie, path="shows/Review.Queue.S01E01.mkv", source=source)
        first.episode = 1
        missing_slot = self._add_resource(movie, path="shows/Review.Queue.S01E02.mkv", source=source)
        missing_slot.episode = None
        duplicate_a = self._add_resource(movie, path="shows/Review.Queue.S01E03.1080p.mkv", source=source)
        duplicate_a.episode = 3
        duplicate_b = self._add_resource(movie, path="shows/Review.Queue.S01E03.2160p.mkv", source=source)
        duplicate_b.episode = 3
        db.session.commit()

        response = self.client.get("/api/v1/metadata/episode-review-items")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self._assert_snapshot_meta(data)
        self.assertEqual(1, data["pagination"]["total_items"])
        item = data["items"][0]
        self.assertEqual(movie.id, item["movie_id"])
        self.assertTrue(item["playable"])
        self.assertIn(
            item["primary_resource_id"],
            {first.id, missing_slot.id, duplicate_a.id, duplicate_b.id},
        )
        self.assertEqual(1, item["auto_update_count"])
        self.assertEqual([{"id": missing_slot.id, "season": 1, "episode": 2}], item["apply_payload"]["items"])
        issue_codes = {issue["code"] for issue in item["metadata_issues"]}
        self.assertIn("missing_episode_numbers", issue_codes)
        self.assertIn("duplicate_episode_numbers", issue_codes)

    def test_episode_review_items_marks_orphaned_resources_unplayable(self):
        movie = self._add_movie(title="离线剧集", scraper_source="TMDB")
        db.session.add(MovieSeasonMetadata(movie_id=movie.id, season=1, title="第一季", episode_count=2))
        resource = self._add_resource(movie, path="shows/Offline.Show.S01E01.mkv")
        resource.episode = None
        db.session.commit()

        response = self.client.get("/api/v1/metadata/episode-review-items")

        self.assertEqual(200, response.status_code)
        item = response.get_json()["data"]["items"][0]
        self.assertEqual(movie.id, item["movie_id"])
        self.assertFalse(item["playable"])
        self.assertIsNone(item["primary_resource_id"])

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

    def test_pipeline_preview_maps_candidate_alias_fields(self):
        movie = self._add_movie(title="旧标题", cover="")
        resource = self._add_resource(movie, path="movies/New.Title.2024.mkv")
        entity_context = self._entity_context(resource)
        resolution = MetadataResolution(
            meta_data={
                "tmdb_id": "movie/100",
                "title": "New Title",
                "original_title": "New Original",
                "year": 2024,
                "overview": "候选简介",
                "poster_url": "https://example.test/poster.jpg",
                "backdrop_url": "https://example.test/backdrop.jpg",
                "category": ["剧情"],
                "director": "Creator",
                "actors": ["Actor"],
                "country": "JP",
                "scraper_source": "TMDB",
            },
            resolved_tmdb_id="movie/100",
            scrape_layer="fallback",
            scrape_strategy="manual_candidate",
            reason="manual_candidate",
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

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual("候选简介", data["preview"]["overview"])
        self.assertEqual("https://example.test/poster.jpg", data["preview"]["poster_url"])
        self.assertEqual("https://example.test/backdrop.jpg", data["preview"]["backdrop_url"])

        fields = {item["field"]: item for item in data["diff"]["fields"]}
        self.assertEqual("候选简介", fields["description"]["preview_value"])
        self.assertEqual("https://example.test/poster.jpg", fields["cover"]["preview_value"])
        self.assertEqual("https://example.test/backdrop.jpg", fields["background_cover"]["preview_value"])

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
            "backend.app.services.metadata_providers.tmdb.scraper.search_movie_candidates",
            return_value=candidates,
        ):
            response = self.client.get(
                f"/api/v1/movies/{movie.id}/metadata/search"
                "?query=Deep%20Sea&year=2023&media_type_hint=movie"
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual(["nfo", "tmdb", "local"], payload["data"]["providers"]["order"])
        item = payload["data"]["items"][0]
        self.assertEqual(1, item["rank"])
        self.assertEqual("tmdb", item["provider"])
        self.assertEqual("tmdb", item["source_key"])
        self.assertEqual("movie/667717", item["candidate_id"])
        self.assertEqual("high", item["match_explanation"]["confidence"])
        self.assertIn("title_exact", item["match_explanation"]["reason_codes"])
        self.assertIn("year_match", item["match_explanation"]["reason_codes"])
        self.assertIn("media_type_match", item["match_explanation"]["reason_codes"])

    def test_keyword_search_does_not_reuse_movie_year_without_explicit_year(self):
        movie = self._add_movie(title="旧标题", scraper_source="LOCAL_FALLBACK")
        captured = {}

        def fake_search(context, query, **kwargs):
            captured["context_year"] = context.year
            captured["query"] = query
            captured["year"] = kwargs.get("year")
            return {
                "items": [],
                "providers": {
                    "order": ["bangumi", "local"],
                    "attempts": [],
                    "warnings": [],
                },
            }

        with patch(
            "backend.app.api.library_routes.metadata_scraper.search_candidates",
            side_effect=fake_search,
        ):
            response = self.client.get(
                f"/api/v1/movies/{movie.id}/metadata/search",
                query_string={"query": "葬送的芙莉莲", "providers": "bangumi"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("葬送的芙莉莲", captured["query"])
        self.assertIsNone(captured["context_year"])
        self.assertIsNone(captured["year"])
        self.assertIsNone(payload["data"]["year"])
        self.assertEqual("none", payload["data"]["year_source"])

    def test_metadata_providers_endpoint_lists_searchable_provider(self):
        response = self.client.get("/api/v1/metadata/providers")
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        data = payload["data"]
        self.assertEqual(["nfo", "tmdb", "local"], data["default_order"])
        providers = {item["key"]: item for item in data["providers"]}
        self.assertTrue(providers["tmdb"]["supports_search"])
        self.assertTrue(providers["bangumi"]["supports_search"])
        self.assertFalse(providers["local"]["supports_search"])

    def test_match_accepts_bangumi_candidate_id_and_provider_alias(self):
        movie = self._add_movie(title="旧动画", scraper_source="LOCAL_FALLBACK", cover="")

        bangumi_metadata = {
            "tmdb_id": "bangumi/361761",
            "title": "葬送的芙莉莲",
            "original_title": "葬送のフリーレン",
            "year": 2023,
            "rating": 8.7,
            "description": "updated",
            "cover": "poster",
            "background_cover": "",
            "category": ["动画", "奇幻"],
            "director": "斋藤圭一郎",
            "actors": [],
            "country": "日本",
            "scraper_source": "BANGUMI",
        }

        class _Result:
            metadata = bangumi_metadata

        with patch(
            "backend.app.api.library_routes.metadata_scraper.get_candidate_metadata",
            return_value=_Result(),
        ) as get_candidate_metadata:
            response = self.client.post(
                f"/api/v1/movies/{movie.id}/metadata/match",
                json={"candidate_id": "361761", "provider": "bangumi", "media_type_hint": "tv", "apply": True},
            )

        self.assertEqual(200, response.status_code)
        get_candidate_metadata.assert_called_once()
        self.assertEqual("361761", get_candidate_metadata.call_args.args[0])
        self.assertEqual("bangumi", get_candidate_metadata.call_args.kwargs["provider_name"])
        refreshed = db.session.get(Movie, movie.id)
        self.assertEqual("bangumi/361761", refreshed.tmdb_id)
        self.assertEqual("葬送的芙莉莲", refreshed.title)
        self.assertEqual("BANGUMI", refreshed.scraper_source)

    def test_metadata_issue_filter_matches_low_confidence_resource_issue(self):
        movie = self._add_movie(title="低置信资源", scraper_source="TMDB")
        self._add_resource(movie, path="shows/Low.Confidence.S01E01.mkv")
        resource = movie.resources.first()
        resource.tech_specs = {
            "metadata_trace": {
                "confidence": "low",
                "scrape_layer": "structured",
            }
        }
        db.session.commit()

        self.assertEqual(["低置信资源"], self._work_item_titles("low_confidence_resources"))

    def test_metadata_issue_filter_matches_locked_fields_issue(self):
        movie = self._add_movie(title="锁定字段", scraper_source="TMDB")
        movie.set_locked_fields(["title"])
        db.session.commit()

        self.assertEqual(["锁定字段"], self._work_item_titles("locked_fields_present"))

    def test_metadata_issue_filter_matches_season_metadata_missing_issue(self):
        movie = self._add_movie(title="缺季资料", scraper_source="TMDB")
        self._add_resource(movie, path="shows/Missing.Season.Metadata.S01E01.mkv")
        resource = movie.resources.first()
        resource.tech_specs = {
            "metadata_trace": {
                "confidence": "high",
                "scrape_layer": "structured",
            }
        }
        db.session.commit()

        self.assertEqual(["缺季资料"], self._work_item_titles("season_metadata_missing"))

    def test_metadata_issue_filter_matches_episode_diagnostic_issues(self):
        missing = self._add_movie(title="缺集", scraper_source="TMDB")
        db.session.add(MovieSeasonMetadata(movie_id=missing.id, season=1, title="第一季", episode_count=3))
        self._add_resource(missing, path="shows/Missing.Episodes.S01E01.mkv")
        missing_episode_three = self._add_resource(missing, path="shows/Missing.Episodes.S01E03.mkv")
        missing_episode_three.episode = 3

        duplicate = self._add_movie(title="重复集号", scraper_source="TMDB")
        db.session.add(MovieSeasonMetadata(movie_id=duplicate.id, season=1, title="第一季", episode_count=2))
        self._add_resource(duplicate, path="shows/Duplicate.Episodes.S01E01.1080p.mkv")
        self._add_resource(duplicate, path="shows/Duplicate.Episodes.S01E01.2160p.mkv")
        duplicate_episode_two = self._add_resource(duplicate, path="shows/Duplicate.Episodes.S01E02.1080p.mkv")
        duplicate_episode_two.episode = 2
        duplicate_episode_three = self._add_resource(duplicate, path="shows/Duplicate.Episodes.S01E03.1080p.mkv")
        duplicate_episode_three.episode = 3

        unnumbered = self._add_movie(title="缺集号", scraper_source="TMDB")
        self._add_resource(unnumbered, path="shows/Unnumbered.Special.mkv")
        unnumbered_resource = unnumbered.resources.first()
        unnumbered_resource.episode = None
        db.session.commit()

        self.assertEqual(["缺集"], self._work_item_titles("missing_episode_numbers"))
        self.assertCountEqual(["缺集", "重复集号"], self._work_item_titles("episode_count_mismatch"))
        self.assertEqual(["重复集号"], self._work_item_titles("duplicate_episode_numbers"))
        self.assertEqual(["缺集号"], self._work_item_titles("episode_number_missing"))

    def test_metadata_issue_filter_uses_exact_model_issue_codes(self):
        local_only = self._add_movie(title="本地 NFO", scraper_source="NFO_LOCAL")
        placeholder = self._add_movie(title="本地占位", scraper_source="LOCAL_FALLBACK")

        self.assertIn(
            "local_only_metadata",
            {item["code"] for item in local_only.get_metadata_issues()},
        )
        self.assertIn(
            "placeholder_metadata",
            {item["code"] for item in placeholder.get_metadata_issues()},
        )
        self.assertEqual(["本地 NFO"], self._work_item_titles("local_only_metadata"))


if __name__ == "__main__":
    unittest.main()
