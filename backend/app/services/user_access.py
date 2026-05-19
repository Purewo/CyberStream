from __future__ import annotations

from backend.app.extensions import db
from backend.app.models import Library, LibraryMovieMembership, LibrarySource, MediaResource, Movie, User, UserLibraryRule
from backend.app.security import get_current_user, is_admin_request, is_user_management_enabled


def _normalize_library_root_path(root_path):
    root_path = (root_path or '/').strip()
    if not root_path or root_path == '/':
        return '/'
    return root_path.strip('/')


def _build_library_binding_path_filter(binding):
    normalized_root = _normalize_library_root_path(binding.root_path)
    if normalized_root == '/':
        return MediaResource.source_id == binding.source_id
    return db.and_(
        MediaResource.source_id == binding.source_id,
        db.or_(
            MediaResource.path == normalized_root,
            MediaResource.path.like(f'{normalized_root}/%'),
        ),
    )


def _apply_public_movie_visibility_filter(query):
    visibility_status = db.func.coalesce(Movie.catalog_visibility_status, Movie.CATALOG_VISIBILITY_AUTO)
    manual_auto_visible = db.func.upper(Movie.scraper_source).in_(list(Movie.MANUAL_CONTENT_SOURCES))
    auto_visible = db.and_(
        db.func.upper(Movie.scraper_source).in_(list(Movie.get_metadata_non_attention_sources())),
        db.or_(
            db.and_(Movie.cover.isnot(None), Movie.cover != ""),
            manual_auto_visible,
        ),
    )
    return query.filter(
        db.or_(
            visibility_status == Movie.CATALOG_VISIBILITY_PUBLISHED,
            db.and_(
                visibility_status != Movie.CATALOG_VISIBILITY_HIDDEN,
                auto_visible,
            ),
        )
    )


def _library_movie_ids(library_id):
    library = db.session.get(Library, library_id)
    if not library or not library.is_enabled:
        return set()

    bindings = library.source_bindings.filter_by(is_enabled=True).all()
    auto_ids = set()
    if bindings:
        filters = [_build_library_binding_path_filter(binding) for binding in bindings]
        rows = (
            _apply_public_movie_visibility_filter(
                db.session.query(MediaResource.movie_id)
                .join(Movie, Movie.id == MediaResource.movie_id)
                .filter(db.or_(*filters))
                .filter(MediaResource.movie_id.isnot(None))
            )
            .distinct()
            .all()
        )
        auto_ids = {row[0] for row in rows if row[0]}

    membership_rows = LibraryMovieMembership.query.filter_by(library_id=library_id).all()
    include_ids = {row.movie_id for row in membership_rows if row.mode == 'include'}
    exclude_ids = {row.movie_id for row in membership_rows if row.mode == 'exclude'}
    return (auto_ids | include_ids) - exclude_ids


def _public_movie_ids():
    rows = _apply_public_movie_visibility_filter(db.session.query(Movie.id)).all()
    return {row[0] for row in rows if row[0]}


def _rule_sets_for_user(user_id):
    rows = UserLibraryRule.query.filter_by(user_id=user_id).all()
    allow_ids = {row.library_id for row in rows if row.mode == UserLibraryRule.MODE_ALLOW}
    deny_ids = {row.library_id for row in rows if row.mode == UserLibraryRule.MODE_DENY}
    return allow_ids, deny_ids


def _visible_movie_ids_for_user(user_id):
    user = db.session.get(User, user_id)
    if not user or not user.is_enabled:
        return frozenset()

    allow_ids, deny_ids = _rule_sets_for_user(user_id)
    if allow_ids:
        visible_ids = set()
        for library_id in allow_ids:
            visible_ids.update(_library_movie_ids(library_id))
    else:
        visible_ids = _public_movie_ids()

    for library_id in deny_ids:
        visible_ids.difference_update(_library_movie_ids(library_id))

    return frozenset(visible_ids)


def rule_sets_for_user(user_id):
    allow_ids, deny_ids = _rule_sets_for_user(user_id)
    return set(allow_ids), set(deny_ids)


def library_movie_ids(library_id):
    return set(_library_movie_ids(library_id))


def visible_movie_ids_for_user(user_id):
    return _visible_movie_ids_for_user(user_id)


def visible_library_ids_for_user(user_id):
    user = db.session.get(User, user_id)
    if not user or not user.is_enabled:
        return set()
    allow_ids, deny_ids = _rule_sets_for_user(user_id)
    if allow_ids:
        library_ids = set(allow_ids)
    else:
        library_ids = {
            row[0]
            for row in db.session.query(Library.id).filter_by(is_enabled=True).all()
        }
    return library_ids - deny_ids


def build_user_visibility_preview(user, sample_limit=12):
    sample_limit = max(0, min(int(sample_limit or 0), 50))
    allow_ids, deny_ids = rule_sets_for_user(user.id)
    visible_library_ids = visible_library_ids_for_user(user.id)
    visible_movie_ids = visible_movie_ids_for_user(user.id)
    default_scope = "disabled_user" if not user.is_enabled else ("allow_libraries" if allow_ids else "all_libraries")

    library_items = []
    libraries = Library.query.order_by(Library.sort_order.asc(), Library.id.asc()).all()
    for library in libraries:
        movie_ids = library_movie_ids(library.id)
        if library.id in allow_ids:
            rule_mode = UserLibraryRule.MODE_ALLOW
        elif library.id in deny_ids:
            rule_mode = UserLibraryRule.MODE_DENY
        else:
            rule_mode = "implicit"
        library_items.append({
            "id": library.id,
            "name": library.name,
            "slug": library.slug,
            "is_enabled": bool(library.is_enabled),
            "rule_mode": rule_mode,
            "visible": library.id in visible_library_ids,
            "public_movie_count": len(movie_ids),
            "visible_movie_count": len(movie_ids.intersection(visible_movie_ids)),
        })

    sample_movies = []
    if visible_movie_ids and sample_limit > 0:
        sample_movies = [
            movie.to_simple_dict(include_season_cards=False)
            for movie in (
                Movie.query
                .filter(Movie.id.in_(list(visible_movie_ids)))
                .order_by(Movie.added_at.desc(), Movie.id.asc())
                .limit(sample_limit)
                .all()
            )
        ]

    return {
        "user": user.to_dict(include_rules=True),
        "default_scope": default_scope,
        "allow_library_ids": sorted(allow_ids),
        "deny_library_ids": sorted(deny_ids),
        "visible_library_ids": sorted(visible_library_ids),
        "visible_movie_count": len(visible_movie_ids),
        "sample_limit": sample_limit,
        "sample_movies": sample_movies,
        "libraries": library_items,
    }


def clear_user_access_cache():
    return None


def current_user_id_for_personal_data():
    if not is_user_management_enabled():
        return None
    user = get_current_user()
    return user.id if user else None


def current_visible_movie_ids():
    if not is_user_management_enabled() or is_admin_request():
        return None
    user = get_current_user()
    if not user:
        return frozenset()
    return _visible_movie_ids_for_user(user.id)


def apply_current_user_movie_visibility_filter(query):
    visible_ids = current_visible_movie_ids()
    if visible_ids is None:
        return query
    if not visible_ids:
        return query.filter(db.false())
    return query.filter(Movie.id.in_(list(visible_ids)))


def can_current_user_access_movie_id(movie_id):
    if not is_user_management_enabled() or is_admin_request():
        return True
    visible_ids = current_visible_movie_ids() or frozenset()
    return str(movie_id) in visible_ids


def can_current_user_access_resource_id(resource_id):
    if not is_user_management_enabled() or is_admin_request():
        return True
    resource = db.session.get(MediaResource, str(resource_id))
    return bool(resource and can_current_user_access_movie_id(resource.movie_id))


def visible_library_ids_for_current_user():
    if not is_user_management_enabled() or is_admin_request():
        return None
    user = get_current_user()
    if not user:
        return set()
    return visible_library_ids_for_user(user.id)


def can_current_user_access_library_id(library_id):
    visible_ids = visible_library_ids_for_current_user()
    if visible_ids is None:
        return True
    return int(library_id) in visible_ids
