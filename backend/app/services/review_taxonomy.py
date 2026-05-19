from __future__ import annotations

from datetime import datetime

from backend.app.models import Movie
from backend.app.services.episode_diagnostics import EPISODE_DIAGNOSTIC_ISSUES
from backend.app.services.resource_governance import RESOURCE_GOVERNANCE_ISSUES


TAXONOMY_VERSION = "review-workbench-v2"

BUCKETS = [
    {
        "id": "normal_catalog",
        "label": "普通影视库",
        "description": "前台消费视角，只展示公开目录可见的影片。不要在这里混入工作台筛选。",
        "owner": "catalog",
        "entrypoints": [
            {"method": "GET", "endpoint": "/api/v1/movies"},
            {"method": "GET", "endpoint": "/api/v1/libraries/{library_id}/movies"},
        ],
    },
    {
        "id": "metadata_review",
        "label": "元数据审查",
        "description": "处理占位资料、本地资料、低置信匹配、缺海报和锁定字段等影片级元数据问题。",
        "owner": "review_workbench",
        "entrypoints": [
            {"method": "GET", "endpoint": "/api/v1/metadata/quality-summary"},
            {"method": "GET", "endpoint": "/api/v1/metadata/work-items"},
        ],
    },
    {
        "id": "manual_content",
        "label": "其他视频归档",
        "description": "处理不会刮削成功的自建课程、爬虫视频、录屏等资源；可手工新建电影/电视剧壳并挂入资源库。",
        "owner": "review_workbench",
        "entrypoints": [
            {"method": "GET", "endpoint": "/api/v1/other-videos"},
            {"method": "POST", "endpoint": "/api/v1/movies/manual"},
            {"method": "POST", "endpoint": "/api/v1/movies/{movie_id}/resources/attach"},
        ],
    },
    {
        "id": "episode_review",
        "label": "剧集审查",
        "description": "处理缺集、重复集号、资源缺集号、季资料缺失和集数不一致。",
        "owner": "review_workbench",
        "entrypoints": [
            {"method": "GET", "endpoint": "/api/v1/metadata/episode-review-items"},
            {"method": "GET", "endpoint": "/api/v1/movies/{movie_id}/episode-diagnostics"},
        ],
    },
    {
        "id": "resource_governance",
        "label": "资源治理",
        "description": "处理文件、索引、重复资源、失效路径和存储源可用性问题，不等同于元数据审查。",
        "owner": "resource_governance",
        "entrypoints": [
            {"method": "GET", "endpoint": "/api/v1/resources/governance-summary"},
            {"method": "GET", "endpoint": "/api/v1/resources/governance-items"},
        ],
    },
    {
        "id": "catalog_visibility",
        "label": "目录发布控制",
        "description": "只控制影片是否进入普通影视库；发布/隐藏不代表元数据已经修复。",
        "owner": "catalog",
        "entrypoints": [
            {"method": "PATCH", "endpoint": "/api/v1/movies/{movie_id}/catalog-visibility"},
        ],
    },
]


ACTIONS = {
    "none": {
        "id": "none",
        "label": "无需处理",
        "description": "仅展示状态，不显示修复按钮。",
    },
    "refresh_metadata": {
        "id": "refresh_metadata",
        "label": "刷新元数据",
        "description": "基于当前外部 ID 或标题刷新影片资料。",
        "method": "POST",
        "endpoint_template": "/api/v1/movies/{movie_id}/metadata/refresh",
    },
    "re_scrape": {
        "id": "re_scrape",
        "label": "重新识别",
        "description": "基于当前已入库资源重新走元数据管线。",
        "method": "POST",
        "endpoint_template": "/api/v1/movies/{movie_id}/metadata/re-scrape",
    },
    "batch_reidentify_plan": {
        "id": "batch_reidentify_plan",
        "label": "批量重识别预览",
        "description": "先生成 dry-run 计划，用户确认后再提交批量重识别任务。",
        "method": "POST",
        "endpoint": "/api/v1/metadata/re-scrape/plan",
    },
    "match_metadata": {
        "id": "match_metadata",
        "label": "手动匹配",
        "description": "先搜索候选，再由用户确认绑定候选元数据。",
        "search": {
            "method": "GET",
            "endpoint_template": "/api/v1/movies/{movie_id}/metadata/search",
        },
        "apply": {
            "method": "POST",
            "endpoint_template": "/api/v1/movies/{movie_id}/metadata/match",
        },
    },
    "review_match": {
        "id": "review_match",
        "label": "复核匹配",
        "description": "展示当前候选、解析信号和置信度，用户确认后可刷新或手动匹配。",
        "method": "POST",
        "endpoint_template": "/api/v1/movies/{movie_id}/metadata/preview",
    },
    "rename_and_match": {
        "id": "rename_and_match",
        "label": "修正命名后匹配",
        "description": "路径无法稳定解析时先修正命名或资源归组，再手动匹配。",
        "search": {
            "method": "GET",
            "endpoint_template": "/api/v1/movies/{movie_id}/metadata/search",
        },
    },
    "edit_episode_metadata": {
        "id": "edit_episode_metadata",
        "label": "编辑剧集元数据",
        "description": "使用诊断返回的 apply_payload 修正资源季集信息。",
        "method": "PATCH",
        "endpoint_template": "/api/v1/movies/{movie_id}/resources/metadata",
    },
    "resource_governance_plan": {
        "id": "resource_governance_plan",
        "label": "资源治理预览",
        "description": "先生成 dry-run 计划，确认后再提交治理 job。",
        "method": "POST",
        "endpoint": "/api/v1/resources/governance/plan",
    },
    "resource_live_check": {
        "id": "resource_live_check",
        "label": "资源路径检查",
        "description": "只读检查存储源文件是否仍存在或大小是否变化。",
        "method": "POST",
        "endpoint": "/api/v1/resources/governance/live-check/jobs",
    },
    "manual_review": {
        "id": "manual_review",
        "label": "人工复核",
        "description": "后端不会自动修改，需要用户查看详情后选择下一步。",
    },
    "create_manual_content": {
        "id": "create_manual_content",
        "label": "手工归档",
        "description": "为不适合刮削的视频新建电影/电视剧壳，并把资源挂入指定资源库。",
        "method": "POST",
        "endpoint": "/api/v1/movies/manual",
    },
    "inspect_metadata": {
        "id": "inspect_metadata",
        "label": "检查元数据",
        "description": "展示条目详情、诊断字段和可用操作，由用户决定刷新、重识别或手动匹配。",
        "method": "GET",
        "endpoint_template": "/api/v1/movies/{movie_id}",
    },
    "catalog_publish": {
        "id": "catalog_publish",
        "label": "发布到目录",
        "description": "只控制普通影视库可见性；有 blocker 时必须显式 force。",
        "method": "PATCH",
        "endpoint_template": "/api/v1/movies/{movie_id}/catalog-visibility",
    },
}


METADATA_ISSUE_DEFINITIONS = [
    {
        "code": "placeholder_metadata",
        "label": "占位元数据",
        "label_en": "Placeholder Metadata",
        "severity": "high",
        "bucket": "metadata_review",
        "description": "没有可靠外部匹配，只由本地路径生成了占位影片资料。",
        "primary_action": "match_metadata",
        "bulk_action": None,
    },
    {
        "code": "local_only_metadata",
        "label": "仅本地元数据",
        "label_en": "Local Only Metadata",
        "severity": "medium",
        "bucket": "metadata_review",
        "description": "存在本地或 NFO 资料，但没有绑定外部元数据来源。",
        "primary_action": "match_metadata",
        "bulk_action": None,
    },
    {
        "code": "fallback_pipeline_match",
        "label": "兜底链路匹配",
        "label_en": "Fallback Pipeline Match",
        "severity": "medium",
        "bucket": "metadata_review",
        "description": "资源通过兜底解析链路入库，建议复核标题、年份、季集和匹配来源。",
        "primary_action": "review_match",
        "bulk_action": "batch_reidentify_plan",
    },
    {
        "code": "low_confidence_resources",
        "label": "低置信资源",
        "label_en": "Low Confidence Resources",
        "severity": "medium",
        "bucket": "metadata_review",
        "description": "至少一个资源的解析或刮削置信度较低。",
        "primary_action": "review_match",
        "bulk_action": "batch_reidentify_plan",
    },
    {
        "code": "nfo_candidates_available",
        "label": "存在 NFO 候选",
        "label_en": "NFO Candidates Available",
        "severity": "low",
        "bucket": "metadata_review",
        "description": "扫描时发现可参考的 NFO 候选，前端可提示用户优先检查本地资料。",
        "primary_action": "review_match",
        "bulk_action": None,
    },
    {
        "code": "poster_missing",
        "label": "缺少海报",
        "label_en": "Poster Missing",
        "severity": "high",
        "bucket": "metadata_review",
        "description": "影片没有海报，默认不会进入普通影视库自动展示。",
        "primary_action": "refresh_metadata",
        "bulk_action": "batch_reidentify_plan",
    },
    {
        "code": "locked_fields_present",
        "label": "存在锁定字段",
        "label_en": "Locked Fields Present",
        "severity": "low",
        "bucket": "metadata_review",
        "description": "影片有手动锁定字段，刷新或重识别时默认不会覆盖这些字段。",
        "primary_action": "manual_review",
        "bulk_action": None,
    },
    {
        "code": "season_metadata_missing",
        "label": "缺少季资料",
        "label_en": "Season Metadata Missing",
        "severity": "medium",
        "bucket": "episode_review",
        "description": "影片包含分季资源，但没有可用的季元数据。",
        "primary_action": "edit_episode_metadata",
        "bulk_action": None,
    },
    {
        "code": "episode_number_missing",
        "label": "资源缺集号",
        "label_en": EPISODE_DIAGNOSTIC_ISSUES["episode_number_missing"]["label"],
        "severity": EPISODE_DIAGNOSTIC_ISSUES["episode_number_missing"]["severity"],
        "bucket": "episode_review",
        "description": "部分分集资源没有可靠集号。",
        "primary_action": "edit_episode_metadata",
        "bulk_action": None,
    },
    {
        "code": "duplicate_episode_numbers",
        "label": "重复集号",
        "label_en": EPISODE_DIAGNOSTIC_ISSUES["duplicate_episode_numbers"]["label"],
        "severity": EPISODE_DIAGNOSTIC_ISSUES["duplicate_episode_numbers"]["severity"],
        "bucket": "episode_review",
        "description": "同一季下存在多个资源使用相同集号，需要人工判断是否为重复、版本或错误解析。",
        "primary_action": "edit_episode_metadata",
        "bulk_action": None,
    },
    {
        "code": "missing_episode_numbers",
        "label": "缺集",
        "label_en": EPISODE_DIAGNOSTIC_ISSUES["missing_episode_numbers"]["label"],
        "severity": EPISODE_DIAGNOSTIC_ISSUES["missing_episode_numbers"]["severity"],
        "bucket": "episode_review",
        "description": "根据季元数据或已入库集号范围推断存在缺失集号。",
        "primary_action": "edit_episode_metadata",
        "bulk_action": None,
    },
    {
        "code": "episode_count_mismatch",
        "label": "集数不一致",
        "label_en": EPISODE_DIAGNOSTIC_ISSUES["episode_count_mismatch"]["label"],
        "severity": EPISODE_DIAGNOSTIC_ISSUES["episode_count_mismatch"]["severity"],
        "bucket": "episode_review",
        "description": "已入库集数与季元数据中的期望集数不一致。",
        "primary_action": "edit_episode_metadata",
        "bulk_action": None,
    },
    {
        "code": "manual_review_required",
        "label": "需要人工复核",
        "label_en": "Manual Review Required",
        "severity": "medium",
        "bucket": "metadata_review",
        "description": "影片状态需要处理，但没有命中更具体的问题码。",
        "primary_action": "manual_review",
        "bulk_action": None,
    },
]


RESOURCE_ISSUE_LABELS = {
    "detached_source_resource": "孤儿资源索引",
    "movie_without_resources": "空壳影片",
    "duplicate_playback_resource": "重复播放资源",
    "invalid_path": "失效路径",
    "size_mismatch": "文件大小变化",
    "source_unavailable": "存储源不可用",
    "live_check_skipped": "路径检查已跳过",
}


RESOURCE_ISSUE_ACTIONS = {
    "detached_source_resource": "resource_governance_plan",
    "movie_without_resources": "manual_review",
    "duplicate_playback_resource": "resource_governance_plan",
    "invalid_path": "resource_governance_plan",
    "size_mismatch": "manual_review",
    "source_unavailable": "manual_review",
    "live_check_skipped": "resource_live_check",
}


RESOLUTION_CLASSIFICATIONS = [
    {
        "code": "orphan_group",
        "label": "孤儿分组",
        "severity": "high",
        "description": "路径解析无法恢复可靠标题，被归为未知分组。",
        "primary_action": "rename_and_match",
    },
    {
        "code": "placeholder_metadata",
        "label": "占位元数据",
        "severity": "high",
        "description": "未解析到外部元数据，生成本地占位资料。",
        "primary_action": "match_metadata",
    },
    {
        "code": "local_only_metadata",
        "label": "仅本地元数据",
        "severity": "medium",
        "description": "存在本地或 NFO 元数据，但没有外部匹配。",
        "primary_action": "match_metadata",
    },
    {
        "code": "external_match_needs_review",
        "label": "外部匹配待复核",
        "severity": "medium",
        "description": "已匹配外部候选，但来自兜底路径或置信度不足。",
        "primary_action": "review_match",
    },
    {
        "code": "external_match",
        "label": "外部匹配",
        "severity": "none",
        "description": "已获得较可靠外部元数据。",
        "primary_action": "none",
    },
    {
        "code": "unresolved_metadata",
        "label": "未解析元数据",
        "severity": "high",
        "description": "元数据管线没有产出可识别的外部或本地结果。",
        "primary_action": "inspect_metadata",
    },
]


def _metadata_issue_entry(definition):
    code = definition["code"]
    bucket = definition["bucket"]
    if bucket == "episode_review":
        list_endpoint = "/api/v1/metadata/episode-review-items"
    else:
        list_endpoint = "/api/v1/metadata/work-items"

    primary_action = definition["primary_action"]
    bulk_action = definition.get("bulk_action")
    return {
        **definition,
        "domain": "metadata",
        "list": {
            "method": "GET",
            "endpoint": list_endpoint,
            "params": {"metadata_issue_code": code},
        },
        "detail": {
            "method": "GET",
            "endpoint_template": "/api/v1/movies/{movie_id}",
        },
        "action": ACTIONS.get(primary_action, {"id": primary_action}),
        "bulk": ACTIONS.get(bulk_action) if bulk_action else None,
    }


def _resource_issue_entries():
    items = []
    for code, meta in RESOURCE_GOVERNANCE_ISSUES.items():
        primary_action = RESOURCE_ISSUE_ACTIONS.get(code, "manual_review")
        items.append({
            "code": code,
            "label": RESOURCE_ISSUE_LABELS.get(code, meta["label"]),
            "label_en": meta["label"],
            "severity": meta["severity"],
            "bucket": "resource_governance",
            "domain": "resource",
            "description": meta.get("description"),
            "primary_action": primary_action,
            "list": {
                "method": "GET",
                "endpoint": "/api/v1/resources/governance-items",
                "params": {"issue_code": code},
            },
            "detail": {
                "method": "GET",
                "endpoint": "/api/v1/resources/governance-items",
                "params": {"issue_code": code},
            },
            "action": ACTIONS.get(primary_action, {"id": primary_action}),
            "bulk": ACTIONS.get("resource_governance_plan") if primary_action == "resource_governance_plan" else None,
        })
    return items


def _metadata_source_entries():
    public_sources = Movie.get_metadata_non_attention_sources()
    source_codes = [
        "BANGUMI",
        "TENCENT_VIDEO",
        "TMDB_STRICT",
        "TMDB",
        "TMDB_FALLBACK",
        "NFO_TMDB",
        "NFO_LOCAL",
        "NFO",
        "LOCAL_FALLBACK",
        "LOCAL_ORPHAN",
        "LOCAL_MANUAL_MOVIE",
        "LOCAL_MANUAL_TV",
    ]
    items = []
    for code in source_codes:
        state = Movie.build_metadata_ui_state(code)
        items.append({
            "code": code,
            "source_group": state["source_group"],
            "label": state["source_label"],
            "confidence": state["confidence"],
            "needs_attention": state["needs_attention"],
            "review_priority": state["review_priority"],
            "recommended_action": state["recommended_action"],
            "catalog_auto_visible_when_poster": code in public_sources,
        })
    return items


def build_review_taxonomy():
    metadata_issues = [_metadata_issue_entry(definition) for definition in METADATA_ISSUE_DEFINITIONS]
    resource_issues = _resource_issue_entries()
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "generated_at": datetime.utcnow().isoformat(),
        "buckets": BUCKETS,
        "actions": list(ACTIONS.values()),
        "metadata_sources": _metadata_source_entries(),
        "issue_codes": metadata_issues + resource_issues,
        "metadata_issue_codes": metadata_issues,
        "resource_governance_issue_codes": resource_issues,
        "resolution_classifications": RESOLUTION_CLASSIFICATIONS,
        "catalog_visibility": {
            "default_rule": "普通 /api/v1/movies 默认只返回自动达标或手动发布的公开目录影片。",
            "statuses": [
                {
                    "status": Movie.CATALOG_VISIBILITY_AUTO,
                    "label": "自动",
                    "description": "后端按标题、元数据状态和海报自动判断是否进入公开目录。",
                },
                {
                    "status": Movie.CATALOG_VISIBILITY_PUBLISHED,
                    "label": "手动发布",
                    "description": "管理员显式发布；存在 blocker 时必须传 force=true。",
                },
                {
                    "status": Movie.CATALOG_VISIBILITY_HIDDEN,
                    "label": "手动隐藏",
                    "description": "管理员显式隐藏，普通影视库不会展示。",
                },
            ],
            "blockers": [
                {"code": "title_missing", "label": "缺少标题"},
                {"code": "metadata_needs_attention", "label": "元数据需要审查"},
                {"code": "poster_missing", "label": "缺少海报"},
            ],
            "warnings": [
                {"code": "overview_missing", "label": "缺少简介"},
            ],
        },
        "frontend_rules": [
            "普通影视库、首页、推荐和资源库默认使用公开目录视角，不传 metadata_* 工作台筛选。",
            "元数据审查使用 metadata_issue_codes 和 /metadata/work-items，不从 scraper_source 自行推断问题。",
            "剧集审查使用 /metadata/episode-review-items 和单片 episode-diagnostics，不混入资源治理列表。",
            "资源治理使用 resources/governance-*，只处理文件和索引问题，不代表元数据修复。",
            "catalog_visibility 只控制可见性；发布或隐藏不等于修复问题。",
        ],
    }
