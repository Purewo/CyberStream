from datetime import datetime

from flask import Blueprint, request
from sqlalchemy.exc import IntegrityError

from backend.app.api.helpers import get_history_map
from backend.app.api.library_helpers import apply_movie_filters, apply_public_movie_visibility_filter
from backend.app.extensions import db
from backend.app.models import HomepageSetting, Movie
from backend.app.utils.genres import normalize_genres
from backend.app.utils.response import api_error, api_response


homepage_bp = Blueprint('homepage', __name__, url_prefix='/api/v1')

DEFAULT_SECTION_LIMIT = 15

DEFAULT_HOMEPAGE_SECTIONS = [
    {"key": "sci_fi", "title": "科幻", "genre": "科幻", "mode": "latest", "limit": DEFAULT_SECTION_LIMIT, "movie_ids": [], "enabled": True, "sort_order": 0},
    {"key": "action", "title": "动作", "genre": "动作", "mode": "latest", "limit": DEFAULT_SECTION_LIMIT, "movie_ids": [], "enabled": True, "sort_order": 1},
    {"key": "drama", "title": "剧情", "genre": "剧情", "mode": "latest", "limit": DEFAULT_SECTION_LIMIT, "movie_ids": [], "enabled": True, "sort_order": 2},
    {"key": "animation", "title": "动画", "genre": "动画", "mode": "latest", "limit": DEFAULT_SECTION_LIMIT, "movie_ids": [], "enabled": True, "sort_order": 3},
]

SECTION_MODES = {"custom", "latest"}
MAX_SECTION_LIMIT = 20
HOMEPAGE_SETTING_ID = 1
LEGACY_DEFAULT_SECTION_LIMITS = {4, 10}


class HomepageConfigError(ValueError):
    pass


def _default_sections():
    return [dict(section) for section in DEFAULT_HOMEPAGE_SECTIONS]


def _get_json_payload():
    return request.get_json(silent=True) or {}


def _get_or_create_homepage_setting():
    setting = db.session.get(HomepageSetting, HOMEPAGE_SETTING_ID)
    if setting:
        _upgrade_legacy_default_sections(setting)
        return setting

    setting = HomepageSetting(
        id=HOMEPAGE_SETTING_ID,
        hero_movie_id=None,
        sections=_default_sections(),
    )
    db.session.add(setting)
    try:
        db.session.commit()
        return setting
    except IntegrityError:
        db.session.rollback()
        existing = db.session.get(HomepageSetting, HOMEPAGE_SETTING_ID)
        if existing:
            return existing
        raise


def _upgrade_legacy_default_sections(setting):
    sections = setting.sections or []
    if not _is_legacy_default_sections(sections):
        return

    upgraded_sections = []
    for section in sections:
        upgraded = dict(section)
        upgraded["limit"] = DEFAULT_SECTION_LIMIT
        upgraded_sections.append(upgraded)
    setting.sections = upgraded_sections
    setting.updated_at = datetime.utcnow()
    db.session.add(setting)
    db.session.commit()


def _is_legacy_default_sections(sections):
    if not isinstance(sections, list) or len(sections) != len(DEFAULT_HOMEPAGE_SECTIONS):
        return False

    defaults_by_key = {section["key"]: section for section in DEFAULT_HOMEPAGE_SECTIONS}
    for raw_section in sections:
        if not isinstance(raw_section, dict):
            return False
        key = raw_section.get("key")
        default_section = defaults_by_key.get(key)
        if not default_section:
            return False
        if raw_section.get("genre") != default_section["genre"]:
            return False
        if raw_section.get("mode", "latest") != "latest":
            return False
        if raw_section.get("movie_ids") not in (None, []):
            return False
        if raw_section.get("limit") not in LEGACY_DEFAULT_SECTION_LIMITS:
            return False
    return True


def _coerce_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_limit(value):
    if value is None:
        return DEFAULT_SECTION_LIMIT
    if isinstance(value, bool):
        raise HomepageConfigError("section.limit must be an integer")
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise HomepageConfigError("section.limit must be an integer")
    if limit < 1 or limit > MAX_SECTION_LIMIT:
        raise HomepageConfigError(f"section.limit must be between 1 and {MAX_SECTION_LIMIT}")
    return limit


def _normalize_sort_order(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, bool):
        raise HomepageConfigError("section.sort_order must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HomepageConfigError("section.sort_order must be an integer")


def _normalize_movie_ids(value, validate=True):
    if value is None:
        return []
    if not isinstance(value, list):
        raise HomepageConfigError("section.movie_ids must be an array")

    movie_ids = []
    seen = set()
    for raw_id in value:
        if not isinstance(raw_id, str):
            raise HomepageConfigError("section.movie_ids must contain movie id strings")
        movie_id = raw_id.strip()
        if not movie_id:
            raise HomepageConfigError("section.movie_ids must not contain empty values")
        if movie_id in seen:
            continue
        seen.add(movie_id)
        movie_ids.append(movie_id)

    if validate and movie_ids:
        existing_ids = {
            row[0]
            for row in db.session.query(Movie.id).filter(Movie.id.in_(movie_ids)).all()
        }
        missing_ids = [movie_id for movie_id in movie_ids if movie_id not in existing_ids]
        if missing_ids:
            raise HomepageConfigError(f"movie not found: {missing_ids[0]}")

    return movie_ids


def _normalize_hero_movie_id(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise HomepageConfigError("hero_movie_id must be a movie id string")
    movie_id = value.strip()
    if not movie_id:
        return None
    if not db.session.get(Movie, movie_id):
        raise HomepageConfigError(f"movie not found: {movie_id}")
    return movie_id


def _normalize_section(raw_section, index, validate_movie_ids=True):
    if not isinstance(raw_section, dict):
        raise HomepageConfigError("sections must contain objects")

    key = str(raw_section.get("key") or f"section_{index + 1}").strip()
    if not key:
        raise HomepageConfigError("section.key is required")

    raw_genre = raw_section.get("genre")
    genres = normalize_genres([raw_genre])
    if not genres:
        raise HomepageConfigError("section.genre is required")
    genre = genres[0]

    title = str(raw_section.get("title") or genre).strip() or genre
    mode = str(raw_section.get("mode") or "latest").strip().lower()
    if mode not in SECTION_MODES:
        raise HomepageConfigError("section.mode must be custom or latest")

    return {
        "key": key,
        "title": title,
        "genre": genre,
        "mode": mode,
        "limit": _normalize_limit(raw_section.get("limit")),
        "movie_ids": _normalize_movie_ids(raw_section.get("movie_ids"), validate=validate_movie_ids),
        "enabled": _coerce_bool(raw_section.get("enabled"), default=True),
        "sort_order": _normalize_sort_order(raw_section.get("sort_order"), index),
    }


def _normalize_sections(raw_sections, validate_movie_ids=True):
    if raw_sections is None:
        return _default_sections()
    if not isinstance(raw_sections, list):
        raise HomepageConfigError("sections must be an array")
    return [
        _normalize_section(section, index, validate_movie_ids=validate_movie_ids)
        for index, section in enumerate(raw_sections)
    ]


def _get_enabled_sections(setting):
    normalized_sections = _normalize_sections(setting.sections or [], validate_movie_ids=False)
    enabled_sections = [section for section in normalized_sections if section["enabled"]]
    return sorted(enabled_sections, key=lambda section: (section["sort_order"], section["key"]))


def _movie_genres(movie):
    return normalize_genres(movie.category or [])


def _movie_has_genre(movie, genre):
    return genre in _movie_genres(movie)


def _movie_has_animation(movie):
    return "动画" in _movie_genres(movie)


def _is_auto_quality_movie(movie):
    if not movie.cover:
        return False
    source = (movie.scraper_source or "").strip().upper()
    return source in Movie.get_metadata_non_attention_sources()


def _passes_section_rules(movie, section, used_ids, animation_section_enabled):
    if movie.id in used_ids:
        return False
    if not _movie_has_genre(movie, section["genre"]):
        return False
    if animation_section_enabled and section["genre"] != "动画" and _movie_has_animation(movie):
        return False
    return True


def _select_custom_section_movies(section, used_ids, animation_section_enabled):
    movies = []
    for movie_id in section["movie_ids"]:
        movie = db.session.get(Movie, movie_id)
        if not movie:
            continue
        if not _passes_section_rules(movie, section, used_ids, animation_section_enabled):
            continue
        movies.append(movie)
        if len(movies) >= section["limit"]:
            break
    return movies


def _select_latest_section_movies(section, used_ids, animation_section_enabled):
    query = apply_public_movie_visibility_filter(apply_movie_filters(Movie.query, genre=section["genre"]))
    query = query.filter(Movie.cover.isnot(None), Movie.cover != "")
    query = query.order_by(Movie.added_at.desc(), Movie.id.asc())

    selected = []
    batch_size = max(section["limit"] * 8, 40)
    offset = 0
    while len(selected) < section["limit"]:
        candidates = query.offset(offset).limit(batch_size).all()
        if not candidates:
            break
        for movie in candidates:
            if not _is_auto_quality_movie(movie):
                continue
            if not _passes_section_rules(movie, section, used_ids, animation_section_enabled):
                continue
            selected.append(movie)
            if len(selected) >= section["limit"]:
                break
        offset += batch_size
        if offset >= 1000:
            break
    return selected


def _select_section_movies(section, used_ids, animation_section_enabled):
    if section["mode"] == "custom":
        return _select_custom_section_movies(section, used_ids, animation_section_enabled)
    return _select_latest_section_movies(section, used_ids, animation_section_enabled)


def _select_hero_movie(setting):
    if setting.hero_movie_id:
        hero_movie = db.session.get(Movie, setting.hero_movie_id)
        if hero_movie:
            return hero_movie, "custom"

    hero_movie = apply_public_movie_visibility_filter(Movie.query).filter(
        Movie.background_cover.isnot(None),
        Movie.background_cover != "",
    ).order_by(Movie.added_at.desc(), Movie.id.asc()).first()

    if hero_movie:
        return hero_movie, "latest"
    return None, None


def _serialize_config(setting):
    return {
        "hero_movie_id": setting.hero_movie_id,
        "sections": _normalize_sections(setting.sections or [], validate_movie_ids=False),
        "created_at": setting.created_at.isoformat() if setting.created_at else None,
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
    }


@homepage_bp.route('/homepage', methods=['GET'])
def get_homepage():
    setting = _get_or_create_homepage_setting()
    sections = _get_enabled_sections(setting)
    animation_section_enabled = any(section["genre"] == "动画" for section in sections)

    used_ids = set()
    hero_movie, hero_mode = _select_hero_movie(setting)
    if hero_movie:
        used_ids.add(hero_movie.id)

    section_results = []

    for section in sections:
        movies = _select_section_movies(section, used_ids, animation_section_enabled)
        used_ids.update(movie.id for movie in movies)
        section_results.append((section, movies))

    all_movies = []
    if hero_movie:
        all_movies.append(hero_movie)
    for _, movies in section_results:
        all_movies.extend(movies)
    history_map = get_history_map([movie.id for movie in all_movies])

    hero_payload = {
        "mode": hero_mode,
        "movie": hero_movie.to_detail_dict(user_history=history_map.get(hero_movie.id)) if hero_movie else None,
    }
    sections_payload = []
    for section, movies in section_results:
        sections_payload.append({
            "key": section["key"],
            "title": section["title"],
            "genre": section["genre"],
            "mode": section["mode"],
            "limit": section["limit"],
            "items": [
                movie.to_simple_dict(user_history=history_map.get(movie.id), include_season_cards=False)
                for movie in movies
            ],
        })

    return api_response(data={
        "hero": hero_payload,
        "sections": sections_payload,
    })


@homepage_bp.route('/homepage/config', methods=['GET'])
def get_homepage_config():
    setting = _get_or_create_homepage_setting()
    return api_response(data=_serialize_config(setting))


@homepage_bp.route('/homepage/config', methods=['PATCH'])
def update_homepage_config():
    setting = _get_or_create_homepage_setting()
    payload = _get_json_payload()

    try:
        if "hero_movie_id" in payload:
            setting.hero_movie_id = _normalize_hero_movie_id(payload.get("hero_movie_id"))
        if "sections" in payload:
            setting.sections = _normalize_sections(payload.get("sections"), validate_movie_ids=True)
        setting.updated_at = datetime.utcnow()
    except HomepageConfigError as e:
        return api_error(code=40070, msg=str(e), http_status=400)

    db.session.add(setting)
    db.session.commit()
    return api_response(data=_serialize_config(setting))
