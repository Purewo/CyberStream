import json
import random
import re
from collections import Counter
from datetime import datetime

from backend.app.extensions import db
from backend.app.models import History, LibraryMovieMembership, LibrarySource, Movie, MediaResource
from backend.app.utils.genres import get_genre_query_terms, normalize_genres

RECOMMENDATION_STRATEGIES = {'default', 'latest', 'top_rated', 'surprise', 'continue_watching'}
MAX_RECOMMENDATION_LIMIT = 50
MAX_RECOMMENDATION_CANDIDATES = 240
ANIMATION_GENRE = "动画"


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
        )
    )


def get_enabled_library_bindings(library):
    return library.source_bindings.filter_by(is_enabled=True).order_by(
        LibrarySource.scan_order.asc(),
        LibrarySource.id.asc(),
    ).all()


def build_library_movie_id_context(library):
    bindings = get_enabled_library_bindings(library)
    auto_ids = set()
    if bindings:
        filters = [_build_library_binding_path_filter(binding) for binding in bindings]
        query = (
            db.session.query(MediaResource.movie_id)
            .join(Movie, Movie.id == MediaResource.movie_id)
            .filter(db.or_(*filters))
            .filter(MediaResource.movie_id.isnot(None))
        )
        rows = apply_public_movie_visibility_filter(query).distinct().all()
        auto_ids = {row[0] for row in rows if row[0]}

    membership_rows = LibraryMovieMembership.query.filter_by(library_id=library.id).all()
    include_ids = {row.movie_id for row in membership_rows if row.mode == 'include'}
    exclude_ids = {row.movie_id for row in membership_rows if row.mode == 'exclude'}
    final_ids = (auto_ids | include_ids) - exclude_ids

    membership_map = {}
    for movie_id in final_ids:
        is_auto = movie_id in auto_ids
        is_manual = movie_id in include_ids
        if is_auto and is_manual:
            membership_map[movie_id] = 'both'
        elif is_manual:
            membership_map[movie_id] = 'manual'
        else:
            membership_map[movie_id] = 'auto'

    return {
        "bindings": bindings,
        "auto_ids": auto_ids,
        "include_ids": include_ids,
        "exclude_ids": exclude_ids,
        "final_ids": final_ids,
        "membership_map": membership_map,
    }


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
        hero_movie = db.session.get(Movie, custom_hero_id)
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


def normalize_recommendation_limit(raw_limit, default=12):
    try:
        limit = int(raw_limit if raw_limit is not None else default)
    except (TypeError, ValueError):
        limit = default
    return min(max(limit, 1), MAX_RECOMMENDATION_LIMIT)


def normalize_recommendation_strategy(raw_strategy):
    strategy = (raw_strategy or 'default').strip().lower() if isinstance(raw_strategy, str) else 'default'
    return strategy if strategy in RECOMMENDATION_STRATEGIES else 'default'


def _safe_progress_ratio(history_record):
    if not history_record or not history_record.duration:
        return 0
    try:
        ratio = float(history_record.progress or 0) / float(history_record.duration or 0)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0
    return min(max(ratio, 0), 1)


def _get_recent_history_by_movie(movie_ids):
    if not movie_ids:
        return {}

    rows = db.session.query(History, MediaResource.movie_id) \
        .join(MediaResource, History.resource_id == MediaResource.id) \
        .filter(MediaResource.movie_id.in_(movie_ids)) \
        .order_by(MediaResource.movie_id.asc(), History.last_watched.desc(), History.id.desc()) \
        .all()

    history_map = {}
    for history_record, movie_id in rows:
        history_map.setdefault(movie_id, history_record)
    return history_map


def _get_resource_count_by_movie(movie_ids):
    if not movie_ids:
        return {}

    rows = db.session.query(MediaResource.movie_id, db.func.count(MediaResource.id)) \
        .filter(MediaResource.movie_id.in_(movie_ids)) \
        .group_by(MediaResource.movie_id) \
        .all()
    return {movie_id: int(count or 0) for movie_id, count in rows}


def _age_days(value):
    if not value:
        return None
    return max((datetime.utcnow() - value).days, 0)


def _build_reason(code, label, detail=None, weight=None):
    item = {
        "code": code,
        "label": label,
    }
    if detail is not None:
        item["detail"] = detail
    if weight is not None:
        item["weight"] = round(float(weight), 2)
    return item


def movie_has_animation(movie):
    return ANIMATION_GENRE in normalize_genres(movie.category or [])


def _movie_partition(movie):
    return "anime" if movie_has_animation(movie) else "live_action"


def _strip_title_subtitle(value):
    text = str(value or "").strip()
    for separator in ("：", ":", " - ", " – ", " — ", "-", "–", "—"):
        if separator in text:
            prefix = text.split(separator, 1)[0].strip()
            if prefix:
                return prefix
    return text


def build_title_family_key(movie):
    title = _strip_title_subtitle(movie.original_title or movie.title)
    title = title.lower()
    title = re.sub(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）|【[^】]*】", " ", title)
    title = re.sub(r"\b(?:19|20)\d{2}\b", " ", title)
    title = re.sub(r"(?i)\b(?:season|series|part|vol|volume|chapter)\s*\d+\b", " ", title)
    title = re.sub(r"(?i)\bs\d{1,2}\b", " ", title)
    title = re.sub(r"第\s*[一二三四五六七八九十百千万\d]+\s*[季部篇章集]", " ", title)
    title = re.sub(r"(?i)\b(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\b$", " ", title)
    title = re.sub(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+$", " ", title)
    title = re.sub(r"\b\d+\b$", " ", title)
    title = re.sub(r"[^\w\u4e00-\u9fff]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    compact = re.sub(r"\s+", "", title)
    if not compact:
        return None
    if compact.isascii() and len(compact) < 3:
        return None
    if not compact.isascii() and len(compact) < 2:
        return None
    return compact


def _score_recommendation_movie(movie, strategy, history_record=None, resource_count=0):
    reasons = []
    score = 0.0

    progress_ratio = _safe_progress_ratio(history_record)
    if history_record and 0.03 <= progress_ratio < 0.92:
        continue_weight = 85 + (1 - progress_ratio) * 10
        score += continue_weight
        reasons.append(_build_reason(
            "continue_watching",
            "Continue watching",
            f"{round(progress_ratio * 100)}% watched",
            continue_weight,
        ))
    elif history_record and progress_ratio >= 0.92:
        score -= 18

    rating = float(movie.rating or 0)
    if rating > 0:
        rating_weight = rating * 4
        score += rating_weight
        if rating >= 7.5:
            reasons.append(_build_reason("high_rating", "High rating", f"{rating:.1f}", rating_weight))

    days = _age_days(movie.added_at)
    if days is not None:
        recent_weight = max(0, 28 - min(days, 56) * 0.5)
        score += recent_weight
        if days <= 30:
            reasons.append(_build_reason("recently_added", "Recently added", f"{days} days ago", recent_weight))

    quality_badge = movie.get_quality_badge()
    quality_weights = {
        Movie.QUALITY_BADGE_REMUX: 14,
        Movie.QUALITY_BADGE_4K: 11,
        Movie.QUALITY_BADGE_HD: 6,
    }
    quality_weight = quality_weights.get(quality_badge, 0)
    if quality_weight:
        score += quality_weight
        reasons.append(_build_reason("quality_available", f"{quality_badge} version", weight=quality_weight))

    if resource_count > 0:
        score += 8
        reasons.append(_build_reason("playable_resource", "Playable resource", f"{resource_count} resources", 8))
    else:
        score -= 20

    if strategy == 'latest':
        score += max(0, 120 - (days or 0))
    elif strategy == 'top_rated':
        score += rating * 12
    elif strategy == 'continue_watching':
        if history_record and 0.03 <= progress_ratio < 0.92:
            score += 120
        else:
            score -= 120
    elif strategy == 'surprise':
        score = random.random() * 100
        reasons.insert(0, _build_reason("surprise_pick", "Surprise pick"))

    if not reasons:
        reasons.append(_build_reason("catalog_pick", "Catalog pick"))

    return {
        "score": score,
        "reasons": reasons,
        "progress_ratio": progress_ratio,
        "quality_badge": quality_badge,
        "resource_count": resource_count,
    }


def _rank_recommendation_candidates(movies, limit, strategy):
    movie_ids = [movie.id for movie in movies]
    history_map = _get_recent_history_by_movie(movie_ids)
    resource_count_map = _get_resource_count_by_movie(movie_ids)
    scored = []

    for movie in movies:
        scored.append({
            "movie": movie,
            "recommendation": _score_recommendation_movie(
                movie,
                strategy=strategy,
                history_record=history_map.get(movie.id),
                resource_count=resource_count_map.get(movie.id, 0),
            ),
        })

    if strategy in {'latest', 'top_rated'}:
        return scored[:limit]
    if strategy == 'surprise':
        scored.sort(key=lambda item: item["recommendation"]["score"], reverse=True)
    else:
        scored.sort(key=lambda item: item["recommendation"]["score"], reverse=True)

    if strategy != 'default':
        return scored[:limit]

    selected = []
    selected_genres = Counter()
    remaining = list(scored)
    while remaining and len(selected) < limit:
        best_index = 0
        best_value = None
        for index, item in enumerate(remaining):
            genres = normalize_genres(item["movie"].category or [])
            diversity_bonus = 0
            if genres and any(selected_genres[genre] == 0 for genre in genres):
                diversity_bonus = 12
            value = item["recommendation"]["score"] + diversity_bonus
            if best_value is None or value > best_value:
                best_value = value
                best_index = index

        chosen = remaining.pop(best_index)
        genres = normalize_genres(chosen["movie"].category or [])
        if selected and genres and any(selected_genres[genre] == 0 for genre in genres):
            chosen["recommendation"]["reasons"].append(
                _build_reason("genre_diversity", "Adds genre variety", ", ".join(genres), 12)
            )
        for genre in genres:
            selected_genres[genre] += 1
        selected.append(chosen)

    return selected


def _build_recommendation_payload(item, strategy, rank):
    recommendation = item["recommendation"]
    reasons = recommendation["reasons"]
    primary_reason = reasons[0] if reasons else _build_reason("catalog_pick", "Catalog pick")
    return {
        "strategy": strategy,
        "rank": rank,
        "score": round(recommendation["score"], 2),
        "primary_reason": primary_reason,
        "reasons": reasons,
        "reason_text": primary_reason["label"],
        "signals": {
            "progress_ratio": round(recommendation["progress_ratio"], 4),
            "quality_badge": recommendation["quality_badge"],
            "resource_count": recommendation["resource_count"],
        },
    }


def attach_recommendation_payload(movie_payload, recommendation_item, strategy, rank):
    movie_payload["recommendation"] = _build_recommendation_payload(recommendation_item, strategy, rank)
    return movie_payload


def _base_context_candidate_query(anchor_movie):
    if movie_has_animation(anchor_movie):
        return apply_movie_filters(apply_public_movie_visibility_filter(Movie.query), genre=ANIMATION_GENRE)

    category_text = Movie.category.cast(db.String)
    return apply_public_movie_visibility_filter(Movie.query).filter(
        db.or_(
            Movie.category.is_(None),
            db.and_(
                db.not_(category_text.like('%"动画"%')),
                db.not_(category_text.like('%animation%')),
                db.not_(category_text.like('%Animation%')),
            ),
        )
    )


def _append_context_reason(item, code, label, detail=None, weight=0, prepend=True):
    item["recommendation"]["score"] += weight
    reason = _build_reason(code, label, detail, weight if weight else None)
    if prepend:
        item["recommendation"]["reasons"].insert(0, reason)
    else:
        item["recommendation"]["reasons"].append(reason)


def _context_same_genre_count(anchor_genres, candidate):
    candidate_genres = set(normalize_genres(candidate.category or []))
    return len(set(anchor_genres) & candidate_genres)


def _normalize_movie_id_set(movie_ids):
    if not movie_ids:
        return set()
    return {str(movie_id) for movie_id in movie_ids if movie_id}


def _get_context_candidates(anchor_movie, anchor_partition, include_movie_ids=None, exclude_movie_ids=None):
    query = _base_context_candidate_query(anchor_movie).filter(Movie.id != anchor_movie.id)

    include_ids = _normalize_movie_id_set(include_movie_ids)
    if include_movie_ids is not None:
        if not include_ids:
            return []
        query = query.filter(Movie.id.in_(list(include_ids)))

    exclude_ids = _normalize_movie_id_set(exclude_movie_ids)
    if exclude_ids:
        query = query.filter(db.not_(Movie.id.in_(list(exclude_ids))))

    raw_candidates = query.order_by(Movie.added_at.desc(), Movie.id.asc()).limit(MAX_RECOMMENDATION_CANDIDATES).all()
    return [
        candidate
        for candidate in raw_candidates
        if _movie_partition(candidate) == anchor_partition
    ]


def _select_context_recommendation_items(anchor_movie, candidates, limit, anchor_partition):
    if limit <= 0 or not candidates:
        return []

    anchor_family_key = build_title_family_key(anchor_movie)
    anchor_genres = normalize_genres(anchor_movie.category or [])
    scored = _rank_recommendation_candidates(candidates, len(candidates), strategy='default')
    selected = []
    selected_ids = set()

    def add_group(group_items, reason_code, label, detail_fn, weight):
        for item in group_items:
            if len(selected) >= limit:
                return
            movie_id = item["movie"].id
            if movie_id in selected_ids:
                continue
            _append_context_reason(item, reason_code, label, detail_fn(item["movie"]), weight)
            _append_context_reason(
                item,
                "anime_partition" if anchor_partition == "anime" else "live_action_partition",
                "Anime partition" if anchor_partition == "anime" else "Live action partition",
                weight=0,
                prepend=False,
            )
            selected.append(item)
            selected_ids.add(movie_id)

    if anchor_family_key:
        same_family = [
            item
            for item in scored
            if build_title_family_key(item["movie"]) == anchor_family_key
        ]
        same_family.sort(
            key=lambda item: (
                item["movie"].year or 0,
                item["movie"].added_at or datetime.min,
                item["recommendation"]["score"],
            ),
            reverse=True,
        )
        add_group(
            same_family,
            "same_title_family",
            "Same series",
            lambda _movie: anchor_family_key,
            180,
        )

    same_genre = [
        item
        for item in scored
        if item["movie"].id not in selected_ids and _context_same_genre_count(anchor_genres, item["movie"]) > 0
    ]
    same_genre.sort(
        key=lambda item: (
            _context_same_genre_count(anchor_genres, item["movie"]),
            item["recommendation"]["score"],
            item["movie"].rating or 0,
        ),
        reverse=True,
    )
    add_group(
        same_genre,
        "same_genre",
        "Same genre",
        lambda movie: ", ".join(sorted(set(anchor_genres) & set(normalize_genres(movie.category or [])))),
        90,
    )

    fallback = [
        item
        for item in scored
        if item["movie"].id not in selected_ids
    ]
    fallback.sort(key=lambda item: item["recommendation"]["score"], reverse=True)
    add_group(
        fallback,
        "same_partition_fallback",
        "Same catalog partition",
        lambda _movie: "anime" if anchor_partition == "anime" else "live action",
        30,
    )

    return selected[:limit]


def get_context_recommendation_items(anchor_movie, limit=6, preferred_movie_ids=None):
    """生成单片详情页相关推荐，强制动漫/非动漫分区隔离。

    preferred_movie_ids 用于资源库内详情页：先从当前资源库候选中选，不足再用全局候选补齐。
    """
    limit = normalize_recommendation_limit(limit, default=6)
    anchor_partition = _movie_partition(anchor_movie)
    selected = []
    selected_ids = set()
    preferred_scope_requested = preferred_movie_ids is not None
    preferred_ids = _normalize_movie_id_set(preferred_movie_ids)
    preferred_ids.discard(anchor_movie.id)

    if preferred_ids:
        preferred_candidates = _get_context_candidates(
            anchor_movie,
            anchor_partition,
            include_movie_ids=preferred_ids,
        )
        preferred_items = _select_context_recommendation_items(
            anchor_movie,
            preferred_candidates,
            limit,
            anchor_partition,
        )
        for item in preferred_items:
            _append_context_reason(item, "same_library", "Within current library", weight=0, prepend=False)
            selected.append(item)
            selected_ids.add(item["movie"].id)

    remaining_limit = limit - len(selected)
    if remaining_limit <= 0:
        return selected[:limit]

    exclude_ids = set(selected_ids)
    if preferred_ids:
        exclude_ids.update(preferred_ids)
    fallback_candidates = _get_context_candidates(
        anchor_movie,
        anchor_partition,
        exclude_movie_ids=exclude_ids,
    )
    fallback_items = _select_context_recommendation_items(
        anchor_movie,
        fallback_candidates,
        remaining_limit,
        anchor_partition,
    )
    if preferred_scope_requested:
        for item in fallback_items:
            _append_context_reason(item, "outside_library_fill", "Outside library fill", weight=0, prepend=False)
    selected.extend(fallback_items)

    return selected[:limit]


def get_recommendation_items_from_query(query, limit=12, strategy='default'):
    """基于已有 Movie 查询生成带解释的推荐结果。"""
    limit = normalize_recommendation_limit(limit)
    strategy = normalize_recommendation_strategy(strategy)
    candidate_limit = min(MAX_RECOMMENDATION_CANDIDATES, max(limit * 8, limit))
    base_query = query.order_by(None)

    if strategy == 'latest':
        candidates = base_query.order_by(Movie.added_at.desc(), Movie.id.asc()).limit(candidate_limit).all()
    elif strategy == 'top_rated':
        candidates = base_query.order_by(Movie.rating.desc(), Movie.added_at.desc(), Movie.id.asc()).limit(candidate_limit).all()
    elif strategy == 'surprise':
        candidates = base_query.order_by(db.func.random()).limit(candidate_limit).all()
    else:
        candidates = base_query.order_by(Movie.added_at.desc(), Movie.id.asc()).limit(candidate_limit).all()

    return _rank_recommendation_candidates(candidates, limit, strategy)


def get_recommendation_items(limit, strategy):
    """获取全局推荐条目并附带推荐解释。"""
    query = apply_public_movie_visibility_filter(Movie.query)
    return get_recommendation_items_from_query(query, limit=limit, strategy=strategy)


def get_recommendation_movies(limit, strategy):
    """按策略获取推荐电影列表。保留给旧调用方使用。"""
    return [item["movie"] for item in get_recommendation_items(limit, strategy)]


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
