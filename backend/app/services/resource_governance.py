import logging
import posixpath
import re
from collections import Counter
from datetime import datetime

from backend.app.extensions import db
from backend.app.models import History, MediaResource, Movie, ResourceSubtitle, StorageSource
from backend.app.providers.factory import provider_factory

logger = logging.getLogger(__name__)


RESOURCE_GOVERNANCE_ISSUES = {
    "detached_source_resource": {
        "label": "Detached Source Resource",
        "severity": "high",
        "description": "Resource is still indexed but no longer points to a storage source.",
    },
    "movie_without_resources": {
        "label": "Movie Without Resources",
        "severity": "high",
        "description": "Movie metadata exists without any playable resources.",
    },
    "duplicate_playback_resource": {
        "label": "Duplicate Playback Resource",
        "severity": "medium",
        "description": "Multiple resources under the same movie share season, episode, filename and size.",
    },
    "invalid_path": {
        "label": "Invalid Resource Path",
        "severity": "high",
        "description": "Live storage check could not find the indexed file in its parent directory.",
    },
    "size_mismatch": {
        "label": "Resource Size Mismatch",
        "severity": "medium",
        "description": "Live storage check found the file but its current size differs from the indexed size.",
    },
    "source_unavailable": {
        "label": "Source Unavailable",
        "severity": "high",
        "description": "Storage source cannot be initialized or its directory listing failed during live check.",
    },
    "live_check_skipped": {
        "label": "Live Check Skipped",
        "severity": "info",
        "description": "Resource path existence was not checked in this read-only report.",
    },
}

AUTO_RESOURCE_GOVERNANCE_ACTION_ISSUES = (
    "duplicate_playback_resource",
    "detached_source_resource",
    "invalid_path",
)
RESOURCE_GOVERNANCE_APPLY_ACTION_TYPE = "remove_resource_index"
RESOURCE_GOVERNANCE_RESTORE_ACTION_TYPE = "restore_resource_index"


class ResourceGovernanceValidationError(ValueError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def _normalize_filename(value):
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return text or None


def _resource_path_parts(resource):
    path = str(resource.path or "").replace("\\", "/").strip("/")
    filename = resource.filename or posixpath.basename(path)
    parent = posixpath.dirname(path)
    return path, filename, parent


def _storage_source_summary(source):
    if not source:
        return None
    return {
        "id": source.id,
        "name": source.name,
        "type": source.type,
    }


def _isoformat_datetime(value):
    return value.isoformat() if value else None


def _resource_summary(resource):
    movie = resource.movie
    return {
        "resource_id": resource.id,
        "movie_id": resource.movie_id,
        "movie_title": movie.title if movie else None,
        "filename": resource.filename,
        "path": resource.path,
        "size_bytes": resource.size,
        "season": resource.season,
        "episode": resource.episode,
        "source": _storage_source_summary(resource.source),
        "created_at": _isoformat_datetime(resource.created_at),
    }


def _resource_restore_snapshot(resource):
    if not resource:
        return None
    return {
        "model": "MediaResource",
        "table": "media_resources",
        "generated_at": datetime.utcnow().isoformat(),
        "delete_physical_file": False,
        "manual_restore_note": "Restore by recreating a MediaResource row with fields below after confirming the movie and storage source still exist.",
        "movie": _movie_summary(resource.movie) if resource.movie else None,
        "source": _storage_source_summary(resource.source),
        "fields": {
            "id": resource.id,
            "movie_id": resource.movie_id,
            "source_id": resource.source_id,
            "path": resource.path,
            "filename": resource.filename,
            "size": resource.size,
            "season": resource.season,
            "episode": resource.episode,
            "title": resource.title,
            "overview": resource.overview,
            "label": resource.label,
            "tech_specs": resource.tech_specs,
            "metadata_edited_at": _isoformat_datetime(resource.metadata_edited_at),
            "created_at": _isoformat_datetime(resource.created_at),
        },
    }


def _movie_summary(movie):
    return {
        "movie_id": movie.id,
        "title": movie.title,
        "original_title": movie.original_title,
        "year": movie.year,
        "poster_url": movie.cover,
        "scraper_source": movie.scraper_source,
    }


def _duplicate_key(resource):
    path, filename, _ = _resource_path_parts(resource)
    filename = _normalize_filename(filename)
    size = int(resource.size or 0)
    if not filename or size <= 0:
        return None
    season = resource.season if resource.season is not None else "movie"
    episode = resource.episode if resource.episode is not None else "feature"
    return f"{resource.movie_id}|{season}|{episode}|{size}|{filename}"


def _build_duplicate_item(resources):
    primary = resources[0]
    return {
        "issue_code": "duplicate_playback_resource",
        "issue_type": "resource_group",
        "severity": RESOURCE_GOVERNANCE_ISSUES["duplicate_playback_resource"]["severity"],
        "movie_id": primary.movie_id,
        "movie_title": primary.movie.title if primary.movie else None,
        "duplicate_key": {
            "filename": primary.filename,
            "size_bytes": primary.size,
            "season": primary.season,
            "episode": primary.episode,
        },
        "resource_ids": [resource.id for resource in resources],
        "resources": [_resource_summary(resource) for resource in resources],
        "recommendation": "Keep the best resource as the primary playback source and review whether other copies are valid alternates before deleting anything.",
    }


def _add_issue_item(items_by_issue, code, item):
    items_by_issue.setdefault(code, []).append({
        "issue_code": code,
        "label": RESOURCE_GOVERNANCE_ISSUES[code]["label"],
        "severity": RESOURCE_GOVERNANCE_ISSUES[code]["severity"],
        **item,
    })


def _find_live_file(provider, resource, directory_cache):
    path, filename, parent = _resource_path_parts(resource)
    cache_key = parent or ""
    if cache_key not in directory_cache:
        directory_cache[cache_key] = provider.list_items(cache_key)
    items = directory_cache[cache_key] or []
    filename_lower = (filename or "").lower()
    for item in items:
        item_name = item.get("name") or posixpath.basename(str(item.get("path") or ""))
        if str(item_name or "").lower() == filename_lower and not item.get("isdir"):
            return item
    return None


def _collect_live_path_issues(resources, live_check_limit, items_by_issue):
    checked = 0
    skipped = 0
    valid = 0
    source_errors = {}
    provider_cache = {}
    directory_caches = {}

    for resource in resources:
        if resource.source is None:
            continue
        if checked >= live_check_limit:
            skipped += 1
            continue

        checked += 1
        source = resource.source
        try:
            if source.id not in provider_cache:
                provider_cache[source.id] = provider_factory.get_provider(source)
                directory_caches[source.id] = {}
            provider = provider_cache[source.id]
            live_item = _find_live_file(provider, resource, directory_caches[source.id])
        except Exception as exc:
            logger.warning("Resource governance live check failed source_id=%s path=%s error=%s", source.id, resource.path, exc)
            source_errors[source.id] = str(exc)
            _add_issue_item(items_by_issue, "source_unavailable", {
                "issue_type": "source",
                "source": _storage_source_summary(source),
                "resource": _resource_summary(resource),
                "message": str(exc),
                "recommendation": "Check the storage source configuration and connectivity, then run a scoped scan after the source is healthy.",
            })
            continue

        if not live_item:
            _add_issue_item(items_by_issue, "invalid_path", {
                "issue_type": "resource",
                "resource": _resource_summary(resource),
                "path_check": {
                    "status": "missing",
                    "checked_parent": _resource_path_parts(resource)[2] or "/",
                },
                "recommendation": "Verify whether the file moved or was deleted. Prefer re-scanning the storage source before removing metadata.",
            })
            continue

        indexed_size = int(resource.size or 0)
        live_size = int(live_item.get("size") or 0)
        if indexed_size > 0 and live_size > 0 and indexed_size != live_size:
            _add_issue_item(items_by_issue, "size_mismatch", {
                "issue_type": "resource",
                "resource": _resource_summary(resource),
                "path_check": {
                    "status": "size_mismatch",
                    "indexed_size_bytes": indexed_size,
                    "live_size_bytes": live_size,
                },
                "recommendation": "Re-scan this source so technical metadata and duplicate grouping use the current file size.",
            })
            continue

        valid += 1

    return {
        "checked": checked,
        "valid": valid,
        "skipped": skipped,
        "source_error_count": len(source_errors),
    }


def _collect_resource_governance(live_check=False, live_check_limit=50):
    resources = MediaResource.query.order_by(MediaResource.created_at.desc(), MediaResource.id.asc()).all()
    movies = Movie.query.order_by(Movie.updated_at.desc(), Movie.id.asc()).all()
    sources = StorageSource.query.order_by(StorageSource.id.asc()).all()
    items_by_issue = {}

    for resource in resources:
        if resource.source_id is None or resource.source is None:
            _add_issue_item(items_by_issue, "detached_source_resource", {
                "issue_type": "resource",
                "resource": _resource_summary(resource),
                "recommendation": "Reattach the resource by re-scanning the original storage source, or remove it only after confirming it is no longer playable.",
            })

    for movie in movies:
        if movie.resources.count() == 0:
            _add_issue_item(items_by_issue, "movie_without_resources", {
                "issue_type": "movie",
                "movie": _movie_summary(movie),
                "recommendation": "Attach resources by scanning the correct source, or hide/delete the metadata entry after review.",
            })

    grouped = {}
    for resource in resources:
        key = _duplicate_key(resource)
        if key:
            grouped.setdefault(key, []).append(resource)
    for group_resources in grouped.values():
        if len(group_resources) <= 1:
            continue
        ordered = sorted(group_resources, key=lambda item: (
            int(item.size or 0),
            item.created_at or datetime.min,
            item.id,
        ), reverse=True)
        _add_issue_item(items_by_issue, "duplicate_playback_resource", _build_duplicate_item(ordered))

    live_stats = {
        "checked": 0,
        "valid": 0,
        "skipped": len([resource for resource in resources if resource.source is not None]),
        "source_error_count": 0,
    }
    if live_check:
        live_stats = _collect_live_path_issues(resources, live_check_limit, items_by_issue)
    elif live_stats["skipped"] > 0:
        _add_issue_item(items_by_issue, "live_check_skipped", {
            "issue_type": "check",
            "resource_count": live_stats["skipped"],
            "recommendation": "Call the endpoint with live_check=true and a bounded live_check_limit to validate indexed paths against storage sources.",
        })

    return {
        "resources": resources,
        "movies": movies,
        "sources": sources,
        "items_by_issue": items_by_issue,
        "live_stats": live_stats,
    }


def _issue_count(code, items):
    if code == "duplicate_playback_resource":
        return sum(max(0, len(item.get("resource_ids") or []) - 1) for item in items)
    return len(items)


def _build_issue_payload(code, items, sample_size):
    meta = RESOURCE_GOVERNANCE_ISSUES[code]
    return {
        "code": code,
        "label": meta["label"],
        "severity": meta["severity"],
        "description": meta["description"],
        "count": _issue_count(code, items),
        "item_count": len(items),
        "samples": items[:sample_size],
    }


def _build_resource_governance_summary_payload(collected, live_check=False, live_check_limit=50, sample_size=3):
    items_by_issue = collected["items_by_issue"]
    issues = [
        _build_issue_payload(code, items, sample_size)
        for code, items in sorted(
            items_by_issue.items(),
            key=lambda item: (-_issue_count(item[0], item[1]), item[0]),
        )
    ]

    issue_counts = {issue["code"]: issue["count"] for issue in issues}
    actionable_issue_count = sum(
        issue["count"]
        for issue in issues
        if issue["code"] != "live_check_skipped"
    )
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "dry_run": True,
        "live_check": live_check,
        "selection": {
            "live_check_limit": live_check_limit,
            "sample_size": sample_size,
        },
        "totals": {
            "movie_count": len(collected["movies"]),
            "resource_count": len(collected["resources"]),
            "storage_source_count": len(collected["sources"]),
            "actionable_issue_count": actionable_issue_count,
            "issue_code_counts": issue_counts,
            "live_path_checked_count": collected["live_stats"]["checked"],
            "live_path_valid_count": collected["live_stats"]["valid"],
            "live_path_skipped_count": collected["live_stats"]["skipped"],
            "live_source_error_count": collected["live_stats"]["source_error_count"],
        },
        "issues": issues,
        "actions": [
            {
                "id": "validate_resource_paths",
                "label": "验证资源路径",
                "method": "GET",
                "endpoint": "/api/v1/resources/governance-summary",
                "payload": {
                    "live_check": True,
                    "live_check_limit": live_check_limit,
                },
            },
            {
                "id": "review_duplicate_resources",
                "label": "复核重复资源",
                "method": "GET",
                "endpoint": "/api/v1/resources/governance-items?issue_code=duplicate_playback_resource",
                "payload": None,
            },
            {
                "id": "rescan_sources",
                "label": "重新扫描存储源",
                "method": "POST",
                "endpoint": "/api/v1/scan",
                "payload": None,
            },
        ],
    }


def build_resource_governance_summary(live_check=False, live_check_limit=50, sample_size=3):
    collected = _collect_resource_governance(live_check=live_check, live_check_limit=live_check_limit)
    return _build_resource_governance_summary_payload(
        collected,
        live_check=live_check,
        live_check_limit=live_check_limit,
        sample_size=sample_size,
    )


def _build_resource_governance_items_payload(collected, live_check=False, issue_code=None, page=1, page_size=20):
    items_by_issue = collected["items_by_issue"]
    normalized_issue_code = (issue_code or "").strip()
    if normalized_issue_code:
        items = list(items_by_issue.get(normalized_issue_code, []))
    else:
        items = [
            item
            for code in sorted(items_by_issue)
            for item in items_by_issue[code]
        ]
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        },
        "summary": {
            "issue_code": normalized_issue_code or None,
            "total_items": total,
            "live_check": live_check,
            "live_path_checked_count": collected["live_stats"]["checked"],
            "live_path_skipped_count": collected["live_stats"]["skipped"],
        },
    }


def build_resource_governance_items(live_check=False, live_check_limit=50, issue_code=None, page=1, page_size=20):
    collected = _collect_resource_governance(live_check=live_check, live_check_limit=live_check_limit)
    return _build_resource_governance_items_payload(
        collected,
        live_check=live_check,
        issue_code=issue_code,
        page=page,
        page_size=page_size,
    )


def _normalize_governance_bool(value, default=False, field_name="value"):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ResourceGovernanceValidationError(code=40094, msg=f"Invalid field type: {field_name} should be boolean")


def _normalize_governance_int(value, default, minimum=1, maximum=500, field_name="value"):
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ResourceGovernanceValidationError(code=40095, msg=f"Invalid field type: {field_name} should be int")
    return max(minimum, min(number, maximum))


def _normalize_optional_governance_int(value, minimum=1, maximum=500, field_name="value"):
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ResourceGovernanceValidationError(code=40095, msg=f"Invalid field type: {field_name} should be int")
    return max(minimum, min(number, maximum))


def _normalize_governance_string_list(value, default=None, field_name="items"):
    if value is None:
        return list(default) if default is not None else []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise ResourceGovernanceValidationError(code=40096, msg=f"Invalid field type: {field_name} should be list or comma separated string")

    items = []
    seen = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, str):
            raise ResourceGovernanceValidationError(code=40097, msg=f"Invalid field value: {field_name} should contain strings")
        item = raw_item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items


def _parse_governance_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _normalize_governance_plan_selection(payload):
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ResourceGovernanceValidationError(code=40098, msg="Invalid request body")

    issue_codes = _normalize_governance_string_list(
        payload.get("issue_codes", payload.get("issue_code")),
        default=AUTO_RESOURCE_GOVERNANCE_ACTION_ISSUES,
        field_name="issue_codes",
    )
    unknown_codes = [code for code in issue_codes if code not in RESOURCE_GOVERNANCE_ISSUES]
    if unknown_codes:
        raise ResourceGovernanceValidationError(code=40099, msg=f"Unknown resource governance issue code: {unknown_codes[0]}")

    page = _normalize_optional_governance_int(payload.get("page"), minimum=1, maximum=10000, field_name="page")
    page_size = _normalize_optional_governance_int(payload.get("page_size"), minimum=1, maximum=200, field_name="page_size")
    limit = _normalize_optional_governance_int(payload.get("limit"), minimum=1, maximum=500, field_name="limit")
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 50

    return {
        "issue_codes": issue_codes,
        "resource_ids": set(_normalize_governance_string_list(payload.get("resource_ids"), field_name="resource_ids")),
        "movie_ids": set(_normalize_governance_string_list(payload.get("movie_ids"), field_name="movie_ids")),
        "live_check": _normalize_governance_bool(payload.get("live_check"), default=False, field_name="live_check"),
        "live_check_limit": _normalize_governance_int(payload.get("live_check_limit"), 50, minimum=1, maximum=500, field_name="live_check_limit"),
        "page": page,
        "page_size": page_size,
        "limit": limit,
    }


def _resource_has_history(resource_id):
    return History.query.filter_by(resource_id=resource_id).first() is not None


def _resource_bound_subtitle_count(resource_id):
    return ResourceSubtitle.query.filter_by(resource_id=resource_id).count()


def _movie_resource_count(movie_id):
    return MediaResource.query.filter_by(movie_id=movie_id).count()


def _resource_matches_selection(resource, resource_ids=None, movie_ids=None):
    if not resource:
        return False
    if resource_ids and resource.id not in resource_ids:
        return False
    if movie_ids and resource.movie_id not in movie_ids:
        return False
    return True


def _resource_summary_matches_selection(resource_summary, resource_ids=None, movie_ids=None):
    if not resource_summary:
        return False
    if resource_ids and resource_summary.get("resource_id") not in resource_ids:
        return False
    if movie_ids and resource_summary.get("movie_id") not in movie_ids:
        return False
    return True


def _issue_item_matches_selection(item, resource_ids=None, movie_ids=None):
    resource_summary = item.get("resource")
    if resource_summary:
        return _resource_summary_matches_selection(resource_summary, resource_ids=resource_ids, movie_ids=movie_ids)

    resource_summaries = item.get("resources") or []
    if resource_summaries:
        return any(_resource_summary_matches_selection(summary, resource_ids=resource_ids, movie_ids=movie_ids) for summary in resource_summaries)

    movie_summary = item.get("movie")
    if movie_summary and movie_ids:
        return movie_summary.get("movie_id") in movie_ids
    return not resource_ids and not movie_ids


def _evaluate_remove_resource_safety(resource, primary_resource_id=None):
    if not resource:
        return False, "resource_not_found", {}

    safety = {
        "delete_physical_file": False,
        "has_history": False,
        "bound_subtitle_count": 0,
        "movie_resource_count": _movie_resource_count(resource.movie_id),
    }

    if primary_resource_id and resource.id == primary_resource_id:
        return False, "primary_resource_protected", safety

    if _resource_has_history(resource.id):
        safety["has_history"] = True
        return False, "has_history", safety

    bound_subtitle_count = _resource_bound_subtitle_count(resource.id)
    safety["bound_subtitle_count"] = bound_subtitle_count
    if bound_subtitle_count > 0:
        return False, "has_bound_subtitles", safety

    if safety["movie_resource_count"] <= 1:
        return False, "last_resource_for_movie", safety

    return True, None, safety


def _build_apply_action(issue_code, resource_id, primary_resource_id=None):
    action = {
        "type": RESOURCE_GOVERNANCE_APPLY_ACTION_TYPE,
        "issue_code": issue_code,
        "resource_id": resource_id,
        "delete_physical_file": False,
    }
    if primary_resource_id:
        action["primary_resource_id"] = primary_resource_id
    return action


def _build_remove_resource_plan_item(issue_code, resource_id, primary_resource_id=None):
    resource = db.session.get(MediaResource, resource_id)
    ok, skip_reason, safety = _evaluate_remove_resource_safety(resource, primary_resource_id=primary_resource_id)
    action = _build_apply_action(issue_code, resource_id, primary_resource_id=primary_resource_id)
    item = {
        "id": f"{RESOURCE_GOVERNANCE_APPLY_ACTION_TYPE}:{issue_code}:{resource_id}",
        "status": "planned" if ok else "skipped",
        "issue_code": issue_code,
        "action": RESOURCE_GOVERNANCE_APPLY_ACTION_TYPE,
        "resource_id": resource_id,
        "primary_resource_id": primary_resource_id,
        "resource": _resource_summary(resource) if resource else None,
        "safety": safety,
        "delete_physical_file": False,
        "restore_snapshot_available": bool(resource),
        "skip_reason": skip_reason,
        "apply_item": action if ok else None,
        "message": "Remove this resource index only; the physical file is never deleted." if ok else None,
    }
    return item


def _build_manual_review_plan_item(issue_code, issue_item, index, reason="manual_review_required"):
    return {
        "id": f"manual_review:{issue_code}:{index}",
        "status": "manual_review",
        "issue_code": issue_code,
        "action": "manual_review",
        "skip_reason": reason,
        "item": issue_item,
        "apply_item": None,
        "message": "This issue is reported for review only and is not eligible for automatic cleanup.",
    }


def _build_plan_summary(items, planned_actions):
    status_counts = Counter(item.get("status") for item in items)
    issue_counts = Counter(item.get("issue_code") for item in items)
    skip_reason_counts = Counter(item.get("skip_reason") for item in items if item.get("skip_reason"))
    return {
        "total": len(items),
        "planned": status_counts.get("planned", 0),
        "skipped": status_counts.get("skipped", 0),
        "manual_review": status_counts.get("manual_review", 0),
        "issue_code_counts": dict(issue_counts),
        "skip_reason_counts": dict(skip_reason_counts),
        "planned_resource_ids": [action["resource_id"] for action in planned_actions],
    }


def _slice_governance_plan_items(items, selection):
    total = len(items)
    page = selection.get("page")
    page_size = selection.get("page_size")
    limit = selection.get("limit")

    if page is not None and page_size is not None:
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end], {
            "paginated": True,
            "current_page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
            "limit": limit,
        }

    if limit is not None:
        return items[:limit], {
            "paginated": True,
            "current_page": 1,
            "page_size": limit,
            "total_items": total,
            "total_pages": (total + limit - 1) // limit if total else 0,
            "limit": limit,
        }

    page_size = total or 0
    return list(items), {
        "paginated": False,
        "current_page": 1,
        "page_size": page_size,
        "total_items": total,
        "total_pages": 1 if total else 0,
        "limit": None,
    }


def _planned_actions_from_items(items):
    return [
        item["apply_item"]
        for item in items
        if item.get("apply_item")
    ]


def build_resource_governance_plan(payload=None):
    selection = _normalize_governance_plan_selection(payload)
    collected = _collect_resource_governance(
        live_check=selection["live_check"],
        live_check_limit=selection["live_check_limit"],
    )
    items_by_issue = collected["items_by_issue"]
    plan_items = []
    planned_actions = []
    planned_resource_ids = set()
    manual_index = 0

    for issue_code in selection["issue_codes"]:
        issue_items = items_by_issue.get(issue_code, [])

        if issue_code == "duplicate_playback_resource":
            for issue_item in issue_items:
                resource_ids = issue_item.get("resource_ids") or []
                if len(resource_ids) <= 1:
                    continue
                primary_resource_id = resource_ids[0]
                for resource_id in resource_ids[1:]:
                    resource = db.session.get(MediaResource, resource_id)
                    if not _resource_matches_selection(resource, selection["resource_ids"], selection["movie_ids"]):
                        continue
                    if resource_id in planned_resource_ids:
                        continue
                    plan_item = _build_remove_resource_plan_item(issue_code, resource_id, primary_resource_id=primary_resource_id)
                    plan_items.append(plan_item)
                    planned_resource_ids.add(resource_id)
                    if plan_item["apply_item"]:
                        planned_actions.append(plan_item["apply_item"])
            continue

        if issue_code in {"detached_source_resource", "invalid_path"}:
            for issue_item in issue_items:
                resource_summary = issue_item.get("resource") or {}
                resource_id = resource_summary.get("resource_id")
                if not resource_id:
                    continue
                resource = db.session.get(MediaResource, resource_id)
                if not _resource_matches_selection(resource, selection["resource_ids"], selection["movie_ids"]):
                    continue
                if resource_id in planned_resource_ids:
                    continue
                plan_item = _build_remove_resource_plan_item(issue_code, resource_id)
                plan_items.append(plan_item)
                planned_resource_ids.add(resource_id)
                if plan_item["apply_item"]:
                    planned_actions.append(plan_item["apply_item"])
            continue

        for issue_item in issue_items:
            if not _issue_item_matches_selection(issue_item, selection["resource_ids"], selection["movie_ids"]):
                continue
            manual_index += 1
            plan_items.append(_build_manual_review_plan_item(issue_code, issue_item, manual_index))

    selection_payload = {
        "issue_codes": selection["issue_codes"],
        "resource_ids": sorted(selection["resource_ids"]),
        "movie_ids": sorted(selection["movie_ids"]),
        "live_check": selection["live_check"],
        "live_check_limit": selection["live_check_limit"],
        "page": selection["page"],
        "page_size": selection["page_size"],
        "limit": selection["limit"],
    }
    returned_items, pagination = _slice_governance_plan_items(plan_items, selection)
    returned_planned_actions = _planned_actions_from_items(returned_items)
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "dry_run": True,
        "apply_method": "POST",
        "apply_endpoint": "/api/v1/resources/governance/jobs",
        "selection": selection_payload,
        "items": returned_items,
        "summary": _build_plan_summary(plan_items, planned_actions),
        "returned_summary": _build_plan_summary(returned_items, returned_planned_actions),
        "pagination": pagination,
        "apply_payload": {
            "confirm": True,
            "items": returned_planned_actions,
        },
    }


def normalize_resource_governance_apply_payload(payload):
    if not isinstance(payload, dict):
        raise ResourceGovernanceValidationError(code=40100, msg="Invalid request body")
    if payload.get("confirm") is not True:
        raise ResourceGovernanceValidationError(code=40101, msg="confirm=true is required before applying resource governance actions")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ResourceGovernanceValidationError(code=40102, msg="items must be a non-empty list")

    normalized_items = []
    seen = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise ResourceGovernanceValidationError(code=40103, msg=f"Invalid action at index {index}")
        action_type = raw_item.get("type") or raw_item.get("action")
        if action_type != RESOURCE_GOVERNANCE_APPLY_ACTION_TYPE:
            raise ResourceGovernanceValidationError(code=40104, msg=f"Unsupported action type at index {index}")
        issue_code = raw_item.get("issue_code")
        if issue_code not in AUTO_RESOURCE_GOVERNANCE_ACTION_ISSUES:
            raise ResourceGovernanceValidationError(code=40105, msg=f"Unsupported issue_code at index {index}")
        resource_id = raw_item.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ResourceGovernanceValidationError(code=40106, msg=f"Invalid resource_id at index {index}")
        resource_id = resource_id.strip()
        key = (action_type, resource_id)
        if key in seen:
            continue
        seen.add(key)

        primary_resource_id = raw_item.get("primary_resource_id")
        if primary_resource_id is not None:
            if not isinstance(primary_resource_id, str) or not primary_resource_id.strip():
                raise ResourceGovernanceValidationError(code=40107, msg=f"Invalid primary_resource_id at index {index}")
            primary_resource_id = primary_resource_id.strip()

        normalized = _build_apply_action(issue_code, resource_id, primary_resource_id=primary_resource_id)
        normalized_items.append(normalized)

    if not normalized_items:
        raise ResourceGovernanceValidationError(code=40102, msg="items must be a non-empty list")

    return {
        "confirm": True,
        "items": normalized_items,
    }


def normalize_resource_governance_live_check_payload(payload):
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ResourceGovernanceValidationError(code=40108, msg="Invalid request body")

    issue_code = payload.get("issue_code") or payload.get("resource_issue_code")
    if issue_code is not None:
        if not isinstance(issue_code, str):
            raise ResourceGovernanceValidationError(code=40109, msg="Invalid field type: issue_code should be string")
        issue_code = issue_code.strip() or None
        if issue_code and issue_code not in RESOURCE_GOVERNANCE_ISSUES:
            raise ResourceGovernanceValidationError(code=40110, msg=f"Unknown resource governance issue code: {issue_code}")

    return {
        "live_check_limit": _normalize_governance_int(payload.get("live_check_limit"), 100, minimum=1, maximum=500, field_name="live_check_limit"),
        "sample_size": _normalize_governance_int(payload.get("sample_size"), 3, minimum=0, maximum=20, field_name="sample_size"),
        "issue_code": issue_code,
        "page": _normalize_governance_int(payload.get("page"), 1, minimum=1, maximum=10000, field_name="page"),
        "page_size": _normalize_governance_int(payload.get("page_size"), 20, minimum=1, maximum=100, field_name="page_size"),
    }


def _current_duplicate_group(resource):
    key = _duplicate_key(resource)
    if not key:
        return []
    resources = MediaResource.query.filter_by(movie_id=resource.movie_id).all()
    group = [item for item in resources if _duplicate_key(item) == key]
    return sorted(group, key=lambda item: (
        int(item.size or 0),
        item.created_at or datetime.min,
        item.id,
    ), reverse=True)


def _resource_still_matches_issue(resource, action):
    issue_code = action.get("issue_code")

    if issue_code == "detached_source_resource":
        if resource.source_id is None or resource.source is None:
            return True, None, {}
        return False, "issue_resolved", {}

    if issue_code == "duplicate_playback_resource":
        group = _current_duplicate_group(resource)
        if len(group) <= 1:
            return False, "issue_resolved", {}
        current_primary = group[0]
        if resource.id == current_primary.id:
            return False, "primary_resource_protected", {
                "current_primary_resource_id": current_primary.id,
            }
        return True, None, {
            "current_primary_resource_id": current_primary.id,
            "duplicate_resource_ids": [item.id for item in group],
        }

    if issue_code == "invalid_path":
        if resource.source is None:
            return False, "issue_changed", {}
        try:
            provider = provider_factory.get_provider(resource.source)
            live_item = _find_live_file(provider, resource, {})
        except Exception as exc:
            logger.warning("Resource governance apply invalid path recheck failed resource_id=%s error=%s", resource.id, exc)
            return False, "source_unavailable", {"message": str(exc)}
        if live_item:
            return False, "issue_resolved", {
                "live_path": live_item.get("path"),
                "live_size_bytes": live_item.get("size"),
            }
        return True, None, {}

    return False, "unsupported_issue_code", {}


def _snapshot_fields(snapshot):
    if not isinstance(snapshot, dict):
        return {}
    fields = snapshot.get("fields")
    return fields if isinstance(fields, dict) else {}


def _extract_restore_snapshot(raw_item, index):
    if not isinstance(raw_item, dict):
        raise ResourceGovernanceValidationError(code=40111, msg=f"Invalid restore item at index {index}")
    snapshot = raw_item.get("restore_snapshot") if "restore_snapshot" in raw_item else raw_item
    if not isinstance(snapshot, dict):
        raise ResourceGovernanceValidationError(code=40112, msg=f"Invalid restore snapshot at index {index}")
    fields = _snapshot_fields(snapshot)
    if not fields:
        raise ResourceGovernanceValidationError(code=40113, msg=f"Missing restore snapshot fields at index {index}")
    for field_name in ("id", "movie_id", "path"):
        value = fields.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ResourceGovernanceValidationError(code=40114, msg=f"Invalid restore snapshot field {field_name} at index {index}")
    return snapshot


def _normalize_restore_snapshot_items(value):
    if not isinstance(value, list) or not value:
        raise ResourceGovernanceValidationError(code=40115, msg="restore_snapshots must be a non-empty list")
    snapshots = []
    seen = set()
    for index, raw_item in enumerate(value):
        snapshot = _extract_restore_snapshot(raw_item, index)
        resource_id = _snapshot_fields(snapshot)["id"].strip()
        if resource_id in seen:
            continue
        seen.add(resource_id)
        snapshots.append(snapshot)
    if not snapshots:
        raise ResourceGovernanceValidationError(code=40115, msg="restore_snapshots must be a non-empty list")
    return snapshots


def _restore_snapshots_from_payload(payload):
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ResourceGovernanceValidationError(code=40116, msg="Invalid request body")
    raw_items = payload.get("restore_snapshots")
    if raw_items is None:
        raw_items = payload.get("snapshots")
    if raw_items is None:
        raw_items = payload.get("items")
    return _normalize_restore_snapshot_items(raw_items)


def _build_restore_apply_action(snapshot):
    return {
        "type": RESOURCE_GOVERNANCE_RESTORE_ACTION_TYPE,
        "restore_snapshot": snapshot,
        "delete_physical_file": False,
        "restore_history": False,
        "restore_subtitles": False,
    }


def _evaluate_restore_snapshot(snapshot):
    fields = _snapshot_fields(snapshot)
    resource_id = fields.get("id")
    movie_id = fields.get("movie_id")
    source_id = fields.get("source_id")
    path = fields.get("path")
    safety = {
        "delete_physical_file": False,
        "restore_history": False,
        "restore_subtitles": False,
        "movie_exists": False,
        "source_exists": source_id is None,
        "resource_exists": False,
        "source_path_available": True,
    }

    movie = db.session.get(Movie, movie_id)
    safety["movie_exists"] = movie is not None
    if not movie:
        return False, "movie_not_found", safety

    if source_id is not None:
        source = db.session.get(StorageSource, source_id)
        safety["source_exists"] = source is not None
        if not source:
            return False, "source_not_found", safety

    existing_resource = db.session.get(MediaResource, resource_id)
    safety["resource_exists"] = existing_resource is not None
    if existing_resource:
        return False, "resource_already_exists", safety

    if source_id is not None:
        path_conflict = MediaResource.query.filter(
            MediaResource.source_id == source_id,
            MediaResource.path == path,
            MediaResource.id != resource_id,
        ).first()
        safety["source_path_available"] = path_conflict is None
        if path_conflict:
            safety["conflict_resource_id"] = path_conflict.id
            return False, "source_path_conflict", safety

    return True, None, safety


def _build_restore_plan_item(snapshot):
    fields = _snapshot_fields(snapshot)
    ok, skip_reason, safety = _evaluate_restore_snapshot(snapshot)
    action = _build_restore_apply_action(snapshot)
    return {
        "id": f"{RESOURCE_GOVERNANCE_RESTORE_ACTION_TYPE}:{fields.get('id')}",
        "status": "planned" if ok else "skipped",
        "action": RESOURCE_GOVERNANCE_RESTORE_ACTION_TYPE,
        "resource_id": fields.get("id"),
        "movie_id": fields.get("movie_id"),
        "source_id": fields.get("source_id"),
        "path": fields.get("path"),
        "snapshot": snapshot,
        "safety": safety,
        "skip_reason": skip_reason,
        "apply_item": action if ok else None,
        "message": "Restore this MediaResource index only; history, subtitles and physical files are not changed." if ok else None,
    }


def _build_restore_plan_summary(items, actions):
    status_counts = Counter(item.get("status") for item in items)
    skip_reason_counts = Counter(item.get("skip_reason") for item in items if item.get("skip_reason"))
    return {
        "total": len(items),
        "planned": status_counts.get("planned", 0),
        "skipped": status_counts.get("skipped", 0),
        "skip_reason_counts": dict(skip_reason_counts),
        "planned_resource_ids": [
            _snapshot_fields(action.get("restore_snapshot")).get("id")
            for action in actions
        ],
    }


def build_resource_governance_restore_plan(payload=None):
    snapshots = _restore_snapshots_from_payload(payload)
    items = [_build_restore_plan_item(snapshot) for snapshot in snapshots]
    actions = [item["apply_item"] for item in items if item.get("apply_item")]
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "dry_run": True,
        "apply_method": "POST",
        "apply_endpoint": "/api/v1/resources/governance/restore/jobs",
        "items": items,
        "summary": _build_restore_plan_summary(items, actions),
        "apply_payload": {
            "confirm": True,
            "items": actions,
        },
    }


def normalize_resource_governance_restore_payload(payload):
    if not isinstance(payload, dict):
        raise ResourceGovernanceValidationError(code=40116, msg="Invalid request body")
    if payload.get("confirm") is not True:
        raise ResourceGovernanceValidationError(code=40117, msg="confirm=true is required before restoring resource governance snapshots")
    raw_items = payload.get("items")
    snapshots = _normalize_restore_snapshot_items(raw_items)
    return {
        "confirm": True,
        "items": [_build_restore_apply_action(snapshot) for snapshot in snapshots],
    }


def _restore_resource_from_snapshot(snapshot):
    fields = _snapshot_fields(snapshot)
    ok, skip_reason, safety = _evaluate_restore_snapshot(snapshot)
    if not ok:
        return {
            "status": "skipped",
            "skip_reason": skip_reason,
            "restore_snapshot": snapshot,
            "safety": safety,
        }

    resource = MediaResource(
        id=fields.get("id"),
        movie_id=fields.get("movie_id"),
        source_id=fields.get("source_id"),
        path=fields.get("path"),
        filename=fields.get("filename"),
        size=fields.get("size") or 0,
        season=fields.get("season"),
        episode=fields.get("episode"),
        title=fields.get("title"),
        overview=fields.get("overview"),
        label=fields.get("label"),
        tech_specs=fields.get("tech_specs") if isinstance(fields.get("tech_specs"), dict) else None,
        metadata_edited_at=_parse_governance_datetime(fields.get("metadata_edited_at")),
        created_at=_parse_governance_datetime(fields.get("created_at")) or datetime.utcnow(),
    )
    db.session.add(resource)
    db.session.commit()
    return {
        "status": "restored",
        "resource": _resource_summary(resource),
        "restore_snapshot": snapshot,
        "safety": safety,
        "message": "Resource index restored; history, subtitles and physical files were not changed.",
    }


def _build_restore_apply_summary(results):
    status_counts = Counter(item.get("status") for item in results)
    skip_reason_counts = Counter(item.get("skip_reason") for item in results if item.get("skip_reason"))
    return {
        "total": len(results),
        "restored": status_counts.get("restored", 0),
        "skipped": status_counts.get("skipped", 0),
        "failed": status_counts.get("failed", 0),
        "skip_reason_counts": dict(skip_reason_counts),
        "restored_resource_ids": [
            item.get("resource", {}).get("resource_id")
            for item in results
            if item.get("status") == "restored" and item.get("resource")
        ],
    }


def execute_resource_governance_restore_actions(payload, progress_callback=None):
    normalized = normalize_resource_governance_restore_payload(payload)
    actions = normalized["items"]
    results = []
    total = len(actions)
    for index, action in enumerate(actions, start=1):
        if progress_callback:
            progress_callback(index - 1, total, f"Restoring resource index {index}/{total}")
        try:
            result = _restore_resource_from_snapshot(action["restore_snapshot"])
        except Exception as exc:
            db.session.rollback()
            logger.exception("Resource governance restore failed index=%s error=%s", index, exc)
            result = {
                "status": "failed",
                "error": str(exc),
                "restore_snapshot": action.get("restore_snapshot"),
            }
        results.append(result)
        if progress_callback:
            progress_callback(index, total, f"Restored resource index {index}/{total}")

    return {
        "restored_at": datetime.utcnow().isoformat(),
        "delete_physical_file": False,
        "restore_history": False,
        "restore_subtitles": False,
        "summary": _build_restore_apply_summary(results),
        "items": results,
    }


def _execute_remove_resource_action(action):
    resource = db.session.get(MediaResource, action["resource_id"])
    resource_summary = _resource_summary(resource) if resource else None
    restore_snapshot = _resource_restore_snapshot(resource) if resource else None
    ok, skip_reason, safety = _evaluate_remove_resource_safety(resource, primary_resource_id=action.get("primary_resource_id"))
    if not ok:
        return {
            "status": "skipped",
            "skip_reason": skip_reason,
            "action": action,
            "resource": resource_summary,
            "safety": safety,
        }

    issue_ok, issue_skip_reason, issue_context = _resource_still_matches_issue(resource, action)
    if not issue_ok:
        return {
            "status": "skipped",
            "skip_reason": issue_skip_reason,
            "action": action,
            "resource": resource_summary,
            "safety": safety,
            "issue_context": issue_context,
        }

    db.session.delete(resource)
    db.session.commit()
    return {
        "status": "removed",
        "action": action,
        "resource": resource_summary,
        "restore_snapshot": restore_snapshot,
        "safety": safety,
        "issue_context": issue_context,
        "message": "Resource index removed; physical file was not touched.",
    }


def _build_apply_summary(results):
    status_counts = Counter(item.get("status") for item in results)
    skip_reason_counts = Counter(item.get("skip_reason") for item in results if item.get("skip_reason"))
    return {
        "total": len(results),
        "removed": status_counts.get("removed", 0),
        "skipped": status_counts.get("skipped", 0),
        "failed": status_counts.get("failed", 0),
        "skip_reason_counts": dict(skip_reason_counts),
        "restore_snapshot_count": sum(1 for item in results if item.get("restore_snapshot")),
        "removed_resource_ids": [
            item.get("resource", {}).get("resource_id")
            for item in results
            if item.get("status") == "removed" and item.get("resource")
        ],
    }


def execute_resource_governance_actions(payload, progress_callback=None):
    normalized = normalize_resource_governance_apply_payload(payload)
    actions = normalized["items"]
    results = []
    total = len(actions)

    for index, action in enumerate(actions, start=1):
        if progress_callback:
            progress_callback(index - 1, total, f"Applying resource governance action {index}/{total}")
        try:
            result = _execute_remove_resource_action(action)
        except Exception as exc:
            db.session.rollback()
            logger.exception("Resource governance apply action failed resource_id=%s error=%s", action.get("resource_id"), exc)
            result = {
                "status": "failed",
                "error": str(exc),
                "action": action,
            }
        results.append(result)
        if progress_callback:
            progress_callback(index, total, f"Applied resource governance action {index}/{total}")

    return {
        "applied_at": datetime.utcnow().isoformat(),
        "delete_physical_file": False,
        "summary": _build_apply_summary(results),
        "items": results,
    }


def execute_resource_governance_live_check(payload=None, progress_callback=None):
    normalized = normalize_resource_governance_live_check_payload(payload)
    if progress_callback:
        progress_callback(0, 2, "Starting resource governance live check")

    collected = _collect_resource_governance(
        live_check=True,
        live_check_limit=normalized["live_check_limit"],
    )
    if progress_callback:
        progress_callback(1, 2, "Building resource governance live check result")

    summary = _build_resource_governance_summary_payload(
        collected,
        live_check=True,
        live_check_limit=normalized["live_check_limit"],
        sample_size=normalized["sample_size"],
    )
    items = _build_resource_governance_items_payload(
        collected,
        live_check=True,
        issue_code=normalized["issue_code"],
        page=normalized["page"],
        page_size=normalized["page_size"],
    )

    if progress_callback:
        progress_callback(2, 2, "Resource governance live check completed")

    return {
        "checked_at": datetime.utcnow().isoformat(),
        "dry_run": True,
        "selection": normalized,
        "summary": summary,
        "items": items["items"],
        "pagination": items["pagination"],
        "item_summary": items["summary"],
    }
