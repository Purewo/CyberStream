import hashlib
import logging
import posixpath
import re
from datetime import datetime
from uuid import uuid4

from flask import Blueprint, current_app, redirect, request, send_file

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
from backend.app.models import Library, LibraryMovieMembership, MediaResource, Movie, MovieSeasonMetadata
from backend.app.services.image_assets import (
    IMAGE_KINDS,
    MovieImageAssetError,
    clear_movie_image_asset_cache,
    get_movie_image_cache_statuses,
    movie_image_original_url,
    preload_movie_image_asset,
    refresh_movie_image_asset_for_cdn,
    resolve_movie_image_asset,
)
from backend.app.services.jobs import job_manager
from backend.app.services.episode_diagnostics import (
    EPISODE_DIAGNOSTIC_ISSUES,
    build_episode_diagnostics_summary,
    build_season_episode_diagnostics,
)
from backend.app.services.media_path_cleaner import MediaPathCleaner
from backend.app.services.metadata_policy import ScraperPolicyError, normalize_scraper_policy_payload
from backend.app.services.metadata_scraper import ScrapeContext, metadata_scraper
from backend.app.services.review_taxonomy import build_review_taxonomy
from backend.app.services.resource_governance import (
    ResourceGovernanceValidationError,
    build_resource_governance_restore_plan,
    build_resource_governance_plan,
    build_resource_governance_items,
    build_resource_governance_summary,
    execute_resource_governance_actions,
    execute_resource_governance_live_check,
    execute_resource_governance_restore_actions,
    normalize_resource_governance_apply_payload,
    normalize_resource_governance_live_check_payload,
    normalize_resource_governance_restore_payload,
)
from backend.app.services.user_access import clear_user_access_cache
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

METADATA_BULK_REIDENTIFY_ISSUES = {
    "fallback_pipeline_match",
    "poster_missing",
    "low_confidence_resources",
}

EPISODE_REVIEW_ISSUE_CODES = set(EPISODE_DIAGNOSTIC_ISSUES) | {"season_metadata_missing"}

METADATA_QUALITY_ACTIONS = [
    {
        "id": "bulk_reidentify",
        "label": "批量重识别 dry-run",
        "description": "先预览 fallback、缺海报和低置信资源的重识别结果，用户确认后再提交批量 re-scrape。",
        "issue_codes": sorted(METADATA_BULK_REIDENTIFY_ISSUES),
        "method": "POST",
        "endpoint": "/api/v1/metadata/re-scrape/plan",
    },
    {
        "id": "episode_review_queue",
        "label": "剧集复核队列",
        "description": "聚合缺集、重复集号、资源缺集号和季元数据缺失，供前端逐项确认修复。",
        "issue_codes": sorted(set(EPISODE_DIAGNOSTIC_ISSUES) | {"season_metadata_missing"}),
        "method": "GET",
        "endpoint": "/api/v1/metadata/episode-review-items",
    },
]

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

MANUAL_MEDIA_TYPES = {'movie', 'tv'}
MANUAL_MEDIA_TYPE_ALIASES = {
    'movie': 'movie',
    'film': 'movie',
    '电影': 'movie',
    'tv': 'tv',
    'series': 'tv',
    'show': 'tv',
    'episode': 'tv',
    'episodes': 'tv',
    '电视剧': 'tv',
    '剧集': 'tv',
    '课程': 'tv',
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
    return _normalize_metadata_candidate_id(raw_tmdb_id, field_name='tmdb_id')


def _normalize_metadata_candidate_id(raw_candidate_id, field_name='candidate_id'):
    if raw_candidate_id is None:
        return None
    if not isinstance(raw_candidate_id, str):
        raise MetadataValidationError(code=40014, msg=f"Invalid field type: {field_name} should be string")

    candidate_id = raw_candidate_id.strip()
    if not candidate_id:
        raise MetadataValidationError(code=40015, msg=f"Invalid field value: {field_name} cannot be empty")

    return candidate_id


def _normalize_metadata_provider(raw_provider):
    if raw_provider is None:
        return None
    if not isinstance(raw_provider, str):
        raise MetadataValidationError(code=40027, msg="Invalid field type: provider should be string")

    raw_provider = raw_provider.strip()
    if not raw_provider:
        return None

    provider = metadata_scraper._normalize_provider_name(raw_provider)
    if not provider:
        raise MetadataValidationError(code=40028, msg=f"Unsupported metadata provider: {raw_provider}")
    return provider


def _extract_metadata_candidate_payload(payload, required=False):
    if not isinstance(payload, dict):
        if required:
            raise MetadataValidationError(code=40015, msg="Invalid field value: candidate_id is required")
        return None, None

    provider = _normalize_metadata_provider(payload.get('provider') or payload.get('source_key'))
    for field_name in ('candidate_id', 'external_id', 'tmdb_id'):
        if field_name in payload and payload.get(field_name) is not None:
            return _normalize_metadata_candidate_id(payload.get(field_name), field_name=field_name), provider

    if required:
        raise MetadataValidationError(code=40015, msg="Invalid field value: candidate_id is required")
    return None, provider


def _normalize_boolean_payload_field(payload, field_name, default=False):
    if not isinstance(payload, dict) or field_name not in payload:
        return default

    value = payload.get(field_name)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'n', 'off'}:
            return False

    raise MetadataValidationError(code=40029, msg=f"Invalid field type: {field_name} should be boolean")


EXTERNAL_METADATA_FIELD_ALIASES = {
    "description": ("description", "overview"),
    "cover": ("cover", "poster_url", "poster"),
    "background_cover": ("background_cover", "backdrop_url", "backdrop"),
}


def _external_metadata_field_names(field):
    return EXTERNAL_METADATA_FIELD_ALIASES.get(field, (field,))


def _external_metadata_has_field(source, field):
    if not isinstance(source, dict):
        return False
    return any(name in source for name in _external_metadata_field_names(field))


def _external_metadata_field_value(source, field):
    if not isinstance(source, dict):
        return None
    for name in _external_metadata_field_names(field):
        if name in source:
            return source.get(name)
    return None


def _build_external_metadata_update_payload(meta_data):
    payload = {}
    source = meta_data if isinstance(meta_data, dict) else {}

    for field in TMDB_REFRESHABLE_FIELDS:
        value = _external_metadata_field_value(source, field)

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


def _normalize_catalog_visibility_payload(payload):
    if not isinstance(payload, dict) or not payload:
        raise MetadataValidationError(code=40000, msg="No input data")

    raw_status = payload.get('status')
    if raw_status is None:
        raw_status = payload.get('catalog_visibility_status')
    if raw_status is None:
        raw_status = payload.get('visibility')
    if raw_status is None:
        raise MetadataValidationError(code=40029, msg="Missing required field: status")

    status = Movie.normalize_catalog_visibility_status(raw_status)
    if not status:
        raise MetadataValidationError(code=40030, msg="Invalid field value: status should be auto, published, or hidden")

    raw_note = payload.get('note')
    if raw_note is not None and not isinstance(raw_note, str):
        raise MetadataValidationError(code=40031, msg="Invalid field type: note should be string")

    note = raw_note.strip() if isinstance(raw_note, str) else None
    force = bool(payload.get('force', False))
    return status, note, force


def _normalize_image_kind_list(raw_kinds, default=None):
    if raw_kinds is None:
        return list(default or sorted(IMAGE_KINDS))

    if isinstance(raw_kinds, str):
        raw_items = [item.strip() for item in raw_kinds.split(',')]
    elif isinstance(raw_kinds, list):
        raw_items = raw_kinds
    else:
        raise MetadataValidationError(code=40083, msg="Invalid field type: kinds should be list or comma separated string")

    kinds = []
    for raw_item in raw_items:
        if not isinstance(raw_item, str):
            raise MetadataValidationError(code=40084, msg="Invalid field value: kinds should contain strings")
        kind = raw_item.strip().lower()
        if not kind:
            continue
        if kind not in IMAGE_KINDS:
            raise MetadataValidationError(code=40082, msg="Unsupported movie image kind")
        if kind not in kinds:
            kinds.append(kind)

    if not kinds:
        raise MetadataValidationError(code=40085, msg="Invalid field value: kinds cannot be empty")
    return kinds


def _normalize_request_bool(value, *, default=False, field_name="refresh"):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise MetadataValidationError(code=40090, msg=f"Invalid field type: {field_name} should be boolean")


def _normalize_image_selection_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    kinds = _normalize_image_kind_list(payload.get("kinds"), default=sorted(IMAGE_KINDS))

    raw_limit = payload.get("limit", 20)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise MetadataValidationError(code=40086, msg="Invalid field type: limit should be int")
    limit = max(1, min(limit, 100))

    raw_movie_ids = payload.get("movie_ids")
    movie_ids = None
    if raw_movie_ids is not None:
        if not isinstance(raw_movie_ids, list):
            raise MetadataValidationError(code=40087, msg="Invalid field type: movie_ids should be list")
        movie_ids = []
        seen = set()
        for raw_movie_id in raw_movie_ids:
            if not isinstance(raw_movie_id, str) or not raw_movie_id.strip():
                raise MetadataValidationError(code=40088, msg="Invalid field value: movie_ids should contain non-empty strings")
            movie_id = raw_movie_id.strip()
            if movie_id in seen:
                continue
            seen.add(movie_id)
            movie_ids.append(movie_id)
        if not movie_ids:
            raise MetadataValidationError(code=40089, msg="Invalid field value: movie_ids cannot be empty")

    return {
        "kinds": kinds,
        "limit": limit,
        "movie_ids": movie_ids,
    }


def _normalize_image_preload_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    selection = _normalize_image_selection_payload(payload)
    selection["refresh"] = _normalize_request_bool(payload.get("refresh"), default=False)
    return selection


def _normalize_image_refresh_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    selection = _normalize_image_selection_payload(payload)
    selection.update({
        "purge": _normalize_request_bool(payload.get("purge"), default=True, field_name="purge"),
        "clear_cache": _normalize_request_bool(payload.get("clear_cache"), default=False, field_name="clear_cache"),
        "preload": _normalize_request_bool(payload.get("preload"), default=True, field_name="preload"),
        "refresh": _normalize_request_bool(payload.get("refresh"), default=True),
    })
    return selection


def _select_image_movies(movie_ids, limit):
    movies = []
    missing_movie_ids = []
    if movie_ids is not None:
        for movie_id in movie_ids[:limit]:
            movie = db.session.get(Movie, movie_id)
            if movie:
                movies.append(movie)
            else:
                missing_movie_ids.append(movie_id)
    else:
        movies = Movie.query.order_by(Movie.updated_at.desc(), Movie.id.asc()).limit(limit).all()
    return movies, missing_movie_ids


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


def _normalize_manual_media_type(raw_media_type):
    if raw_media_type is None:
        media_type = 'movie'
    elif isinstance(raw_media_type, str):
        media_type = raw_media_type.strip().lower()
    else:
        raise MetadataValidationError(code=40032, msg="Invalid field value: media_type should be movie or tv")
    if not media_type:
        media_type = 'movie'
    media_type = MANUAL_MEDIA_TYPE_ALIASES.get(media_type, media_type)
    if media_type not in MANUAL_MEDIA_TYPES:
        raise MetadataValidationError(code=40032, msg="Invalid field value: media_type should be movie or tv")
    return media_type


def _manual_scraper_source_for_media_type(media_type):
    return Movie.MANUAL_SOURCE_TV if media_type == 'tv' else Movie.MANUAL_SOURCE_MOVIE


def _normalize_library_id_list(raw_library_ids):
    if raw_library_ids is None:
        return []
    if not isinstance(raw_library_ids, list):
        raise MetadataValidationError(code=40033, msg="Invalid field type: library_ids should be list")

    library_ids = []
    seen = set()
    for raw_library_id in raw_library_ids:
        if isinstance(raw_library_id, bool):
            raise MetadataValidationError(code=40034, msg="Invalid field value: library_ids should contain integers")
        if isinstance(raw_library_id, str):
            raw_library_id = raw_library_id.strip()
            if not raw_library_id.isdigit():
                raise MetadataValidationError(code=40034, msg="Invalid field value: library_ids should contain integers")
            raw_library_id = int(raw_library_id)
        if not isinstance(raw_library_id, int):
            raise MetadataValidationError(code=40034, msg="Invalid field value: library_ids should contain integers")
        if raw_library_id in seen:
            continue
        seen.add(raw_library_id)
        library_ids.append(raw_library_id)
    return library_ids


def _normalize_manual_resource_items(payload):
    payload = payload if isinstance(payload, dict) else {}
    raw_items = []

    raw_resource_ids = payload.get('resource_ids')
    if raw_resource_ids is not None:
        if not isinstance(raw_resource_ids, list):
            raise MetadataValidationError(code=40035, msg="Invalid field type: resource_ids should be list")
        for raw_resource_id in raw_resource_ids:
            raw_items.append({"id": raw_resource_id})

    raw_resources = payload.get('resources')
    if raw_resources is not None:
        if not isinstance(raw_resources, list):
            raise MetadataValidationError(code=40036, msg="Invalid field type: resources should be list")
        raw_items.extend(raw_resources)

    if not raw_items:
        return []

    normalized_items = {}
    ordered_ids = []
    for raw_item in raw_items:
        if isinstance(raw_item, str):
            raw_item = {"id": raw_item}
        if not isinstance(raw_item, dict):
            raise MetadataValidationError(code=40037, msg="Invalid field value: resources should contain strings or objects")

        resource_id = raw_item.get('id') or raw_item.get('resource_id')
        resource_id = _normalize_metadata_candidate_id(resource_id, field_name='resource_id')
        if resource_id not in normalized_items:
            normalized_items[resource_id] = {"id": resource_id}
            ordered_ids.append(resource_id)
        item = normalized_items[resource_id]

        for field in ('season', 'episode'):
            if field in raw_item:
                item[field] = _normalize_positive_int_field(field, raw_item.get(field))

        for field in ('title', 'overview', 'label'):
            if field in raw_item:
                item[field] = _normalize_optional_text_field(field, raw_item.get(field))

    return [normalized_items[resource_id] for resource_id in ordered_ids]


def _normalize_manual_content_payload(payload):
    if not isinstance(payload, dict):
        raise MetadataValidationError(code=40001, msg="Invalid input data: JSON object expected")

    allowed = {
        'title', 'name', 'description', 'overview', 'intro', 'media_type', 'type',
        'resource_ids', 'resources', 'library_ids', 'default_season', 'episode_start',
        'catalog_visibility_status', 'status', 'note', 'preserve_episode_metadata',
    }
    unknown = sorted([key for key in payload.keys() if key not in allowed])
    if unknown:
        raise MetadataValidationError(code=40002, msg=f"Unsupported fields: {', '.join(unknown)}")

    title = payload.get('title')
    if title is None:
        title = payload.get('name')
    title = _normalize_text_field('title', title)

    description = payload.get('description')
    if description is None:
        description = payload.get('overview')
    if description is None:
        description = payload.get('intro')
    description = _normalize_optional_text_field('description', description)

    media_type = _normalize_manual_media_type(payload.get('media_type') or payload.get('type'))
    source = _manual_scraper_source_for_media_type(media_type)

    raw_status = payload.get('catalog_visibility_status')
    if raw_status is None:
        raw_status = payload.get('status')
    if raw_status is None:
        raw_status = Movie.CATALOG_VISIBILITY_HIDDEN
    catalog_visibility_status = Movie.normalize_catalog_visibility_status(raw_status)
    if not catalog_visibility_status:
        raise MetadataValidationError(code=40030, msg="Invalid field value: status should be auto, published, or hidden")

    note = _normalize_optional_text_field('note', payload.get('note')) if 'note' in payload else None
    resources = _normalize_manual_resource_items(payload)
    library_ids = _normalize_library_id_list(payload.get('library_ids'))
    default_season = _normalize_positive_int_field('default_season', payload.get('default_season')) if 'default_season' in payload else None
    episode_start = _normalize_positive_int_field('episode_start', payload.get('episode_start')) if 'episode_start' in payload else None
    preserve_episode_metadata = _normalize_request_bool(
        payload.get('preserve_episode_metadata'),
        default=False,
        field_name='preserve_episode_metadata',
    )

    return {
        "title": title,
        "description": description,
        "media_type": media_type,
        "scraper_source": source,
        "catalog_visibility_status": catalog_visibility_status,
        "catalog_visibility_note": note,
        "resources": resources,
        "library_ids": library_ids,
        "default_season": default_season,
        "episode_start": episode_start,
        "preserve_episode_metadata": preserve_episode_metadata,
    }


def _apply_manual_resource_defaults(resource_items, media_type, default_season=None, episode_start=None, preserve_episode_metadata=False):
    applied_items = []
    next_episode = episode_start
    for item in resource_items:
        normalized = dict(item)
        if media_type == 'movie' and not preserve_episode_metadata:
            normalized.setdefault('season', None)
            normalized.setdefault('episode', None)
        elif media_type == 'tv':
            if normalized.get('season') is None and default_season is not None:
                normalized['season'] = default_season
            if normalized.get('episode') is None and next_episode is not None:
                normalized['episode'] = next_episode
                next_episode += 1
        applied_items.append(normalized)
    return applied_items


def _get_existing_movies_map(movie_ids):
    if not movie_ids:
        return {}
    rows = db.session.query(Movie.id, Movie).filter(Movie.id.in_(list(movie_ids))).all()
    return {movie_id: movie for movie_id, movie in rows}


def _get_library_map(library_ids):
    if not library_ids:
        return {}
    rows = db.session.query(Library.id, Library).filter(Library.id.in_(list(library_ids))).all()
    return {library_id: library for library_id, library in rows}


def _attach_resources_to_movie(movie, resource_items, media_type, preserve_episode_metadata=False):
    if not resource_items:
        return {
            "attached_resource_ids": [],
            "updated_resource_ids": [],
            "removed_movie_ids": [],
        }

    resource_ids = [item["id"] for item in resource_items]
    existing_resources = {
        resource.id: resource
        for resource in db.session.query(MediaResource).filter(MediaResource.id.in_(resource_ids)).all()
    }
    missing_resource_ids = [resource_id for resource_id in resource_ids if resource_id not in existing_resources]
    if missing_resource_ids:
        raise MetadataValidationError(code=40413, msg=f"Resource not found: {missing_resource_ids[0]}",)

    updated_resource_ids = []
    source_movie_ids = set()
    for item in resource_items:
        resource = existing_resources[item["id"]]
        source_movie_ids.add(resource.movie_id)
        changed = False

        if resource.movie_id != movie.id:
            resource.movie_id = movie.id
            changed = True

        for field in ('season', 'episode'):
            if field in item:
                next_value = item[field]
            elif media_type == 'movie' and not preserve_episode_metadata:
                next_value = None
            else:
                continue
            if getattr(resource, field) != next_value:
                setattr(resource, field, next_value)
                changed = True

        for field in ('title', 'overview', 'label'):
            if field in item and getattr(resource, field) != item[field]:
                setattr(resource, field, item[field])
                changed = True

        if 'label' not in item and (changed or resource.label is None):
            resource.label = _build_resource_label(resource, resource.season, resource.episode)

        if changed:
            resource.metadata_edited_at = datetime.utcnow()
            updated_resource_ids.append(resource.id)

    db.session.flush()

    removed_movie_ids = []
    for source_movie_id in sorted(source_movie_ids):
        if not source_movie_id or source_movie_id == movie.id:
            continue
        source_movie = db.session.get(Movie, source_movie_id)
        if not source_movie:
            continue
        if source_movie.resources.count() > 0:
            continue
        LibraryMovieMembership.query.filter_by(movie_id=source_movie_id).delete(synchronize_session=False)
        db.session.delete(source_movie)
        removed_movie_ids.append(source_movie_id)

    return {
        "attached_resource_ids": resource_ids,
        "updated_resource_ids": updated_resource_ids,
        "removed_movie_ids": removed_movie_ids,
    }


def _upsert_manual_library_memberships(movie, library_ids):
    if not library_ids:
        return []

    existing_rows = {
        row.library_id: row
        for row in LibraryMovieMembership.query.filter_by(movie_id=movie.id).all()
    }

    saved_rows = []
    for index, library_id in enumerate(library_ids):
        membership = existing_rows.get(library_id)
        if not membership:
            membership = LibraryMovieMembership(library_id=library_id, movie_id=movie.id)
            db.session.add(membership)
        membership.mode = 'include'
        membership.sort_order = index
        saved_rows.append(membership)
    return saved_rows


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
        if media_type == 'bangumi':
            return fallback if fallback in TMDB_SEARCH_SOURCE_HINTS else 'tv'
        if media_type == 'tencent_video':
            return fallback if fallback in TMDB_SEARCH_SOURCE_HINTS else 'tv'

    fallback = (fallback or '').strip().lower()
    if fallback in TMDB_SEARCH_SOURCE_HINTS:
        return fallback
    return None


def _is_external_metadata_id(tmdb_id):
    if isinstance(tmdb_id, str) and tmdb_id.strip().lower().startswith('bangumi/'):
        return True
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
    resource_map = {resource.id: resource for resource in resources}
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
        resource_dict = resource.to_dict(include_subtitle_discovery=True)
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
        primary_resources = [
            resource_map[resource_id]
            for resource_id in season_entry["primary_resource_ids"]
            if resource_id in resource_map
        ]
        season_entry["episode_diagnostics"] = build_season_episode_diagnostics(
            primary_resources,
            expected_episode_count=season_entry.get("tmdb_episode_count"),
        )

    episode_diagnostics_summary = build_episode_diagnostics_summary({
        season_entry["season"]: season_entry.get("episode_diagnostics")
        for season_entry in season_groups
    })

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
            "episode_diagnostics": episode_diagnostics_summary,
            "metadata_source_group": metadata_state["source_group"],
            "has_placeholder_metadata": metadata_state["is_placeholder"],
            "is_local_only_metadata": metadata_state["is_local_only"],
            "needs_attention": metadata_state["needs_attention"],
            "review_priority": metadata_state["review_priority"],
        },
    }


def _compact_resource_summary(resource, resource_item=None):
    resource_item = resource_item or {}
    info = resource_item.get("resource_info") or {}
    file_info = info.get("file") or {}
    display = info.get("display") or {}
    technical = info.get("technical") or {}
    return {
        "id": resource.id,
        "filename": file_info.get("filename") or resource.filename,
        "relative_path": file_info.get("relative_path") or resource.path,
        "size_bytes": file_info.get("size_bytes") if "size_bytes" in file_info else resource.size,
        "season": display.get("season") if "season" in display else resource.season,
        "episode": display.get("episode") if "episode" in display else resource.episode,
        "episode_label": display.get("episode_label") or resource.get_episode_label(),
        "label": display.get("label") if "label" in display else resource.label,
        "quality_rank": technical.get("quality_rank"),
        "video_resolution_label": technical.get("video_resolution_label"),
    }


def _episode_parse_candidate(resource, cleaner):
    parsed = cleaner.parse_path_metadata(resource.path or resource.filename or "")
    suggested_season = parsed.season if parsed.season is not None else resource.season
    suggested_episode = parsed.episode
    confidence = "none"
    if suggested_episode is not None:
        confidence = "high" if parsed.parse_mode == "standard" and not parsed.needs_review else "medium"

    return {
        "season": suggested_season,
        "episode": suggested_episode,
        "title": parsed.title,
        "year": parsed.year,
        "parse_mode": parsed.parse_mode,
        "parse_strategy": parsed.parse_strategy,
        "needs_review": parsed.needs_review,
        "confidence": confidence,
    }


def _build_episode_update_suggestion(resource, candidate, reason):
    return {
        "type": "update_resource_episode",
        "reason": reason,
        "confidence": candidate.get("confidence"),
        "resource_id": resource.id,
        "current": {
            "season": resource.season,
            "episode": resource.episode,
        },
        "suggested": {
            "season": candidate.get("season"),
            "episode": candidate.get("episode"),
        },
        "parse": {
            "title": candidate.get("title"),
            "year": candidate.get("year"),
            "parse_mode": candidate.get("parse_mode"),
            "parse_strategy": candidate.get("parse_strategy"),
            "needs_review": candidate.get("needs_review"),
        },
        "apply_item": {
            "id": resource.id,
            "season": candidate.get("season"),
            "episode": candidate.get("episode"),
        },
    }


def _build_movie_episode_repair_plan(movie):
    resource_groups = _build_movie_resource_groups(movie)
    resources = movie.resources.all()
    resource_map = {resource.id: resource for resource in resources}
    resource_items = {item["id"]: item for item in resource_groups["items"]}
    resource_history_map = get_resource_history_map([resource.id for resource in resources])
    cleaner = MediaPathCleaner()
    suggested_updates = []
    warnings = []
    seasons = []

    apply_endpoint = f"/api/v1/movies/{movie.id}/resources/metadata"

    for season_entry in resource_groups["groups"]["seasons"]:
        diagnostics = season_entry.get("episode_diagnostics") or {}
        issue_codes = set(diagnostics.get("issue_codes") or [])
        season_number = season_entry.get("season")
        suggestions = []
        affected_resource_ids = set(diagnostics.get("unnumbered_resource_ids") or [])

        for duplicate in diagnostics.get("duplicate_episode_resources") or []:
            affected_resource_ids.update(duplicate.get("resource_ids") or [])
        affected_resource_ids.update(season_entry.get("resource_ids") or [])

        missing_numbers = set(diagnostics.get("missing_episode_numbers") or [])
        occupied_numbers = set(diagnostics.get("available_episode_numbers") or [])
        unnumbered_ids = diagnostics.get("unnumbered_resource_ids") or []

        for resource_id in unnumbered_ids:
            resource = resource_map.get(resource_id)
            if not resource:
                continue
            candidate = _episode_parse_candidate(resource, cleaner)
            suggested_episode = candidate.get("episode")
            suggested_season = candidate.get("season")
            if suggested_episode is None:
                suggestions.append({
                    "type": "manual_review",
                    "reason": "episode_number_missing",
                    "resource_id": resource.id,
                    "confidence": "none",
                    "message": "Path parser could not infer an episode number for this resource.",
                    "parse": candidate,
                })
                continue
            if suggested_season != season_number:
                suggestions.append({
                    "type": "manual_review",
                    "reason": "season_candidate_mismatch",
                    "resource_id": resource.id,
                    "confidence": candidate.get("confidence"),
                    "current": {"season": resource.season, "episode": resource.episode},
                    "suggested": {"season": suggested_season, "episode": suggested_episode},
                    "parse": candidate,
                })
                continue

            reason = "fill_missing_episode_number"
            if missing_numbers and suggested_episode in missing_numbers:
                reason = "fill_missing_episode_slot"
            elif suggested_episode in occupied_numbers:
                warnings.append({
                    "code": "parsed_episode_already_occupied",
                    "resource_id": resource.id,
                    "episode": suggested_episode,
                })
                suggestions.append({
                    "type": "manual_review",
                    "reason": "parsed_episode_already_occupied",
                    "resource_id": resource.id,
                    "confidence": candidate.get("confidence"),
                    "current": {"season": resource.season, "episode": resource.episode},
                    "suggested": {"season": suggested_season, "episode": suggested_episode},
                    "parse": candidate,
                    "message": "Path parser inferred an episode number that is already assigned to another primary resource.",
                })
                continue
            elif missing_numbers and suggested_episode not in missing_numbers:
                warnings.append({
                    "code": "parsed_episode_not_missing_slot",
                    "resource_id": resource.id,
                    "episode": suggested_episode,
                    "missing_episode_numbers": sorted(missing_numbers),
                })
                suggestions.append({
                    "type": "manual_review",
                    "reason": "parsed_episode_not_missing_slot",
                    "resource_id": resource.id,
                    "confidence": candidate.get("confidence"),
                    "current": {"season": resource.season, "episode": resource.episode},
                    "suggested": {"season": suggested_season, "episode": suggested_episode},
                    "parse": candidate,
                    "missing_episode_numbers": sorted(missing_numbers),
                    "message": "Path parser inferred an episode number outside the current missing episode list.",
                })
                continue

            suggestion = _build_episode_update_suggestion(resource, candidate, reason)
            suggestions.append(suggestion)
            suggested_updates.append(suggestion)

        for duplicate in diagnostics.get("duplicate_episode_resources") or []:
            duplicate_resources = [
                resource_map[resource_id]
                for resource_id in duplicate.get("resource_ids") or []
                if resource_id in resource_map
            ]
            ordered = sorted(
                duplicate_resources,
                key=lambda resource: _resource_quality_sort_value(
                    resource,
                    resource_items.get(resource.id, {}),
                    resource_history_map.get(resource.id),
                ),
                reverse=True,
            )
            suggestions.append({
                "type": "review_duplicate_episode",
                "reason": "duplicate_episode_numbers",
                "episode": duplicate.get("episode"),
                "confidence": "manual",
                "recommended_primary_resource_id": ordered[0].id if ordered else None,
                "resource_ids": [resource.id for resource in ordered],
                "message": "Multiple primary playback resources share the same season and episode. Keep the best source as primary or edit the incorrect episode number.",
            })

        if "missing_episode_numbers" in issue_codes:
            suggestions.append({
                "type": "locate_missing_episodes",
                "reason": "missing_episode_numbers",
                "confidence": "manual",
                "missing_episode_numbers": diagnostics.get("missing_episode_numbers") or [],
                "message": "No matching resource is currently indexed for these episode numbers.",
            })

        if "episode_count_mismatch" in issue_codes:
            suggestions.append({
                "type": "review_episode_count",
                "reason": "episode_count_mismatch",
                "confidence": "manual",
                "expected_episode_count": diagnostics.get("expected_episode_count"),
                "available_episode_count": diagnostics.get("available_episode_count"),
                "expected_source": diagnostics.get("expected_source"),
                "message": "Season metadata episode count and indexed episode count do not match.",
            })

        if issue_codes or suggestions:
            seasons.append({
                "season": season_number,
                "title": season_entry.get("title"),
                "display_title": season_entry.get("display_title"),
                "diagnostics": diagnostics,
                "affected_resource_ids": sorted(affected_resource_ids),
                "affected_resources": [
                    _compact_resource_summary(resource_map[resource_id], resource_items.get(resource_id))
                    for resource_id in sorted(affected_resource_ids)
                    if resource_id in resource_map
                ],
                "suggestions": suggestions,
            })

    apply_items = [
        suggestion["apply_item"]
        for suggestion in suggested_updates
        if suggestion.get("apply_item")
    ]

    return {
        "movie_id": movie.id,
        "title": movie.title,
        "dry_run": True,
        "apply_method": "PATCH",
        "apply_endpoint": apply_endpoint,
        "apply_payload": {"items": apply_items},
        "summary": resource_groups["summary"].get("episode_diagnostics"),
        "seasons": seasons,
        "suggested_updates": suggested_updates,
        "warnings": warnings,
    }


def _build_episode_review_queue_item(movie, plan=None, snapshot=None):
    snapshot = snapshot or movie.get_metadata_snapshot()
    plan = plan or _build_movie_episode_repair_plan(movie)
    episode_issues = [
        issue
        for issue in snapshot["issues"]
        if issue.get("code") in EPISODE_REVIEW_ISSUE_CODES
    ]
    suggestions = [
        suggestion
        for season in plan.get("seasons") or []
        for suggestion in season.get("suggestions") or []
    ]
    apply_items = (plan.get("apply_payload") or {}).get("items") or []
    manual_suggestions = [
        suggestion
        for suggestion in suggestions
        if suggestion.get("type") != "update_resource_episode"
    ]
    return {
        "movie_id": movie.id,
        "title": movie.title,
        "original_title": movie.original_title,
        "year": movie.year,
        "poster_url": movie.cover,
        "scraper_source": movie.scraper_source,
        "metadata_state": snapshot["state"],
        "metadata_actions": snapshot["actions"],
        "metadata_issues": episode_issues,
        "episode_diagnostics": plan.get("summary"),
        "season_count": len(plan.get("seasons") or []),
        "seasons_needing_attention": (plan.get("summary") or {}).get("seasons_needing_attention") or [],
        "auto_update_count": len(apply_items),
        "manual_suggestion_count": len(manual_suggestions),
        "warning_count": len(plan.get("warnings") or []),
        "diagnostics_endpoint": f"/api/v1/movies/{movie.id}/episode-diagnostics",
        "apply_method": plan.get("apply_method"),
        "apply_endpoint": plan.get("apply_endpoint"),
        "apply_payload": plan.get("apply_payload"),
    }


def _build_episode_review_queue(page=1, page_size=20, issue_code=None):
    issue_code = (issue_code or "").strip()
    if issue_code and issue_code not in EPISODE_REVIEW_ISSUE_CODES:
        return {
            "items": [],
            "pagination": _build_manual_pagination(0, page, page_size),
            "summary": {
                "total_items": 0,
                "issue_code_counts": {},
                "auto_update_count": 0,
                "manual_suggestion_count": 0,
                "warning_count": 0,
            },
        }

    all_items = []
    issue_code_counts = {}
    auto_update_count = 0
    manual_suggestion_count = 0
    warning_count = 0

    for movie in Movie.query.order_by(Movie.updated_at.desc(), Movie.id.asc()).all():
        if movie.is_manual_content():
            continue
        snapshot = movie.get_metadata_snapshot()
        matching_issues = [
            issue
            for issue in snapshot["issues"]
            if issue.get("code") in EPISODE_REVIEW_ISSUE_CODES and (not issue_code or issue.get("code") == issue_code)
        ]
        if not matching_issues:
            continue

        item = _build_episode_review_queue_item(movie, snapshot=snapshot)
        if issue_code:
            item["metadata_issues"] = [
                issue for issue in item["metadata_issues"] if issue.get("code") == issue_code
            ]
        all_items.append(item)
        auto_update_count += item["auto_update_count"]
        manual_suggestion_count += item["manual_suggestion_count"]
        warning_count += item["warning_count"]
        for issue in item["metadata_issues"]:
            code = issue.get("code")
            if code:
                issue_code_counts[code] = issue_code_counts.get(code, 0) + 1

    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": all_items[start:end],
        "pagination": _build_manual_pagination(len(all_items), page, page_size),
        "summary": {
            "total_items": len(all_items),
            "issue_code_counts": issue_code_counts,
            "auto_update_count": auto_update_count,
            "manual_suggestion_count": manual_suggestion_count,
            "warning_count": warning_count,
        },
    }


def _build_raw_metadata_preview_from_resolution(resolution, entity_context):
    meta_data = resolution.meta_data or {}
    scraper_source = meta_data.get('scraper_source')
    ui_state = Movie.build_metadata_ui_state(scraper_source)

    return {
        "tmdb_id": meta_data.get('tmdb_id') or resolution.resolved_tmdb_id,
        "scraper_source": scraper_source,
        "metadata_state": ui_state,
        "title": meta_data.get('title'),
        "original_title": meta_data.get('original_title'),
        "year": meta_data.get('year'),
        "country": meta_data.get('country'),
        "director": meta_data.get('director'),
        "category": normalize_genres(meta_data.get('category') or []),
        "actors": meta_data.get('actors') or [],
        "overview": _external_metadata_field_value(meta_data, 'description'),
        "poster_url": _external_metadata_field_value(meta_data, 'cover'),
        "backdrop_url": _external_metadata_field_value(meta_data, 'background_cover'),
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


METADATA_PREVIEW_FIELD_ALIASES = {
    "description": "overview",
    "cover": "poster_url",
    "background_cover": "backdrop_url",
}


def _build_movie_metadata_preview_from_update(movie, update_payload, target_tmdb_id=None):
    preview = _build_current_movie_metadata_preview(movie)
    preview["tmdb_id"] = target_tmdb_id or preview["tmdb_id"]

    for field in TMDB_REFRESHABLE_FIELDS:
        if field not in update_payload:
            continue
        preview_field = METADATA_PREVIEW_FIELD_ALIASES.get(field, field)
        preview[preview_field] = _normalize_metadata_diff_value(field, update_payload.get(field))

    preview["metadata_state"] = Movie.build_metadata_ui_state(preview.get("scraper_source"))
    return preview


def _build_metadata_preview_from_resolution(resolution, entity_context, movie=None, update_payload=None):
    preview = _build_raw_metadata_preview_from_resolution(resolution, entity_context)
    if movie is not None:
        meta_data = resolution.meta_data or {}
        final_payload = update_payload
        if final_payload is None:
            final_payload = _build_external_metadata_update_payload(meta_data)
        preview = {
            **_build_movie_metadata_preview_from_update(
                movie,
                final_payload,
                target_tmdb_id=meta_data.get('tmdb_id') or resolution.resolved_tmdb_id,
            ),
            "parse": preview["parse"],
            "resolve": preview["resolve"],
            "explanation": preview["explanation"],
        }
    return preview


def _normalize_metadata_diff_value(field, value):
    if field in ('category', 'actors'):
        return value or []
    if field in ('title', 'original_title', 'description', 'cover', 'background_cover', 'director', 'country', 'scraper_source'):
        return value or None
    return value


def _get_movie_metadata_field_value(movie, field):
    value = getattr(movie, field)
    return _normalize_metadata_diff_value(field, value)


def _build_movie_metadata_diff(movie, meta_data, unlocked_fields=None, fields_present=None):
    unlocked = set(unlocked_fields or [])
    locked = set(movie.get_locked_fields())
    source = meta_data if isinstance(meta_data, dict) else {}
    if fields_present is None:
        present_fields = {
            field
            for field in TMDB_REFRESHABLE_FIELDS
            if _external_metadata_has_field(source, field)
        }
    else:
        present_fields = set(fields_present)
    field_diffs = []

    for field in TMDB_REFRESHABLE_FIELDS:
        current_value = _get_movie_metadata_field_value(movie, field)
        if field in present_fields:
            preview_value = _normalize_metadata_diff_value(field, _external_metadata_field_value(source, field))
        else:
            preview_value = current_value
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


def _build_current_movie_metadata_preview(movie):
    return {
        "tmdb_id": movie.tmdb_id,
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
    }


def _build_external_metadata_preview(meta_data, fallback_tmdb_id=None):
    source = meta_data if isinstance(meta_data, dict) else {}
    scraper_source = source.get('scraper_source')
    return {
        "tmdb_id": source.get('tmdb_id') or fallback_tmdb_id,
        "scraper_source": scraper_source,
        "metadata_state": Movie.build_metadata_ui_state(scraper_source),
        "title": source.get('title'),
        "original_title": source.get('original_title'),
        "year": source.get('year'),
        "country": source.get('country'),
        "director": source.get('director'),
        "category": normalize_genres(source.get('category') or []),
        "actors": source.get('actors') or [],
        "overview": _external_metadata_field_value(source, 'description'),
        "poster_url": _external_metadata_field_value(source, 'cover'),
        "backdrop_url": _external_metadata_field_value(source, 'background_cover'),
    }


def _build_metadata_match_preview(movie, meta_data, candidate_id, candidate_provider=None, media_type_hint=None, unlock_fields=None):
    update_payload = _build_external_metadata_update_payload(meta_data)
    target_tmdb_id = (meta_data or {}).get('tmdb_id') or candidate_id
    final_poster_url = update_payload.get('cover') if 'cover' in update_payload else movie.cover
    warnings = []

    if not final_poster_url:
        warnings.append({
            "code": "poster_missing",
            "severity": "warning",
            "message": "Matched metadata has no poster; applying it can hide the item in poster-only clients.",
        })

    apply_payload = {
        "candidate_id": candidate_id,
        "apply": True,
    }
    if candidate_provider:
        apply_payload["provider"] = candidate_provider
    if media_type_hint:
        apply_payload["media_type_hint"] = media_type_hint
    if unlock_fields:
        apply_payload["metadata_unlocked_fields"] = unlock_fields

    return {
        "dry_run": True,
        "movie_id": movie.id,
        "candidate_id": candidate_id,
        "provider": candidate_provider,
        "media_type_hint": media_type_hint,
        "current": _build_current_movie_metadata_preview(movie),
        "preview": _build_movie_metadata_preview_from_update(
            movie,
            update_payload,
            target_tmdb_id=target_tmdb_id,
        ),
        "identity": {
            "current_tmdb_id": movie.tmdb_id,
            "target_tmdb_id": target_tmdb_id,
            "changed": movie.tmdb_id != target_tmdb_id,
        },
        "diff": _build_movie_metadata_diff(movie, update_payload, unlocked_fields=unlock_fields),
        "warnings": warnings,
        "apply_method": "POST",
        "apply_endpoint": f"/api/v1/movies/{movie.id}/metadata/match",
        "apply_payload": apply_payload,
    }


def _metadata_match_would_leave_movie_without_poster(movie, meta_data):
    update_payload = _build_external_metadata_update_payload(meta_data)
    final_poster_url = update_payload.get('cover') if 'cover' in update_payload else movie.cover
    return not final_poster_url


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


def _normalize_string_list(value, default=None, field_name="items"):
    if value is None:
        return list(default) if default is not None else None
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise MetadataValidationError(code=40091, msg=f"Invalid field type: {field_name} should be list or comma separated string")

    items = []
    seen = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, str):
            raise MetadataValidationError(code=40092, msg=f"Invalid field value: {field_name} should contain strings")
        item = raw_item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items


def _normalize_limited_int(value, default, minimum=1, maximum=100, field_name="limit"):
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise MetadataValidationError(code=40093, msg=f"Invalid field type: {field_name} should be int")
    return max(minimum, min(number, maximum))


def _build_manual_pagination(total, page, page_size):
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "current_page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": total_pages,
    }


def _build_metadata_quality_sample(movie, issue=None, snapshot=None):
    snapshot = snapshot or movie.get_metadata_snapshot()
    return {
        "movie_id": movie.id,
        "title": movie.title,
        "original_title": movie.original_title,
        "year": movie.year,
        "poster_url": movie.cover,
        "scraper_source": movie.scraper_source,
        "metadata_state": snapshot["state"],
        "metadata_actions": snapshot["actions"],
        "matching_issue": issue,
    }


def _build_metadata_quality_summary(sample_size=3):
    movies = Movie.query.order_by(Movie.updated_at.desc(), Movie.id.asc()).all()
    overview = _build_metadata_overview()
    issue_stats = {}
    action_movie_ids = {action["id"]: set() for action in METADATA_QUALITY_ACTIONS}
    issue_movie_count = 0

    for movie in movies:
        snapshot = movie.get_metadata_snapshot()
        issue_codes = set()
        for issue in snapshot["issues"]:
            code = issue.get("code")
            if not code:
                continue
            issue_codes.add(code)
            stat = issue_stats.setdefault(code, {
                "code": code,
                "label": issue.get("label"),
                "severity": issue.get("severity"),
                "movie_count": 0,
                "affected_count": 0,
                "samples": [],
            })
            stat["movie_count"] += 1
            stat["affected_count"] += int(issue.get("count") or 1)
            if len(stat["samples"]) < sample_size:
                stat["samples"].append(_build_metadata_quality_sample(movie, issue=issue, snapshot=snapshot))

        if issue_codes:
            issue_movie_count += 1
        if issue_codes & METADATA_BULK_REIDENTIFY_ISSUES:
            action_movie_ids["bulk_reidentify"].add(movie.id)
        if issue_codes & (set(EPISODE_DIAGNOSTIC_ISSUES) | {"season_metadata_missing"}):
            action_movie_ids["episode_review_queue"].add(movie.id)

    issue_items = sorted(
        issue_stats.values(),
        key=lambda item: (-item["movie_count"], item["code"]),
    )
    actions = []
    for action in METADATA_QUALITY_ACTIONS:
        movie_count = len(action_movie_ids.get(action["id"], set()))
        actions.append({
            **action,
            "movie_count": movie_count,
            "enabled": movie_count > 0,
            "payload": {
                "issue_codes": action["issue_codes"],
                "limit": min(max(movie_count, 1), 20),
            } if action["method"] == "POST" else None,
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "sample_size": sample_size,
        "totals": {
            **overview["totals"],
            "issue_movie_count": issue_movie_count,
            "bulk_reidentify_movie_count": len(action_movie_ids["bulk_reidentify"]),
            "episode_review_movie_count": len(action_movie_ids["episode_review_queue"]),
        },
        "source_groups": overview["source_groups"],
        "review_priorities": overview["review_priorities"],
        "recommended_actions": overview["recommended_actions"],
        "issues": issue_items,
        "actions": actions,
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


def _normalize_metadata_batch_rescrape_payload(payload):
    if not payload:
        raise MetadataValidationError(code=40000, msg="No input data")

    items = payload.get('items') if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise MetadataValidationError(code=40022, msg="Invalid field value: items should be a non-empty array")
    return items


def _execute_metadata_batch_rescrape(items, progress_callback=None):
    results = []
    updated_movie_ids = []

    for index, item in enumerate(items):
        if progress_callback:
            progress_callback(index, len(items), f"Processing item {index + 1}/{len(items)}")

        if not isinstance(item, dict):
            raise MetadataValidationError(code=40023, msg=f"Invalid item at index {index}: object expected")

        raw_movie_id = item.get('id') or item.get('movie_id')
        if not isinstance(raw_movie_id, str) or not raw_movie_id.strip():
            raise MetadataValidationError(code=40024, msg=f"Invalid item at index {index}: movie id required")

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
    if progress_callback:
        progress_callback(len(items), len(items), "Metadata batch re-scrape completed")

    status_counts = {}
    for item in results:
        status = item.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    failed_items = [item for item in results if item.get("status") == "failed"]
    return {
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
    }


def _normalize_metadata_reidentify_plan_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    issue_codes = _normalize_string_list(
        payload.get("issue_codes") or payload.get("metadata_issue_codes"),
        default=sorted(METADATA_BULK_REIDENTIFY_ISSUES),
        field_name="issue_codes",
    )
    movie_ids = _normalize_string_list(
        payload.get("movie_ids") or payload.get("ids"),
        default=None,
        field_name="movie_ids",
    )
    limit = _normalize_limited_int(payload.get("limit"), 20, minimum=1, maximum=50)
    media_type_hint = _normalize_media_type_hint(payload.get("media_type_hint")) if payload.get("media_type_hint") is not None else None
    unlock_fields = _normalize_lock_field_names(payload.get("metadata_unlocked_fields")) if payload.get("metadata_unlocked_fields") is not None else None
    return {
        "issue_codes": issue_codes,
        "movie_ids": movie_ids,
        "limit": limit,
        "media_type_hint": media_type_hint,
        "metadata_unlocked_fields": unlock_fields,
    }


def _movie_matches_any_issue(movie, issue_codes):
    issue_codes = set(issue_codes or [])
    if not issue_codes:
        return True
    movie_issue_codes = {
        issue.get("code")
        for issue in movie.get_metadata_issues()
        if isinstance(issue, dict)
    }
    return bool(movie_issue_codes & issue_codes)


def _select_metadata_reidentify_movies(movie_ids=None, issue_codes=None, limit=20):
    movies = []
    missing_movie_ids = []
    if movie_ids is not None:
        seen = set()
        for movie_id in movie_ids:
            if movie_id in seen:
                continue
            seen.add(movie_id)
            movie = db.session.get(Movie, movie_id)
            if movie:
                movies.append(movie)
            else:
                missing_movie_ids.append(movie_id)
            if len(movies) >= limit:
                break
        return movies, missing_movie_ids

    for movie in Movie.query.order_by(Movie.updated_at.desc(), Movie.id.asc()).all():
        if _movie_matches_any_issue(movie, issue_codes):
            movies.append(movie)
        if len(movies) >= limit:
            break
    return movies, missing_movie_ids


def _build_metadata_reidentify_apply_item(movie, media_type_hint=None, unlock_fields=None):
    item = {"id": movie.id}
    if media_type_hint:
        item["media_type_hint"] = media_type_hint
    if unlock_fields:
        item["metadata_unlocked_fields"] = sorted(unlock_fields)
    return item


def _build_metadata_reidentify_plan(payload):
    normalized = _normalize_metadata_reidentify_plan_payload(payload)
    movies, missing_movie_ids = _select_metadata_reidentify_movies(
        movie_ids=normalized["movie_ids"],
        issue_codes=normalized["issue_codes"],
        limit=normalized["limit"],
    )
    results = []
    apply_items = []

    for missing_movie_id in missing_movie_ids:
        results.append({
            **_build_metadata_missing_batch_result(missing_movie_id),
            "dry_run": True,
            "apply_item": None,
        })

    for movie in movies:
        snapshot = movie.get_metadata_snapshot()
        matching_issues = [
            issue
            for issue in snapshot["issues"]
            if issue.get("code") in set(normalized["issue_codes"])
        ]
        apply_item = _build_metadata_reidentify_apply_item(
            movie,
            media_type_hint=normalized["media_type_hint"],
            unlock_fields=normalized["metadata_unlocked_fields"],
        )
        try:
            result = movie_metadata_rescrape_service.resolve_movie(
                movie,
                media_type_hint=normalized["media_type_hint"],
            )
            resolution = result["resolution"]
            update_payload = _build_external_metadata_update_payload(resolution.meta_data or {})
            diff = _build_movie_metadata_diff(
                movie,
                update_payload,
                unlocked_fields=normalized["metadata_unlocked_fields"],
            )
            preview = _build_metadata_preview_from_resolution(
                resolution,
                result["entity_context"],
                movie=movie,
                update_payload=update_payload,
            )
            plan_item = {
                "movie_id": movie.id,
                "title": movie.title,
                "scraper_source": movie.scraper_source,
                "status": "planned",
                "dry_run": True,
                "matched_issue_codes": [issue["code"] for issue in matching_issues],
                "metadata_state": snapshot["state"],
                "metadata_actions": snapshot["actions"],
                "metadata_diagnostics": snapshot["diagnostics"],
                "metadata_issues": snapshot["issues"],
                "entity_context": _build_metadata_entity_context_info(
                    result["entity_context"],
                    resource_count=result["resource_count"],
                ),
                "preview": preview,
                "diff": diff,
                "resolution": _build_metadata_resolution_info(resolution),
                "explanation": _build_metadata_resolution_feedback(resolution, result["entity_context"]),
                "apply_item": apply_item,
            }
            results.append(plan_item)
            apply_items.append(apply_item)
        except MetadataValidationError as e:
            results.append(_build_metadata_batch_result(movie, error={"code": e.code, "msg": e.msg}) | {
                "dry_run": True,
                "matched_issue_codes": [issue["code"] for issue in matching_issues],
                "apply_item": None,
            })
        except ValueError as e:
            results.append(_build_metadata_batch_result(movie, error={"code": 40026, "msg": str(e)}) | {
                "dry_run": True,
                "matched_issue_codes": [issue["code"] for issue in matching_issues],
                "apply_item": None,
            })
        except Exception as e:
            logger.exception("Metadata reidentify dry-run failed movie_id=%s error=%s", movie.id, e)
            results.append(_build_metadata_batch_result(movie, error={"code": 50014, "msg": "Re-scrape preview failed"}) | {
                "dry_run": True,
                "matched_issue_codes": [issue["code"] for issue in matching_issues],
                "apply_item": None,
            })

    status_counts = {}
    for item in results:
        status = item.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    issue_code_counts = {}
    for item in results:
        for code in item.get("matched_issue_codes") or []:
            issue_code_counts[code] = issue_code_counts.get(code, 0) + 1

    return {
        "dry_run": True,
        "selection": {
            "issue_codes": normalized["issue_codes"],
            "movie_ids": normalized["movie_ids"],
            "limit": normalized["limit"],
            "media_type_hint": normalized["media_type_hint"],
            "metadata_unlocked_fields": sorted(normalized["metadata_unlocked_fields"] or []),
        },
        "apply_method": "POST",
        "apply_endpoint": "/api/v1/metadata/re-scrape",
        "apply_payload": {"items": apply_items},
        "items": results,
        "summary": {
            "total": len(results),
            "planned": status_counts.get("planned", 0),
            "failed": status_counts.get("failed", 0),
            "apply_item_count": len(apply_items),
            "status_counts": status_counts,
            "issue_code_counts": issue_code_counts,
            "failed_movie_ids": [item["movie_id"] for item in results if item.get("status") == "failed" and item.get("movie_id")],
        },
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


def _filename_stem(filename):
    if not filename:
        return None
    stem = posixpath.splitext(str(filename).strip())[0].strip()
    return stem or None


def _coerce_optional_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _compact_payload(payload):
    return {key: value for key, value in payload.items() if value is not None}


def _build_other_video_metadata_match_context(resource, resource_data):
    movie = resource.movie
    metadata = resource_data.get("metadata") or {}
    analysis = metadata.get("analysis") or {}
    path_cleaning = analysis.get("path_cleaning") or {}
    edit_context = metadata.get("edit_context") or {}
    resource_info = resource_data.get("resource_info") or {}
    file_info = resource_info.get("file") or {}

    title_hint = (path_cleaning.get("title_hint") or "").strip()
    if title_hint:
        title_hint_source = "path_cleaning"
    elif movie and (movie.original_title or movie.title):
        title_hint = (movie.original_title or movie.title or "").strip()
        title_hint_source = "movie"
    else:
        title_hint = _filename_stem(file_info.get("filename") or resource.filename)
        title_hint_source = "filename"

    source_media_type_hint = edit_context.get("media_type_hint")
    if source_media_type_hint not in TMDB_SEARCH_SOURCE_HINTS:
        source_media_type_hint = None

    manual_media_type = Movie.manual_media_type_from_source(movie.scraper_source) if movie else None
    if manual_media_type:
        suggested_media_type_hint = manual_media_type
    elif resource.season is not None:
        suggested_media_type_hint = "tv"
    else:
        suggested_media_type_hint = "movie"

    return {
        "suggested_query": title_hint,
        "suggested_year": _coerce_optional_int(path_cleaning.get("year_hint")) or (movie.year if movie else None),
        "suggested_media_type_hint": suggested_media_type_hint,
        "source_media_type_hint": source_media_type_hint,
        "media_type_options": ["movie", "tv"],
        "title_hint_source": title_hint_source,
    }


def _build_other_video_resource_actions(resource, match_context):
    movie = resource.movie
    actions = {
        "create_manual_movie": {
            "method": "POST",
            "endpoint": "/api/v1/movies/manual",
            "body": _compact_payload({
                "title": match_context.get("suggested_query"),
                "media_type": match_context.get("suggested_media_type_hint") or "movie",
                "resource_ids": [resource.id],
            }),
        },
    }

    if not movie:
        return actions

    movie_endpoint_prefix = f"/api/v1/movies/{movie.id}/metadata"
    search_params = _compact_payload({
        "query": match_context.get("suggested_query"),
        "year": match_context.get("suggested_year"),
        "media_type_hint": match_context.get("suggested_media_type_hint"),
    })
    match_body_template = _compact_payload({
        "candidate_id": "<candidate_id>",
        "provider": "<provider>",
        "media_type_hint": match_context.get("suggested_media_type_hint"),
    })
    actions["match_metadata"] = {
        "search": {
            "method": "GET",
            "endpoint": f"{movie_endpoint_prefix}/search",
            "params": search_params,
        },
        "preview": {
            "method": "POST",
            "endpoint": f"{movie_endpoint_prefix}/match",
            "body_template": match_body_template,
        },
        "apply": {
            "method": "POST",
            "endpoint": f"{movie_endpoint_prefix}/match",
            "body_template": {**match_body_template, "apply": True},
        },
    }
    actions["preview_pipeline"] = {
        "method": "POST",
        "endpoint": f"{movie_endpoint_prefix}/preview",
        "body": _compact_payload({
            "media_type_hint": match_context.get("suggested_media_type_hint"),
        }),
    }
    return actions


def _serialize_other_video_resource(resource):
    resource_data = resource.to_dict()
    movie = resource.movie
    movie_state = movie.get_metadata_snapshot() if movie else None
    match_context = _build_other_video_metadata_match_context(resource, resource_data)
    metadata_state = None
    metadata_issues = []
    if movie_state:
        metadata_issues = [
            issue
            for issue in movie_state["issues"]
            if issue.get("code") not in EPISODE_REVIEW_ISSUE_CODES
        ]
        metadata_state = dict(movie_state["state"])
        metadata_state["issue_codes"] = [issue.get("code") for issue in metadata_issues if issue.get("code")]
        metadata_state["issue_count"] = len(metadata_issues)
        metadata_state["primary_issue_code"] = metadata_state["issue_codes"][0] if metadata_state["issue_codes"] else None
    return {
        "resource_id": resource.id,
        "movie_id": movie.id if movie else None,
        "movie_title": movie.title if movie else None,
        "movie_original_title": movie.original_title if movie else None,
        "movie_year": movie.year if movie else None,
        "movie_manual_content": movie.get_manual_content_info() if movie else None,
        "resource_info": resource_data.get("resource_info"),
        "playback": resource_data.get("playback"),
        "metadata": resource_data.get("metadata"),
        "catalog_visibility": movie.get_catalog_visibility_state() if movie else None,
        "metadata_state": metadata_state,
        "metadata_issues": metadata_issues,
        "metadata_actions": movie_state["actions"] if movie_state else None,
        "metadata_match_context": match_context,
        "recommended_resolution": "manual_content" if movie and movie.is_manual_content() else "match_metadata",
        "actions": _build_other_video_resource_actions(resource, match_context),
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


@library_bp.route('/metadata/quality-summary', methods=['GET'])
def get_metadata_quality_summary():
    try:
        sample_size = _normalize_limited_int(request.args.get('sample_size'), 3, minimum=0, maximum=10, field_name="sample_size")
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)
    return api_response(data=_build_metadata_quality_summary(sample_size=sample_size))


@library_bp.route('/metadata/review-taxonomy', methods=['GET'])
def get_metadata_review_taxonomy():
    """Return the frontend contract for metadata review and resource governance."""
    return api_response(data=build_review_taxonomy())


@library_bp.route('/jobs', methods=['GET'])
def list_background_jobs():
    try:
        limit = _normalize_limited_int(request.args.get('limit'), 20, minimum=1, maximum=100)
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)
    job_type = request.args.get('type')
    items = job_manager.list(job_type=job_type, limit=limit)
    return api_response(data={
        "items": items,
        "summary": {
            "count": len(items),
            "limit": limit,
            "type": job_type,
        },
    })


@library_bp.route('/jobs/prune', methods=['POST'])
def prune_background_jobs():
    payload = _get_json_payload()
    try:
        raw_days = payload.get('retention_days', request.args.get('retention_days')) if isinstance(payload, dict) else request.args.get('retention_days')
        retention_days = None
        if raw_days is not None and raw_days != "":
            retention_days = _normalize_limited_int(raw_days, 30, minimum=0, maximum=3650, field_name="retention_days")
        dry_run = _normalize_request_bool(
            payload.get('dry_run', request.args.get('dry_run')) if isinstance(payload, dict) else request.args.get('dry_run'),
            default=False,
            field_name="dry_run",
        )
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    job_type = payload.get('type', request.args.get('type')) if isinstance(payload, dict) else request.args.get('type')
    if isinstance(job_type, str):
        job_type = job_type.strip() or None
    else:
        job_type = None

    try:
        data = job_manager.prune(days=retention_days, job_type=job_type, dry_run=dry_run)
        return api_response(data=data, msg="Background jobs prune completed")
    except Exception as e:
        logger.exception("Background jobs prune failed error=%s", e)
        return api_error(code=50018, msg="Background jobs prune failed", http_status=500)


@library_bp.route('/jobs/<job_id>', methods=['GET'])
def get_background_job(job_id):
    job = job_manager.get(job_id)
    if not job:
        return api_error(code=40420, msg="Job not found", http_status=404)
    return api_response(data=job)


@library_bp.route('/metadata/providers', methods=['GET'])
def list_metadata_providers():
    return api_response(data=metadata_scraper.provider_catalog())


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


@library_bp.route('/metadata/episode-review-items', methods=['GET'])
def list_episode_review_items():
    try:
        page = _normalize_limited_int(request.args.get('page'), 1, minimum=1, maximum=10000, field_name="page")
        page_size = _normalize_limited_int(request.args.get('page_size'), 20, minimum=1, maximum=100, field_name="page_size")
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    issue_code = request.args.get('metadata_issue_code') or request.args.get('issue_code')
    return api_response(data=_build_episode_review_queue(page=page, page_size=page_size, issue_code=issue_code))


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


@library_bp.route('/other-videos', methods=['GET'])
def list_other_videos():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    keyword = request.args.get('keyword')
    source_id = request.args.get('source_id', type=int)
    raw_needs_attention = request.args.get('needs_attention')
    include_manual = request.args.get('include_manual', 'false').strip().lower() in {'1', 'true', 'yes'}

    needs_attention = None
    if raw_needs_attention is not None:
        needs_attention = raw_needs_attention.strip().lower() in {'1', 'true', 'yes'}

    query = MediaResource.query.join(Movie)
    if source_id:
        query = query.filter(MediaResource.source_id == source_id)
    if keyword:
        keyword_like = f"%{keyword}%"
        query = query.filter(
            db.or_(
                Movie.title.like(keyword_like),
                Movie.original_title.like(keyword_like),
                MediaResource.filename.like(keyword_like),
                MediaResource.path.like(keyword_like),
            )
        )

    source_state = db.func.upper(Movie.scraper_source)
    non_attention_sources = list(Movie.get_metadata_non_attention_sources())
    manual_sources = list(Movie.MANUAL_CONTENT_SOURCES)
    manual_source_condition = source_state.in_(manual_sources)
    unarchived_other_video_condition = db.and_(
        # Season-indexed resources belong to the episode review queue, not the
        # manual "other videos" archive queue.
        MediaResource.season.is_(None),
        ~Movie.resources.any(MediaResource.season.isnot(None)),
        db.or_(
            Movie.scraper_source.is_(None),
            Movie.scraper_source == "",
            source_state.notin_(non_attention_sources),
        ),
    )

    if needs_attention is None:
        default_conditions = [unarchived_other_video_condition]
        if include_manual:
            default_conditions.append(manual_source_condition)
        query = query.filter(db.or_(*default_conditions))
    elif needs_attention:
        query = query.filter(unarchived_other_video_condition)
    elif include_manual:
        query = query.filter(manual_source_condition)
    else:
        query = query.filter(MediaResource.id.is_(None))

    query = query.order_by(MediaResource.created_at.desc(), MediaResource.id.desc())
    pagination = query.paginate(page=page, per_page=page_size, error_out=False)
    items = [_serialize_other_video_resource(resource) for resource in pagination.items]
    return api_response(data={
        "items": items,
        "pagination": build_pagination_meta(pagination, page, page_size),
        "summary": {
            "total_items": pagination.total,
            "manual_movie_count": sum(1 for item in items if (item.get("movie_manual_content") or {}).get("is_manual")),
        },
        "actions": {
            "create_manual_movie": {
                "method": "POST",
                "endpoint": "/api/v1/movies/manual",
            },
            "attach_resources": {
                "method": "POST",
                "endpoint": "/api/v1/movies/{movie_id}/resources/attach",
            },
        },
    })


@library_bp.route('/movies/manual', methods=['POST'])
def create_manual_movie():
    payload = _get_json_payload()
    try:
        normalized = _normalize_manual_content_payload(payload)
    except MetadataValidationError as e:
        http_status = 404 if 40400 <= e.code < 40500 else 400
        return api_error(code=e.code, msg=e.msg, http_status=http_status)

    library_map = _get_library_map(normalized["library_ids"])
    missing_library_ids = [library_id for library_id in normalized["library_ids"] if library_id not in library_map]
    if missing_library_ids:
        return api_error(code=40410, msg=f"Library not found: {missing_library_ids[0]}", http_status=404)

    resources = _apply_manual_resource_defaults(
        normalized["resources"],
        normalized["media_type"],
        default_season=normalized["default_season"],
        episode_start=normalized["episode_start"],
        preserve_episode_metadata=normalized["preserve_episode_metadata"],
    )

    try:
        movie = Movie(
            tmdb_id=f"manual/{normalized['media_type']}/{uuid4()}",
            title=normalized["title"],
            original_title=normalized["title"],
            description=normalized["description"],
            scraper_source=normalized["scraper_source"],
            catalog_visibility_status=normalized["catalog_visibility_status"],
            catalog_visibility_note=normalized["catalog_visibility_note"],
            catalog_visibility_updated_at=datetime.utcnow(),
        )
        db.session.add(movie)
        db.session.flush()

        attachment_result = _attach_resources_to_movie(
            movie,
            resources,
            normalized["media_type"],
            preserve_episode_metadata=normalized["preserve_episode_metadata"],
        )
        library_memberships = _upsert_manual_library_memberships(movie, normalized["library_ids"])

        db.session.commit()
        clear_user_access_cache()
        return api_response(data={
            "movie": movie.to_detail_dict(),
            "manual_content": movie.get_manual_content_info(),
            "resource_attachment": attachment_result,
            "library_memberships": [membership.to_dict(include_movie=False) for membership in library_memberships],
        }, msg="Manual movie created", http_status=201)
    except MetadataValidationError as e:
        db.session.rollback()
        http_status = 404 if 40400 <= e.code < 40500 else 400
        return api_error(code=e.code, msg=e.msg, http_status=http_status)
    except Exception as e:
        db.session.rollback()
        logger.exception('Create manual movie failed error=%s', e)
        return api_error(code=50020, msg='Create manual movie failed', http_status=500)


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


@library_bp.route('/movies/<uuid:id>/catalog-visibility', methods=['PATCH'])
def update_movie_catalog_visibility(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    try:
        status, note, force = _normalize_catalog_visibility_payload(_get_json_payload())
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    current_state = movie.get_catalog_visibility_state()
    if status == Movie.CATALOG_VISIBILITY_PUBLISHED and current_state["requires_force"] and not force:
        return api_response(
            data={
                "movie_id": movie.id,
                "catalog_visibility": current_state,
                "required_force": True,
            },
            code=40901,
            msg="Catalog publish requires force because metadata is not public-ready",
            http_status=409,
        )

    try:
        movie.catalog_visibility_status = status
        movie.catalog_visibility_note = note
        movie.catalog_visibility_updated_at = datetime.utcnow()
        db.session.commit()
        logger.info(
            "Movie catalog visibility updated movie_id=%s status=%s force=%s",
            movie.id,
            status,
            force,
        )
        return api_response(data=movie.to_detail_dict(), msg="Movie catalog visibility updated")
    except Exception as e:
        db.session.rollback()
        logger.exception("Update movie catalog visibility failed movie_id=%s error=%s", movie.id, e)
        return api_error(code=50017, msg="Catalog visibility update failed", http_status=500)


@library_bp.route('/movies/<uuid:id>/images/status', methods=['GET'])
def get_movie_image_asset_status(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    raw_kinds = request.args.get("kinds")
    if raw_kinds is None and request.args.get("kind"):
        raw_kinds = request.args.get("kind")

    try:
        kinds = _normalize_image_kind_list(raw_kinds, default=sorted(IMAGE_KINDS))
        return api_response(data=get_movie_image_cache_statuses(movie, kinds=kinds))
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)
    except MovieImageAssetError as e:
        return api_error(code=e.code, msg=str(e), http_status=e.http_status)


@library_bp.route('/images/preload', methods=['POST'])
def preload_movie_images():
    try:
        normalized = _normalize_image_preload_payload(_get_json_payload())
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    movie_ids = normalized["movie_ids"]
    limit = normalized["limit"]
    kinds = normalized["kinds"]
    refresh = normalized["refresh"]

    movies, missing_movie_ids = _select_image_movies(movie_ids, limit)

    items = []
    for movie_id in missing_movie_ids:
        items.append({
            "movie_id": movie_id,
            "title": None,
            "kind": None,
            "status": "failed",
            "reason": "movie_not_found",
            "error": {
                "code": 40401,
                "msg": "Movie not found",
            },
        })

    for movie in movies:
        for kind in kinds:
            items.append(preload_movie_image_asset(movie, kind, refresh=refresh))

    status_counts = {}
    for item in items:
        status = item.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    data = {
        "items": items,
        "summary": {
            "total": len(items),
            "cached": status_counts.get("cached", 0),
            "stale": status_counts.get("stale", 0),
            "skipped": status_counts.get("skipped", 0),
            "failed": status_counts.get("failed", 0),
            "status_counts": status_counts,
            "movie_count": len(movies),
            "missing_movie_count": len(missing_movie_ids),
        },
        "selection": {
            "mode": "explicit" if movie_ids is not None else "latest",
            "limit": limit,
            "kinds": kinds,
            "refresh": refresh,
            "requested_movie_count": len(movie_ids) if movie_ids is not None else None,
        },
    }
    return api_response(data=data, msg="Movie image preload completed")


@library_bp.route('/images/refresh', methods=['POST'])
def refresh_movie_images():
    try:
        normalized = _normalize_image_refresh_payload(_get_json_payload())
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    movie_ids = normalized["movie_ids"]
    limit = normalized["limit"]
    kinds = normalized["kinds"]
    purge = normalized["purge"]
    clear_cache = normalized["clear_cache"]
    preload = normalized["preload"]
    refresh = normalized["refresh"]

    movies, missing_movie_ids = _select_image_movies(movie_ids, limit)

    items = []
    for movie_id in missing_movie_ids:
        items.append({
            "movie_id": movie_id,
            "title": None,
            "kind": None,
            "status": "failed",
            "reason": "movie_not_found",
            "error": {
                "code": 40401,
                "msg": "Movie not found",
            },
            "asset_url": None,
            "before": None,
            "after": None,
            "purge": None,
            "clear_cache": None,
            "preload": None,
        })

    for movie in movies:
        for kind in kinds:
            try:
                items.append(refresh_movie_image_asset_for_cdn(
                    movie,
                    kind,
                    purge=purge,
                    clear_cache=clear_cache,
                    preload=preload,
                    refresh=refresh,
                ))
            except MovieImageAssetError as e:
                items.append({
                    "movie_id": movie.id,
                    "title": movie.title,
                    "kind": kind,
                    "status": "failed",
                    "reason": "image_asset_error",
                    "error": {
                        "code": e.code,
                        "msg": str(e),
                    },
                    "asset_url": None,
                    "before": None,
                    "after": None,
                    "purge": None,
                    "clear_cache": None,
                    "preload": None,
                })

    status_counts = {}
    purge_status_counts = {}
    preload_status_counts = {}
    cdn_status_counts = {}
    for item in items:
        status = item.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

        purge_result = item.get("purge")
        if isinstance(purge_result, dict):
            purge_status = purge_result.get("status", "unknown")
            purge_status_counts[purge_status] = purge_status_counts.get(purge_status, 0) + 1

        preload_result = item.get("preload")
        if isinstance(preload_result, dict):
            preload_status = preload_result.get("status", "unknown")
            preload_status_counts[preload_status] = preload_status_counts.get(preload_status, 0) + 1

        cdn_result = item.get("cdn")
        if isinstance(cdn_result, dict):
            cdn_status = cdn_result.get("status", "unknown")
            cdn_status_counts[cdn_status] = cdn_status_counts.get(cdn_status, 0) + 1

    data = {
        "items": items,
        "summary": {
            "total": len(items),
            "refreshed": status_counts.get("refreshed", 0),
            "planned": status_counts.get("planned", 0),
            "cleared": status_counts.get("cleared", 0),
            "skipped": status_counts.get("skipped", 0),
            "failed": status_counts.get("failed", 0),
            "status_counts": status_counts,
            "purge_status_counts": purge_status_counts,
            "preload_status_counts": preload_status_counts,
            "cdn_status_counts": cdn_status_counts,
            "movie_count": len(movies),
            "missing_movie_count": len(missing_movie_ids),
        },
        "selection": {
            "mode": "explicit" if movie_ids is not None else "latest",
            "limit": limit,
            "kinds": kinds,
            "purge": purge,
            "clear_cache": clear_cache,
            "preload": preload,
            "refresh": refresh,
            "requested_movie_count": len(movie_ids) if movie_ids is not None else None,
        },
    }
    return api_response(data=data, msg="Movie image refresh orchestration completed")


@library_bp.route('/movies/<uuid:id>/images/<kind>', methods=['GET'])
def get_movie_image_asset(id, kind):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    refresh = str(request.args.get("refresh") or "").strip().lower() in ("1", "true", "yes")
    try:
        asset = resolve_movie_image_asset(movie, kind, refresh=refresh)
    except MovieImageAssetError as e:
        try:
            original_url = movie_image_original_url(movie, kind, validate=True)
        except MovieImageAssetError:
            original_url = None
        if original_url and e.http_status >= 500:
            response = redirect(original_url, code=302)
            response.headers["Cache-Control"] = "private, max-age=60"
            response.headers["X-Cyber-Image-Cache"] = "fallback_original"
            response.headers["X-Cyber-Image-Fallback"] = "original"
            response.headers["X-Cyber-Image-Error-Code"] = str(e.code)
            return response
        return api_error(code=e.code, msg=str(e), http_status=e.http_status)

    response = send_file(
        asset.path,
        mimetype=asset.mimetype,
        conditional=True,
        max_age=asset.max_age_seconds,
    )
    response.headers["Cache-Control"] = f"public, max-age={asset.max_age_seconds}"
    response.headers["X-Cyber-Image-Cache"] = asset.cache_status
    response.headers["X-Cyber-Image-Source"] = asset.source
    return response


@library_bp.route('/movies/<uuid:id>/images/<kind>', methods=['DELETE'])
def clear_movie_image_asset(id, kind):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    try:
        data = clear_movie_image_asset_cache(movie, kind)
        return api_response(data=data, msg="Movie image cache clear completed")
    except MovieImageAssetError as e:
        return api_error(code=e.code, msg=str(e), http_status=e.http_status)


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


@library_bp.route('/resources/governance-summary', methods=['GET'])
def get_resource_governance_summary():
    try:
        live_check = _normalize_request_bool(request.args.get("live_check"), default=False, field_name="live_check")
        live_check_limit = _normalize_limited_int(
            request.args.get("live_check_limit"),
            50,
            minimum=1,
            maximum=500,
            field_name="live_check_limit",
        )
        sample_size = _normalize_limited_int(
            request.args.get("sample_size"),
            3,
            minimum=0,
            maximum=20,
            field_name="sample_size",
        )
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    return api_response(data=build_resource_governance_summary(
        live_check=live_check,
        live_check_limit=live_check_limit,
        sample_size=sample_size,
    ))


@library_bp.route('/resources/governance-items', methods=['GET'])
def list_resource_governance_items():
    try:
        live_check = _normalize_request_bool(request.args.get("live_check"), default=False, field_name="live_check")
        live_check_limit = _normalize_limited_int(
            request.args.get("live_check_limit"),
            50,
            minimum=1,
            maximum=500,
            field_name="live_check_limit",
        )
        page = _normalize_limited_int(request.args.get("page"), 1, minimum=1, maximum=10000, field_name="page")
        page_size = _normalize_limited_int(request.args.get("page_size"), 20, minimum=1, maximum=100, field_name="page_size")
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    issue_code = request.args.get("issue_code") or request.args.get("resource_issue_code")
    return api_response(data=build_resource_governance_items(
        live_check=live_check,
        live_check_limit=live_check_limit,
        issue_code=issue_code,
        page=page,
        page_size=page_size,
    ))


@library_bp.route('/resources/governance/plan', methods=['POST'])
def plan_resource_governance_cleanup():
    try:
        data = build_resource_governance_plan(_get_json_payload())
        return api_response(data=data, msg="Resource governance dry-run completed")
    except ResourceGovernanceValidationError as e:
        return api_error(code=e.code, msg=e.msg)


@library_bp.route('/resources/governance/jobs', methods=['POST'])
def start_resource_governance_cleanup_job():
    try:
        payload = normalize_resource_governance_apply_payload(_get_json_payload())
    except ResourceGovernanceValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    app = current_app._get_current_object()

    def target(job_id):
        return execute_resource_governance_actions(
            payload,
            progress_callback=lambda current, total, message: job_manager.update_progress(
                job_id,
                current=current,
                total=total,
                message=message,
            ),
        )

    job = job_manager.start(
        app,
        "resource_governance_apply",
        target,
        title="Resource governance apply",
        request=payload,
        inline=bool(current_app.config.get("BACKGROUND_JOBS_INLINE")),
    )
    return api_response(data={"job": job}, msg="Resource governance job accepted", http_status=202)


@library_bp.route('/resources/governance/live-check/jobs', methods=['POST'])
def start_resource_governance_live_check_job():
    try:
        payload = normalize_resource_governance_live_check_payload(_get_json_payload())
    except ResourceGovernanceValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    app = current_app._get_current_object()

    def target(job_id):
        return execute_resource_governance_live_check(
            payload,
            progress_callback=lambda current, total, message: job_manager.update_progress(
                job_id,
                current=current,
                total=total,
                message=message,
            ),
        )

    job = job_manager.start(
        app,
        "resource_governance_live_check",
        target,
        title="Resource governance live check",
        request=payload,
        inline=bool(current_app.config.get("BACKGROUND_JOBS_INLINE")),
    )
    return api_response(data={"job": job}, msg="Resource governance live check job accepted", http_status=202)


@library_bp.route('/resources/governance/restore/plan', methods=['POST'])
def plan_resource_governance_restore():
    try:
        data = build_resource_governance_restore_plan(_get_json_payload())
        return api_response(data=data, msg="Resource governance restore dry-run completed")
    except ResourceGovernanceValidationError as e:
        return api_error(code=e.code, msg=e.msg)


@library_bp.route('/resources/governance/restore/jobs', methods=['POST'])
def start_resource_governance_restore_job():
    try:
        payload = normalize_resource_governance_restore_payload(_get_json_payload())
    except ResourceGovernanceValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    app = current_app._get_current_object()

    def target(job_id):
        return execute_resource_governance_restore_actions(
            payload,
            progress_callback=lambda current, total, message: job_manager.update_progress(
                job_id,
                current=current,
                total=total,
                message=message,
            ),
        )

    job = job_manager.start(
        app,
        "resource_governance_restore",
        target,
        title="Resource governance restore",
        request=payload,
        inline=bool(current_app.config.get("BACKGROUND_JOBS_INLINE")),
    )
    return api_response(data={"job": job}, msg="Resource governance restore job accepted", http_status=202)


@library_bp.route('/movies/<uuid:id>/resources', methods=['GET'])
def get_movie_resources(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    return api_response(data=_build_movie_resource_groups(movie))


@library_bp.route('/movies/<uuid:id>/resources/attach', methods=['POST'])
def attach_movie_resources(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    payload = _get_json_payload()
    if not isinstance(payload, dict) or not payload:
        return api_error(code=40000, msg="No input data")

    allowed = {
        "resource_ids", "resources", "library_ids", "default_season",
        "episode_start", "preserve_episode_metadata", "media_type", "note",
    }
    unknown = sorted([key for key in payload.keys() if key not in allowed])
    if unknown:
        return api_error(code=40002, msg=f"Unsupported fields: {', '.join(unknown)}")

    try:
        media_type = _normalize_manual_media_type(
            payload.get("media_type") or Movie.manual_media_type_from_source(movie.scraper_source) or "movie"
        )
        resource_items = _normalize_manual_resource_items(payload)
        if not resource_items:
            return api_error(code=40038, msg="Missing required field: resource_ids or resources")
        library_ids = _normalize_library_id_list(payload.get("library_ids"))
        library_map = _get_library_map(library_ids)
        missing_library_ids = [library_id for library_id in library_ids if library_id not in library_map]
        if missing_library_ids:
            return api_error(code=40410, msg=f"Library not found: {missing_library_ids[0]}", http_status=404)

        default_season = _normalize_positive_int_field('default_season', payload.get('default_season')) if 'default_season' in payload else None
        episode_start = _normalize_positive_int_field('episode_start', payload.get('episode_start')) if 'episode_start' in payload else None
        preserve_episode_metadata = _normalize_request_bool(
            payload.get('preserve_episode_metadata'),
            default=False,
            field_name='preserve_episode_metadata',
        )
        resource_items = _apply_manual_resource_defaults(
            resource_items,
            media_type,
            default_season=default_season,
            episode_start=episode_start,
            preserve_episode_metadata=preserve_episode_metadata,
        )
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        attachment_result = _attach_resources_to_movie(
            movie,
            resource_items,
            media_type,
            preserve_episode_metadata=preserve_episode_metadata,
        )
        library_memberships = _upsert_manual_library_memberships(movie, library_ids)
        if Movie.is_manual_content_source(movie.scraper_source):
            movie.scraper_source = _manual_scraper_source_for_media_type(media_type)
        if payload.get("note") is not None:
            movie.catalog_visibility_note = _normalize_optional_text_field('note', payload.get('note'))
        movie.updated_at = datetime.utcnow()

        db.session.commit()
        clear_user_access_cache()
        return api_response(data={
            "movie": movie.to_detail_dict(),
            "manual_content": movie.get_manual_content_info(),
            "resource_attachment": attachment_result,
            "library_memberships": [membership.to_dict(include_movie=False) for membership in library_memberships],
        }, msg="Movie resources attached")
    except MetadataValidationError as e:
        db.session.rollback()
        http_status = 404 if 40400 <= e.code < 40500 else 400
        return api_error(code=e.code, msg=e.msg, http_status=http_status)
    except Exception as e:
        db.session.rollback()
        logger.exception('Attach movie resources failed movie_id=%s error=%s', movie.id, e)
        return api_error(code=50021, msg='Attach movie resources failed', http_status=500)


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


@library_bp.route('/movies/<uuid:id>/episode-diagnostics', methods=['GET'])
def get_movie_episode_diagnostics(id):
    movie = db.session.get(Movie, str(id))
    if not movie:
        return api_error(code=40401, msg="Movie not found", http_status=404)

    return api_response(data=_build_movie_episode_repair_plan(movie))


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
        candidate_id, candidate_provider = _extract_metadata_candidate_payload(payload)
        tmdb_id = candidate_id or movie.tmdb_id
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

    provider_key = metadata_scraper._provider_for_candidate(tmdb_id, provider_name=candidate_provider)
    if provider_key and provider_key != 'tmdb':
        scrape_result = metadata_scraper.get_candidate_metadata(
            tmdb_id,
            provider_name=provider_key,
            media_type_hint=media_type_hint,
        )
        meta_data = scrape_result.metadata if scrape_result else None
    else:
        meta_data = scraper.get_movie_details(tmdb_id)
    if not meta_data:
        return api_error(code=50201, msg="Metadata refresh failed", http_status=502)

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
    try:
        items = _normalize_metadata_batch_rescrape_payload(_get_json_payload())
        return api_response(data=_execute_metadata_batch_rescrape(items), msg="Metadata batch re-scrape completed")
    except MetadataValidationError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.msg)
    except Exception as e:
        db.session.rollback()
        logger.exception("Batch re-scrape transaction failed error=%s", e)
        return api_error(code=50016, msg="Batch re-scrape failed", http_status=500)


@library_bp.route('/metadata/re-scrape/jobs', methods=['POST'])
def start_batch_re_scrape_movie_metadata_job():
    try:
        payload = _get_json_payload()
        items = _normalize_metadata_batch_rescrape_payload(payload)
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    app = current_app._get_current_object()
    request_payload = {"items": items}

    def target(job_id):
        return _execute_metadata_batch_rescrape(
            items,
            progress_callback=lambda current, total, message: job_manager.update_progress(
                job_id,
                current=current,
                total=total,
                message=message,
            ),
        )

    job = job_manager.start(
        app,
        "metadata_re_scrape",
        target,
        title="Metadata batch re-scrape",
        request=request_payload,
        inline=bool(current_app.config.get("BACKGROUND_JOBS_INLINE")),
    )
    return api_response(data={"job": job}, msg="Metadata batch re-scrape job accepted", http_status=202)


@library_bp.route('/metadata/re-scrape/plan', methods=['POST'])
def plan_batch_re_scrape_movie_metadata():
    try:
        data = _build_metadata_reidentify_plan(_get_json_payload())
        return api_response(data=data, msg="Metadata batch re-scrape dry-run completed")
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)


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
        update_payload = _build_external_metadata_update_payload(resolution.meta_data or {})
        preview = _build_metadata_preview_from_resolution(
            resolution,
            result["entity_context"],
            movie=movie,
            update_payload=update_payload,
        )
        diff = _build_movie_metadata_diff(movie, update_payload, unlocked_fields=unlock_fields)
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
        raw_query = request.args.get('query')
        query = _normalize_tmdb_search_query(raw_query) or movie.original_title or movie.title
        year_param_present = 'year' in request.args
        year = request.args.get('year', type=int) if year_param_present else None
        if year_param_present and year is None:
            raise MetadataValidationError(code=40019, msg="Invalid field value: year should be int")
        if not year_param_present and raw_query is None:
            year = movie.year
            year_source = "movie"
        elif year_param_present:
            year_source = "request"
        else:
            year_source = "none"
        limit = request.args.get('limit', 8, type=int)
        media_type_hint = _normalize_media_type_hint(request.args.get('media_type_hint'))
        scraper_policy = normalize_scraper_policy_payload(
            provider_order=request.args.get('providers') or request.args.get('provider_order')
        )
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)
    except ScraperPolicyError as e:
        return api_error(code=e.code, msg=e.msg)

    try:
        search_result = metadata_scraper.search_candidates(
            ScrapeContext(
                title=query,
                year=year,
                source_id=0,
                content_type=media_type_hint,
                scraper_policy=scraper_policy,
            ),
            query,
            year=year,
            limit=limit,
            media_type_hint=media_type_hint,
        )
        candidates = search_result["items"]
        candidates = _annotate_metadata_candidates(
            candidates,
            query=query,
            year=year,
            media_type_hint=media_type_hint,
        )
        return api_response(data={
            "query": query,
            "year": year,
            "year_source": year_source,
            "media_type_hint": media_type_hint,
            "providers": search_result["providers"],
            "items": candidates,
        })
    except Exception as e:
        logger.exception("Search movie metadata candidates failed movie_id=%s query=%r error=%s", movie.id, query, e)
        return api_error(code=50202, msg="Metadata search failed", http_status=502)


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
            return api_response(data=resource.to_dict(include_subtitle_discovery=True), msg="Resource metadata unchanged")

        db.session.commit()
        logger.info("Resource metadata updated resource_id=%s fields=%s", resource.id, ','.join(updated_fields))
        return api_response(data=resource.to_dict(include_subtitle_discovery=True), msg="Resource metadata updated")
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
        tmdb_id, candidate_provider = _extract_metadata_candidate_payload(payload, required=True)
        unlock_fields = _normalize_lock_field_names(payload.get('metadata_unlocked_fields')) if isinstance(payload, dict) else None
        media_type_hint = _normalize_media_type_hint(payload.get('media_type_hint')) if isinstance(payload, dict) else None
        apply_changes = _normalize_boolean_payload_field(payload, 'apply', default=False)
        allow_missing_poster = _normalize_boolean_payload_field(payload, 'allow_missing_poster', default=False)
    except MetadataValidationError as e:
        return api_error(code=e.code, msg=e.msg)

    requested_candidate_id = tmdb_id
    if tmdb_id.startswith('imdb/') or tmdb_id.startswith('tvdb/'):
        resolved_tmdb_id = scraper.find_by_external_id(tmdb_id, media_type_hint=media_type_hint)
        if not resolved_tmdb_id:
            return api_error(code=40402, msg="TMDB match not found", http_status=404)
        tmdb_id = resolved_tmdb_id

    provider_key = metadata_scraper._provider_for_candidate(tmdb_id, provider_name=candidate_provider)
    if provider_key and provider_key != 'tmdb':
        scrape_result = metadata_scraper.get_candidate_metadata(
            tmdb_id,
            provider_name=provider_key,
            media_type_hint=media_type_hint,
        )
        meta_data = scrape_result.metadata if scrape_result else None
    else:
        meta_data = scraper.get_movie_details(tmdb_id)
    if not meta_data:
        return api_error(code=50201, msg="Metadata refresh failed", http_status=502)

    if not apply_changes:
        return api_response(
            data=_build_metadata_match_preview(
                movie,
                meta_data,
                requested_candidate_id,
                candidate_provider=candidate_provider,
                media_type_hint=media_type_hint,
                unlock_fields=unlock_fields,
            ),
            msg="Movie metadata match preview",
        )

    if (
        _metadata_match_would_leave_movie_without_poster(movie, meta_data)
        and not allow_missing_poster
    ):
        return api_error(
            code=40920,
            msg="Matched metadata has no poster; pass allow_missing_poster=true to apply anyway",
            http_status=409,
        )

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
