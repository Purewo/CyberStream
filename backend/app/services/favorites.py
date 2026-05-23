from __future__ import annotations

from datetime import datetime

from backend.app.extensions import db
from backend.app.models import Movie, UserFavorite
from backend.app.services.user_access import (
    apply_current_user_movie_visibility_filter,
    can_current_user_access_movie_id,
    current_user_id_for_personal_data,
)
from backend.app.services.vault import is_vault_admin_session, require_vault_unlocked


FAVORITES_LIBRARY_ID = "favorites"
FAVORITES_LIBRARY_SLUG = "favorites"


class FavoriteValidationError(ValueError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def favorite_scope_context():
    user_id = current_user_id_for_personal_data()
    return (f"user:{user_id}" if user_id is not None else "default"), user_id


def favorite_movie_query():
    require_vault_unlocked()
    scope_key, _user_id = favorite_scope_context()
    query = Movie.query.join(UserFavorite, UserFavorite.movie_id == Movie.id) \
        .filter(UserFavorite.scope_key == scope_key)
    return apply_current_user_movie_visibility_filter(query)


def favorite_movie_ids():
    return [
        row[0]
        for row in favorite_movie_query()
        .with_entities(Movie.id)
        .order_by(Movie.id.asc())
        .all()
    ]


def favorite_count():
    return favorite_movie_query().count()


def visible_vault_favorite_count():
    if not is_vault_admin_session():
        return 0
    scope_key, _user_id = favorite_scope_context()
    return UserFavorite.query.filter_by(scope_key=scope_key).count()


def favorite_created_at_map(movie_ids):
    if not movie_ids:
        return {}
    scope_key, _user_id = favorite_scope_context()
    rows = UserFavorite.query.filter(
        UserFavorite.scope_key == scope_key,
        UserFavorite.movie_id.in_(movie_ids),
    ).all()
    return {row.movie_id: row.created_at for row in rows}


def favorite_membership_map(movie_ids):
    return {movie_id: "favorite" for movie_id in (movie_ids or [])}


def build_favorites_library_payload(require_access=True):
    count = favorite_count() if require_access else visible_vault_favorite_count()
    return {
        "id": FAVORITES_LIBRARY_ID,
        "name": "我的收藏",
        "slug": FAVORITES_LIBRARY_SLUG,
        "description": "用户收藏的影视条目",
        "is_enabled": True,
        "sort_order": -100,
        "settings": {
            "virtual": True,
            "kind": "favorites",
        },
        "created_at": None,
        "updated_at": None,
        "is_virtual": True,
        "kind": "favorites",
        "movie_count": count,
        "actions": {
            "can_scan": False,
            "can_bind_sources": False,
            "can_manage_memberships": False,
            "can_delete": False,
        },
    }


def get_favorite_row(movie_id):
    scope_key, _user_id = favorite_scope_context()
    return UserFavorite.query.filter_by(scope_key=scope_key, movie_id=str(movie_id)).first()


def favorite_state(movie_id):
    require_vault_unlocked()
    row = get_favorite_row(movie_id)
    return {
        "movie_id": str(movie_id),
        "is_favorite": bool(row),
        "created_at": row.created_at.isoformat() if row and row.created_at else None,
    }


def add_favorite(movie_id):
    require_vault_unlocked()
    movie = db.session.get(Movie, str(movie_id))
    if not movie:
        raise FavoriteValidationError(40401, "Movie not found")
    if not can_current_user_access_movie_id(movie.id):
        raise FavoriteValidationError(40320, "Movie is not visible for current user")

    scope_key, user_id = favorite_scope_context()
    row = UserFavorite.query.filter_by(scope_key=scope_key, movie_id=movie.id).first()
    created = row is None
    if not row:
        row = UserFavorite(
            scope_key=scope_key,
            user_id=user_id,
            movie_id=movie.id,
            created_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()

    return {
        "favorite": row.to_dict(),
        "is_favorite": True,
        "newly_added": created,
        "library": build_favorites_library_payload(),
    }


def remove_favorite(movie_id):
    require_vault_unlocked()
    row = get_favorite_row(movie_id)
    removed = row is not None
    if row:
        db.session.delete(row)
        db.session.commit()
    return {
        "movie_id": str(movie_id),
        "is_favorite": False,
        "removed": removed,
        "library": build_favorites_library_payload() if favorite_count() > 0 else None,
    }


def list_favorites_payload(include_movies=False):
    require_vault_unlocked()
    scope_key, _user_id = favorite_scope_context()
    query = UserFavorite.query.filter_by(scope_key=scope_key).join(Movie, UserFavorite.movie_id == Movie.id)
    query = query.filter(Movie.id.in_([item for item in favorite_movie_ids()]))
    rows = query.order_by(UserFavorite.created_at.desc(), UserFavorite.id.desc()).all()
    return {
        "items": [row.to_dict(include_movie=include_movies) for row in rows],
        "movie_ids": [row.movie_id for row in rows],
        "total": len(rows),
        "library": build_favorites_library_payload() if rows else None,
    }
