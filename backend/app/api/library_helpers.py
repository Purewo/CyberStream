import json
from collections import Counter

from backend.app.extensions import db
from backend.app.models import Movie, MediaResource
from backend.app.utils.genres import get_genre_query_terms, normalize_genres


def apply_public_movie_visibility_filter(query):
    """普通影视库默认只展示无需人工处理的影片。"""
    return query.filter(
        db.func.upper(Movie.scraper_source).in_(list(Movie.get_metadata_non_attention_sources())),
        Movie.cover.isnot(None),
        Movie.cover != "",
    )


def get_filter_options(includes):
    """按 include 列表返回全局筛选字典。"""
    data = {}

    if 'genres' in includes:
        movies = apply_public_movie_visibility_filter(db.session.query(Movie.category)).all()
        counter = Counter()
        for movie in movies:
            categories = movie[0]
            if categories and isinstance(categories, list):
                for category in normalize_genres(categories):
                    counter[category] += 1

        data['genres'] = [
            {"name": name, "slug": name, "count": count}
            for name, count in counter.most_common()
        ]

    if 'years' in includes:
        query = apply_public_movie_visibility_filter(db.session.query(Movie.year, db.func.count(Movie.id))) \
            .filter(Movie.year.isnot(None)) \
            .group_by(Movie.year) \
            .order_by(Movie.year.desc())
        data['years'] = [{"year": row[0], "count": row[1]} for row in query.all()]

    if 'countries' in includes:
        query = apply_public_movie_visibility_filter(db.session.query(Movie.country, db.func.count(Movie.id))) \
            .filter(Movie.country.isnot(None)) \
            .filter(Movie.country != "") \
            .group_by(Movie.country)

        countries = []
        for row in query.all():
            name = row[0]
            count = row[1]
            countries.append({"name": name, "code": name, "count": count})

        countries.sort(key=lambda item: item['count'], reverse=True)
        data['countries'] = countries

    if 'metadata_source_groups' in includes:
        data['metadata_source_groups'] = _build_metadata_source_group_filters()

    if 'metadata_review_priorities' in includes:
        data['metadata_review_priorities'] = _build_metadata_review_priority_filters()

    if 'metadata_issue_codes' in includes:
        data['metadata_issue_codes'] = _build_metadata_issue_code_filters()

    return data


def _build_metadata_source_group_filters():
    items = []
    source_group_map = Movie.get_metadata_source_group_map()

    for group, source_codes in source_group_map.items():
        count = Movie.query.filter(Movie.scraper_source.in_(source_codes)).count()
        items.append({
            "name": group,
            "slug": group,
            "count": count,
        })

    unknown_count = Movie.query.filter(
        db.or_(Movie.scraper_source.is_(None), Movie.scraper_source == "")
    ).count()
    items.append({
        "name": "unknown",
        "slug": "unknown",
        "count": unknown_count,
    })
    return items


def _build_metadata_review_priority_filters():
    items = []
    review_priority_map = Movie.get_metadata_review_priority_map()

    for priority, source_codes in review_priority_map.items():
        count = Movie.query.filter(Movie.scraper_source.in_(source_codes)).count()
        items.append({
            "name": priority,
            "slug": priority,
            "count": count,
        })

    unknown_count = Movie.query.filter(
        db.or_(Movie.scraper_source.is_(None), Movie.scraper_source == "")
    ).count()
    items.append({
        "name": "unknown",
        "slug": "unknown",
        "count": unknown_count,
    })
    return items


def _build_metadata_issue_code_filters():
    counter = Counter()
    for movie in Movie.query.all():
        for issue in movie.get_metadata_issues():
            counter[issue["code"]] += 1

    return [
        {"name": key, "slug": key, "count": count}
        for key, count in counter.most_common()
    ]


def apply_movie_filters(query, genre=None, keyword=None, country=None, year_param=None):
    """给已有 Movie 查询追加通用筛选条件。"""
    if genre:
        conditions = []
        for term in get_genre_query_terms(genre):
            if not term:
                continue
            try:
                escaped_term = json.dumps(term).strip('"')
                conditions.append(Movie.category.cast(db.String).like(f'%"{escaped_term}"%'))
            except Exception:
                pass
            conditions.append(Movie.category.cast(db.String).like(f'%"{term}"%'))
        if conditions:
            query = query.filter(db.or_(*conditions))

    if keyword:
        keyword_like = f"%{keyword}%"
        query = query.filter(
            db.or_(
                Movie.title.like(keyword_like),
                Movie.original_title.like(keyword_like),
                Movie.director.like(keyword_like),
                Movie.actors.cast(db.String).like(keyword_like)
            )
        )

    if country:
        query = query.filter(Movie.country == country)

    if year_param:
        if '-' in year_param:
            parts = year_param.split('-')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                query = query.filter(Movie.year >= int(parts[0]), Movie.year <= int(parts[1]))
        elif year_param.isdigit():
            query = query.filter(Movie.year == int(year_param))

    return query


def get_featured_movies(limit=5, custom_hero_id=None):
    """获取首页精选电影列表。"""
    featured_movies = []

    if custom_hero_id:
        hero_movie = Movie.query.get(custom_hero_id)
        if hero_movie:
            featured_movies.append(hero_movie)

    base_query = apply_public_movie_visibility_filter(Movie.query).filter(
        Movie.background_cover.isnot(None),
        Movie.background_cover != ""
    )

    existing_ids = [movie.id for movie in featured_movies]
    if existing_ids:
        base_query = base_query.filter(Movie.id.notin_(existing_ids))

    remaining_limit = limit - len(featured_movies)
    if remaining_limit > 0:
        auto_movies = base_query.filter(Movie.rating >= 7.0) \
            .order_by(Movie.added_at.desc()) \
            .limit(remaining_limit).all()
        featured_movies.extend(auto_movies)

        if len(featured_movies) < limit:
            existing_ids = [movie.id for movie in featured_movies]
            more_limit = limit - len(featured_movies)
            more_movies = base_query.filter(Movie.id.notin_(existing_ids)) \
                .order_by(Movie.added_at.desc()) \
                .limit(more_limit).all()
            featured_movies.extend(more_movies)

    return featured_movies


def get_recommendation_movies(limit, strategy):
    """按策略获取推荐电影列表。"""
    query = apply_public_movie_visibility_filter(Movie.query)

    if strategy == 'latest':
        query = query.order_by(Movie.added_at.desc())
    elif strategy == 'top_rated':
        query = query.order_by(Movie.rating.desc())
    else:
        query = query.order_by(db.func.random())

    return query.limit(limit).all()


def build_movie_list_query(
    source_id=None,
    genre=None,
    keyword=None,
    country=None,
    year_param=None,
    metadata_source_group=None,
    metadata_review_priority=None,
    needs_attention=None,
    metadata_issue_code=None,
):
    """构造电影列表查询。排序由调用方继续补充。"""
    query = Movie.query

    if source_id:
        query = query.join(MediaResource).filter(MediaResource.source_id == source_id)

    query = apply_movie_filters(
        query,
        genre=genre,
        keyword=keyword,
        country=country,
        year_param=year_param,
    )

    if metadata_source_group:
        if metadata_source_group == 'unknown':
            query = query.filter(db.or_(Movie.scraper_source.is_(None), Movie.scraper_source == ""))
        else:
            source_codes = Movie.get_metadata_source_group_map().get(metadata_source_group)
            if source_codes:
                query = query.filter(Movie.scraper_source.in_(source_codes))

    if metadata_review_priority:
        if metadata_review_priority == 'unknown':
            query = query.filter(db.or_(Movie.scraper_source.is_(None), Movie.scraper_source == ""))
        else:
            source_codes = Movie.get_metadata_review_priority_map().get(metadata_review_priority)
            if source_codes:
                query = query.filter(Movie.scraper_source.in_(source_codes))

    if needs_attention is not None:
        if needs_attention:
            query = query.filter(
                db.or_(
                    Movie.scraper_source.is_(None),
                    Movie.scraper_source == "",
                    db.func.upper(Movie.scraper_source).notin_(list(Movie.get_metadata_non_attention_sources())),
                    Movie.cover.is_(None),
                    Movie.cover == "",
                )
            )
        else:
            query = apply_public_movie_visibility_filter(query)

    if metadata_issue_code:
        if metadata_issue_code == 'poster_missing':
            return query.filter(db.or_(Movie.cover.is_(None), Movie.cover == ""))

        issue_source_map = {
            'placeholder_metadata': list(Movie.get_metadata_placeholder_sources()),
            'local_only_metadata': list(Movie.get_metadata_local_only_sources()),
            'fallback_pipeline_match': ['TMDB_FALLBACK', 'LOCAL_FALLBACK', 'LOCAL_ORPHAN', 'NFO_LOCAL', 'NFO'],
            'nfo_candidates_available': ['NFO_TMDB', 'NFO_LOCAL', 'NFO'],
        }
        source_codes = issue_source_map.get(metadata_issue_code)
        if source_codes:
            query = query.filter(Movie.scraper_source.in_(source_codes))

    return query


def build_review_queue_query(source_id=None, provider=None, parse_mode=None, keyword=None):
    """构造待人工复核资源查询。"""
    query = MediaResource.query.join(Movie).filter(
        db.func.json_extract(MediaResource.tech_specs, '$.analysis.path_cleaning.needs_review') == 1
    )

    if source_id:
        query = query.filter(MediaResource.source_id == source_id)

    normalized_provider = (provider or '').strip().lower()
    if normalized_provider:
        query = query.filter(
            db.func.json_extract(MediaResource.tech_specs, '$.analysis.scraping.provider') == normalized_provider
        )

    normalized_parse_mode = (parse_mode or '').strip().lower()
    if normalized_parse_mode in {'standard', 'fallback'}:
        query = query.filter(
            db.func.json_extract(MediaResource.tech_specs, '$.analysis.path_cleaning.parse_mode') == normalized_parse_mode
        )

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

    return query


def resolve_movie_sort_column(sort_by):
    """将 sort_by 参数映射到实际排序字段。"""
    if sort_by == 'year':
        return Movie.year
    if sort_by == 'rating':
        return Movie.rating
    if sort_by == 'title':
        return Movie.title
    if sort_by == 'updated_at':
        return Movie.updated_at
    return Movie.added_at
