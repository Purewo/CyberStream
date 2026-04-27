import re


_TMDB_GENRE_ID_MAP = {
    12: ["冒险"],
    14: ["奇幻"],
    16: ["动画"],
    18: ["剧情"],
    27: ["恐怖"],
    28: ["动作"],
    35: ["喜剧"],
    36: ["历史"],
    37: ["西部"],
    53: ["惊悚"],
    80: ["犯罪"],
    99: ["纪录"],
    878: ["科幻"],
    9648: ["悬疑"],
    10402: ["音乐"],
    10749: ["爱情"],
    10751: ["家庭"],
    10752: ["战争"],
    10759: ["动作", "冒险"],
    10762: ["儿童"],
    10763: ["新闻"],
    10764: ["真人秀"],
    10765: ["科幻", "奇幻"],
    10766: ["肥皂剧"],
    10767: ["脱口秀"],
    10768: ["战争", "政治"],
    10770: ["电视电影"],
}

_GENRE_ALIAS_OUTPUTS = {
    "action": ["动作"],
    "动作": ["动作"],
    "adventure": ["冒险"],
    "冒险": ["冒险"],
    "animation": ["动画"],
    "动画": ["动画"],
    "comedy": ["喜剧"],
    "喜剧": ["喜剧"],
    "crime": ["犯罪"],
    "犯罪": ["犯罪"],
    "documentary": ["纪录"],
    "纪录": ["纪录"],
    "drama": ["剧情"],
    "剧情": ["剧情"],
    "family": ["家庭"],
    "家庭": ["家庭"],
    "fantasy": ["奇幻"],
    "奇幻": ["奇幻"],
    "history": ["历史"],
    "历史": ["历史"],
    "horror": ["恐怖"],
    "恐怖": ["恐怖"],
    "kids": ["儿童"],
    "儿童": ["儿童"],
    "music": ["音乐"],
    "音乐": ["音乐"],
    "mystery": ["悬疑"],
    "悬疑": ["悬疑"],
    "news": ["新闻"],
    "新闻": ["新闻"],
    "reality": ["真人秀"],
    "真人秀": ["真人秀"],
    "romance": ["爱情"],
    "爱情": ["爱情"],
    "science fiction": ["科幻"],
    "sci fi": ["科幻"],
    "sci-fi": ["科幻"],
    "科幻": ["科幻"],
    "soap": ["肥皂剧"],
    "肥皂剧": ["肥皂剧"],
    "talk": ["脱口秀"],
    "脱口秀": ["脱口秀"],
    "thriller": ["惊悚"],
    "惊悚": ["惊悚"],
    "tv movie": ["电视电影"],
    "电视电影": ["电视电影"],
    "war": ["战争"],
    "战争": ["战争"],
    "war & politics": ["战争", "政治"],
    "战争政治": ["战争", "政治"],
    "politics": ["政治"],
    "政治": ["政治"],
    "western": ["西部"],
    "西部": ["西部"],
    "action & adventure": ["动作", "冒险"],
    "action adventure": ["动作", "冒险"],
    "动作冒险": ["动作", "冒险"],
    "sci-fi & fantasy": ["科幻", "奇幻"],
    "sci fi & fantasy": ["科幻", "奇幻"],
    "sci fi fantasy": ["科幻", "奇幻"],
    "science fiction & fantasy": ["科幻", "奇幻"],
    "science fiction and fantasy": ["科幻", "奇幻"],
    "科幻奇幻": ["科幻", "奇幻"],
}

_EXCLUDED_GENRE_KEYS = {
    "local",
    "movie",
    "tv",
    "misc",
    "unknown",
}


def _normalize_key(value):
    text = str(value or "").strip().lower()
    text = text.replace("＆", "&").replace("和", "&")
    text = text.replace("/", " ")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*&\s*", " & ", text)
    return text.strip()


def _is_internal_genre(value):
    return _normalize_key(value) in _EXCLUDED_GENRE_KEYS


def _normalize_genre_value(value):
    text = str(value or "").strip()
    if not text or _is_internal_genre(text):
        return []

    mapped = _GENRE_ALIAS_OUTPUTS.get(_normalize_key(text))
    if mapped:
        return list(mapped)
    return [text]


def normalize_genres(values):
    normalized = []
    seen = set()

    for value in values or []:
        if not isinstance(value, str):
            continue
        for item in _normalize_genre_value(value):
            if item in seen:
                continue
            seen.add(item)
            normalized.append(item)

    return normalized


def normalize_tmdb_genres(values):
    normalized = []
    seen = set()

    for value in values or []:
        mapped = None
        if isinstance(value, dict):
            mapped = _TMDB_GENRE_ID_MAP.get(value.get("id"))
            if mapped is None:
                mapped = _normalize_genre_value(value.get("name"))
        elif isinstance(value, str):
            mapped = _normalize_genre_value(value)

        for item in mapped or []:
            if item in seen:
                continue
            seen.add(item)
            normalized.append(item)

    return normalized


def get_genre_query_terms(value):
    canonical_terms = normalize_genres([value])
    if not canonical_terms:
        raw = str(value or "").strip()
        return [raw] if raw else []

    query_terms = set(canonical_terms)
    for alias, outputs in _GENRE_ALIAS_OUTPUTS.items():
        if any(item in canonical_terms for item in outputs):
            query_terms.add(alias)

    for term in list(query_terms):
        if term.isascii():
            query_terms.add(term.title())
            query_terms.add(term.upper())
    return sorted(query_terms)
