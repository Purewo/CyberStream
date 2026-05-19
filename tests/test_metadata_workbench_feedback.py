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
from backend.app.models import MediaResource, Movie, MovieSeasonMetadata
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

    def test_batch_re_scrape_job_tracks_status_and_result(self):
        movie = self._add_movie()
        resource = self._add_resource(movie)
        entity_context = self._entity_context(resource)
        resolution = self._tmdb_resolution()

        with patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.resolve_movie",
            return_value={
                "resources": [resource],
                "entity_context": entity_context,
                "resolution": resolution,
                "resource_count": 1,
            },
        ), patch(
            "backend.app.api.library_routes.movie_metadata_rescrape_service.apply_resource_traces",
        ):
            response = self.client.post(
                "/api/v1/metadata/re-scrape/jobs",
                json={"items": [{"id": movie.id, "media_type_hint": "tv"}]},
            )

        self.assertEqual(202, response.status_code)
        job = response.get_json()["data"]["job"]
        self.assertEqual("metadata_re_scrape", job["type"])
        self.assertEqual("succeeded", job["status"])
        self.assertEqual(1, job["result"]["summary"]["updated"])
        self.assertEqual(1, job["progress"]["current"])
        db.session.expire_all()
        self.assertEqual("New Title", db.session.get(Movie, movie.id).title)

        detail = self.client.get(f"/api/v1/jobs/{job['id']}")
        self.assertEqual(200, detail.status_code)
        self.assertEqual("succeeded", detail.get_json()["data"]["status"])

        listing = self.client.get("/api/v1/jobs", query_string={"type": "metadata_re_scrape"})
        self.assertEqual(200, listing.status_code)
        self.assertEqual([job["id"]], [item["id"] for item in listing.get_json()["data"]["items"]])

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
        issues = {item["code"]: item for item in data["issues"]}
        self.assertEqual(1, issues["poster_missing"]["movie_count"])
        self.assertEqual(1, issues["fallback_pipeline_match"]["movie_count"])
        self.assertEqual("质量汇总", issues["poster_missing"]["samples"][0]["title"])
        actions = {item["id"]: item for item in data["actions"]}
        self.assertTrue(actions["bulk_reidentify"]["enabled"])
        self.assertEqual("/api/v1/metadata/re-scrape/plan", actions["bulk_reidentify"]["endpoint"])

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
        entity_context = self._entity_context(resource)
        resolution = self._tmdb_resolution()

        def resolve_movie(target_movie, media_type_hint=None):
            if target_movie.id == movie.id:
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
        ) as apply_resource_traces:
            response = self.client.post(
                "/api/v1/metadata/re-scrape/plan",
                json={"movie_ids": [movie.id, failed_movie.id], "media_type_hint": "tv"},
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["dry_run"])
        self.assertEqual("/api/v1/metadata/re-scrape", data["apply_endpoint"])
        self.assertEqual([{"id": movie.id, "media_type_hint": "tv"}], data["apply_payload"]["items"])
        planned = {item["movie_id"]: item for item in data["items"]}
        self.assertEqual("planned", planned[movie.id]["status"])
        self.assertIn("title", planned[movie.id]["diff"]["summary"]["will_apply_fields"])
        self.assertEqual("failed", planned[failed_movie.id]["status"])
        self.assertEqual("no_resources", planned[failed_movie.id]["error"]["category"])
        self.assertEqual("旧标题", db.session.get(Movie, movie.id).title)
        apply_resource_traces.assert_not_called()

    def test_episode_review_items_returns_queue_with_dry_run_payload(self):
        movie = self._add_movie(title="剧集队列", scraper_source="TMDB")
        db.session.add(MovieSeasonMetadata(movie_id=movie.id, season=1, title="第一季", episode_count=3))
        first = self._add_resource(movie, path="shows/Review.Queue.S01E01.mkv")
        first.episode = 1
        missing_slot = self._add_resource(movie, path="shows/Review.Queue.S01E02.mkv")
        missing_slot.episode = None
        duplicate_a = self._add_resource(movie, path="shows/Review.Queue.S01E03.1080p.mkv")
        duplicate_a.episode = 3
        duplicate_b = self._add_resource(movie, path="shows/Review.Queue.S01E03.2160p.mkv")
        duplicate_b.episode = 3
        db.session.commit()

        response = self.client.get("/api/v1/metadata/episode-review-items")

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(1, data["pagination"]["total_items"])
        item = data["items"][0]
        self.assertEqual(movie.id, item["movie_id"])
        self.assertEqual(1, item["auto_update_count"])
        self.assertEqual([{"id": missing_slot.id, "season": 1, "episode": 2}], item["apply_payload"]["items"])
        issue_codes = {issue["code"] for issue in item["metadata_issues"]}
        self.assertIn("missing_episode_numbers", issue_codes)
        self.assertIn("duplicate_episode_numbers", issue_codes)

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
        db.session.add(MovieSeasonMetadata(movie_id=duplicate.id, season=1, title="第一季", episode_count=1))
        self._add_resource(duplicate, path="shows/Duplicate.Episodes.S01E01.1080p.mkv")
        self._add_resource(duplicate, path="shows/Duplicate.Episodes.S01E01.2160p.mkv")

        unnumbered = self._add_movie(title="缺集号", scraper_source="TMDB")
        self._add_resource(unnumbered, path="shows/Unnumbered.Special.mkv")
        unnumbered_resource = unnumbered.resources.first()
        unnumbered_resource.episode = None
        db.session.commit()

        self.assertEqual(["缺集"], self._work_item_titles("missing_episode_numbers"))
        self.assertEqual(["缺集"], self._work_item_titles("episode_count_mismatch"))
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
