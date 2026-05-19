from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app


OPENAPI_PATH = PROJECT_ROOT / "backend/openapi/openapi-1.21.0-beta/openapi-1.21.0-beta.json"
HTTP_METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}


def _flask_rule_to_openapi_path(rule):
    return re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule)


class OpenApiContractTests(unittest.TestCase):
    def _load_openapi(self):
        return json.loads(OPENAPI_PATH.read_text())

    def test_openapi_paths_match_registered_runtime_routes(self):
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        runtime_operations = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            path = _flask_rule_to_openapi_path(rule.rule)
            for method in rule.methods:
                if method in HTTP_METHODS:
                    runtime_operations.add((path, method))

        openapi = self._load_openapi()
        documented_operations = {
            (path, method.upper())
            for path, path_item in openapi["paths"].items()
            for method in path_item.keys()
            if method.upper() in HTTP_METHODS
        }

        self.assertEqual(set(), runtime_operations - documented_operations)
        self.assertEqual(set(), documented_operations - runtime_operations)

    def test_online_subtitle_openapi_uses_concrete_search_fields(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        response_schema = schemas["OnlineSubtitleSearchApiResponse"]
        candidate_schema = schemas["OnlineSubtitleCandidate"]

        self.assertNotIn("allOf", response_schema)
        self.assertEqual(
            "#/components/schemas/OnlineSubtitleSearchData",
            response_schema["properties"]["data"]["$ref"],
        )
        self.assertIn("candidate_id", candidate_schema["properties"])
        self.assertIn("source_key", candidate_schema["properties"])

    def test_metadata_openapi_documents_provider_candidate_fields(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        candidate_schema = schemas["MovieMatchSearchResult"]
        search_data_schema = schemas["MovieMetadataSearchResponseData"]
        match_request_schema = schemas["MovieMetadataMatchRequest"]

        self.assertIn("source_url", candidate_schema["properties"])
        self.assertIn("episode_count", candidate_schema["properties"])
        self.assertIn("year_source", search_data_schema["properties"])
        self.assertIn("candidate_id", match_request_schema["properties"])
        self.assertIn("provider", match_request_schema["properties"])
        self.assertIn("apply", match_request_schema["properties"])
        self.assertIn("allow_missing_poster", match_request_schema["properties"])
        self.assertIn("MovieMetadataMatchPreviewResponse", schemas)

    def test_manual_content_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/other-videos", paths)
        self.assertIn("/api/v1/movies/manual", paths)
        self.assertIn("/api/v1/movies/{id}/resources/attach", paths)
        self.assertIn("manual_content", schemas["MovieSimple"]["properties"])
        self.assertIn("manual_content", schemas["MetadataWorkItem"]["properties"])
        self.assertIn("manual", schemas["MetadataState"]["properties"]["source_group"]["enum"])
        self.assertIn("manual", schemas["MetadataState"]["properties"]["confidence"]["enum"])
        self.assertIn("metadata_match_context", schemas["OtherVideoItem"]["properties"])
        self.assertIn("actions", schemas["OtherVideoItem"]["properties"])

    def test_catalog_visibility_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/movies/{id}/catalog-visibility", paths)
        self.assertIn("catalog_visibility", schemas["MovieSimple"]["properties"])
        self.assertIn("MovieCatalogVisibility", schemas)
        self.assertIn("MovieCatalogVisibilityUpdateRequest", schemas)

    def test_image_cache_openapi_documents_status_and_preload_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/movies/{id}/images/status", paths)
        self.assertIn("/api/v1/images/preload", paths)
        self.assertIn("/api/v1/images/refresh", paths)
        self.assertIn("delete", paths["/api/v1/movies/{id}/images/{kind}"])
        self.assertIn("MovieImageCacheStatus", schemas)
        self.assertIn("MovieImageSourceInfo", schemas)
        self.assertIn("MovieImageCacheClearData", schemas)
        self.assertIn("MovieImagePreloadRequest", schemas)
        self.assertIn("MovieImagePreloadResponseData", schemas)
        self.assertIn("MovieImageRefreshRequest", schemas)
        self.assertIn("MovieImageRefreshResponseData", schemas)
        self.assertIn("poster_source_info", schemas["MovieSimple"]["properties"])
        self.assertIn("SuperCDNAssetRecord", schemas)
        self.assertIn("cdn", schemas["MovieImageCacheStatus"]["properties"])
        self.assertIn("cdn", schemas["MovieImageRefreshItem"]["properties"])
        subtitle_item_properties = schemas["ResourceSubtitlePlayback"]["properties"]["items"]["items"]["properties"]
        self.assertIn("cdn", subtitle_item_properties)

    def test_season_episode_diagnostics_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/movies/{id}/episode-diagnostics", paths)
        self.assertIn("SeasonEpisodeDiagnostics", schemas)
        self.assertIn("EpisodeDiagnosticsSummary", schemas)
        self.assertIn("EpisodeRepairResourceSummary", schemas)
        self.assertIn("EpisodeRepairSuggestion", schemas)
        self.assertIn("EpisodeRepairSeason", schemas)
        self.assertIn("MovieEpisodeDiagnosticsData", schemas)
        self.assertIn("MovieEpisodeDiagnosticsResponse", schemas)
        season_group_properties = schemas["SeasonGroup"]["allOf"][1]["properties"]
        summary_properties = schemas["MovieResourceGroupsSummary"]["properties"]
        metadata_diagnostics_properties = schemas["MetadataDiagnostics"]["properties"]
        self.assertIn("episode_diagnostics", season_group_properties)
        self.assertIn("episode_diagnostics", summary_properties)
        self.assertIn("episode_diagnostics", metadata_diagnostics_properties)

    def test_metadata_quality_workbench_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/metadata/quality-summary", paths)
        self.assertIn("/api/v1/metadata/review-taxonomy", paths)
        self.assertIn("/api/v1/metadata/re-scrape/plan", paths)
        self.assertIn("/api/v1/metadata/re-scrape/jobs", paths)
        self.assertIn("/api/v1/metadata/episode-review-items", paths)
        self.assertIn("/api/v1/jobs", paths)
        self.assertIn("/api/v1/jobs/prune", paths)
        self.assertIn("/api/v1/jobs/{job_id}", paths)
        self.assertIn("MetadataQualitySummaryResponse", schemas)
        self.assertIn("MetadataReviewTaxonomyResponse", schemas)
        self.assertIn("MetadataReScrapePlanResponse", schemas)
        self.assertIn("EpisodeReviewQueueResponse", schemas)
        self.assertIn("BackgroundJob", schemas)
        self.assertIn("BackgroundJobListResponse", schemas)
        self.assertIn("BackgroundJobPruneResponse", schemas)
        self.assertIn("bangumi", schemas["MetadataState"]["properties"]["source_group"]["enum"])

    def test_resource_governance_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/resources/governance-summary", paths)
        self.assertIn("/api/v1/resources/governance-items", paths)
        self.assertIn("/api/v1/resources/governance/plan", paths)
        self.assertIn("/api/v1/resources/governance/jobs", paths)
        self.assertIn("/api/v1/resources/governance/live-check/jobs", paths)
        self.assertIn("/api/v1/resources/governance/restore/plan", paths)
        self.assertIn("/api/v1/resources/governance/restore/jobs", paths)
        self.assertIn("ResourceGovernanceSummaryResponse", schemas)
        self.assertIn("ResourceGovernanceItemsResponse", schemas)
        self.assertIn("ResourceGovernancePlanResponse", schemas)
        self.assertIn("ResourceGovernanceApplyRequest", schemas)
        self.assertIn("ResourceGovernanceRestoreSnapshot", schemas)
        self.assertIn("ResourceGovernanceLiveCheckJobRequest", schemas)
        self.assertIn("ResourceGovernanceRestorePlanResponse", schemas)
        self.assertIn("ResourceGovernanceRestoreApplyRequest", schemas)
        self.assertIn("persisted", schemas["BackgroundJob"]["properties"])

    def test_subtitle_settings_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/resources/{id}/subtitle-settings", paths)
        self.assertIn("get", paths["/api/v1/resources/{id}/subtitle-settings"])
        self.assertIn("put", paths["/api/v1/resources/{id}/subtitle-settings"])
        self.assertIn("patch", paths["/api/v1/resources/{id}/subtitle-settings"])
        self.assertIn("SubtitleDisplaySettings", schemas)
        self.assertIn("ResourceSubtitleSettingsRequest", schemas)
        self.assertIn("ResourceSubtitleSettingsResponse", schemas)
        subtitle_properties = schemas["ResourceSubtitlePlayback"]["properties"]
        self.assertEqual("#/components/schemas/SubtitleDisplaySettings", subtitle_properties["settings"]["$ref"])
        for field in ["zhSize", "zhColor", "enSize", "enColor", "gap", "offset"]:
            self.assertIn(field, schemas["SubtitleDisplaySettings"]["properties"])

    def test_external_playback_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/resources/{id}/external-playback", paths)
        self.assertIn("get", paths["/api/v1/resources/{id}/external-playback"])
        self.assertIn("ResourceExternalPlaybackManifestResponse", schemas)
        self.assertIn("ResourceExternalPlaybackManifest", schemas)
        self.assertIn("ResourceExternalPlaybackStream", schemas)
        self.assertIn("ResourceExternalPlaybackSubtitles", schemas)
        self.assertIn("ResourceExternalPlaybackHandoff", schemas)
        self.assertIn("ExternalPlayerProfile", schemas)
        self.assertIn(
            "audio/x-mpegurl",
            paths["/api/v1/resources/{id}/external-playback"]["get"]["responses"]["200"]["content"],
        )

    def test_user_management_openapi_documents_runtime_contract(self):
        openapi = self._load_openapi()
        schemas = openapi["components"]["schemas"]
        paths = openapi["paths"]

        self.assertIn("/api/v1/auth/login", paths)
        self.assertIn("/api/v1/auth/logout", paths)
        self.assertIn("/api/v1/auth/me", paths)
        self.assertIn("/api/v1/user/profile", paths)
        self.assertIn("/api/v1/user/password", paths)
        self.assertIn("/api/v1/admin/users", paths)
        self.assertIn("/api/v1/admin/users/{user_id}", paths)
        self.assertIn("/api/v1/admin/users/{user_id}/password", paths)
        self.assertIn("/api/v1/admin/users/{user_id}/library-rules", paths)
        self.assertIn("/api/v1/admin/users/{user_id}/visibility-preview", paths)
        self.assertIn("/api/v1/admin/audit-logs", paths)
        self.assertIn("cookieAuth", openapi["components"]["securitySchemes"])
        self.assertIn("User", schemas)
        self.assertIn("UserLibraryRule", schemas)
        self.assertIn("UserVisibilityPreview", schemas)
        self.assertIn("UserVisibilityLibraryPreview", schemas)
        self.assertIn("AuthStatus", schemas)
        self.assertIn("AuditLog", schemas)
        self.assertIn("session_version", schemas["User"]["properties"])


if __name__ == "__main__":
    unittest.main()
