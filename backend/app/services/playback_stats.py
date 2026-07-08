from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.extensions import db
from backend.app.models import History, MediaResource


PLAYBACK_STAT_WINDOWS = {
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
    "all_time": None,
}

PLAYBACK_STAT_WINDOW_ALIASES = {
    "week": "weekly",
    "weekly": "weekly",
    "month": "monthly",
    "monthly": "monthly",
    "all": "all_time",
    "all-time": "all_time",
    "all_time": "all_time",
    "alltime": "all_time",
}


def normalize_playback_stat_window(raw_window, default="all_time"):
    value = str(raw_window or default).strip().lower()
    normalized = PLAYBACK_STAT_WINDOW_ALIASES.get(value)
    if not normalized:
        raise ValueError("window must be weekly, monthly, or all_time")
    return normalized


def playback_stat_window_cutoff(window):
    normalized = normalize_playback_stat_window(window)
    delta = PLAYBACK_STAT_WINDOWS[normalized]
    if delta is None:
        return None
    return datetime.utcnow() - delta


def _play_count_expression():
    return db.case((History.view_count > 0, History.view_count), else_=1)


def movie_play_count_query(window="all_time", movie_ids=None):
    normalized_window = normalize_playback_stat_window(window)
    query = (
        db.session.query(
            MediaResource.movie_id.label("movie_id"),
            db.func.sum(_play_count_expression()).label("play_count"),
        )
        .join(MediaResource, History.resource_id == MediaResource.id)
        .filter(MediaResource.movie_id.isnot(None))
    )
    if movie_ids is not None:
        normalized_ids = [str(movie_id) for movie_id in movie_ids if movie_id]
        if not normalized_ids:
            return None
        query = query.filter(MediaResource.movie_id.in_(normalized_ids))

    cutoff = playback_stat_window_cutoff(normalized_window)
    if cutoff is not None:
        query = query.filter(History.last_watched >= cutoff)

    return query.group_by(MediaResource.movie_id)


def movie_play_count_subquery(window="all_time"):
    return movie_play_count_query(window=window).subquery()


def build_movie_play_count_map(movie_ids=None, window="all_time"):
    query = movie_play_count_query(window=window, movie_ids=movie_ids)
    if query is None:
        return {}
    return {
        movie_id: int(play_count or 0)
        for movie_id, play_count in query.all()
    }


def attach_movie_play_counts(movies, window="all_time", counts=None):
    movie_list = list(movies or [])
    if counts is None:
        counts = build_movie_play_count_map([movie.id for movie in movie_list], window=window)
    for movie in movie_list:
        setattr(movie, "_cyber_play_count", int(counts.get(movie.id, 0) or 0))
    return movie_list
