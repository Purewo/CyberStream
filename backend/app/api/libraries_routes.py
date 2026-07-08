import logging
import threading

from flask import Blueprint, current_app, request

from backend.app.api.helpers import build_pagination_meta, get_history_map, get_json_object_payload
from backend.app.api.library_helpers import (
    apply_movie_filters,
    apply_public_movie_visibility_filter,
    attach_recommendation_payload,
    build_filter_options_from_rows,
    build_library_movie_id_context,
    get_recommendation_items_from_query,
    normalize_recommendation_strategy,
    resolve_movie_sort_column,
)
from backend.app.extensions import db
from backend.app.models import Library, LibraryMovieMembership, LibrarySource, MediaResource, Movie, StorageSource, UserFavorite
from backend.app.providers.base import StorageProviderError
from backend.app.providers.factory import provider_factory
from backend.app.services.favorites import (
    FAVORITES_LIBRARY_ID,
    build_favorites_library_payload,
    favorite_count,
    favorite_membership_map,
    favorite_movie_query,
)
from backend.app.services.metadata_policy import ScraperPolicyError, normalize_scraper_policy_payload
from backend.app.services.scanner import scanner_engine
from backend.app.services.accounts import account_scope, get_account_scoped
from backend.app.services.filter_options_cache import get_cached_filter_payload, normalize_filter_includes
from backend.app.services.playback_stats import attach_movie_play_counts
from backend.app.services.user_access import (
    apply_current_user_movie_visibility_filter,
    clear_user_access_cache,
    visible_library_ids_for_current_user,
)
from backend.app.services.vault import VaultAccessError, require_vault_unlocked
from backend.app.security import get_current_account_id, is_admin_request
from backend.app.storage.source_registry import get_source_capabilities
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

libraries_bp = Blueprint('libraries', __name__, url_prefix='/api/v1')

LIBRARY_MOVIE_MEMBERSHIP_MODES = {'include', 'exclude'}


def _get_json_payload():
    return get_json_object_payload()


def _normalize_page_args():
    page = request.args.get('page', 1, type=int) or 1
    page_size = request.args.get('page_size', 20, type=int) or 20
    return max(page, 1), min(max(page_size, 1), 100)


def _empty_movie_list_payload(page, page_size):
    return {
        "items": [],
        "total": 0,
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_items": 0,
            "total_pages": 0,
        },
    }


def _normalize_root_path(root_path):
    if root_path is not None and not isinstance(root_path, str):
        raise ValueError("Invalid field type: root_path should be string")
    root_path = (root_path or '/').strip()
    if not root_path or root_path == '/':
        return '/'
    return root_path.strip('/')


def _normalize_request_text(value, *, field_name, default=None, strip=True):
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"Invalid field type: {field_name} should be string")
    return value.strip() if strip else value


def _build_binding_path_filter(binding):
    normalized_root = _normalize_root_path(binding.root_path)
    if normalized_root == '/':
        return MediaResource.source_id == binding.source_id

    return db.and_(
        MediaResource.source_id == binding.source_id,
        db.or_(
            MediaResource.path == normalized_root,
            MediaResource.path.like(f'{normalized_root}/%'),
        )
    )


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
    raise ValueError(f"Invalid field type: {field_name} should be boolean")


def _normalize_request_int(value, *, default=0, field_name="value"):
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"Invalid field type: {field_name} should be integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return default
        try:
            return int(normalized)
        except ValueError:
            pass
    raise ValueError(f"Invalid field type: {field_name} should be integer")


def _source_refresh_supported(source):
    if not source:
        return False
    try:
        _, capabilities = get_source_capabilities(source.type)
    except StorageProviderError:
        return False
    return bool(capabilities.get('refresh'))


def _refresh_library_binding_source(library_id, binding):
    source = binding.source
    if not source or not _source_refresh_supported(source):
        return []

    root_path = binding.root_path or '/'
    try:
        provider = provider_factory.get_provider(source)
    except Exception as e:
        logger.warning(
            'Library scan refresh provider unavailable library_id=%s source_id=%s root_path=%s error=%s',
            library_id,
            source.id,
            root_path,
            e,
        )
        return [(root_path, e)]

    try:
        provider.refresh_directory(root_path)
    except Exception as e:
        logger.warning(
            'Library scan refresh failed library_id=%s source_id=%s root_path=%s error=%s',
            library_id,
            source.id,
            root_path,
            e,
        )
        return [(root_path, e)]
    return []


def _scan_library_background_task(app, library_id, refresh=True, account_id=None):
    with app.app_context():
        with account_scope(account_id):
            session_started = False
            try:
                library = get_account_scoped(Library, library_id)
                if not library:
                    logger.warning('Library scan skipped library_id=%s reason=not_found', library_id)
                    return

                bindings = _get_enabled_library_bindings(library)
                if not bindings:
                    logger.info('Library scan skipped library_id=%s reason=no_bindings', library_id)
                    return

                scanner_engine._begin_scan_session(current_source=f'library:{library.name}')
                session_started = True
                app_instance = current_app._get_current_object()
                refresh_errors = []
                for binding in bindings:
                    if not binding.source or not binding.is_enabled:
                        continue
                    if refresh:
                        refresh_errors.extend(_refresh_library_binding_source(library_id, binding))
                    scanner_engine.scan_source(
                        binding.source,
                        app_instance=app_instance,
                        root_path=binding.root_path,
                        content_type=binding.content_type,
                        scrape_enabled=binding.scrape_enabled,
                        library_id=binding.library_id,
                        library_source_id=binding.id,
                        scraper_policy=binding.scraper_policy or {},
                    )
                for path, error in refresh_errors:
                    scanner_engine._record_indexing_directory_skip(path, error)
            except Exception as e:
                logger.exception('Library scan failed library_id=%s error=%s', library_id, e)
            finally:
                if session_started:
                    scanner_engine._finish_scan_session()
                scanner_engine.finish_scan()
                logger.info('Library scan finished library_id=%s', library_id)


def _get_library_or_404(id):
    library = get_account_scoped(Library, id)
    if not library:
        return None, api_error(code=40410, msg='Library not found', http_status=404)
    return library, None


def _get_enabled_library_bindings(library):
    return library.source_bindings.filter_by(is_enabled=True).order_by(LibrarySource.scan_order.asc(), LibrarySource.id.asc()).all()


def _get_library_auto_movie_ids(library):
    bindings = _get_enabled_library_bindings(library)
    if not bindings:
        return set(), bindings

    filters = [_build_binding_path_filter(binding) for binding in bindings]
    query = (
        db.session.query(MediaResource.movie_id)
        .join(Movie, Movie.id == MediaResource.movie_id)
        .filter(db.or_(*filters))
        .filter(MediaResource.movie_id.isnot(None))
    )
    rows = apply_public_movie_visibility_filter(query).distinct().all()
    return {row[0] for row in rows if row[0]}, bindings


def _build_library_movie_context(library):
    return build_library_movie_id_context(library)


def _build_library_movie_query(library):
    context = _build_library_movie_context(library)
    final_ids = context["final_ids"]
    if not final_ids:
        return None, context

    query = Movie.query.filter(Movie.id.in_(list(final_ids)))
    query = apply_current_user_movie_visibility_filter(query)
    return query, context


def _get_library_movies(library, order_by=None, limit=None):
    query, context = _build_library_movie_query(library)
    if query is None:
        return [], context

    if order_by is not None:
        query = query.order_by(*order_by)

    if limit is not None:
        query = query.limit(limit)

    movies = query.all()
    attach_movie_play_counts(movies)
    return movies, context


def _serialize_library_movie(movie, membership_map, user_history=None, detail=False):
    data = movie.to_detail_dict(user_history=user_history) if detail else movie.to_simple_dict(user_history=user_history)
    data["library_membership"] = membership_map.get(movie.id, "auto")
    return data


def _favorites_library_or_404():
    try:
        require_vault_unlocked()
    except VaultAccessError as e:
        return None, api_error(code=e.code, msg=e.msg, http_status=e.http_status)
    if favorite_count() <= 0:
        return None, api_error(code=40410, msg='Library not found', http_status=404)
    return build_favorites_library_payload(), None


def _favorite_query_and_memberships():
    query = favorite_movie_query()
    movie_ids = [row[0] for row in query.with_entities(Movie.id).all()]
    return query, favorite_membership_map(movie_ids)


def _normalize_membership_mode(raw_mode):
    mode = (raw_mode or 'include').strip().lower() if isinstance(raw_mode, str) else ''
    return mode if mode in LIBRARY_MOVIE_MEMBERSHIP_MODES else None


def _normalize_membership_movie_ids(raw_movie_ids):
    if not isinstance(raw_movie_ids, list) or not raw_movie_ids:
        return None, api_error(code=40013, msg='movie_ids must be a non-empty array')

    movie_ids = []
    seen = set()
    for raw_movie_id in raw_movie_ids:
        if not isinstance(raw_movie_id, str):
            return None, api_error(code=40014, msg='movie_ids must contain movie id strings')
        movie_id = raw_movie_id.strip()
        if not movie_id:
            return None, api_error(code=40015, msg='movie_ids must not contain empty values')
        if movie_id in seen:
            continue
        seen.add(movie_id)
        movie_ids.append(movie_id)

    existing_ids = {
        row[0]
        for row in db.session.query(Movie.id).filter(Movie.id.in_(movie_ids)).all()
    }
    missing_ids = [movie_id for movie_id in movie_ids if movie_id not in existing_ids]
    if missing_ids:
        return None, api_error(code=40412, msg=f'Movie not found: {missing_ids[0]}', http_status=404)

    return movie_ids, None


@libraries_bp.route('/libraries', methods=['GET'])
def list_libraries():
    query = Library.query
    visible_ids = visible_library_ids_for_current_user()
    if visible_ids is not None:
        query = query.filter(Library.id.in_(list(visible_ids))) if visible_ids else query.filter(db.false())
    libraries = query.order_by(Library.sort_order.asc(), Library.id.asc()).all()
    return api_response(data=[library.to_dict() for library in libraries])


@libraries_bp.route('/libraries', methods=['POST'])
def create_library():
    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    allowed = {'name', 'slug', 'description', 'is_enabled', 'sort_order', 'settings'}
    unknown = sorted([key for key in payload.keys() if key not in allowed])
    if unknown:
        return api_error(code=40004, msg=f"Unsupported fields: {', '.join(unknown)}")

    try:
        name = _normalize_request_text(payload.get('name'), field_name='name', default='')
        slug = _normalize_request_text(payload.get('slug'), field_name='slug', default='')
        description = _normalize_request_text(
            payload.get('description'),
            field_name='description',
            default=None,
            strip=False,
        )
    except ValueError as e:
        return api_error(code=40018, msg=str(e))

    if not name or not slug:
        return api_error(code=40001, msg='Missing required fields: name, slug')

    if Library.query.filter((Library.name == name) | (Library.slug == slug)).first():
        return api_error(code=40003, msg='Library name or slug already exists')

    try:
        is_enabled = _normalize_request_bool(payload.get('is_enabled'), default=True, field_name='is_enabled')
        sort_order = _normalize_request_int(payload.get('sort_order'), default=0, field_name='sort_order')
    except ValueError as e:
        return api_error(code=40018, msg=str(e))

    settings = payload.get('settings')
    if settings is not None and not isinstance(settings, dict):
        return api_error(code=40009, msg='Invalid field type: settings should be object')

    library = Library(
        name=name,
        slug=slug,
        description=description,
        is_enabled=is_enabled,
        sort_order=sort_order,
        settings=settings or {},
    )
    db.session.add(library)
    db.session.commit()
    clear_user_access_cache()
    return api_response(data=library.to_dict(), msg='Library created', http_status=201)


@libraries_bp.route('/libraries/<int:id>', methods=['GET'])
def get_library(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response
    return api_response(data=library.to_dict(include_sources=is_admin_request()))


@libraries_bp.route('/libraries/favorites', methods=['GET'])
def get_favorites_library():
    library, error_response = _favorites_library_or_404()
    if error_response:
        return error_response
    library["sources"] = []
    return api_response(data=library)


@libraries_bp.route('/libraries/<int:id>', methods=['PATCH'])
def update_library(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    allowed = {'name', 'slug', 'description', 'is_enabled', 'sort_order', 'settings'}
    unknown = sorted([k for k in payload.keys() if k not in allowed])
    if unknown:
        return api_error(code=40004, msg=f"Unsupported fields: {', '.join(unknown)}")

    try:
        if 'name' in payload:
            name = _normalize_request_text(payload.get('name'), field_name='name', default='')
            if not name:
                return api_error(code=40005, msg='Invalid field value: name cannot be empty')
            existing = Library.query.filter(Library.name == name, Library.id != id).first()
            if existing:
                return api_error(code=40006, msg='Library name already exists')
            library.name = name

        if 'slug' in payload:
            slug = _normalize_request_text(payload.get('slug'), field_name='slug', default='')
            if not slug:
                return api_error(code=40007, msg='Invalid field value: slug cannot be empty')
            existing = Library.query.filter(Library.slug == slug, Library.id != id).first()
            if existing:
                return api_error(code=40008, msg='Library slug already exists')
            library.slug = slug

        if 'description' in payload:
            library.description = _normalize_request_text(
                payload.get('description'),
                field_name='description',
                default=None,
                strip=False,
            )
        if 'is_enabled' in payload:
            library.is_enabled = _normalize_request_bool(payload.get('is_enabled'), default=bool(library.is_enabled), field_name='is_enabled')
        if 'sort_order' in payload:
            library.sort_order = _normalize_request_int(payload.get('sort_order'), default=0, field_name='sort_order')
        if 'settings' in payload:
            settings = payload.get('settings')
            if settings is not None and not isinstance(settings, dict):
                return api_error(code=40009, msg='Invalid field type: settings should be object')
            library.settings = settings or {}

        db.session.commit()
        clear_user_access_cache()
        return api_response(data=library.to_dict(), msg='Library updated')
    except ValueError as e:
        db.session.rollback()
        return api_error(code=40018, msg=str(e))
    except Exception as e:
        db.session.rollback()
        logger.exception('Update library failed id=%s error=%s', id, e)
        return api_error(code=50009, msg='Update failed', http_status=500)


@libraries_bp.route('/libraries/<int:id>', methods=['DELETE'])
def delete_library(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    try:
        db.session.delete(library)
        db.session.commit()
        clear_user_access_cache()
        return api_response(msg='Library deleted')
    except Exception as e:
        db.session.rollback()
        logger.exception('Delete library failed id=%s error=%s', id, e)
        return api_error(code=50010, msg='Delete failed', http_status=500)


@libraries_bp.route('/libraries/<int:id>/sources', methods=['GET'])
def list_library_sources(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    bindings = library.source_bindings.order_by(LibrarySource.scan_order.asc(), LibrarySource.id.asc()).all()
    return api_response(data=[binding.to_dict() for binding in bindings])


@libraries_bp.route('/libraries/<int:id>/sources', methods=['POST'])
def bind_library_source(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    try:
        source_id = _normalize_request_int(payload.get('source_id'), default=None, field_name='source_id')
    except ValueError as e:
        return api_error(code=40018, msg=str(e))
    if source_id is None:
        return api_error(code=40001, msg='Missing required field: source_id')

    source = get_account_scoped(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg='Source not found', http_status=404)

    try:
        root_path = _normalize_root_path(payload.get('root_path'))
        content_type = _normalize_request_text(payload.get('content_type'), field_name='content_type', default=None)
        scrape_enabled = _normalize_request_bool(payload.get('scrape_enabled'), default=True, field_name='scrape_enabled')
        scan_order = _normalize_request_int(payload.get('scan_order'), default=0, field_name='scan_order')
        is_enabled = _normalize_request_bool(payload.get('is_enabled'), default=True, field_name='is_enabled')
        scraper_policy = normalize_scraper_policy_payload(
            raw_policy=payload.get('scraper_policy'),
            provider_order=payload.get('provider_order') or payload.get('providers'),
        )
    except ValueError as e:
        return api_error(code=40018, msg=str(e))
    except ScraperPolicyError as e:
        return api_error(code=e.code, msg=e.msg)

    exists = LibrarySource.query.filter_by(library_id=id, source_id=source_id, root_path=root_path).first()
    if exists:
        return api_error(code=40011, msg='Library source binding already exists')

    binding = LibrarySource(
        library_id=id,
        source_id=source_id,
        root_path=root_path,
        content_type=content_type,
        scrape_enabled=scrape_enabled,
        scraper_policy=scraper_policy,
        scan_order=scan_order,
        is_enabled=is_enabled,
    )
    db.session.add(binding)
    db.session.commit()
    clear_user_access_cache()
    return api_response(data=binding.to_dict(), msg='Library source bound', http_status=201)


@libraries_bp.route('/libraries/<int:id>/sources/<int:binding_id>', methods=['PATCH'])
def update_library_source(id, binding_id):
    binding = LibrarySource.query.filter_by(id=binding_id, library_id=id).first()
    if not binding:
        return api_error(code=40411, msg='Library source binding not found', http_status=404)

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    allowed = {'root_path', 'content_type', 'scrape_enabled', 'scraper_policy', 'provider_order', 'providers', 'scan_order', 'is_enabled'}
    unknown = sorted([k for k in payload.keys() if k not in allowed])
    if unknown:
        return api_error(code=40004, msg=f"Unsupported fields: {', '.join(unknown)}")

    try:
        if 'root_path' in payload:
            binding.root_path = _normalize_root_path(payload.get('root_path'))
        if 'content_type' in payload:
            binding.content_type = _normalize_request_text(payload.get('content_type'), field_name='content_type', default=None)
        if 'scrape_enabled' in payload:
            binding.scrape_enabled = _normalize_request_bool(payload.get('scrape_enabled'), default=bool(binding.scrape_enabled), field_name='scrape_enabled')
        if 'scraper_policy' in payload or 'provider_order' in payload or 'providers' in payload:
            binding.scraper_policy = normalize_scraper_policy_payload(
                raw_policy=payload.get('scraper_policy'),
                provider_order=payload.get('provider_order') or payload.get('providers'),
            )
        if 'scan_order' in payload:
            binding.scan_order = _normalize_request_int(payload.get('scan_order'), default=0, field_name='scan_order')
        if 'is_enabled' in payload:
            binding.is_enabled = _normalize_request_bool(payload.get('is_enabled'), default=bool(binding.is_enabled), field_name='is_enabled')

        db.session.commit()
        clear_user_access_cache()
        return api_response(data=binding.to_dict(), msg='Library source updated')
    except ValueError as e:
        db.session.rollback()
        return api_error(code=40018, msg=str(e))
    except ScraperPolicyError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.msg)
    except Exception as e:
        db.session.rollback()
        logger.exception('Update library source failed binding_id=%s error=%s', binding_id, e)
        return api_error(code=50011, msg='Update failed', http_status=500)


@libraries_bp.route('/libraries/<int:id>/sources/<int:binding_id>', methods=['DELETE'])
def delete_library_source(id, binding_id):
    binding = LibrarySource.query.filter_by(id=binding_id, library_id=id).first()
    if not binding:
        return api_error(code=40411, msg='Library source binding not found', http_status=404)

    try:
        db.session.delete(binding)
        db.session.commit()
        clear_user_access_cache()
        return api_response(msg='Library source unbound')
    except Exception as e:
        db.session.rollback()
        logger.exception('Delete library source failed binding_id=%s error=%s', binding_id, e)
        return api_error(code=50010, msg='Delete failed', http_status=500)


@libraries_bp.route('/libraries/<int:id>/movie-memberships', methods=['GET'])
def list_library_movie_memberships(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    mode = request.args.get('mode')
    query = LibraryMovieMembership.query.filter_by(library_id=library.id)
    if mode:
        normalized_mode = _normalize_membership_mode(mode)
        if not normalized_mode:
            return api_error(code=40016, msg='mode must be include or exclude')
        query = query.filter_by(mode=normalized_mode)

    memberships = query.order_by(
        LibraryMovieMembership.mode.asc(),
        LibraryMovieMembership.sort_order.asc(),
        LibraryMovieMembership.id.asc(),
    ).all()
    return api_response(data=[membership.to_dict() for membership in memberships])


@libraries_bp.route('/libraries/<int:id>/movie-memberships', methods=['POST'])
def upsert_library_movie_memberships(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    mode = _normalize_membership_mode(payload.get('mode'))
    if not mode:
        return api_error(code=40016, msg='mode must be include or exclude')

    movie_ids, error_response = _normalize_membership_movie_ids(payload.get('movie_ids'))
    if error_response:
        return error_response

    try:
        base_sort_order = int(payload.get('sort_order') or 0)
    except (TypeError, ValueError):
        return api_error(code=40017, msg='sort_order must be an integer')

    existing_rows = {
        row.movie_id: row
        for row in LibraryMovieMembership.query.filter(
            LibraryMovieMembership.library_id == library.id,
            LibraryMovieMembership.movie_id.in_(movie_ids),
        ).all()
    }

    saved_rows = []
    for index, movie_id in enumerate(movie_ids):
        membership = existing_rows.get(movie_id)
        if not membership:
            membership = LibraryMovieMembership(library_id=library.id, movie_id=movie_id)
            db.session.add(membership)
        membership.mode = mode
        membership.sort_order = base_sort_order + index
        saved_rows.append(membership)

    db.session.commit()
    clear_user_access_cache()
    return api_response(data=[membership.to_dict() for membership in saved_rows], msg='Library movie memberships saved')


@libraries_bp.route('/libraries/<int:id>/movie-memberships/delete', methods=['POST'])
def delete_library_movie_memberships(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    movie_ids, error_response = _normalize_membership_movie_ids(payload.get('movie_ids'))
    if error_response:
        return error_response

    deleted_count = LibraryMovieMembership.query.filter(
        LibraryMovieMembership.library_id == library.id,
        LibraryMovieMembership.movie_id.in_(movie_ids),
    ).delete(synchronize_session=False)
    db.session.commit()
    clear_user_access_cache()
    return api_response(data={"deleted_count": deleted_count}, msg='Library movie memberships deleted')


@libraries_bp.route('/libraries/<int:id>/movies', methods=['GET'])
def list_library_movies(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    page, page_size = _normalize_page_args()
    sort_by = request.args.get('sort_by', 'updated_at')
    order = request.args.get('order', 'desc')
    genre = request.args.get('genre')
    country = request.args.get('country')
    year_param = request.args.get('year')

    query, context = _build_library_movie_query(library)
    if query is None:
        return api_response(data=_empty_movie_list_payload(page, page_size))

    query = apply_movie_filters(
        query,
        genre=genre,
        country=country,
        year_param=year_param,
    )

    sort_column = resolve_movie_sort_column(sort_by)
    query = query.order_by(sort_column.asc() if order == 'asc' else sort_column.desc())
    query = query.order_by(Movie.id.asc())

    pagination = query.paginate(page=page, per_page=page_size, error_out=False)
    movies = pagination.items
    membership_map = context["membership_map"]
    history_map = get_history_map([movie.id for movie in movies])
    return api_response(data={
        "items": [
            _serialize_library_movie(movie, membership_map, user_history=history_map.get(movie.id))
            for movie in movies
        ],
        "total": pagination.total,
        "pagination": build_pagination_meta(pagination, page, page_size),
    })


@libraries_bp.route('/libraries/favorites/movies', methods=['GET'])
def list_favorite_library_movies():
    _library, error_response = _favorites_library_or_404()
    if error_response:
        return error_response

    page, page_size = _normalize_page_args()
    sort_by = request.args.get('sort_by', 'favorited_at')
    order = request.args.get('order', 'desc')
    query, membership_map = _favorite_query_and_memberships()

    if sort_by == 'favorited_at':
        sort_column = UserFavorite.created_at
    else:
        sort_column = resolve_movie_sort_column(sort_by)
    query = query.order_by(sort_column.asc() if order == 'asc' else sort_column.desc())
    query = query.order_by(Movie.id.asc())

    pagination = query.paginate(page=page, per_page=page_size, error_out=False)
    movies = pagination.items
    history_map = get_history_map([movie.id for movie in movies])
    return api_response(data={
        "items": [
            _serialize_library_movie(movie, membership_map, user_history=history_map.get(movie.id))
            for movie in movies
        ],
        "total": pagination.total,
        "pagination": build_pagination_meta(pagination, page, page_size),
    })


@libraries_bp.route('/libraries/<int:id>/featured', methods=['GET'])
def get_library_featured(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    limit = request.args.get('limit', 5, type=int)
    movies, context = _get_library_movies(
        library,
        order_by=[Movie.rating.desc(), Movie.added_at.desc(), Movie.id.asc()],
    )
    movies = [movie for movie in movies if movie.background_cover][:max(limit, 0)]
    membership_map = context["membership_map"]
    history_map = get_history_map([movie.id for movie in movies])

    return api_response(data=[
        _serialize_library_movie(movie, membership_map, user_history=history_map.get(movie.id), detail=True)
        for movie in movies
    ])


@libraries_bp.route('/libraries/favorites/featured', methods=['GET'])
def get_favorite_library_featured():
    _library, error_response = _favorites_library_or_404()
    if error_response:
        return error_response

    limit = request.args.get('limit', 5, type=int)
    query, membership_map = _favorite_query_and_memberships()
    movies = query.filter(
        Movie.background_cover.isnot(None),
        Movie.background_cover != "",
    ).order_by(Movie.rating.desc(), UserFavorite.created_at.desc(), Movie.id.asc()).limit(max(limit, 0)).all()
    history_map = get_history_map([movie.id for movie in movies])
    return api_response(data=[
        _serialize_library_movie(movie, membership_map, user_history=history_map.get(movie.id), detail=True)
        for movie in movies
    ])


@libraries_bp.route('/libraries/<int:id>/recommendations', methods=['GET'])
def get_library_recommendations(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    limit = request.args.get('limit', 12, type=int)
    strategy = normalize_recommendation_strategy(request.args.get('strategy', 'default'))

    query, context = _build_library_movie_query(library)
    if query is None:
        return api_response(data=[])

    recommendation_items = get_recommendation_items_from_query(query, limit=limit, strategy=strategy)
    movies = [item["movie"] for item in recommendation_items]
    membership_map = context["membership_map"]
    history_map = get_history_map([movie.id for movie in movies])
    return api_response(data=[
        attach_recommendation_payload(
            _serialize_library_movie(
                item["movie"],
                membership_map,
                user_history=history_map.get(item["movie"].id),
            ),
            item,
            strategy=strategy,
            rank=index,
        )
        for index, item in enumerate(recommendation_items, start=1)
    ])


@libraries_bp.route('/libraries/favorites/recommendations', methods=['GET'])
def get_favorite_library_recommendations():
    _library, error_response = _favorites_library_or_404()
    if error_response:
        return error_response

    limit = request.args.get('limit', 12, type=int)
    strategy = normalize_recommendation_strategy(request.args.get('strategy', 'default'))
    query, membership_map = _favorite_query_and_memberships()
    recommendation_items = get_recommendation_items_from_query(query, limit=limit, strategy=strategy)
    movies = [item["movie"] for item in recommendation_items]
    history_map = get_history_map([movie.id for movie in movies])
    return api_response(data=[
        attach_recommendation_payload(
            _serialize_library_movie(
                item["movie"],
                membership_map,
                user_history=history_map.get(item["movie"].id),
            ),
            item,
            strategy=strategy,
            rank=index,
        )
        for index, item in enumerate(recommendation_items, start=1)
    ])


def _build_library_filter_options(library, includes):
    query, _ = _build_library_movie_query(library)
    if query is None:
        return {key: [] for key in includes}
    rows = query.with_entities(Movie.category, Movie.year, Movie.country).all()
    return build_filter_options_from_rows(rows, includes)


def _build_favorite_library_filter_options(includes):
    query, _membership_map = _favorite_query_and_memberships()
    rows = query.with_entities(Movie.category, Movie.year, Movie.country).all()
    return build_filter_options_from_rows(rows, includes)


@libraries_bp.route('/libraries/<int:id>/filters', methods=['GET'])
def get_library_filters(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    include_param = request.args.get('include')
    includes = normalize_filter_includes(include_param, default=['genres', 'years', 'countries'])
    data = get_cached_filter_payload(
        "library_filters",
        includes,
        lambda: _build_library_filter_options(library, includes),
        extra_key=str(id),
    )
    return api_response(data=data)


@libraries_bp.route('/libraries/favorites/filters', methods=['GET'])
def get_favorite_library_filters():
    _library, error_response = _favorites_library_or_404()
    if error_response:
        return error_response

    include_param = request.args.get('include')
    includes = normalize_filter_includes(include_param, default=['genres', 'years', 'countries'])
    data = get_cached_filter_payload(
        "favorite_library_filters",
        includes,
        lambda: _build_favorite_library_filter_options(includes),
        extra_key="favorites",
    )
    return api_response(data=data)


@libraries_bp.route('/libraries/<int:id>/scan', methods=['POST'])
def trigger_library_scan(id):
    payload = _get_json_payload()
    try:
        refresh = _normalize_request_bool(payload.get('refresh'), default=True)
    except ValueError as exc:
        return api_error(code=40090, msg=str(exc))

    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    bindings = _get_enabled_library_bindings(library)
    if not bindings:
        return api_error(code=40012, msg='Library has no enabled source bindings')

    if not scanner_engine.try_start_scan():
        return api_error(code=42900, msg='Scanner is already running', http_status=429)

    app = current_app._get_current_object()
    account_id = get_current_account_id() or library.account_id
    thread = threading.Thread(target=_scan_library_background_task, args=(app, id, refresh, account_id))
    thread.start()
    return api_response(msg='Library scan task accepted', http_status=202)
