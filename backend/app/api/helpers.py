from backend.app.extensions import db
from backend.app.models import History, MediaResource


def _history_ordering():
    return History.last_watched.desc(), History.id.desc()


def _build_resource_artwork_context(resource):
    movie = resource.movie
    series_poster_url = movie.cover if movie else None
    season_metadata = None

    if movie and resource.season is not None:
        season_metadata = movie.season_metadata.filter_by(season=resource.season).first()

    season_poster_url = season_metadata.poster if season_metadata else None
    poster_url = season_poster_url or series_poster_url
    if season_poster_url:
        poster_source = "season"
    elif series_poster_url:
        poster_source = "movie_fallback"
    else:
        poster_source = "none"

    return {
        "poster_url": poster_url,
        "poster_source": poster_source,
        "season_poster_url": season_poster_url,
        "series_poster_url": series_poster_url,
        "season_title": season_metadata.title if season_metadata else None,
        "season_display_title": season_metadata.get_display_title() if season_metadata else (
            f"Season {resource.season}" if resource.season is not None else None
        ),
    }


def _history_playback_payload(history_record, resource):
    progress_info = _build_progress_info(history_record.progress, history_record.duration)
    artwork_context = _build_resource_artwork_context(resource)
    return {
        "last_played_at": history_record.last_watched.isoformat() if history_record.last_watched else None,
        "resource_id": resource.id,
        "season": resource.season,
        "episode": resource.episode,
        "episode_label": resource.get_episode_label(),
        "label": resource.label,
        "filename": resource.filename,
        **progress_info,
        **artwork_context,
    }


def get_history_map(movie_ids):
    """批量查询影片最近观看记录，并保留具体资源与季级续播上下文。"""
    if not movie_ids:
        return {}

    rows = db.session.query(History, MediaResource) \
        .join(MediaResource, History.resource_id == MediaResource.id) \
        .filter(MediaResource.movie_id.in_(movie_ids)) \
        .order_by(MediaResource.movie_id.asc(), *_history_ordering()) \
        .all()

    movie_history = {}
    season_history = {}
    for history_record, resource in rows:
        movie_id = resource.movie_id
        payload = _history_playback_payload(history_record, resource)

        movie_history.setdefault(movie_id, payload)
        if resource.season is None:
            continue

        movie_seasons = season_history.setdefault(movie_id, {})
        movie_seasons.setdefault(resource.season, payload)

    for movie_id, payload in list(movie_history.items()):
        seasons_by_number = season_history.get(movie_id, {})
        movie_history[movie_id] = {
            **payload,
            "seasons": [
                dict(seasons_by_number[season])
                for season in sorted(seasons_by_number.keys())
            ],
            "seasons_by_number": {
                str(season): dict(item)
                for season, item in seasons_by_number.items()
            },
        }

    return movie_history


def get_movie_user_history(movie_id):
    """查询单个影片最近观看状态，并带回具体资源、季、集与进度。"""
    return get_history_map([movie_id]).get(movie_id)


def get_resource_history_map(resource_ids):
    """批量查询资源级最近观看记录。"""
    if not resource_ids:
        return {}

    rows = db.session.query(History, MediaResource) \
        .join(MediaResource, History.resource_id == MediaResource.id) \
        .filter(MediaResource.id.in_(resource_ids)) \
        .order_by(MediaResource.id.asc(), *_history_ordering()) \
        .all()

    history_map = {}
    for history_record, resource in rows:
        history_map.setdefault(resource.id, _history_playback_payload(history_record, resource))
    return history_map


def build_pagination_meta(pagination, page, page_size):
    return {
        "current_page": page,
        "page_size": page_size,
        "total_items": pagination.total,
        "total_pages": pagination.pages
    }


def _safe_non_negative_int(value):
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _build_progress_info(progress, duration):
    progress = _safe_non_negative_int(progress)
    duration = _safe_non_negative_int(duration)
    ratio = None
    percent = None
    if duration > 0:
        ratio = min(progress / duration, 1)
        percent = round(ratio * 100, 2)
    return {
        "progress": progress,
        "duration": duration,
        "position_sec": progress,
        "duration_sec": duration,
        "progress_ratio": ratio,
        "progress_percent": percent,
    }


def build_history_item(history_record):
    """将 History 记录组装为接口返回项；无效关联返回 None。"""
    resource = db.session.get(MediaResource, history_record.resource_id) if history_record.resource_id else None
    if not resource or not resource.movie:
        return None

    playback_payload = _history_playback_payload(history_record, resource)

    movie_payload = resource.movie.to_simple_dict(include_season_cards=False)
    movie_payload["series_poster_url"] = playback_payload.get("series_poster_url")
    movie_payload["poster_source"] = playback_payload.get("poster_source")
    if playback_payload.get("poster_url"):
        movie_payload["poster_url"] = playback_payload["poster_url"]

    return {
        "id": history_record.id,
        "resource_id": history_record.resource_id,
        **playback_payload,
        "last_watched": history_record.last_watched.isoformat() if history_record.last_watched else None,
        "view_count": history_record.view_count,
        "device_id": history_record.device_id,
        "device_name": history_record.device_name,
        "movie": movie_payload,
        "episode_label": resource.label,
        "filename": resource.filename
    }
