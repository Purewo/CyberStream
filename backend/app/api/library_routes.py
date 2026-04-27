import hashlib
import logging
import posixpath
import re
from datetime import datetime

from flask import Blueprint, request

from backend.app.api.helpers import build_pagination_meta, get_history_map, get_movie_user_history, get_resource_history_map
from backend.app.api.library_helpers import (
    attach_recommendation_payload,
    build_library_movie_id_context,
    build_movie_list_query,
    build_review_queue_query,
    get_featured_movies,
    get_context_recommendation_items,
    get_filter_options,
    get_recommendation_items,
    normalize_recommendation_strategy,
    resolve_movie_sort_column,
)
from backend.app.db.database import scanner_adapter
from backend.app.extensions import db
from backend.app.metadata.rescrape import movie_metadata_rescrape_service
from backend.app.models import Library, MediaResource, Movie, MovieSeasonMetadata
from backend.app.services.tmdb import scraper
from backend.app.utils.genres import normalize_genres
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

library_bp = Blueprint('library', __name__, url_prefix='/api/v1')

MOVIE_MUTABLE_FIELDS = {
    'title': str,
    'original_title': str,
    'year': int,
    'rating': (int, float),
    'description': str,
    'cover': str,
    'background_cover': str,
    'category': list,
    'director': str,
    'actors': list,
    'country': str,
}

MOVIE_PATCH_ALIASES = {
    'overview': 'description',
    'poster_url': 'cover',
    'backdrop_url': 'background_cover',
    'tags': 'category',
    'genres': 'category',
}

TEXT_FIELDS = {
    'title',
    'original_title',
    'description',
    'cover',
    'background_cover',
    'director',
    'country',
}

LOCKABLE_FIELDS = {
    'title',
    'original_title',
    'year',
    'rating',
    'description',
    'cover',
    'background_cover',
    'category',
    'director',
    'actors',
    'country',
}

TMDB_REFRESHABLE_FIELDS = [
    'title',
    'original_title',
    'year',
    'rating',
    'description',
    'cover',
    'background_cover',
    'category',
    'director',
    'actors',
    'country',
    'scraper_source',
]

TMDB_SEARCH_SOURCE_HINTS = {'movie', 'tv'}

RESOURCE_MUTABLE_FIELDS = {
    'season': int,
    'episode': int,
    'title': str,
    'overview': str,
    'label': str,
}

SEASON_MUTABLE_FIELDS = {
    'title': str,
    'overview': str,
    'air_date': str,
}


class MetadataValidationError(ValueError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def _normalize_text_field(field, value):
    if value is None:
        if field == 'title':
            raise MetadataValidationError(code=40009, msg="Invalid field value: title cannot be empty")
        return None

    if not isinstance(value, str):
        expected_type = MOVIE_MUTABLE_FIELDS.get(field, str)
        expected_name = expected_type.__name__
        raise MetadataValidationError(code=40003, msg=f"Invalid field type: {field} should be {expected_name}")

    value = value.strip()
    if not value:
        if field == 'title':
            raise MetadataValidationError(code=40009, msg="Invalid field value: title cannot be empty")
        return None

    return value


def _normalize_optional_text_field(field, value):
    if value is None:
        return None

    if not isinstance(value, str):
        raise MetadataValidationError(code=40003, msg=f"Invalid field type: {field} should be str")

    value = value.strip()
    return value or None


def _normalize_string_list(field, value):
    if value is None:
        return []

    if not isinstance(value, list):
        raise MetadataValidationError(code=40003, msg=f"Invalid field type: {field} should be list")

    items = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise MetadataValidationError(code=40004, msg=f"Invalid field value: {field} should contain only strings")

        normalized = item.strip()
        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        items.append(normalized)

    return items


def _normalize_actor_list(value):
    if value is None:
        return []

    if not isinstance(value, list):
        raise MetadataValidationError(code=40003, msg="Invalid field type: actors should be list")

    items = []
    seen = set()

    for item in value:
        if isinstance(item, str):
            normalized = item.strip()
        elif isinstance(item, dict):
            actor_name = item.get('name')
            if actor_name is None:
                raise MetadataValidationError(code=40004, msg="Invalid field value: actor objects should contain name")
            if not isinstance(actor_name, str):
                raise MetadataValidationError(code=40004, msg="Invalid field value: actor name should be string")
            normalized = actor_name.strip()
        else:
            raise MetadataValidationError(code=40004, msg="Invalid field value: actors should contain strings or objects")

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        items.append(normalized)

    return items


def _normalize_year(value):
    if value is None:
        return None

    if isinstance(value, bool):
        raise MetadataValidationError(code=40003, msg="Invalid field type: year should be int")

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if not value.isdigit():
            raise MetadataValidationError(code=40003, msg="Invalid field type: year should be int")
        value = int(value)

    if not isinstance(value, int):
        raise MetadataValidationError(code=40003, msg="Invalid field type: year should be int")

    if value <= 0:
        raise MetadataValidationError(code=40005, msg="Invalid field value: year should be positive")

    return value


def _normalize_rating(value):
    if value is None:
        return None

    if isinstance(value, bool):
        raise MetadataValidationError(code=40003, msg="Invalid field type: rating should be int/float")

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = float(value)
        except ValueError as exc:
            raise MetadataValidationError(code=40003, msg="Invalid field type: rating should be int/float") from exc

    if not isinstance(value, (int, float)):
        raise MetadataValidationError(code=40003, msg="Invalid field type: rating should be int/float")

    value = float(value)
    if value < 0 or value > 10:
        raise MetadataValidationError(code=40006, msg="Invalid field value: rating should be between 0 and 10")

    return value


def _normalize_movie_field(field, value):
    if field in TEXT_FIELDS:
        return _normalize_text_field(field, value)
    if field == 'year':
        return _normalize_year(value)
    if field == 'rating':
        return _normalize_rating(value)
    if field == 'category':
        return normalize_genres(_normalize_string_list(field, value))
    if field == 'actors':
        return _normalize_actor_list(value)

    raise MetadataValidationError(code=40002, msg=f"Unsupported field: {field}")


def _normalize_movie_patch_payload(payload):
    if not isinstance(payload, dict):
        raise MetadataValidationError(code=40001, msg="Invalid input data: JSON object expected")

    normalized_payload = {}
    field_sources = {}
    unknown_keys = []

    for raw_field, raw_value in payload.items():
        target_field = MOVIE_PATCH_ALIASES.get(raw_field, raw_field)
        if target_field not in MOVIE_MUTABLE_FIELDS:
            unknown_keys.append(raw_field)
            continue

        existing_source = field_sources.get(target_field)
        if existing_source:
            raise MetadataValidationError(
                code=40008,
                msg=f"Conflicting fields: {existing_source} and {raw_field} both map to {target_field}",
            )

        normalized_payload[target_field] = _normalize_movie_field(target_field, raw_value)
        field_sources[target_field] = raw_field

    if unknown_keys:
        raise MetadataValidationError(code=40002, msg=f"Unsupported fields: {', '.join(sorted(unknown_keys))}")

    return normalized_payload


def _normalize_lock_field_names(raw_fields):
    if raw_fields is None:
        return None

    if not isinstance(raw_fields, list):
        raise MetadataValidationError(code=40010, msg="Invalid field type: metadata_locked_fields should be list")

    normalized = []
    seen = set()

    for raw_field in raw_fields:
        if not isinstance(raw_field, str):
            raise MetadataValidationError(code=40011, msg="Invalid field value: metadata_locked_fields should contain only strings")

        field = MOVIE_PATCH_ALIASES.get(raw_field, raw_field).strip()
        if field not in LOCKABLE_FIELDS:
            raise MetadataValidationError(code=40012, msg=f"Unsupported lock field: {raw_field}")
        if field in seen:
            continue

        seen.add(field)
        normalized.append(field)

    return normalized


def _normalize_tmdb_id(raw_tmdb_id):
    if raw_tmdb_id is None:
        return None
    if not isinstance(raw_tmdb_id, str):
        raise MetadataValidationError(code=40014, msg="Invalid field type: tmdb_id should be string")

    tmdb_id = raw_tmdb_id.strip()
    if not tmdb_id:
        raise MetadataValidationError(code=40015, msg="Invalid field value: tmdb_id cannot be empty")

    return tmdb_id


def _build_external_metadata_update_payload(meta_data):
    payload = {}
    source = meta_data if isinstance(meta_data, dict) else {}

    for field in TMDB_REFRESHABLE_FIELDS:
        value = source.get(field)

        if field == 'category':
            value = normalize_genres(value or [])
            if not value:
                continue
        elif field == 'actors':
            value = _normalize_actor_list(value)
            if not value:
                continue
        elif field == 'year':
            if value in (None, ''):
                continue
            value = _normalize_year(value)
        elif field == 'rating':
            if value is None:
                continue
            value = _normalize_rating(value)
            if value <= 0:
                continue
        elif field == 'scraper_source':
            if value is None:
                continue
            value = str(value).strip()
            if not value:
                continue
        elif field in TEXT_FIELDS:
            if value is None:
                continue
            value = _normalize_text_field(field, value)
            if value is None:
                continue

        payload[field] = value

    return payload


def _normalize_tmdb_search_query(raw_query):
    if raw_query is None:
        return None
    if not isinstance(raw_query, str):
        raise MetadataValidationError(code=40017, msg="Invalid field type: query should be string")

    query = raw_query.strip()
    if not query:
        raise MetadataValidationError(code=40018, msg="Invalid field value: query cannot be empty")

    return query


def _normalize_media_type_hint(raw_hint):
    if raw_hint is None:
        return None
    if not isinstance(raw_hint, str):
        raise MetadataValidationError(code=40021, msg="Invalid field type: media_type_hint should be string")

    hint = raw_hint.strip().lower()
    if not hint:
        return None
    if hint not in TMDB_SEARCH_SOURCE_HINTS:
        raise MetadataValidationError(code=40022, msg="Invalid field value: media_type_hint should be movie or tv")
    return hint


def _normalize_positive_int_field(field, value, allow_none=True):
    if value is None:
        return None if allow_none else 0

    if isinstance(value, bool):
        raise MetadataValidationError(code=40019, msg=f"Invalid field type: {field} should be int")

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None if allow_none else 0
        if not value.isdigit():
            raise MetadataValidationError(code=40019, msg=f"Invalid field type: {field} should be int")
        value = int(value)

    if not isinstance(value, int):
        raise MetadataValidationError(code=40019, msg=f"Invalid field type: {field} should be int")

    if value <= 0:
        raise MetadataValidationError(code=40020, msg=f"Invalid field value: {field} should be positive")

    return value


def _normalize_resource_payload(payload):
    if not isinstance(payload, dict):
        raise MetadataValidationError(code=40001, msg="Invalid input data: JSON object expected")

    normalized = {}
    unknown_keys = []

    for field, value in payload.items():
        if field not in RESOURCE_MUTABLE_FIELDS:
            unknown_keys.append(field)
            continue

        if field in ('season', 'episode'):
            normalized[field] = _normalize_positive_int_field(field, value)
        elif field in ('title', 'overview'):
            normalized[field] = _normalize_optional_text_field(field, value)
        elif field == 'label':
            normalized[field] = _normalize_optional_text_field(field, value)

    if unknown_keys:
        raise MetadataValidationError(code=40002, msg=f"Unsupported fields: {', '.join(sorted(unknown_keys))}")

    if not normalized:
        raise MetadataValidationError(code=40007, msg="No supported fields to update")

    return normalized


def _normalize_air_date(value):
    value = _normalize_optional_text_field('air_date', value)
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise MetadataValidationError(code=40025, msg="Invalid field value: air_date should be YYYY-MM-DD") from exc
    return value


def _normalize_season_payload(payload):
    if not isinstance(payload, dict):
        raise MetadataValidationError(code=40001, msg="Invalid input data: JSON object expected")

    normalized = {}
    unknown_keys = []

    for field, value in payload.items():
        if field not in SEASON_MUTABLE_FIELDS:
            unknown_keys.append(field)
            continue

        if field in ('title', 'overview'):
            normalized[field] = _normalize_optional_text_field(field, value)
        elif field == 'air_date':
            normalized[field] = _normalize_air_date(value)

    if unknown_keys:
        raise MetadataValidationError(code=40002, msg=f"Unsupported fields: {', '.join(sorted(unknown_keys))}")

    if not normalized:
        raise MetadataValidationError(code=40007, msg="No supported fields to update")

    return normalized


def _sync_movie_season_metadata(movie, meta_data):
    if not isinstance(meta_data, dict):
        return {"upserted": 0, "deleted": 0}
    return scanner_adapter.sync_movie_season_metadata(
        movie,
        meta_data.get('season_metadata'),
        prune_missing=True,
    )


def _infer_metadata_media_type(tmdb_id, fallback=None):
    if isinstance(tmdb_id, str) and '/' in tmdb_id:
        media_type = tmdb_id.split('/', 1)[0].strip().lower()
        if media_type in TMDB_SEARCH_SOURCE_HINTS:
            return media_type

    fallback = (fallback or '').strip().lower()
    if fallback in TMDB_SEARCH_SOURCE_HINTS:
        return fallback
    return None


def _is_external_metadata_id(tmdb_id):
    return _infer_metadata_media_type(tmdb_id) in TMDB_SEARCH_SOURCE_HINTS


def _build_metadata_resolution_info(resolution):
    return {
        "scrape_layer": resolution.scrape_layer,
        "scrape_strategy": resolution.scrape_strategy,
        "reason": resolution.reason,
        "resolved_tmdb_id": resolution.resolved_tmdb_id,
    }


def _build_metadata_entity_context_info(entity_context, resource_count=None):
    return {
        "title": entity_context.title,
        "year": entity_context.year,
        "media_type_hint": entity_context.media_type_hint,
        "parse_layer": entity_context.parse_layer,
        "parse_strategy": entity_context.parse_strategy,
        "confidence": entity_context.confidence,
        "nfo_candidates": entity_context.nfo_candidates,
        "resource_count": resource_count if resource_count is not None else len(entity_context.files),
        "sample_path": entity_context.sample_path,
    }


def _build_metadata_resolution_feedback(resolution, entity_context=None):
    meta_data = resolution.meta_data if isinstance(resolution.meta_data, dict) else {}
    source_code = (meta_data.get('scraper_source') or '').strip().upper()
    state = Movie.build_metadata_ui_state(source_code)
    tmdb_id = meta_data.get('tmdb_id') or resolution.resolved_tmdb_id
    media_type = _infer_metadata_media_type(tmdb_id, meta_data.get('media_type_hint'))
    has_external_id = _is_external_metadata_id(tmdb_id) or _is_external_metadata_id(resolution.resolved_tmdb_id)

    if source_code == 'LOCAL_ORPHAN':
        classification = {
            "code": "orphan_group",
            "label": "Orphan Group",
            "severity": "high",
            "status": "unresolved",
            "requires_review": True,
            "recommended_action": "rename_and_match",
        }
        explanation = "Path parsing could not recover a reliable title, so the item was grouped as an unknown series."
    elif state["is_placeholder"] or (not has_external_id and source_code in Movie.get_metadata_placeholder_sources()):
        classification = {
            "code": "placeholder_metadata",
            "label": "Placeholder Metadata",
            "severity": "high",
            "status": "local_placeholder",
            "requires_review": True,
            "recommended_action": "match_metadata",
        }
        explanation = "No external metadata match was resolved, so local placeholder metadata was generated."
    elif state["is_local_only"] and not has_external_id:
        classification = {
            "code": "local_only_metadata",
            "label": "Local Only Metadata",
            "severity": "medium",
            "status": "local_only",
            "requires_review": True,
            "recommended_action": "match_metadata",
        }
        explanation = "Local or NFO metadata was found, but it is not linked to an external TMDB match."
    elif state["is_external_match"] and state["needs_attention"]:
        classification = {
            "code": "external_match_needs_review",
            "label": "External Match Needs Review",
            "severity": "medium",
            "status": "matched_needs_review",
            "requires_review": True,
            "recommended_action": state["recommended_action"],
        }
        explanation = "An external metadata candidate was resolved through a fallback path and should be reviewed."
    elif state["is_external_match"] or has_external_id:
        classification = {
            "code": "external_match",
            "label": "External Match",
            "severity": "none",
            "status": "matched",
            "requires_review": False,
            "recommended_action": state["recommended_action"],
        }
        explanation = "A high confidence external metadata match was resolved."
    else:
        classification = {
            "code": "unresolved_metadata",
            "label": "Unresolved Metadata",
            "severity": "high",
            "status": "unresolved",
            "requires_review": True,
            "recommended_action": "inspect_metadata",
        }
        explanation = "The metadata pipeline did not produce a recognized external or local result."

    signals = {}
    if entity_context:
        signals = {
            "title_hint": entity_context.title,
            "year_hint": entity_context.year,
            "media_type_hint": entity_context.media_type_hint,
            "parse_layer": entity_context.parse_layer,
            "parse_strategy": entity_context.parse_strategy,
            "parse_confidence": entity_context.confidence,
            "file_count": len(entity_context.files),
            "nfo_candidate_count": len(entity_context.nfo_candidates),
            "has_nfo_candidates": bool(entity_context.nfo_candidates),
            "sample_path": entity_context.sample_path,
        }

    return {
        "classification": classification,
        "candidate": {
            "tmdb_id": tmdb_id,
            "resolved_tmdb_id": resolution.resolved_tmdb_id,
            "media_type": media_type,
            "title": meta_data.get('title'),
            "original_title": meta_data.get('original_title'),
            "year": meta_data.get('year'),
            "source_code": source_code or None,
            "source_group": state["source_group"],
            "confidence": state["confidence"],
            "is_external_match": bool(state["is_external_match"] or has_external_id),
            "has_poster": bool(meta_data.get('cover')),
            "has_backdrop": bool(meta_data.get('background_cover')),
        },
        "signals": signals,
        "explanation": explanation,
    }


def _metadata_season_result_changed(season_result):
    season_result = season_result or {}
    return bool(season_result.get("upserted") or season_result.get("deleted"))


def _build_metadata_apply_status(error=None, updated_fields=None, season_result=None):
    if error:
        return "failed"
    if updated_fields or _metadata_season_result_changed(season_result):
        return "updated"
    return "unchanged"


def _classify_metadata_error(code, msg):
    text = (msg or '').lower()
    category = "metadata_pipeline_error"
    retryable = code >= 500
    recommended_action = "retry"

    if code == 40401:
        category = "movie_not_found"
        retryable = False
        recommended_action = "remove_from_batch"
    elif 40000 <= code < 50000 and code != 40026:
        category = "validation_error"
        retryable = False
        recommended_action = "fix_request"
    elif code == 40026:
        retryable = False
        recommended_action = "inspect_metadata"
        if "no resources" in text:
            category = "no_resources"
            recommended_action = "attach_resources"
        elif "no readable resources" in text:
            category = "no_readable_resources"
            recommended_action = "check_storage_source"
        elif "infer entity" in text:
            category = "entity_inference_failed"
            recommended_action = "rename_and_match"
        else:
            category = "pipeline_rejected"
    elif code >= 50000:
        category = "metadata_pipeline_error"
        retryable = True
        recommended_action = "retry"

    return {
        "code": code,
        "msg": msg,
        "category": category,
        "retryable": retryable,
        "recommended_action": recommended_action,
    }


def _normalize_candidate_compare_text(value):
    text = re.sub(r'\s+', ' ', (value or '').strip().lower())
    text = re.sub(r'[-_.:]+', ' ', text)
    return text.strip()


def _build_metadata_candidate_explanation(candidate, query, year=None, media_type_hint=None):
    normalized_query = _normalize_candidate_compare_text(query)
    title = _normalize_candidate_compare_text(candidate.get('title'))
    original_title = _normalize_candidate_compare_text(candidate.get('original_title'))
    candidate_year = candidate.get('year')
    candidate_media_type = candidate.get('media_type')

    reason_codes = []
    score = 0

    if normalized_query and title == normalized_query:
        reason_codes.append("title_exact")
        score += 3
    elif normalized_query and original_title == normalized_query:
        reason_codes.append("original_title_exact")
        score += 3
    elif normalized_query and (normalized_query in title or normalized_query in original_title):
        reason_codes.append("title_contains_query")
        score += 1

    year_delta = None
    if year and candidate_year:
        year_delta = abs(candidate_year - year)
        if year_delta == 0:
            reason_codes.append("year_match")
            score += 2
        elif year_delta <= 1:
            reason_codes.append("near_year_match")
            score += 1
        else:
            reason_codes.append("year_mismatch")
            score -= 1
    elif year and not candidate_year:
        reason_codes.append("candidate_year_missing")

    if media_type_hint:
        if candidate_media_type == media_type_hint:
            reason_codes.append("media_type_match")
            score += 1
        else:
            reason_codes.append("media_type_mismatch")
            score -= 1

    if candidate.get('poster_url'):
        reason_codes.append("poster_available")
    if candidate.get('vote_average'):
        reason_codes.append("rating_available")

    if score >= 5:
        confidence = "high"
    elif score >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "confidence": confidence,
        "reason_codes": reason_codes,
        "query": query,
        "year_hint": year,
        "year_delta": year_delta,
        "media_type_hint": media_type_hint,
    }


def _annotate_metadata_candidates(candidates, query, year=None, media_type_hint=None):
    annotated = []
    for index, candidate in enumerate(candidates, start=1):
        item = dict(candidate)
        item["rank"] = index
        item["match_explanation"] = _build_metadata_candidate_explanation(
            item,
            query=query,
            year=year,
            media_type_hint=media_type_hint,
        )
        annotated.append(item)
    return annotated


def _build_resource_label(resource, season, episode):
    label_prefix = "Movie"
    if season is not None and episode is not None:
        label_prefix = f"S{season:02d}E{episode:02d}"
    elif episode is not None:
        label_prefix = f"EP{episode:02d}"
    elif season is not None:
        label_prefix = f"S{season:02d}"

    resolution = (resource.tech_specs or {}).get('resolution')
    if resolution:
        return f"{label_prefix} - {resolution}"
    return label_prefix


def _is_newer_user_history(candidate, current):
    if not candidate:
        return False
    if not current:
        return True
    return (candidate.get("last_played_at") or "") > (current.get("last_played_at") or "")


def _normalize_duplicate_filename(resource):
    filename = resource.filename or posixpath.basename(resource.path or "")
    filename = re.sub(r"\s+", " ", str(filename or "").strip().lower())
    return filename or None


def _build_playback_source_key(resource):
    filename = _normalize_duplicate_filename(resource)
    size = int(resource.size or 0)
    if not filename or size <= 0:
        return f"resource:{resource.id}"
    season = resource.season if resource.season is not None else "movie"
    episode = resource.episode if resource.episode is not None else "feature"
    return f"{season}|{episode}|{size}|{filename}"


def _build_playback_source_group_id(key):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"ps_{digest}"


def _resource_quality_sort_value(resource, resource_item, user_history):
    technical = ((resource_item.get("resource_info") or {}).get("technical") or {})
    last_played = (user_history or {}).get("last_played_at") or ""
    return (
        1 if user_history else 0,
        last_played,
        int(technical.get("quality_rank") or 0),
        int(technical.get("video_resolution_rank") or 0),
        int(resource.size or 0),
        resource.created_at or datetime.min,
        resource.id,
    )


def _build_playback_source_groups(resources, resource_item_map, resource_history_map):
    grouped = {}
    for resource in resources:
        grouped.setdefault(_build_playback_source_key(resource), []).append(resource)

    playback_sources = []
    for key, group_resources in grouped.items():
        ordered_resources = sorted(
            group_resources,
            key=lambda resource: _resource_quality_sort_value(
                resource,
                resource_item_map[resource.id],
                resource_history_map.get(resource.id),
            ),
            reverse=True,
        )
        primary = ordered_resources[0]
        primary_item = resource_item_map[primary.id]
        resource_ids = [resource.id for resource in ordered_resources]
        alternate_ids = resource_ids[1:]
        primary_info = primary_item.get("resource_info") or {}
        primary_file = primary_info.get("file") or {}
        primary_display = primary_info.get("display") or {}
        source_summary = []
        seen_source_ids = set()

        for resource in ordered_resources:
            file_info = (resource_item_map[resource.id].get("resource_info") or {}).get("file") or {}
            storage_source = file_info.get("storage_source") or {}
            source_id = storage_source.get("id")
            source_key = source_id if source_id is not None else f"unknown:{resource.id}"
            if source_key in seen_source_ids:
                continue
            seen_source_ids.add(source_key)
            source_summary.append({
                "id": source_id,
                "name": storage_source.get("name"),
                "type": storage_source.get("type"),
            })

        playback_sources.append({
            "id": _build_playback_source_group_id(key),
            "primary_resource_id": primary.id,
            "resource_ids": resource_ids,
            "alternate_resource_ids": alternate_ids,
            "count": len(resource_ids),
            "is_duplicate_group": len(resource_ids) > 1,
            "duplicate_key": {
                "filename": _normalize_duplicate_filename(primary),
                "size_bytes": int(primary.size or 0),
                "season": primary.season,
                "episode": primary.episode,
            },
            "match": {
                "type": "same_filename_size" if len(resource_ids) > 1 and not key.startswith("resource:") else "single_source",
                "fields": ["season", "episode", "filename", "size_bytes"] if len(resource_ids) > 1 and not key.startswith("resource:") else [],
            },
            "display": {
                "title": primary_display.get("title"),
                "label": primary_display.get("label"),
                "season": primary_display.get("season"),
                "episode": primary_display.get("episode"),
                "episode_label": primary_display.get("episode_label"),
            },
            "file": {
                "filename": primary_file.get("filename"),
                "size_bytes": primary_file.get("size_bytes"),
            },
            "source_summary": source_summary,
            "user_data": primary_item.get("user_data"),
        })

    playback_sources.sort(key=lambda item: (
        (item.get("display") or {}).get("season") is None,
        (item.get("display") or {}).get("season") if (item.get("display") or {}).get("season") is not None else 0,
        (item.get("display") or {}).get("episode") is None,
        (item.get("display") or {}).get("episode") if (item.get("display") or {}).get("episode") is not None else 0,
        (item.get("file") or {}).get("filename") or "",
    ))
    return playback_sources


def _build_movie_resource_groups(movie):
    resources = movie.resources.all()
    resource_history_map = get_resource_history_map([resource.id for resource in resources])
    season_metadata_map = movie.get_season_metadata_map()
    resources.sort(key=lambda item: (
        item.season is None,
        item.season if item.season is not None else 0,
        item.episode is None,
        item.episode if item.episode is not None else 0,
        item.filename or "",
    ))

    season_groups = []
    season_map = {}
    standalone_resource_ids = []
    standalone_user_history = None
    edited_items = 0
    resource_items = []
    resource_item_map = {}

    for resource in resources:
        resource_dict = resource.to_dict()
        resource_user_history = resource_history_map.get(resource.id)
        resource_dict["user_data"] = resource_user_history
        resource_items.append(resource_dict)
        resource_item_map[resource.id] = resource_dict
        display = resource_dict.get("resource_info", {}).get("display", {})
        if display.get("has_manual_metadata"):
            edited_items += 1
        if resource.season is None:
            standalone_resource_ids.append(resource.id)
            if _is_newer_user_history(resource_user_history, standalone_user_history):
                standalone_user_history = resource_user_history
            continue

        if resource.season not in season_map:
            season_metadata = season_metadata_map.get(resource.season)
            season_data = season_metadata.to_dict() if season_metadata else {
                "season": resource.season,
                "title": None,
                "display_title": f"Season {resource.season}",
                "overview": None,
                "air_date": None,
                "poster_url": None,
                "episode_count": None,
                "has_manual_metadata": False,
                "has_metadata": False,
                "metadata_edited_at": None,
            }
            season_poster = season_data.get("poster_url")
            season_entry = {
                **season_data,
                "poster_url": season_poster or movie.cover,
                "poster_source": "season" if season_poster else ("movie_fallback" if movie.cover else "none"),
                "has_distinct_poster": bool(season_poster and season_poster != movie.cover),
                "resource_ids": [],
                "episode_count": 0,
                "tmdb_episode_count": season_data.get("episode_count"),
                "edited_items_count": 0,
                "has_manual_metadata": season_data["has_manual_metadata"],
                "has_metadata": season_data.get("has_metadata", False),
                "user_data": None,
                "sort": {
                    "season": resource.season,
                    "first_episode": None,
                },
            }
            season_map[resource.season] = season_entry
            season_groups.append(season_entry)

        season_entry = season_map[resource.season]
        season_entry["resource_ids"].append(resource.id)
        season_entry["episode_count"] += 1
        if display.get("has_manual_metadata"):
            season_entry["edited_items_count"] += 1
            season_entry["has_manual_metadata"] = True
        if _is_newer_user_history(resource_user_history, season_entry.get("user_data")):
            season_entry["user_data"] = resource_user_history

        episode = display.get("episode")
        if episode is not None:
            first_episode = season_entry["sort"].get("first_episode")
            if first_episode is None or episode < first_episode:
                season_entry["sort"]["first_episode"] = episode

    standalone_resource_ids.sort(key=lambda resource_id: next(
        (item.filename or "" for item in resources if item.id == resource_id),
        "",
    ))
    season_groups.sort(key=lambda item: item["season"])

    metadata_state = movie.get_metadata_ui_state()
    playback_sources = _build_playback_source_groups(resources, resource_item_map, resource_history_map)
    primary_resource_ids = {item["primary_resource_id"] for item in playback_sources}
    alternate_resource_ids = {
        resource_id
        for item in playback_sources
        for resource_id in item["alternate_resource_ids"]
    }

    standalone_primary_resource_ids = [
        resource_id for resource_id in standalone_resource_ids
        if resource_id in primary_resource_ids
    ]
    standalone_alternate_resource_count = sum(
        1 for resource_id in standalone_resource_ids
        if resource_id in alternate_resource_ids
    )

    for season_entry in season_groups:
        season_resource_ids = season_entry["resource_ids"]
        season_entry["primary_resource_ids"] = [
            resource_id for resource_id in season_resource_ids
            if resource_id in primary_resource_ids
        ]
        season_entry["playback_source_count"] = len(season_entry["primary_resource_ids"])
        season_entry["alternate_resource_count"] = sum(
            1 for resource_id in season_resource_ids
            if resource_id in alternate_resource_ids
        )

    return {
        "items": resource_items,
        "groups": {
            "standalone": {
                "resource_ids": standalone_resource_ids,
                "primary_resource_ids": standalone_primary_resource_ids,
                "count": len(standalone_resource_ids),
                "playback_source_count": len(standalone_primary_resource_ids),
                "alternate_resource_count": standalone_alternate_resource_count,
                "user_data": standalone_user_history,
            },
            "seasons": season_groups,
            "playback_sources": playback_sources,
        },
        "summary": {
            "total_items": len(resources),
            "playback_source_count": len(playback_sources),
            "duplicate_group_count": sum(1 for item in playback_sources if item["is_duplicate_group"]),
            "alternate_resource_count": len(alternate_resource_ids),
            "season_count": len(season_groups),
            "standalone_count": len(standalone_resource_ids),
            "edited_items_count": edited_items,
            "season_metadata_count": sum(1 for season in season_groups if season.get("has_metadata")),
            "metadata_source_group": metadata_state["source_group"],
            "has_placeholder_metadata": metadata_state["is_placeholder"],
            "is_local_only_metadata": metadata_state["is_local_only"],
            "needs_attention": metadata_state["needs_attention"],
            "review_priority": metadata_state["review_priority"],
        },
    }


def _build_metadata_preview_from_resolution(resolution, entity_context):
    meta_data = resolution.meta_data or {}
    scraper_source = meta_data.get('scraper_source')
    ui_state = Movie.build_metadata_ui_state(scraper_source)

    return {
        "scraper_source": scraper_source,
        "metadata_state": ui_state,
        "title": meta_data.get('title'),
        "original_title": meta_data.get('original_title'),
        "year": meta_data.get('year'),
        "country": meta_data.get('country'),
        "director": meta_data.get('director'),
        "category": normalize_genres(meta_data.get('category') or []),
        "actors": meta_data.get('actors') or [],
        "overview": meta_data.get('description'),
        "poster_url": meta_data.get('cover'),
        "backdrop_url": meta_data.get('background_cover'),
        "parse": {
            "title": entity_context.title,
            "year": entity_context.year,
            "media_type_hint": entity_context.media_type_hint,
            "parse_layer": entity_context.parse_layer,
            "parse_strategy": entity_context.parse_strategy,
            "confidence": entity_context.confidence,
            "nfo_candidates": entity_context.nfo_candidates,
            "resource_count": len(entity_context.files),
            "sample_path": entity_context.sample_path,
        },
        "resolve": _build_metadata_resolution_info(resolution),
        "explanation": _build_metadata_resolution_feedback(resolution, entity_context),
    }


def _normalize_metadata_diff_value(field, value):
    if field in ('category', 'actors'):
        return value or []
    if field in ('title', 'original_title', 'description', 'cover', 'background_cover', 'director', 'country', 'scraper_source'):
        return value or None
    return value


def _get_movie_metadata_field_value(movie, field):
    value = getattr(movie, field)
    return _normalize_metadata_diff_value(field, value)


def _build_movie_metadata_diff(movie, meta_data, unlocked_fields=None):
    unlocked = set(unlocked_fields or [])
    locked = set(movie.get_locked_fields())
    field_diffs = []

    for field in TMDB_REFRESHABLE_FIELDS:
        current_value = _get_movie_metadata_field_value(movie, field)
        preview_value = _normalize_metadata_diff_value(field, meta_data.get(field))
        changed = current_value != preview_value
        is_locked = field in locked and field not in unlocked

        field_diffs.append({
            "field": field,
            "current_value": current_value,
            "preview_value": preview_value,
            "changed": changed,
            "locked": is_locked,
            "will_apply": changed and not is_locked,
        })

    return {
        "locked_fields": sorted(locked),
        "unlocked_fields": sorted(unlocked),
        "fields": field_diffs,
        "summary": {
            "changed_count": sum(1 for item in field_diffs if item["changed"]),
            "will_apply_count": sum(1 for item in field_diffs if item["will_apply"]),
            "blocked_count": sum(1 for item in field_diffs if item["changed"] and item["locked"]),
            "changed_fields": [item["field"] for item in field_diffs if item["changed"]],
            "will_apply_fields": [item["field"] for item in field_diffs if item["will_apply"]],
            "blocked_fields": [item["field"] for item in field_diffs if item["changed"] and item["locked"]],
        },
    }


def _build_metadata_overview():
    movies = Movie.query.all()
    total_movies = len(movies)

    source_group_counter = {}
    review_priority_counter = {}
    action_counter = {}
    needs_attention_count = 0
    placeholder_count = 0
    local_only_count = 0
    external_match_count = 0

    low_confidence_resource_count = 0
    fallback_resource_count = 0
    locked_movie_count = 0
    nfo_candidate_movie_count = 0
    issue_counter = {}

    for movie in movies:
        state = movie.get_metadata_ui_state()
        diagnostics = movie.get_metadata_diagnostics()
        actions = movie.get_metadata_actions()
        issues = movie.get_metadata_issues(state=state, diagnostics=diagnostics)

        source_group = state["source_group"]
        review_priority = state["review_priority"]
        primary_action = actions["primary_action"]

        source_group_counter[source_group] = source_group_counter.get(source_group, 0) + 1
        review_priority_counter[review_priority] = review_priority_counter.get(review_priority, 0) + 1
        action_counter[primary_action] = action_counter.get(primary_action, 0) + 1

        if state["needs_attention"]:
            needs_attention_count += 1
        if state["is_placeholder"]:
            placeholder_count += 1
        if state["is_local_only"]:
            local_only_count += 1
        if state["is_external_match"]:
            external_match_count += 1

        if diagnostics["low_confidence_resource_count"] > 0:
            low_confidence_resource_count += diagnostics["low_confidence_resource_count"]
        if diagnostics["fallback_resource_count"] > 0:
            fallback_resource_count += diagnostics["fallback_resource_count"]
        if diagnostics["has_locked_fields"]:
            locked_movie_count += 1
        if diagnostics["nfo_candidate_resource_count"] > 0:
            nfo_candidate_movie_count += 1

        for issue in issues:
            issue_counter[issue["code"]] = issue_counter.get(issue["code"], 0) + 1

    def _counter_to_items(counter):
        return [
            {"key": key, "count": count}
            for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        ]

    return {
        "totals": {
            "movie_count": total_movies,
            "needs_attention_count": needs_attention_count,
            "placeholder_count": placeholder_count,
            "local_only_count": local_only_count,
            "external_match_count": external_match_count,
            "low_confidence_resource_count": low_confidence_resource_count,
            "fallback_resource_count": fallback_resource_count,
            "locked_movie_count": locked_movie_count,
            "nfo_candidate_movie_count": nfo_candidate_movie_count,
        },
        "source_groups": _counter_to_items(source_group_counter),
        "review_priorities": _counter_to_items(review_priority_counter),
        "recommended_actions": _counter_to_items(action_counter),
        "issues": _counter_to_items(issue_counter),
    }


def _build_metadata_work_items(query, page, page_size):
    pagination = query.paginate(page=page, per_page=page_size, error_out=False)
    return {
        "items": [movie.to_metadata_work_item() for movie in pagination.items],
        "pagination": build_pagination_meta(pagination, page, page_size),
    }


def _build_metadata_batch_result(
    movie,
    resolution=None,
    entity_context=None,
    updated_fields=None,
    season_result=None,
    error=None,
):
    item = movie.to_metadata_work_item()
    status = _build_metadata_apply_status(
        error=error,
        updated_fields=updated_fields,
        season_result=season_result,
    )
    result = {
        "movie_id": movie.id,
        "title": movie.title,
        "scraper_source": movie.scraper_source,
        "status": status,
        "changed": status == "updated",
        "updated_fields": updated_fields or [],
        "season_metadata_result": season_result or {"upserted": 0, "deleted": 0},
        "metadata_state": item["metadata_state"],
        "metadata_actions": item["metadata_actions"],
        "metadata_diagnostics": item["metadata_diagnostics"],
        "metadata_issues": item["metadata_issues"],
    }
    if resolution:
        result["resolution"] = _build_metadata_resolution_info(resolution)
        result["explanation"] = _build_metadata_resolution_feedback(resolution, entity_context)
    if error:
        result["error"] = _classify_metadata_error(error["code"], error["msg"])
    return result


def _build_metadata_missing_batch_result(movie_id):
    error = _classify_metadata_error(40401, "Movie not found")
    return {
        "movie_id": movie_id,
        "status": "failed",
        "changed": False,
        "updated_fields": [],
        "season_metadata_result": {"upserted": 0, "deleted": 0},
        "error": error,
    }


def _apply_resource_metadata_update(resource, normalized_payload):
    season = normalized_payload.get('season', resource.season)
    episode = normalized_payload.get('episode', resource.episode)

    if 'episode' in normalized_payload and episode is not None and season is None:
        raise MetadataValidationError(code=40021, msg="Invalid field value: episode requires season")

    updated_fields = []
    label_cleared = 'label' in normalized_payload and normalized_payload.get('label') is None

    for field, value in normalized_payload.items():
        if getattr(resource, field) == value:
            continue
        setattr(resource, field, value)
        updated_fields.append(field)

    if (({'season', 'episode'} & set(normalized_payload.keys())) and ('label' not in normalized_payload or label_cleared)):
        generated_label = _build_resource_label(resource, season, episode)
        if resource.label != generated_label:
            resource.label = generated_label
            if 'label' not in updated_fields:
                updated_fields.append('label')

    if updated_fields:
        resource.metadata_edited_at = datetime.utcnow()
        if 'metadata_edited_at' not in updated_fields:
            updated_fields.append('metadata_edited_at')

    return updated_fields


def _get_or_create_season_metadata(movie, season):
    season_metadata = movie.season_metadata.filter_by(season=season).first()
    if season_metadata:
        return season_metadata

    season_metadata = MovieSeasonMetadata(movie_id=movie.id, season=season)
    db.session.add(season_metadata)
    return season_metadata


def _apply_season_metadata_update(season_metadata, normalized_payload):
    updated_fields = []

    for field, value in normalized_payload.items():
        if getattr(season_metadata, field) == value:
            continue
        setattr(season_metadata, field, value)
        updated_fields.append(field)

    if updated_fields:
        if season_metadata.is_empty():
            season_metadata.metadata_edited_at = None
        else:
            season_metadata.metadata_edited_at = datetime.utcnow()
            if 'metadata_edited_at' not in updated_fields:
                updated_fields.append('metadata_edited_at')

    return updated_fields


def _get_json_payload():
    """统一读取 JSON 请求体；空 body 时返回空字典。"""
    return request.get_json(silent=True) or {}


def _serialize_review_resource(resource):
    resource_data = resource.to_dict()
    metadata = resource_data.get('metadata') or {}
    analysis = metadata.get('analysis') or {}
    path_cleaning = analysis.get('path_cleaning') or {}
    scraping = analysis.get('scraping') or {}
    movie = resource.movie

    return {
        "resource_id": resource.id,
        "movie_id": movie.id if movie else None,
        "movie_title": movie.title if movie else None,
        "movie_original_title": movie.original_title if movie else None,
        "movie_year": movie.year if movie else None,
        "resource_info": resource_data.get("resource_info"),
        "metadata": {
            "path_cleaning": path_cleaning,
            "scraping": scraping,
            "edit_context": metadata.get("edit_context") or {},
        },
    }


@library_bp.route('/filters', methods=['GET'])
def get_global_filters():
    """获取全局筛选字典 (分类, 年份, 地区)。"""
    include_param = request.args.get('include')
    includes = include_param.split(',') if include_param else [
        'genres',
        'years',
        'countries',
        'metadata_source_groups',
        'metadata_review_priorities',
        'metadata_issue_codes',
    ]

    try:
        data = get_filter_options(includes)
    except Exception as e:
        logger.exception("Load filter options failed includes=%s error=%s", includes, e)
        data = {key: [] for key in includes}

    return api_response(data=data)


@library_bp.route('/metadata/overview', methods=['GET'])
def get_metadata_overview():
    return api_response(data=_build_metadata_overview())


@library_bp.route('/metadata/work-items', methods=['GET'])
def list_metadata_work_items():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    metadata_source_group = request.args.get('metadata_source_group')
    metadata_review_priority = request.args.get('metadata_review_priority')
    metadata_issue_code = request.args.get('metadata_issue_code')
    raw_needs_attention = request.args.get('needs_attention')
    keyword = request.args.get('keyword')

    needs_attention = None
    if raw_needs_attention is not None:
        needs_attention = raw_needs_attention.strip().lower() in ('1', 'true', 'yes')

    query = build_movie_list_query(
        keyword=keyword,
        metadata_source_group=metadata_source_group,
        metadata_review_priority=metadata_review_priority,
        needs_attention=needs_attention,
        metadata_issue_code=metadata_issue_code,
    ).order_by(Movie.updated_at.desc(), Movie.id.asc())

    return api_response(data=_build_metadata_work_items(query, page, page_size))


@library_bp.route('/featured', methods=['GET'])
def get_featured_content():
    """
    v1.11.0: 获取首页轮播/置顶内容 (Hero Banner)
    优先返回包含高清横屏背景图 (backdrop_url) 的资源
    """
    limit = 5
    custom_hero_id = "d208f4f6-9f09-4341-9898-ec388cea4c66"

    featured_movies = get_featured_movies(limit=limit, custom_hero_id=custom_hero_id)
    history_map = get_history_map([movie.id for movie in featured_movies])
    return api_response(data=[
        movie.to_detail_dict(user_history=history_map.get(movie.id))
        for movie in featured_movies
    ])


@library_bp.route('/recommendations', methods=['GET'])
def get_recommendations():
    """v1.10.0: 获取推荐影视。"""
    limit = request.args.get('limit', 12, type=int)
    strategy = normalize_recommendation_strategy(request.args.get('strategy', 'default'))

    recommendation_items = get_recommendation_items(limit=limit, strategy=strategy)
    movies = [item["movie"] for item in recommendation_items]
    history_map = get_history_map([movie.id for movie in movies])
    return api_response(data=[
        attach_recommendation_payload(
            item["movie"].to_simple_dict(user_history=history_map.get(item["movie"].id)),
            item,
            strategy=strategy,
            rank=index,
        )
        for index, item in enumerate(recommendation_items, start=1)
    ])


@library_bp.route('/movies/<uuid:id>/recommendations', methods=['GET'])
def get_movie_context_recommendations(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    limit = request.args.get('limit', 6, type=int)
    preferred_movie_ids = None
    library_id = request.args.get('library_id', type=int)
    if library_id is not None:
        library = db.session.get(Library, library_id)
        if not library:
            return api_error(code=40410, msg="Library not found", http_status=404)
        preferred_movie_ids = build_library_movie_id_context(library)["final_ids"]

    recommendation_items = get_context_recommendation_items(
        movie,
        limit=limit,
        preferred_movie_ids=preferred_movie_ids,
    )
    movies = [item["movie"] for item in recommendation_items]
    history_map = get_history_map([movie.id for movie in movies])
    return api_response(data=[
        attach_recommendation_payload(
            item["movie"].to_simple_dict(user_history=history_map.get(item["movie"].id)),
            item,
            strategy="context",
            rank=index,
        )
        for index, item in enumerate(recommendation_items, start=1)
    ])


# 临时注释：用于排查前端是否仍依赖旧接口 `/api/v1/genres`
#
# @library_bp.route('/genres', methods=['GET'])
# def list_genres():
#     """Deprecated: 建议使用 /filters?include=genres 替代。"""
#     return redirect('/api/v1/filters?include=genres', code=302)


@library_bp.route('/movies', methods=['GET'])
def list_movies():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    source_id = request.args.get('source_id', type=int)
    genre = request.args.get('genre')
    keyword = request.args.get('keyword')
    country = request.args.get('country')
    year_param = request.args.get('year')
    metadata_source_group = request.args.get('metadata_source_group')
    metadata_review_priority = request.args.get('metadata_review_priority')
    metadata_issue_code = request.args.get('metadata_issue_code')
    raw_needs_attention = request.args.get('needs_attention')
    sort_by = request.args.get('sort_by', 'date_added')
    order = request.args.get('order', 'desc')

    needs_attention = None
    if raw_needs_attention is not None:
        needs_attention = raw_needs_attention.strip().lower() in ('1', 'true', 'yes')
    elif not any([metadata_source_group, metadata_review_priority, metadata_issue_code]):
        needs_attention = False

    query = build_movie_list_query(
        source_id=source_id,
        genre=genre,
        keyword=keyword,
        country=country,
        year_param=year_param,
        metadata_source_group=metadata_source_group,
        metadata_review_priority=metadata_review_priority,
        needs_attention=needs_attention,
        metadata_issue_code=metadata_issue_code,
    )

    sort_column = resolve_movie_sort_column(sort_by)
    query = query.order_by(sort_column.asc() if order == 'asc' else sort_column.desc())
    query = query.order_by(Movie.id.asc())

    pagination = query.paginate(page=page, per_page=page_size, error_out=False)
    movies_items = pagination.items
    history_map = get_history_map([movie.id for movie in movies_items])

    data = {
        "items": [
            movie.to_simple_dict(user_history=history_map.get(movie.id))
            for movie in movies_items
        ],
        "pagination": build_pagination_meta(pagination, page, page_size)
    }
    return api_response(data=data)


@library_bp.route('/movies/<uuid:id>', methods=['GET'])
def get_movie_detail(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    user_history = get_movie_user_history(movie.id)
    return api_response(data=movie.to_detail_dict(user_history=user_history))


@library_bp.route('/reviews/resources', methods=['GET'])
def list_review_resources():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    source_id = request.args.get('source_id', type=int)
    provider = request.args.get('provider')
    parse_mode = request.args.get('parse_mode')
    keyword = request.args.get('keyword')

    query = build_review_queue_query(
        source_id=source_id,
        provider=provider,
        parse_mode=parse_mode,
        keyword=keyword,
    ).order_by(MediaResource.created_at.desc(), MediaResource.id.desc())

    pagination = query.paginate(page=page, per_page=page_size, error_out=False)
    data = {
        "items": [_serialize_review_resource(resource) for resource in pagination.items],
        "pagination": build_pagination_meta(pagination, page, page_size),
    }
    return api_response(data=data)


@library_bp.route('/movies/<uuid:id>/resources', methods=['GET'])
def get_movie_resources(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    return api_response(data=_build_movie_resource_groups(movie))


@library_bp.route('/movies/<uuid:id>/seasons', methods=['GET'])
def get_movie_seasons(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    resource_groups = _build_movie_resource_groups(movie)
    return api_response(data={
        "items": resource_groups["groups"]["seasons"],
        "summary": resource_groups["summary"],
    })


@library_bp.route('/movies/<uuid:id>', methods=['PATCH'])
def update_movie_detail(id):
    """手动修改电影元数据。"""
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg="No input data")

    raw_lock_fields = payload.pop('metadata_locked_fields', None)
    raw_unlock_fields = payload.pop('metadata_unlocked_fields', None)

    try:
        normalized_payload = _normalize_movie_patch_payload(payload)
        lock_fields = _normalize_lock_field_names(raw_lock_fields)
        unlock_fields = _normalize_lock_field_names(raw_unlock_fields)
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        if not normalized_payload and not lock_fields and not unlock_fields:
            return api_error(code=40007, msg="No supported fields to update")

        if lock_fields and unlock_fields:
            overlap = sorted(set(lock_fields).intersection(unlock_fields))
            if overlap:
                return api_error(code=40013, msg=f"Conflicting lock directives: {', '.join(overlap)}")

        effective_lock_fields = sorted(set(lock_fields or normalized_payload.keys()))
        updated_fields, unchanged_fields = scanner_adapter.update_movie_metadata(
            movie,
            normalized_payload,
            lock_fields=effective_lock_fields,
            unlock_fields=unlock_fields,
        )

        if not updated_fields and not lock_fields and not unlock_fields:
            logger.info("Movie metadata unchanged movie_id=%s fields=%s", movie.id, ','.join(unchanged_fields))
            return api_response(data=movie.to_detail_dict(), msg="Movie metadata unchanged")

        db.session.commit()
        logger.info(
            "Movie metadata updated movie_id=%s fields=%s locked=%s unlocked=%s",
            movie.id,
            ','.join(updated_fields),
            ','.join(lock_fields or effective_lock_fields),
            ','.join(unlock_fields or []),
        )
        return api_response(data=movie.to_detail_dict(), msg="Movie metadata updated")
    except Exception as e:
        db.session.rollback()
        logger.exception("Update movie metadata failed movie_id=%s error=%s", movie.id, e)
        return api_error(code=50008, msg="Update failed", http_status=500)


@library_bp.route('/movies/<uuid:id>/metadata/refresh', methods=['POST'])
def refresh_movie_metadata(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    payload = _get_json_payload()

    try:
        raw_tmdb_id = payload.get('tmdb_id') if isinstance(payload, dict) else None
        tmdb_id = _normalize_tmdb_id(raw_tmdb_id) or movie.tmdb_id
        unlock_fields = _normalize_lock_field_names(payload.get('metadata_unlocked_fields')) if isinstance(payload, dict) else None
        media_type_hint = _normalize_media_type_hint(payload.get('media_type_hint')) if isinstance(payload, dict) else None
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    if not tmdb_id:
        return api_error(code=40016, msg="No tmdb_id available for refresh")

    if tmdb_id.startswith('loc-'):
        search_title = movie.original_title or movie.title
        matched_tmdb_id = scraper.search_movie(search_title, movie.year, media_type_hint=media_type_hint)
        if not matched_tmdb_id:
            return api_error(code=40402, msg="TMDB match not found", http_status=404)
        tmdb_id = matched_tmdb_id

    meta_data = scraper.get_movie_details(tmdb_id)
    if not meta_data:
        return api_error(code=50201, msg="TMDB refresh failed", http_status=502)

    try:
        movie.tmdb_id = meta_data.get('tmdb_id') or tmdb_id
        updated_fields, _ = scanner_adapter.update_movie_metadata(
            movie,
            _build_external_metadata_update_payload(meta_data),
            unlock_fields=unlock_fields,
            respect_locked=True,
        )
        _sync_movie_season_metadata(movie, meta_data)
        db.session.commit()
        logger.info(
            "Movie metadata refreshed movie_id=%s tmdb_id=%s fields=%s unlocked=%s",
            movie.id,
            movie.tmdb_id,
            ','.join(updated_fields),
            ','.join(unlock_fields or []),
        )
        return api_response(data=movie.to_detail_dict(), msg="Movie metadata refreshed")
    except Exception as e:
        db.session.rollback()
        logger.exception("Refresh movie metadata failed movie_id=%s tmdb_id=%s error=%s", movie.id, tmdb_id, e)
        return api_error(code=50009, msg="Refresh failed", http_status=500)


@library_bp.route('/movies/<uuid:id>/metadata/re-scrape', methods=['POST'])
def re_scrape_movie_metadata(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    payload = _get_json_payload()
    try:
        unlock_fields = _normalize_lock_field_names(payload.get('metadata_unlocked_fields')) if isinstance(payload, dict) else None
        media_type_hint = _normalize_media_type_hint(payload.get('media_type_hint')) if isinstance(payload, dict) else None
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        result = movie_metadata_rescrape_service.resolve_movie(movie, media_type_hint=media_type_hint)
        resolution = result["resolution"]
        meta_data = dict(resolution.meta_data)

        if resolution.resolved_tmdb_id:
            movie.tmdb_id = meta_data.get('tmdb_id') or resolution.resolved_tmdb_id
        elif meta_data.get('tmdb_id'):
            movie.tmdb_id = meta_data.get('tmdb_id')

        updated_fields, _ = scanner_adapter.update_movie_metadata(
            movie,
            _build_external_metadata_update_payload(meta_data),
            unlock_fields=unlock_fields,
            respect_locked=True,
        )
        season_result = _sync_movie_season_metadata(movie, meta_data)
        movie_metadata_rescrape_service.apply_resource_traces(
            result["resources"],
            result["entity_context"],
            resolution,
        )
        db.session.commit()
        logger.info(
            "Movie metadata re-scraped movie_id=%s tmdb_id=%s scrape_layer=%s scrape_strategy=%s resources=%s",
            movie.id,
            movie.tmdb_id,
            resolution.scrape_layer,
            resolution.scrape_strategy,
            result["resource_count"],
        )
        status = _build_metadata_apply_status(updated_fields=updated_fields, season_result=season_result)
        return api_response(data={
            "status": status,
            "changed": status == "updated",
            "movie": movie.to_detail_dict(),
            "resolution": _build_metadata_resolution_info(resolution),
            "entity_context": _build_metadata_entity_context_info(
                result["entity_context"],
                resource_count=result["resource_count"],
            ),
            "explanation": _build_metadata_resolution_feedback(resolution, result["entity_context"]),
            "updated_fields": updated_fields,
            "season_metadata_result": season_result,
            "resource_trace_count": result["resource_count"],
        }, msg="Movie metadata re-scraped")
    except ValueError as e:
        return api_error(code=40026, msg=str(e))
    except Exception as e:
        db.session.rollback()
        logger.exception("Re-scrape movie metadata failed movie_id=%s error=%s", movie.id, e)
        return api_error(code=50014, msg="Re-scrape failed", http_status=500)


@library_bp.route('/metadata/re-scrape', methods=['POST'])
def batch_re_scrape_movie_metadata():
    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg="No input data")

    items = payload.get('items') if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return api_error(code=40022, msg="Invalid field value: items should be a non-empty array")

    results = []
    updated_movie_ids = []

    try:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                return api_error(code=40023, msg=f"Invalid item at index {index}: object expected")

            raw_movie_id = item.get('id') or item.get('movie_id')
            if not isinstance(raw_movie_id, str) or not raw_movie_id.strip():
                return api_error(code=40024, msg=f"Invalid item at index {index}: movie id required")

            movie = db.session.get(Movie, raw_movie_id.strip())
            if not movie:
                results.append(_build_metadata_missing_batch_result(raw_movie_id.strip()))
                continue

            try:
                unlock_fields = _normalize_lock_field_names(item.get('metadata_unlocked_fields')) if isinstance(item, dict) else None
                media_type_hint = _normalize_media_type_hint(item.get('media_type_hint')) if isinstance(item, dict) else None
                with db.session.begin_nested():
                    result = movie_metadata_rescrape_service.resolve_movie(movie, media_type_hint=media_type_hint)
                    resolution = result["resolution"]
                    meta_data = dict(resolution.meta_data)

                    if resolution.resolved_tmdb_id:
                        movie.tmdb_id = meta_data.get('tmdb_id') or resolution.resolved_tmdb_id
                    elif meta_data.get('tmdb_id'):
                        movie.tmdb_id = meta_data.get('tmdb_id')

                    updated_fields, _ = scanner_adapter.update_movie_metadata(
                        movie,
                        _build_external_metadata_update_payload(meta_data),
                        unlock_fields=unlock_fields,
                        respect_locked=True,
                    )
                    season_result = _sync_movie_season_metadata(movie, meta_data)
                    movie_metadata_rescrape_service.apply_resource_traces(
                        result["resources"],
                        result["entity_context"],
                        resolution,
                    )

                status = _build_metadata_apply_status(
                    updated_fields=updated_fields,
                    season_result=season_result,
                )
                if status == "updated":
                    updated_movie_ids.append(movie.id)
                results.append(_build_metadata_batch_result(
                    movie,
                    resolution=resolution,
                    entity_context=result["entity_context"],
                    updated_fields=updated_fields,
                    season_result=season_result,
                ))
            except MetadataValidationError as e:
                results.append(_build_metadata_batch_result(movie, error={"code": e.code, "msg": e.msg}))
            except ValueError as e:
                results.append(_build_metadata_batch_result(movie, error={"code": 40026, "msg": str(e)}))
            except Exception as e:
                logger.exception("Batch re-scrape failed movie_id=%s error=%s", movie.id, e)
                results.append(_build_metadata_batch_result(movie, error={"code": 50014, "msg": "Re-scrape failed"}))

        db.session.commit()
        status_counts = {}
        for item in results:
            status = item.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        failed_items = [item for item in results if item.get("status") == "failed"]
        return api_response(data={
            "items": results,
            "summary": {
                "total": len(results),
                "succeeded": len(results) - len(failed_items),
                "updated": len(updated_movie_ids),
                "unchanged": status_counts.get("unchanged", 0),
                "failed": len(failed_items),
                "status_counts": status_counts,
                "updated_movie_ids": updated_movie_ids,
                "failed_movie_ids": [item["movie_id"] for item in failed_items if item.get("movie_id")],
            }
        }, msg="Metadata batch re-scrape completed")
    except Exception as e:
        db.session.rollback()
        logger.exception("Batch re-scrape transaction failed error=%s", e)
        return api_error(code=50016, msg="Batch re-scrape failed", http_status=500)


@library_bp.route('/movies/<uuid:id>/metadata/preview', methods=['POST'])
def preview_movie_metadata_pipeline(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    payload = _get_json_payload()
    try:
        media_type_hint = _normalize_media_type_hint(payload.get('media_type_hint')) if isinstance(payload, dict) else None
        unlock_fields = _normalize_lock_field_names(payload.get('metadata_unlocked_fields')) if isinstance(payload, dict) else None
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        result = movie_metadata_rescrape_service.resolve_movie(movie, media_type_hint=media_type_hint)
        resolution = result["resolution"]
        preview = _build_metadata_preview_from_resolution(resolution, result["entity_context"])
        diff = _build_movie_metadata_diff(movie, resolution.meta_data or {}, unlocked_fields=unlock_fields)
        return api_response(data={
            "movie_id": movie.id,
            "current": {
                "scraper_source": movie.scraper_source,
                "metadata_state": movie.get_metadata_ui_state(),
                "title": movie.title,
                "original_title": movie.original_title,
                "year": movie.year,
                "country": movie.country,
                "director": movie.director,
                "category": normalize_genres(movie.category or []),
                "actors": movie.actors or [],
                "overview": movie.description,
                "poster_url": movie.cover,
                "backdrop_url": movie.background_cover,
            },
            "preview": preview,
            "diff": diff,
            "explanation": _build_metadata_resolution_feedback(resolution, result["entity_context"]),
        })
    except ValueError as e:
        return api_error(code=40026, msg=str(e))
    except Exception as e:
        logger.exception("Preview movie metadata pipeline failed movie_id=%s error=%s", movie.id, e)
        return api_error(code=50015, msg="Preview failed", http_status=500)


@library_bp.route('/movies/<uuid:id>/metadata/search', methods=['GET'])
def search_movie_metadata_candidates(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    try:
        query = _normalize_tmdb_search_query(request.args.get('query')) or movie.original_title or movie.title
        year = request.args.get('year', type=int)
        if year is None:
            year = movie.year
        limit = request.args.get('limit', 8, type=int)
        media_type_hint = _normalize_media_type_hint(request.args.get('media_type_hint'))
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        candidates = scraper.search_movie_candidates(query, year=year, limit=limit)
        if media_type_hint:
            candidates = [item for item in candidates if item.get('media_type') == media_type_hint]
        candidates = _annotate_metadata_candidates(
            candidates,
            query=query,
            year=year,
            media_type_hint=media_type_hint,
        )
        return api_response(data={
            "query": query,
            "year": year,
            "media_type_hint": media_type_hint,
            "items": candidates,
        })
    except Exception as e:
        logger.exception("Search movie metadata candidates failed movie_id=%s query=%r error=%s", movie.id, query, e)
        return api_error(code=50202, msg="TMDB search failed", http_status=502)


@library_bp.route('/resources/<uuid:id>/metadata', methods=['PATCH'])
def update_resource_metadata(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg="No input data")

    try:
        normalized_payload = _normalize_resource_payload(payload)
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        updated_fields = _apply_resource_metadata_update(resource, normalized_payload)
        if not updated_fields:
            return api_response(data=resource.to_dict(), msg="Resource metadata unchanged")

        db.session.commit()
        logger.info("Resource metadata updated resource_id=%s fields=%s", resource.id, ','.join(updated_fields))
        return api_response(data=resource.to_dict(), msg="Resource metadata updated")
    except Exception as e:
        db.session.rollback()
        logger.exception("Update resource metadata failed resource_id=%s error=%s", resource.id, e)
        return api_error(code=50011, msg="Update failed", http_status=500)
    except MetadataValidationError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.msg)


@library_bp.route('/movies/<uuid:id>/resources/metadata', methods=['PATCH'])
def update_movie_resources_metadata(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg="No input data")

    updates = payload.get('items') if isinstance(payload, dict) else None
    if not isinstance(updates, list) or not updates:
        return api_error(code=40022, msg="Invalid field value: items should be a non-empty array")

    try:
        resource_map = {resource.id: resource for resource in movie.resources.all()}
        prepared_updates = []
        updated_resources = []

        for index, item in enumerate(updates):
            if not isinstance(item, dict):
                return api_error(code=40023, msg=f"Invalid item at index {index}: object expected")

            resource_id = item.get('id') or item.get('resource_id')
            if not isinstance(resource_id, str) or not resource_id.strip():
                return api_error(code=40024, msg=f"Invalid item at index {index}: resource id required")

            resource_id = resource_id.strip()
            resource = resource_map.get(resource_id)
            if not resource:
                return api_error(code=40403, msg=f"Resource not found in movie: {resource_id}", http_status=404)

            item_payload = {key: value for key, value in item.items() if key not in ('id', 'resource_id')}
            normalized_payload = _normalize_resource_payload(item_payload)
            prepared_updates.append((resource, normalized_payload))

        for resource, normalized_payload in prepared_updates:
            changed_fields = _apply_resource_metadata_update(resource, normalized_payload)
            if changed_fields:
                updated_resources.append({
                    "id": resource.id,
                    "updated_fields": changed_fields,
                })

        if not updated_resources:
            return api_response(data=_build_movie_resource_groups(movie), msg="Resource metadata unchanged")

        db.session.commit()
        logger.info(
            "Movie resources metadata updated movie_id=%s resources=%s",
            movie.id,
            ','.join(item["id"] for item in updated_resources),
        )
        return api_response(data={
            "updated_resources": updated_resources,
            "resources": _build_movie_resource_groups(movie),
        }, msg="Movie resources metadata updated")
    except MetadataValidationError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.msg)
    except Exception as e:
        db.session.rollback()
        logger.exception("Update movie resources metadata failed movie_id=%s error=%s", movie.id, e)
        return api_error(code=50012, msg="Batch update failed", http_status=500)


@library_bp.route('/movies/<uuid:id>/seasons/<int:season>/metadata', methods=['PATCH'])
def update_movie_season_metadata(id, season):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    if season <= 0:
        return api_error(code=40020, msg="Invalid field value: season should be positive")

    has_resources = movie.resources.filter_by(season=season).count() > 0
    if not has_resources:
        return api_error(code=40404, msg="Season not found in movie", http_status=404)

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg="No input data")

    try:
        normalized_payload = _normalize_season_payload(payload)
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        season_metadata = _get_or_create_season_metadata(movie, season)
        updated_fields = _apply_season_metadata_update(season_metadata, normalized_payload)
        if not updated_fields:
            return api_response(data=season_metadata.to_dict(), msg="Season metadata unchanged")

        response_payload = season_metadata.to_dict()
        if season_metadata.is_empty():
            db.session.delete(season_metadata)

        db.session.commit()
        logger.info(
            "Season metadata updated movie_id=%s season=%s fields=%s",
            movie.id,
            season,
            ','.join(updated_fields),
        )
        return api_response(data=response_payload, msg="Season metadata updated")
    except Exception as e:
        db.session.rollback()
        logger.exception("Update season metadata failed movie_id=%s season=%s error=%s", movie.id, season, e)
        return api_error(code=50013, msg="Season update failed", http_status=500)


@library_bp.route('/movies/<uuid:id>/metadata/match', methods=['POST'])
def match_movie_metadata(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    payload = _get_json_payload()

    try:
        tmdb_id = _normalize_tmdb_id(payload.get('tmdb_id') if isinstance(payload, dict) else None)
        unlock_fields = _normalize_lock_field_names(payload.get('metadata_unlocked_fields')) if isinstance(payload, dict) else None
        media_type_hint = _normalize_media_type_hint(payload.get('media_type_hint')) if isinstance(payload, dict) else None
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    if tmdb_id.startswith('imdb/') or tmdb_id.startswith('tvdb/'):
        resolved_tmdb_id = scraper.find_by_external_id(tmdb_id, media_type_hint=media_type_hint)
        if not resolved_tmdb_id:
            return api_error(code=40402, msg="TMDB match not found", http_status=404)
        tmdb_id = resolved_tmdb_id

    meta_data = scraper.get_movie_details(tmdb_id)
    if not meta_data:
        return api_error(code=50201, msg="TMDB refresh failed", http_status=502)

    try:
        movie.tmdb_id = meta_data.get('tmdb_id') or tmdb_id
        updated_fields, _ = scanner_adapter.update_movie_metadata(
            movie,
            _build_external_metadata_update_payload(meta_data),
            unlock_fields=unlock_fields,
            respect_locked=True,
        )
        _sync_movie_season_metadata(movie, meta_data)
        db.session.commit()
        logger.info(
            "Movie metadata matched movie_id=%s tmdb_id=%s fields=%s unlocked=%s",
            movie.id,
            movie.tmdb_id,
            ','.join(updated_fields),
            ','.join(unlock_fields or []),
        )
        return api_response(data=movie.to_detail_dict(), msg="Movie metadata matched")
    except Exception as e:
        db.session.rollback()
        logger.exception("Match movie metadata failed movie_id=%s tmdb_id=%s error=%s", movie.id, tmdb_id, e)
        return api_error(code=50010, msg="Match failed", http_status=500)
