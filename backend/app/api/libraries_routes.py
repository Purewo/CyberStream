import logging
import threading
from collections import Counter

from flask import Blueprint, current_app, request

from backend.app.api.helpers import build_pagination_meta, get_history_map
from backend.app.api.library_helpers import (
    apply_public_movie_visibility_filter,
    attach_recommendation_payload,
    build_library_movie_id_context,
    get_recommendation_items_from_query,
    normalize_recommendation_strategy,
    resolve_movie_sort_column,
)
from backend.app.extensions import db
from backend.app.models import Library, LibraryMovieMembership, LibrarySource, MediaResource, Movie, StorageSource
from backend.app.services.scanner import scanner_engine
from backend.app.utils.genres import normalize_genres
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

libraries_bp = Blueprint('libraries', __name__, url_prefix='/api/v1')

LIBRARY_MOVIE_MEMBERSHIP_MODES = {'include', 'exclude'}


def _get_json_payload():
    return request.get_json(silent=True) or {}


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
    root_path = (root_path or '/').strip()
    if not root_path or root_path == '/':
        return '/'
    return root_path.strip('/')


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


def _scan_library_background_task(app, library_id):
    with app.app_context():
        session_started = False
        try:
            library = db.session.get(Library, library_id)
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
            for binding in bindings:
                if not binding.source or not binding.is_enabled:
                    continue
                scanner_engine.scan_source(binding.source, app_instance=app_instance, root_path=binding.root_path)
        except Exception as e:
            logger.exception('Library scan failed library_id=%s error=%s', library_id, e)
        finally:
            if session_started:
                scanner_engine._finish_scan_session()
            scanner_engine.finish_scan()
            logger.info('Library scan finished library_id=%s', library_id)


def _get_library_or_404(id):
    library = db.session.get(Library, id)
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
    return query, context


def _get_library_movies(library, order_by=None, limit=None):
    query, context = _build_library_movie_query(library)
    if query is None:
        return [], context

    if order_by is not None:
        query = query.order_by(*order_by)

    if limit is not None:
        query = query.limit(limit)

    return query.all(), context


def _serialize_library_movie(movie, membership_map, user_history=None, detail=False):
    data = movie.to_detail_dict(user_history=user_history) if detail else movie.to_simple_dict(user_history=user_history)
    data["library_membership"] = membership_map.get(movie.id, "auto")
    return data


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
    libraries = Library.query.order_by(Library.sort_order.asc(), Library.id.asc()).all()
    return api_response(data=[library.to_dict() for library in libraries])


@libraries_bp.route('/libraries', methods=['POST'])
def create_library():
    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    name = (payload.get('name') or '').strip()
    slug = (payload.get('slug') or '').strip()
    allowed = {'name', 'slug', 'description', 'is_enabled', 'sort_order', 'settings'}
    unknown = sorted([key for key in payload.keys() if key not in allowed])
    if unknown:
        return api_error(code=40004, msg=f"Unsupported fields: {', '.join(unknown)}")

    if not name or not slug:
        return api_error(code=40001, msg='Missing required fields: name, slug')

    if Library.query.filter((Library.name == name) | (Library.slug == slug)).first():
        return api_error(code=40003, msg='Library name or slug already exists')

    library = Library(
        name=name,
        slug=slug,
        description=payload.get('description'),
        is_enabled=payload.get('is_enabled', True),
        sort_order=payload.get('sort_order', 0),
        settings=payload.get('settings') or {},
    )
    db.session.add(library)
    db.session.commit()
    return api_response(data=library.to_dict(), msg='Library created', http_status=201)


@libraries_bp.route('/libraries/<int:id>', methods=['GET'])
def get_library(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response
    return api_response(data=library.to_dict(include_sources=True))


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
            name = (payload.get('name') or '').strip()
            if not name:
                return api_error(code=40005, msg='Invalid field value: name cannot be empty')
            existing = Library.query.filter(Library.name == name, Library.id != id).first()
            if existing:
                return api_error(code=40006, msg='Library name already exists')
            library.name = name

        if 'slug' in payload:
            slug = (payload.get('slug') or '').strip()
            if not slug:
                return api_error(code=40007, msg='Invalid field value: slug cannot be empty')
            existing = Library.query.filter(Library.slug == slug, Library.id != id).first()
            if existing:
                return api_error(code=40008, msg='Library slug already exists')
            library.slug = slug

        if 'description' in payload:
            library.description = payload.get('description')
        if 'is_enabled' in payload:
            library.is_enabled = bool(payload.get('is_enabled'))
        if 'sort_order' in payload:
            library.sort_order = int(payload.get('sort_order') or 0)
        if 'settings' in payload:
            settings = payload.get('settings')
            if settings is not None and not isinstance(settings, dict):
                return api_error(code=40009, msg='Invalid field type: settings should be object')
            library.settings = settings or {}

        db.session.commit()
        return api_response(data=library.to_dict(), msg='Library updated')
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

    source_id = payload.get('source_id')
    if not source_id:
        return api_error(code=40001, msg='Missing required field: source_id')

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg='Source not found', http_status=404)

    root_path = _normalize_root_path(payload.get('root_path'))

    exists = LibrarySource.query.filter_by(library_id=id, source_id=source_id, root_path=root_path).first()
    if exists:
        return api_error(code=40011, msg='Library source binding already exists')

    binding = LibrarySource(
        library_id=id,
        source_id=source_id,
        root_path=root_path,
        content_type=payload.get('content_type'),
        scrape_enabled=payload.get('scrape_enabled', True),
        scan_order=payload.get('scan_order', 0),
        is_enabled=payload.get('is_enabled', True),
    )
    db.session.add(binding)
    db.session.commit()
    return api_response(data=binding.to_dict(), msg='Library source bound', http_status=201)


@libraries_bp.route('/libraries/<int:id>/sources/<int:binding_id>', methods=['PATCH'])
def update_library_source(id, binding_id):
    binding = LibrarySource.query.filter_by(id=binding_id, library_id=id).first()
    if not binding:
        return api_error(code=40411, msg='Library source binding not found', http_status=404)

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg='No input data')

    allowed = {'root_path', 'content_type', 'scrape_enabled', 'scan_order', 'is_enabled'}
    unknown = sorted([k for k in payload.keys() if k not in allowed])
    if unknown:
        return api_error(code=40004, msg=f"Unsupported fields: {', '.join(unknown)}")

    try:
        if 'root_path' in payload:
            binding.root_path = _normalize_root_path(payload.get('root_path'))
        if 'content_type' in payload:
            binding.content_type = payload.get('content_type')
        if 'scrape_enabled' in payload:
            binding.scrape_enabled = bool(payload.get('scrape_enabled'))
        if 'scan_order' in payload:
            binding.scan_order = int(payload.get('scan_order') or 0)
        if 'is_enabled' in payload:
            binding.is_enabled = bool(payload.get('is_enabled'))

        db.session.commit()
        return api_response(data=binding.to_dict(), msg='Library source updated')
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
    return api_response(data={"deleted_count": deleted_count}, msg='Library movie memberships deleted')


@libraries_bp.route('/libraries/<int:id>/movies', methods=['GET'])
def list_library_movies(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    page, page_size = _normalize_page_args()
    sort_by = request.args.get('sort_by', 'updated_at')
    order = request.args.get('order', 'desc')

    query, context = _build_library_movie_query(library)
    if query is None:
        return api_response(data=_empty_movie_list_payload(page, page_size))

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


@libraries_bp.route('/libraries/<int:id>/filters', methods=['GET'])
def get_library_filters(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    include_param = request.args.get('include')
    includes = include_param.split(',') if include_param else ['genres', 'years', 'countries']
    query, _ = _build_library_movie_query(library)
    if query is None:
        return api_response(data={key: [] for key in includes})

    movies = query.all()
    data = {}

    if 'genres' in includes:
        counter = Counter()
        for movie in movies:
            categories = movie.category or []
            if isinstance(categories, list):
                for category in normalize_genres(categories):
                    counter[category] += 1
        data['genres'] = [{"name": name, "slug": name, "count": count} for name, count in counter.most_common()]

    if 'years' in includes:
        counter = Counter()
        for movie in movies:
            if movie.year is not None:
                counter[movie.year] += 1
        data['years'] = [{"year": year, "count": count} for year, count in sorted(counter.items(), key=lambda item: item[0], reverse=True)]

    if 'countries' in includes:
        counter = Counter()
        for movie in movies:
            if movie.country:
                counter[movie.country] += 1
        data['countries'] = [{"name": name, "code": name, "count": count} for name, count in counter.most_common()]

    return api_response(data=data)


@libraries_bp.route('/libraries/<int:id>/scan', methods=['POST'])
def trigger_library_scan(id):
    library, error_response = _get_library_or_404(id)
    if error_response:
        return error_response

    bindings = _get_enabled_library_bindings(library)
    if not bindings:
        return api_error(code=40012, msg='Library has no enabled source bindings')

    if not scanner_engine.try_start_scan():
        return api_error(code=42900, msg='Scanner is already running', http_status=429)

    app = current_app._get_current_object()
    thread = threading.Thread(target=_scan_library_background_task, args=(app, id))
    thread.start()
    return api_response(msg='Library scan task accepted', http_status=202)
