from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

from backend.app.extensions import db
from backend.app.models import History, MediaResource, Movie, UserAchievement, UserFavorite
from backend.app.security import get_current_user, is_user_management_enabled
from backend.app.services.user_access import current_user_id_for_personal_data


class AchievementValidationError(ValueError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


# Behavior achievements are persisted from explicit UI/client events. Milestone
# achievements below are limited to metrics already derivable from backend
# history and resource data without inventing analytics from seek heartbeats.
ACHIEVEMENT_DEFINITIONS = [
    {"id": "night_runner", "title": "夜行者", "desc": "在凌晨的城市噪声中开始一次观影", "icon": "Moon", "category": "behavior"},
    {"id": "data_miner", "title": "数据矿工", "desc": "把浏览与观影时间沉淀成自己的数据矿脉", "icon": "Database", "category": "behavior"},
    {"id": "network_legend", "title": "网络传奇", "desc": "完整看完 100 部影视", "icon": "Trophy", "category": "milestone", "trigger": {"metric": "completed_movies_count", "op": ">=", "value": 100}},
    {"id": "ghost", "title": "幽灵", "desc": "清空一次观看历史", "icon": "Eraser", "category": "behavior"},
    {"id": "collector", "title": "收藏家", "desc": "收藏 50 部影视", "icon": "Bookmark", "category": "milestone", "trigger": {"metric": "favorites_count", "op": ">=", "value": 50}},
    {"id": "overclock", "title": "超频", "desc": "使用过 2.0 倍速播放", "icon": "Gauge", "category": "behavior"},
    {"id": "data_flood", "title": "数据洪流", "desc": "累计观看 10 小时", "icon": "Waves", "category": "behavior"},
    {"id": "consciousness_immersed", "title": "意识沉浸", "desc": "累计观看 100 小时", "icon": "Brain", "category": "behavior"},
    {"id": "immortal", "title": "永生不灭", "desc": "累计观看 1000 小时", "icon": "Infinity", "category": "behavior"},
    {"id": "marathon", "title": "马拉松", "desc": "单日观看超过 6 小时", "icon": "Timer", "category": "behavior"},
    {"id": "sleepless", "title": "彻夜未眠", "desc": "一次会话连续观看至少 4 小时", "icon": "Coffee", "category": "behavior"},
    {"id": "diverse_access", "title": "多元接入", "desc": "在 3 个不同媒体库各看完 1 部影视", "icon": "Library", "category": "behavior"},
    {"id": "anime_completion", "title": "追番党", "desc": "看完任意一部番剧的全部剧集", "icon": "Clapperboard", "category": "behavior"},
    {"id": "series_completion", "title": "完结撒花", "desc": "看完任意一部剧集类的所有季", "icon": "PartyPopper", "category": "behavior"},
    {"id": "rewatch_classic", "title": "重温经典", "desc": "同一影片完整观看至少 2 次", "icon": "Repeat2", "category": "behavior"},
    {"id": "cold_archaeologist", "title": "冷门考古", "desc": "观看过入库超过 1 年的影片", "icon": "Pickaxe", "category": "milestone", "trigger": {"metric": "watched_legacy_titles_count", "op": ">=", "value": 1}},
    {"id": "frame_analyst", "title": "逐帧分析", "desc": "使用过 0.5 倍速或更低速度播放", "icon": "Search", "category": "behavior"},
    {"id": "seek_expert", "title": "跳跃专家", "desc": "在一次播放中拖拽进度至少 20 次", "icon": "SkipForward", "category": "behavior"},
    {"id": "subtitle_magician", "title": "字幕魔术师", "desc": "在播放过程中切换字幕轨至少 5 次", "icon": "Captions", "category": "behavior"},
    {"id": "multilingual_switch", "title": "多语切换", "desc": "在播放过程中切换音轨至少 3 次", "icon": "Languages", "category": "behavior"},
    {"id": "av_sync", "title": "声画同步", "desc": "使用过音轨偏移调节", "icon": "SlidersHorizontal", "category": "behavior"},
    {"id": "quality_supreme", "title": "画质至上", "desc": "播放过 4K 或 REMUX 资源", "icon": "MonitorPlay", "category": "milestone", "trigger": {"metric": "high_quality_playback_count", "op": ">=", "value": 1}},
    {"id": "dolby_eye", "title": "杜比之眼", "desc": "播放过 Dolby Vision 资源", "icon": "Eye", "category": "milestone", "trigger": {"metric": "dolby_vision_playback_count", "op": ">=", "value": 1}},
    {"id": "surround_field", "title": "环绕声场", "desc": "播放过 Dolby Atmos 资源", "icon": "Volume2", "category": "milestone", "trigger": {"metric": "dolby_atmos_playback_count", "op": ">=", "value": 1}},
    {"id": "librarian", "title": "图书管理员", "desc": "创建至少 3 个媒体库", "icon": "Library", "category": "behavior"},
    {"id": "storage_architect", "title": "存储建筑师", "desc": "接入至少 3 种不同协议的存储节点", "icon": "HardDrive", "category": "behavior"},
    {"id": "metadata_purist", "title": "元数据洁癖", "desc": "手动修正过 10 部影视的元数据匹配", "icon": "Sparkles", "category": "behavior"},
    {"id": "poster_aesthete", "title": "海报审美", "desc": "手动编辑过封面或背景图", "icon": "Image", "category": "behavior"},
    {"id": "reviewer", "title": "审查官", "desc": "完成至少 20 项待审任务", "icon": "ClipboardCheck", "category": "behavior"},
    {"id": "multi_device_sync", "title": "多端同步", "desc": "在至少 2 台设备上留下播放历史", "icon": "Laptop", "category": "milestone", "trigger": {"metric": "playback_device_count", "op": ">=", "value": 2}},
    {"id": "desktop_invasion", "title": "桌面入侵", "desc": "使用过 PC 客户端原生播放器", "icon": "Monitor", "category": "behavior"},
    {"id": "cinema_mode", "title": "影院模式", "desc": "使用过外部播放器拉起", "icon": "Film", "category": "behavior"},
    {"id": "dark_web", "title": "暗网客", "desc": "配置过自定义代理", "icon": "Network", "category": "behavior"},
]

DEFINITIONS_BY_ID = {item["id"]: item for item in ACHIEVEMENT_DEFINITIONS}
COMPLETION_RATIO = 0.9


def _scope_context():
    user_id = current_user_id_for_personal_data()
    return (f"user:{user_id}" if user_id is not None else "default"), user_id


def _history_query_for_scope():
    _scope_key, user_id = _scope_context()
    query = db.session.query(History, MediaResource, Movie) \
        .join(MediaResource, History.resource_id == MediaResource.id) \
        .join(Movie, MediaResource.movie_id == Movie.id)
    if user_id is None:
        return query.filter(History.user_id.is_(None))
    return query.filter(History.user_id == user_id)


def _achievement_rows_for_scope():
    scope_key, _user_id = _scope_context()
    return {
        row.achievement_id: row
        for row in UserAchievement.query.filter_by(scope_key=scope_key).all()
    }


def _has_started(history):
    return int(history.progress or 0) > 0


def _has_completed(history):
    duration = int(history.duration or 0)
    progress = int(history.progress or 0)
    return duration > 0 and progress >= duration * COMPLETION_RATIO


def _resource_technical_info(resource):
    return (resource.to_dict().get("resource_info") or {}).get("technical") or {}


def _build_server_metrics():
    histories = _history_query_for_scope().all()
    completed_movie_ids = {
        resource.movie_id
        for history, resource, _movie in histories
        if _has_completed(history)
    }
    cutoff = datetime.utcnow() - timedelta(days=365)
    legacy_movie_ids = {
        movie.id
        for history, _resource, movie in histories
        if _has_started(history) and movie.added_at and movie.added_at <= cutoff
    }
    device_ids = {
        history.device_id.strip()
        for history, _resource, _movie in histories
        if history.device_id and history.device_id.strip() and _has_started(history)
    }
    scope_key, user_id = _scope_context()
    current_user = get_current_user()
    if not is_user_management_enabled():
        favorites_count = UserFavorite.query.filter_by(scope_key=scope_key).count()
    elif current_user and current_user.is_admin() and current_user.id == user_id:
        favorites_count = UserFavorite.query.filter_by(scope_key=scope_key).count()
    else:
        favorites_count = 0
    high_quality_ids = set()
    dolby_vision_ids = set()
    dolby_atmos_ids = set()
    for history, resource, _movie in histories:
        if not _has_started(history):
            continue
        technical = _resource_technical_info(resource)
        if technical.get("flag_is_4k") or technical.get("flag_is_remux") or technical.get("source_is_remux"):
            high_quality_ids.add(resource.id)
        if technical.get("flag_is_dolby_vision") or technical.get("video_dynamic_range_code") == "dolby_vision":
            dolby_vision_ids.add(resource.id)
        if technical.get("audio_is_atmos") or technical.get("audio_codec_is_atmos"):
            dolby_atmos_ids.add(resource.id)

    return {
        "completed_movies_count": len(completed_movie_ids),
        "watched_legacy_titles_count": len(legacy_movie_ids),
        "high_quality_playback_count": len(high_quality_ids),
        "dolby_vision_playback_count": len(dolby_vision_ids),
        "dolby_atmos_playback_count": len(dolby_atmos_ids),
        "playback_device_count": len(device_ids),
        "favorites_count": favorites_count,
    }


def _trigger_progress(definition, metrics):
    trigger = definition.get("trigger")
    if not trigger:
        return None
    current_value = metrics.get(trigger["metric"], 0)
    target_value = trigger["value"]
    if trigger["op"] == "==":
        return 1 if current_value == target_value else 0
    if target_value <= 0:
        return 1
    return min(max(current_value / target_value, 0), 1)


def _persist_unlock(achievement_id, source, *, commit=True):
    scope_key, user_id = _scope_context()
    row = UserAchievement.query.filter_by(scope_key=scope_key, achievement_id=achievement_id).first()
    created = row is None
    if not row:
        row = UserAchievement(
            scope_key=scope_key,
            user_id=user_id,
            achievement_id=achievement_id,
            unlock_source=source,
            unlocked_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.flush()
    if commit:
        db.session.commit()
    return row, created


def unlock_behavior_achievement(achievement_id, *, source="client", commit=True):
    definition = DEFINITIONS_BY_ID.get(str(achievement_id or "").strip())
    if not definition:
        raise AchievementValidationError(40451, "Achievement not found")
    if definition["category"] != "behavior":
        raise AchievementValidationError(40096, "Milestone achievements are unlocked by server metrics")

    row, created = _persist_unlock(definition["id"], source, commit=commit)
    return {
        "achievement": row.to_user_dict(progress=1),
        "newly_unlocked": created,
    }


def evaluate_and_persist_milestones(*, commit=True):
    metrics = _build_server_metrics()
    rows = _achievement_rows_for_scope()
    newly_unlocked = []
    for definition in ACHIEVEMENT_DEFINITIONS:
        if definition["category"] != "milestone":
            continue
        progress = _trigger_progress(definition, metrics)
        if progress < 1 or definition["id"] in rows:
            continue
        row, created = _persist_unlock(definition["id"], "metric", commit=False)
        rows[definition["id"]] = row
        if created:
            newly_unlocked.append(definition["id"])
    if commit and newly_unlocked:
        db.session.commit()
    return metrics, rows, newly_unlocked


def build_user_achievement_payload():
    metrics, rows, newly_unlocked = evaluate_and_persist_milestones()
    user_items = []
    for definition in ACHIEVEMENT_DEFINITIONS:
        row = rows.get(definition["id"])
        progress = 1 if row else _trigger_progress(definition, metrics)
        item = {
            "id": definition["id"],
            "unlocked_at": row.unlocked_at.isoformat() if row and row.unlocked_at else None,
        }
        if progress is not None:
            item["progress"] = progress
        user_items.append(item)

    return {
        "defs": deepcopy(ACHIEVEMENT_DEFINITIONS),
        "user": user_items,
        "summary": {
            "total": len(ACHIEVEMENT_DEFINITIONS),
            "unlocked": sum(1 for item in user_items if item["unlocked_at"]),
            "milestones": sum(1 for item in ACHIEVEMENT_DEFINITIONS if item["category"] == "milestone"),
            "behaviors": sum(1 for item in ACHIEVEMENT_DEFINITIONS if item["category"] == "behavior"),
            "newly_unlocked_ids": newly_unlocked,
        },
    }
