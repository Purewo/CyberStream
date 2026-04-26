import re
import uuid
from datetime import datetime
from sqlalchemy.dialects.sqlite import JSON
from backend.app.extensions import db
from backend.app.providers.factory import provider_factory
from backend.app.services.playback import build_resource_playback
from backend.app.storage.source_registry import (
    build_source_display_root,
    get_source_capabilities,
    get_source_display_name,
    normalize_source_type,
    sanitize_source_config,
)
from backend.app.utils.genres import normalize_genres


def generate_uuid():
    return str(uuid.uuid4())


class StorageSource(db.Model):
    """存储源配置模型。

    当前真正生效的存储配置主体在 config(JSON) 中，
    由 source_registry + provider_factory + 各 provider 在运行时解释。
    """
    __tablename__ = 'storage_sources'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # e.g. "NAS WebDAV"
    type = db.Column(db.String(20), nullable=False)  # 'local', 'webdav', 'smb'

    # JSON 配置
    config = db.Column(JSON, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def resolve_runtime_state(self, include_health=False):
        normalized_type = self.type
        capabilities = {}
        safe_config = {}
        supported = False
        config_valid = False
        config_error = None

        try:
            normalized_type = normalize_source_type(self.type)
            _, capabilities = get_source_capabilities(normalized_type)
            supported = True
        except Exception as e:
            config_error = str(e)

        if supported:
            try:
                _, safe_config = sanitize_source_config(normalized_type, self.config or {})
                config_valid = True
            except Exception as e:
                config_error = str(e)

        if not config_error and not config_valid:
            config_error = "Invalid storage config"

        health = {
            "status": "unsupported" if not supported else ("unknown" if config_valid else "offline"),
            "message": (
                "Unsupported storage type"
                if not supported
                else ("Health check not requested" if config_valid else config_error)
            ),
        }

        if include_health and supported and config_valid and capabilities.get("health_check"):
            try:
                provider = provider_factory.create(normalized_type, self.config or {})
                health = provider.check_connection() or health
            except Exception as e:
                health = {
                    "status": "offline",
                    "message": str(e),
                }

        actions = {
            "can_preview": supported and config_valid and capabilities.get("preview", False),
            "can_scan": supported and config_valid and capabilities.get("scan", False),
            "can_stream": supported and config_valid and capabilities.get("stream", False),
        }

        return {
            "normalized_type": normalized_type,
            "capabilities": capabilities,
            "safe_config": safe_config,
            "supported": supported,
            "config_valid": config_valid,
            "config_error": config_error,
            "health": health,
            "actions": actions,
        }

    def get_usage_summary(self):
        library_bindings = getattr(self, 'library_bindings', [])
        resources = getattr(self, 'resources', [])

        library_binding_count = library_bindings.count() if hasattr(library_bindings, 'count') and not isinstance(library_bindings, list) else len(library_bindings)
        resource_count = resources.count() if hasattr(resources, 'count') and not isinstance(resources, list) else len(resources)

        return {
            "library_binding_count": library_binding_count,
            "resource_count": resource_count,
            "has_resources": resource_count > 0,
        }

    def get_mutation_guards(self):
        usage = self.get_usage_summary()
        has_dependents = usage["has_resources"] or usage["library_binding_count"] > 0

        return {
            "can_change_type": not has_dependents,
            "can_delete_directly": not has_dependents,
            "requires_keep_metadata_on_delete": usage["has_resources"],
            "has_dependents": has_dependents,
        }

    def to_dict(self, include_health=False):
        """返回面向接口展示的简化存储源结构。

        注意：这里的 root_path 是展示字段，不等同于 local provider
        运行时一定直接读取该字段；真实运行仍以 config 原始内容为准。
        """
        conf = self.config or {}
        display_root = build_source_display_root(self.type, conf)
        state = self.resolve_runtime_state(include_health=include_health)
        normalized_type = state["normalized_type"]
        capabilities = state["capabilities"]
        safe_config = state["safe_config"]
        supported = state["supported"]
        config_valid = state["config_valid"]
        config_error = state["config_error"]
        health = state["health"]
        actions = state["actions"]
        usage = self.get_usage_summary()
        guards = self.get_mutation_guards()
        try:
            _, display_name = get_source_display_name(normalized_type)
        except Exception:
            display_name = normalized_type

        data = {
            "id": self.id,
            "name": self.name,
            "type": normalized_type,
            "display_name": display_name,
            "root_path": display_root,
            "status": health.get("status", "unknown") if include_health else ("unsupported" if not supported else "unknown"),
            "is_supported": supported,
            "config_valid": config_valid,
            "config_error": config_error,
            "capabilities": capabilities,
            "config": safe_config,
            "actions": actions,
            "usage": usage,
            "guards": guards,
        }

        if include_health:
            data["health"] = health

        return data


class Library(db.Model):
    """逻辑资源库。"""
    __tablename__ = 'libraries'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    settings = db.Column(JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_bindings = db.relationship('LibrarySource', backref='library', lazy='dynamic', cascade="all, delete-orphan")
    movie_memberships = db.relationship('LibraryMovieMembership', backref='library', lazy='dynamic', cascade="all, delete-orphan")

    def to_dict(self, include_sources=False):
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "is_enabled": self.is_enabled,
            "sort_order": self.sort_order,
            "settings": self.settings or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_sources:
            data["sources"] = [binding.to_dict() for binding in self.source_bindings.order_by(LibrarySource.scan_order.asc(), LibrarySource.id.asc()).all()]
        return data


class LibrarySource(db.Model):
    """Library 与 StorageSource 的绑定关系。"""
    __tablename__ = 'library_sources'
    __table_args__ = (
        db.UniqueConstraint('library_id', 'source_id', 'root_path', name='uq_library_source_root'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey('libraries.id'), nullable=False, index=True)
    source_id = db.Column(db.Integer, db.ForeignKey('storage_sources.id'), nullable=False, index=True)
    root_path = db.Column(db.String(500), default='/', nullable=False)
    content_type = db.Column(db.String(20))
    scrape_enabled = db.Column(db.Boolean, default=True, nullable=False)
    scan_order = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    source = db.relationship('StorageSource', backref='library_bindings')

    def to_dict(self):
        return {
            "id": self.id,
            "library_id": self.library_id,
            "source_id": self.source_id,
            "root_path": self.root_path,
            "content_type": self.content_type,
            "scrape_enabled": self.scrape_enabled,
            "scan_order": self.scan_order,
            "is_enabled": self.is_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source": self.source.to_dict() if self.source else None,
        }


class LibraryMovieMembership(db.Model):
    """Library 与 Movie 的显式包含/排除规则。"""
    __tablename__ = 'library_movie_memberships'
    __table_args__ = (
        db.UniqueConstraint('library_id', 'movie_id', name='uq_library_movie_membership'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey('libraries.id'), nullable=False, index=True)
    movie_id = db.Column(db.String(36), db.ForeignKey('movies.id'), nullable=False, index=True)
    mode = db.Column(db.String(20), nullable=False, default='include')
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    movie = db.relationship('Movie')

    def to_dict(self, include_movie=True):
        data = {
            "id": self.id,
            "library_id": self.library_id,
            "movie_id": self.movie_id,
            "mode": self.mode,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_movie:
            data["movie"] = self.movie.to_simple_dict(include_season_cards=False) if self.movie else None
        return data


class HomepageSetting(db.Model):
    """首页门户配置，当前按单例记录维护。"""
    __tablename__ = 'homepage_settings'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    hero_movie_id = db.Column(db.String(36), db.ForeignKey('movies.id'), nullable=True)
    sections = db.Column(JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    hero_movie = db.relationship('Movie', foreign_keys=[hero_movie_id])

    def to_dict(self):
        return {
            "id": self.id,
            "hero_movie_id": self.hero_movie_id,
            "sections": self.sections or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Movie(db.Model):
    """影视条目模型，负责基础序列化；列表/详情的附加态由调用方注入。"""
    __tablename__ = 'movies'
    __table_args__ = {'extend_existing': True}

    QUALITY_BADGE_REMUX = "Remux"
    QUALITY_BADGE_4K = "4K"
    QUALITY_BADGE_HD = "HD"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tmdb_id = db.Column(db.String(50), unique=True, index=True)

    title = db.Column(db.String(255), nullable=False, index=True)
    original_title = db.Column(db.String(255))
    year = db.Column(db.Integer)
    rating = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text)

    cover = db.Column(db.String(500))
    background_cover = db.Column(db.String(500))

    category = db.Column(JSON)
    director = db.Column(db.String(100))
    actors = db.Column(JSON)

    country = db.Column(db.String(50))
    scraper_source = db.Column(db.String(20))

    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resources = db.relationship('MediaResource', backref='movie', lazy='dynamic', cascade="all, delete-orphan")
    season_metadata = db.relationship('MovieSeasonMetadata', backref='movie', lazy='dynamic', cascade="all, delete-orphan")
    metadata_lock = db.relationship('MovieMetadataLock', backref='movie', uselist=False, cascade="all, delete-orphan")

    def get_locked_fields(self):
        if not self.metadata_lock:
            return []
        return self.metadata_lock.get_locked_fields()

    def set_locked_fields(self, fields):
        lock = self.metadata_lock
        if not lock:
            lock = MovieMetadataLock(movie_id=self.id)
            self.metadata_lock = lock
        lock.set_locked_fields(fields)
        return lock.get_locked_fields()

    def add_locked_fields(self, fields):
        current = set(self.get_locked_fields())
        current.update(field for field in (fields or []) if isinstance(field, str) and field)
        return self.set_locked_fields(sorted(current))

    def remove_locked_fields(self, fields):
        current = set(self.get_locked_fields())
        current.difference_update(field for field in (fields or []) if isinstance(field, str) and field)
        return self.set_locked_fields(sorted(current))

    def get_season_metadata_map(self, include_empty=False):
        items = self.season_metadata.all()
        if include_empty:
            return {item.season: item for item in items}
        return {item.season: item for item in items if not item.is_empty()}

    def get_season_cards(self, user_history=None, resources=None):
        resources = resources if resources is not None else self.resources.all()
        if not resources:
            return []

        season_metadata_map = self.get_season_metadata_map(include_empty=True)
        season_history_map = {}
        if user_history:
            season_history_map = {
                str(season): payload
                for season, payload in (user_history.get("seasons_by_number") or {}).items()
            }
        grouped = {}

        for resource in resources:
            if resource.season is None:
                continue

            entry = grouped.setdefault(resource.season, {
                "season": resource.season,
                "resource_count": 0,
                "episode_numbers": set(),
                "primary_resource_id": None,
            })
            entry["resource_count"] += 1
            if resource.episode is not None:
                entry["episode_numbers"].add(resource.episode)
            if entry["primary_resource_id"] is None:
                entry["primary_resource_id"] = resource.id

        cards = []
        for season in sorted(grouped.keys()):
            summary = grouped[season]
            season_metadata = season_metadata_map.get(season)
            season_dict = season_metadata.to_dict() if season_metadata else {
                "season": season,
                "title": None,
                "display_title": f"Season {season}",
                "overview": None,
                "air_date": None,
                "poster_url": None,
                "episode_count": None,
                "has_manual_metadata": False,
                "has_metadata": False,
                "metadata_edited_at": None,
            }

            season_poster = season_dict.get("poster_url")
            poster_url = season_poster or self.cover
            poster_source = "season" if season_poster else ("movie_fallback" if self.cover else "none")
            episode_numbers = sorted(summary["episode_numbers"])

            cards.append({
                "id": f"{self.id}:season:{season}",
                "movie_id": self.id,
                "season": season,
                "title": season_dict.get("title"),
                "display_title": season_dict.get("display_title") or f"Season {season}",
                "overview": season_dict.get("overview"),
                "air_date": season_dict.get("air_date"),
                "poster_url": poster_url,
                "poster_source": poster_source,
                "has_distinct_poster": bool(season_poster and season_poster != self.cover),
                "resource_count": summary["resource_count"],
                "available_episode_count": len(episode_numbers),
                "episode_count": season_dict.get("episode_count"),
                "episode_numbers": episode_numbers,
                "primary_resource_id": summary["primary_resource_id"],
                "has_manual_metadata": season_dict.get("has_manual_metadata", False),
                "has_metadata": season_dict.get("has_metadata", False),
                "metadata_edited_at": season_dict.get("metadata_edited_at"),
                "user_data": season_history_map.get(str(season)),
            })

        return cards

    @staticmethod
    def _normalize_quality_marker(value):
        return re.sub(r'[^a-z0-9]+', '', str(value or '').strip().lower())

    @staticmethod
    def _coerce_quality_rank(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _resource_quality_badge(cls, resource):
        specs = resource.tech_specs or {}
        features = specs.get("features") or {}
        tags = specs.get("tags") or []
        tag_markers = {cls._normalize_quality_marker(tag) for tag in tags if tag}

        source_marker = cls._normalize_quality_marker(specs.get("source"))
        quality_marker = cls._normalize_quality_marker(specs.get("quality_tier"))
        codec_marker = cls._normalize_quality_marker(specs.get("codec"))
        quality_label_marker = cls._normalize_quality_marker(specs.get("quality_label"))

        if (
            features.get("is_remux")
            or "remux" in tag_markers
            or "remux" in source_marker
            or quality_marker == "remux"
            or codec_marker == "remux"
            or "remux" in quality_label_marker
        ):
            return cls.QUALITY_BADGE_REMUX

        resolution_marker = cls._normalize_quality_marker(specs.get("resolution"))
        resolution_rank = cls._coerce_quality_rank(specs.get("resolution_rank"))
        if (
            features.get("is_4k")
            or resolution_marker in {"4k", "2160p", "uhd"}
            or resolution_rank == 2160
            or "4k" in tag_markers
            or "2160p" in tag_markers
        ):
            return cls.QUALITY_BADGE_4K

        if (
            resolution_marker == "1080p"
            or resolution_rank == 1080
            or "1080p" in tag_markers
        ):
            return cls.QUALITY_BADGE_HD

        return None

    def get_quality_badge(self, resources=None):
        resources = resources if resources is not None else self.resources.all()
        has_4k = False
        has_hd = False

        for resource in resources:
            badge = self._resource_quality_badge(resource)
            if badge == self.QUALITY_BADGE_REMUX:
                return self.QUALITY_BADGE_REMUX
            if badge == self.QUALITY_BADGE_4K:
                has_4k = True
            elif badge == self.QUALITY_BADGE_HD:
                has_hd = True

        if has_4k:
            return self.QUALITY_BADGE_4K
        if has_hd:
            return self.QUALITY_BADGE_HD
        return None

    @staticmethod
    def get_metadata_source_group_map():
        return {
            "tmdb": ['TMDB_STRICT', 'TMDB_FALLBACK', 'TMDB'],
            "nfo_tmdb": ['NFO_TMDB'],
            "nfo_local": ['NFO_LOCAL', 'NFO'],
            "local": ['LOCAL_FALLBACK', 'LOCAL_ORPHAN'],
        }

    @staticmethod
    def get_metadata_review_priority_map():
        return {
            "none": ['TMDB_STRICT', 'NFO_TMDB'],
            "low": ['TMDB'],
            "medium": ['TMDB_FALLBACK', 'NFO_LOCAL', 'NFO'],
            "high": ['LOCAL_FALLBACK', 'LOCAL_ORPHAN'],
        }

    @staticmethod
    def get_metadata_non_attention_sources():
        return {'TMDB_STRICT', 'NFO_TMDB', 'TMDB'}

    @staticmethod
    def get_metadata_placeholder_sources():
        return {'LOCAL_FALLBACK', 'LOCAL_ORPHAN'}

    @staticmethod
    def get_metadata_local_only_sources():
        return {'NFO_LOCAL', 'NFO', 'LOCAL_FALLBACK', 'LOCAL_ORPHAN'}

    @staticmethod
    def build_metadata_ui_state(scraper_source):
        source = (scraper_source or '').strip().upper()
        state = {
            "source_code": scraper_source,
            "source_group": "unknown",
            "source_label": "Unknown",
            "is_placeholder": False,
            "is_local_only": False,
            "is_external_match": False,
            "confidence": "unknown",
            "needs_attention": True,
            "review_priority": "high",
            "badge_tone": "danger",
            "recommended_action": "match_metadata",
        }

        if source == 'TMDB_STRICT':
            state.update({
                "source_group": "tmdb",
                "source_label": "TMDB Strict",
                "is_external_match": True,
                "confidence": "high",
                "needs_attention": False,
                "review_priority": "none",
                "badge_tone": "success",
                "recommended_action": "none",
            })
        elif source == 'TMDB_FALLBACK':
            state.update({
                "source_group": "tmdb",
                "source_label": "TMDB Fallback",
                "is_external_match": True,
                "confidence": "medium",
                "needs_attention": True,
                "review_priority": "medium",
                "badge_tone": "warning",
                "recommended_action": "review_match",
            })
        elif source == 'NFO_TMDB':
            state.update({
                "source_group": "nfo_tmdb",
                "source_label": "NFO + TMDB",
                "is_external_match": True,
                "confidence": "high",
                "needs_attention": False,
                "review_priority": "none",
                "badge_tone": "success",
                "recommended_action": "none",
            })
        elif source == 'NFO_LOCAL':
            state.update({
                "source_group": "nfo_local",
                "source_label": "NFO Local",
                "is_local_only": True,
                "confidence": "medium",
                "needs_attention": True,
                "review_priority": "medium",
                "badge_tone": "info",
                "recommended_action": "match_metadata",
            })
        elif source == 'LOCAL_FALLBACK':
            state.update({
                "source_group": "local",
                "source_label": "Local Fallback",
                "is_placeholder": True,
                "is_local_only": True,
                "confidence": "low",
                "needs_attention": True,
                "review_priority": "high",
                "badge_tone": "danger",
                "recommended_action": "match_metadata",
            })
        elif source == 'LOCAL_ORPHAN':
            state.update({
                "source_group": "local",
                "source_label": "Local Orphan",
                "is_placeholder": True,
                "is_local_only": True,
                "confidence": "low",
                "needs_attention": True,
                "review_priority": "high",
                "badge_tone": "danger",
                "recommended_action": "rename_and_match",
            })
        elif source == 'TMDB':
            state.update({
                "source_group": "tmdb",
                "source_label": "TMDB",
                "is_external_match": True,
                "confidence": "medium",
                "needs_attention": False,
                "review_priority": "low",
                "badge_tone": "brand",
                "recommended_action": "refresh_metadata",
            })
        elif source == 'NFO':
            state.update({
                "source_group": "nfo_local",
                "source_label": "NFO",
                "is_local_only": True,
                "confidence": "medium",
                "needs_attention": True,
                "review_priority": "medium",
                "badge_tone": "info",
                "recommended_action": "match_metadata",
            })
        else:
            state.update({
                "needs_attention": True,
                "review_priority": "high",
                "badge_tone": "danger",
                "recommended_action": "inspect_metadata",
            })

        return state

    def get_metadata_ui_state(self):
        state = self.build_metadata_ui_state(self.scraper_source)
        if not self.cover:
            state.update({
                "needs_attention": True,
                "review_priority": "high",
                "badge_tone": "danger",
                "recommended_action": "refresh_metadata" if state["is_external_match"] else state["recommended_action"],
            })
        return state

    def get_metadata_diagnostics(self):
        resources = self.resources.all()
        season_resource_count = 0
        standalone_resource_count = 0
        edited_resource_count = 0
        low_confidence_resource_count = 0
        fallback_resource_count = 0
        nfo_candidate_resource_count = 0

        for resource in resources:
            if resource.season is None:
                standalone_resource_count += 1
            else:
                season_resource_count += 1

            if resource.has_manual_metadata():
                edited_resource_count += 1

            specs = resource.tech_specs or {}
            trace = specs.get('metadata_trace', {}) if isinstance(specs, dict) else {}
            confidence = trace.get('confidence')
            if confidence in ('low', 'unknown', None):
                low_confidence_resource_count += 1

            if trace.get('scrape_layer') == 'fallback':
                fallback_resource_count += 1

            if trace.get('has_nfo_candidates'):
                nfo_candidate_resource_count += 1

        metadata_lock = self.get_locked_fields()
        season_metadata_items = [item for item in self.season_metadata.all() if not item.is_empty()]

        return {
            "resource_count": len(resources),
            "season_resource_count": season_resource_count,
            "standalone_resource_count": standalone_resource_count,
            "edited_resource_count": edited_resource_count,
            "low_confidence_resource_count": low_confidence_resource_count,
            "fallback_resource_count": fallback_resource_count,
            "nfo_candidate_resource_count": nfo_candidate_resource_count,
            "locked_field_count": len(metadata_lock),
            "has_locked_fields": bool(metadata_lock),
            "season_metadata_count": len(season_metadata_items),
            "has_season_metadata": bool(season_metadata_items),
        }

    def get_metadata_actions(self, state=None, diagnostics=None):
        diagnostics = diagnostics or self.get_metadata_diagnostics()
        state = state or self.get_metadata_ui_state()

        can_refresh = bool(self.tmdb_id or self.title or self.original_title)
        can_manual_match = bool(self.title or self.original_title)
        can_re_scrape = diagnostics["resource_count"] > 0
        can_edit_resources = diagnostics["resource_count"] > 0
        can_edit_seasons = diagnostics["season_resource_count"] > 0

        return {
            "can_refresh": can_refresh,
            "can_manual_match": can_manual_match,
            "can_re_scrape": can_re_scrape,
            "can_edit_resources": can_edit_resources,
            "can_edit_seasons": can_edit_seasons,
            "primary_action": state["recommended_action"],
            "suggest_manual_review": state["needs_attention"],
        }

    def get_metadata_issues(self, state=None, diagnostics=None):
        state = dict(state or self.get_metadata_ui_state())
        diagnostics = diagnostics or self.get_metadata_diagnostics()
        issues = []

        def add_issue(code, label, severity, count=None):
            issues.append({
                "code": code,
                "label": label,
                "severity": severity,
                "count": count,
            })

        if state["is_placeholder"]:
            add_issue("placeholder_metadata", "Placeholder Metadata", "high")
        elif state["is_local_only"]:
            add_issue("local_only_metadata", "Local Only Metadata", "medium")

        if diagnostics["fallback_resource_count"] > 0:
            add_issue("fallback_pipeline_match", "Fallback Pipeline Match", "medium", diagnostics["fallback_resource_count"])

        if diagnostics["low_confidence_resource_count"] > 0:
            add_issue("low_confidence_resources", "Low Confidence Resources", "medium", diagnostics["low_confidence_resource_count"])

        if diagnostics["nfo_candidate_resource_count"] > 0:
            add_issue("nfo_candidates_available", "NFO Candidates Available", "low", diagnostics["nfo_candidate_resource_count"])

        if not self.cover:
            add_issue("poster_missing", "Poster Missing", "high")

        if diagnostics["has_locked_fields"]:
            add_issue("locked_fields_present", "Locked Fields Present", "low", diagnostics["locked_field_count"])

        if diagnostics["season_resource_count"] > 0 and not diagnostics["has_season_metadata"]:
            add_issue("season_metadata_missing", "Season Metadata Missing", "medium")

        if state["needs_attention"] and not issues:
            add_issue("manual_review_required", "Manual Review Required", state["review_priority"])

        return issues

    def get_metadata_snapshot(self):
        diagnostics = self.get_metadata_diagnostics()
        base_state = self.get_metadata_ui_state()
        issues = self.get_metadata_issues(state=base_state, diagnostics=diagnostics)
        state = {
            **base_state,
            "issue_count": len(issues),
            "issue_codes": [item["code"] for item in issues],
            "primary_issue_code": issues[0]["code"] if issues else None,
        }
        actions = self.get_metadata_actions(state=state, diagnostics=diagnostics)
        return {
            "state": state,
            "diagnostics": diagnostics,
            "actions": actions,
            "issues": issues,
        }

    def to_metadata_work_item(self):
        snapshot = self.get_metadata_snapshot()
        return {
            "id": self.id,
            "title": self.title,
            "original_title": self.original_title,
            "year": self.year,
            "poster_url": self.cover,
            "backdrop_url": self.background_cover,
            "country": self.country,
            "scraper_source": self.scraper_source,
            "metadata_state": snapshot["state"],
            "metadata_actions": snapshot["actions"],
            "metadata_diagnostics": snapshot["diagnostics"],
            "metadata_issues": snapshot["issues"],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_simple_dict(self, user_history=None, include_season_cards=True):
        resources = self.resources.all()
        # 聚合该电影所在的存储源 ID
        source_ids = list(set([r.source_id for r in resources if r.source_id]))
        snapshot = self.get_metadata_snapshot()
        public_categories = normalize_genres(self.category or [])
        if include_season_cards:
            season_cards = self.get_season_cards(user_history=user_history, resources=resources)
            season_count = len(season_cards)
        else:
            season_cards = []
            season_count = self.resources.filter(MediaResource.season.isnot(None)) \
                .with_entities(MediaResource.season).distinct().count()
        user_data = None
        if user_history:
            user_data_fields = (
                "last_played_at",
                "resource_id",
                "season",
                "episode",
                "episode_label",
                "label",
                "filename",
                "progress",
                "duration",
                "position_sec",
                "duration_sec",
                "progress_ratio",
                "progress_percent",
                "poster_url",
                "poster_source",
                "season_poster_url",
                "series_poster_url",
                "season_title",
                "season_display_title",
                "seasons",
            )
            user_data = {
                field: user_history.get(field)
                for field in user_data_fields
                if field in user_history
            }

        return {
            "id": self.id,
            "title": self.title,
            "poster_url": self.cover,
            "rating": self.rating,
            "year": self.year,
            "country": self.country,
            "quality_badge": self.get_quality_badge(resources=resources),
            "scraper_source": self.scraper_source,
            "metadata_state": snapshot["state"],
            "date_added": self.added_at.isoformat() if self.added_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "tags": public_categories,
            "source_ids": source_ids,
            "season_cards": season_cards,
            "season_count": season_count,
            "has_multi_season_content": season_count > 1,
            "user_data": user_data,
        }

    def to_detail_dict(self, user_history=None):
        simple = self.to_simple_dict(user_history=user_history)
        snapshot = self.get_metadata_snapshot()
        detailed = {
            "original_title": self.original_title,
            "overview": self.description,
            "backdrop_url": self.background_cover,
            "director": self.director,
            "actors": [{"name": a, "role": "Actor", "avatar": ""} for a in (self.actors or [])],
            "metadata_locked_fields": self.get_locked_fields(),
            "metadata_actions": snapshot["actions"],
            "metadata_diagnostics": snapshot["diagnostics"],
            "metadata_issues": snapshot["issues"],
        }
        return {**simple, **detailed}


class History(db.Model):
    __tablename__ = 'history'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.String(36), db.ForeignKey('media_resources.id'), nullable=True)
    file_path = db.Column(db.String(500))  # Legacy
    progress = db.Column(db.Integer, default=0)
    duration = db.Column(db.Integer, default=0)
    view_count = db.Column(db.Integer, default=1)
    device_id = db.Column(db.String(50))
    device_name = db.Column(db.String(50))
    last_watched = db.Column(db.DateTime, default=datetime.utcnow)


class MovieMetadataLock(db.Model):
    __tablename__ = 'movie_metadata_locks'
    __table_args__ = {'extend_existing': True}

    movie_id = db.Column(db.String(36), db.ForeignKey('movies.id'), primary_key=True)
    locked_fields = db.Column(JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_locked_fields(self):
        fields = self.locked_fields or []
        normalized = []
        seen = set()
        for field in fields:
            if not isinstance(field, str):
                continue
            field = field.strip()
            if not field or field in seen:
                continue
            seen.add(field)
            normalized.append(field)
        return normalized

    def set_locked_fields(self, fields):
        normalized = []
        seen = set()
        for field in fields or []:
            if not isinstance(field, str):
                continue
            field = field.strip()
            if not field or field in seen:
                continue
            seen.add(field)
            normalized.append(field)
        self.locked_fields = normalized
        return self.locked_fields


class MovieSeasonMetadata(db.Model):
    __tablename__ = 'movie_season_metadata'
    __table_args__ = {'extend_existing': True}

    movie_id = db.Column(db.String(36), db.ForeignKey('movies.id'), primary_key=True)
    season = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    overview = db.Column(db.Text)
    air_date = db.Column(db.String(10))
    poster = db.Column(db.String(500))
    episode_count = db.Column(db.Integer)
    metadata_edited_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_display_title(self):
        return self.title or f"Season {self.season}"

    def has_manual_metadata(self):
        return bool(self.title or self.overview or self.air_date)

    def has_metadata(self):
        return bool(self.title or self.overview or self.air_date or self.poster or self.episode_count is not None)

    def is_empty(self):
        return not self.has_metadata()

    def to_dict(self):
        return {
            "season": self.season,
            "title": self.title,
            "display_title": self.get_display_title(),
            "overview": self.overview,
            "air_date": self.air_date,
            "poster_url": self.poster,
            "episode_count": self.episode_count,
            "has_manual_metadata": self.has_manual_metadata(),
            "has_metadata": self.has_metadata(),
            "metadata_edited_at": self.metadata_edited_at.isoformat() if self.metadata_edited_at else None,
        }


class MediaResource(db.Model):
    __tablename__ = 'media_resources'
    __table_args__ = (
        db.UniqueConstraint('source_id', 'path', name='uq_media_resources_source_path'),
        {'extend_existing': True},
    )

    RESOLUTION_PROFILES = {
        '8k': {
            "code": "8k",
            "label": "8K",
            "bucket": "8k",
            "rank": 4320,
            "badge_label": "8K",
        },
        '2160p': {
            "code": "2160p",
            "label": "2160P",
            "bucket": "4k",
            "rank": 2160,
            "badge_label": "4K",
        },
        '1080p': {
            "code": "1080p",
            "label": "1080P",
            "bucket": "full_hd",
            "rank": 1080,
            "badge_label": "1080P",
        },
        '720p': {
            "code": "720p",
            "label": "720P",
            "bucket": "hd",
            "rank": 720,
            "badge_label": "720P",
        },
        '480p': {
            "code": "480p",
            "label": "480P",
            "bucket": "sd",
            "rank": 480,
            "badge_label": "480P",
        },
    }

    VIDEO_CODEC_PROFILES = {
        'av1': {"code": "av1", "label": "AV1"},
        'hevc': {"code": "hevc", "label": "HEVC"},
        'avc': {"code": "avc", "label": "AVC"},
        'vc_1': {"code": "vc1", "label": "VC-1"},
        'vp9': {"code": "vp9", "label": "VP9"},
    }

    AUDIO_CODEC_PROFILES = {
        'dolby_truehd_atmos': {"code": "truehd_atmos", "label": "Dolby TrueHD Atmos", "is_atmos": True, "is_lossless": True},
        'truehd_atmos': {"code": "truehd_atmos", "label": "Dolby TrueHD Atmos", "is_atmos": True, "is_lossless": True},
        'dolby_atmos': {"code": "dolby_atmos", "label": "Dolby Atmos", "is_atmos": True, "is_lossless": False},
        'dts_x': {"code": "dts_x", "label": "DTS:X", "is_atmos": False, "is_lossless": False},
        'dts_hd_ma': {"code": "dts_hd_ma", "label": "DTS-HD MA", "is_atmos": False, "is_lossless": True},
        'dolby_truehd': {"code": "truehd", "label": "Dolby TrueHD", "is_atmos": False, "is_lossless": True},
        'truehd': {"code": "truehd", "label": "Dolby TrueHD", "is_atmos": False, "is_lossless": True},
        'e_ac3': {"code": "eac3", "label": "E-AC3", "is_atmos": False, "is_lossless": False},
        'ac3': {"code": "ac3", "label": "AC3", "is_atmos": False, "is_lossless": False},
        'aac': {"code": "aac", "label": "AAC", "is_atmos": False, "is_lossless": False},
    }

    SOURCE_PROFILES = {
        'uhd_blu_ray_remux': {"code": "uhd_bluray_remux", "label": "UHD Blu-ray Remux", "kind": "disc", "is_remux": True, "is_uhd_bluray": True},
        'blu_ray_remux': {"code": "bluray_remux", "label": "Blu-ray Remux", "kind": "disc", "is_remux": True, "is_uhd_bluray": False},
        'uhd_blu_ray': {"code": "uhd_bluray", "label": "UHD Blu-ray", "kind": "disc", "is_remux": False, "is_uhd_bluray": True},
        'blu_ray': {"code": "bluray", "label": "Blu-ray", "kind": "disc", "is_remux": False, "is_uhd_bluray": False},
        'web_dl': {"code": "web_dl", "label": "WEB-DL", "kind": "web", "is_remux": False, "is_uhd_bluray": False},
        'webrip': {"code": "webrip", "label": "WEBRip", "kind": "web", "is_remux": False, "is_uhd_bluray": False},
        'hdtv': {"code": "hdtv", "label": "HDTV", "kind": "broadcast", "is_remux": False, "is_uhd_bluray": False},
    }

    HDR_PROFILES = {
        'dolby_vision': {"code": "dolby_vision", "label": "Dolby Vision", "is_hdr": True},
        'hdr10_plus': {"code": "hdr10_plus", "label": "HDR10+", "is_hdr": True},
        'hdr10': {"code": "hdr10", "label": "HDR10", "is_hdr": True},
        'hlg': {"code": "hlg", "label": "HLG", "is_hdr": True},
        'hdr': {"code": "hdr", "label": "HDR", "is_hdr": True},
        'sdr': {"code": "sdr", "label": "SDR", "is_hdr": False},
    }

    QUALITY_TIER_PROFILES = {
        'reference': {"code": "reference", "label": "Reference", "rank": 500},
        'remux': {"code": "remux", "label": "Remux", "rank": 400},
        'premium': {"code": "premium", "label": "Premium", "rank": 300},
        'uhd': {"code": "uhd", "label": "UHD", "rank": 250},
        'hd': {"code": "hd", "label": "HD", "rank": 200},
        'standard': {"code": "standard", "label": "Standard", "rank": 100},
    }

    BADGE_PROFILES = {
        '8k': {"code": "8k", "label": "8K", "category": "resolution", "priority": 100},
        '4k': {"code": "4k", "label": "4K", "category": "resolution", "priority": 100},
        '1080p': {"code": "1080p", "label": "1080P", "category": "resolution", "priority": 95},
        '720p': {"code": "720p", "label": "720P", "category": "resolution", "priority": 90},
        '480p': {"code": "480p", "label": "480P", "category": "resolution", "priority": 80},
        'hdr': {"code": "hdr", "label": "HDR", "category": "dynamic_range", "priority": 85},
        'hdr10': {"code": "hdr10", "label": "HDR10", "category": "dynamic_range", "priority": 85},
        'hdr10_plus': {"code": "hdr10_plus", "label": "HDR10+", "category": "dynamic_range", "priority": 87},
        'hlg': {"code": "hlg", "label": "HLG", "category": "dynamic_range", "priority": 84},
        'dolby_vision': {"code": "dolby_vision", "label": "Dolby Vision", "category": "dynamic_range", "priority": 88},
        'atmos': {"code": "atmos", "label": "Atmos", "category": "audio", "priority": 70},
        'remux': {"code": "remux", "label": "REMUX", "category": "source", "priority": 75},
        'imax': {"code": "imax", "label": "IMAX", "category": "edition", "priority": 60},
        '10bit': {"code": "10bit", "label": "10bit", "category": "video", "priority": 55},
    }

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    movie_id = db.Column(db.String(36), db.ForeignKey('movies.id'), nullable=False)

    # 新增: 关联存储源
    source_id = db.Column(db.Integer, db.ForeignKey('storage_sources.id'), nullable=True)
    source = db.relationship('StorageSource', backref='resources')

    # path 现在存储相对于 StorageSource 根目录的路径
    path = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(255))

    size = db.Column(db.Integer, default=0)
    season = db.Column(db.Integer, nullable=True)
    episode = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(255))
    overview = db.Column(db.Text)
    metadata_edited_at = db.Column(db.DateTime)
    label = db.Column(db.String(50))
    tech_specs = db.Column(JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_episode_label(self):
        if self.season is not None and self.episode is not None:
            return f"S{self.season:02d}E{self.episode:02d}"
        if self.episode is not None:
            return f"EP{self.episode:02d}"
        return None

    def get_display_title(self):
        if self.title:
            return self.title
        if self.get_episode_label():
            return self.get_episode_label()
        return self.filename

    def get_sort_key(self):
        return {
            "season": self.season if self.season is not None else 9999,
            "episode": self.episode if self.episode is not None else 9999,
            "filename": self.filename or "",
        }

    def has_manual_metadata(self):
        return bool(self.metadata_edited_at or self.title or self.overview)

    @staticmethod
    def _normalize_media_value(value):
        return re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')

    @classmethod
    def _build_resolution_profile(cls, resolution, resolution_rank):
        label = str(resolution or '').strip() or 'Unknown'
        key = cls._normalize_media_value(label)
        profile = dict(cls.RESOLUTION_PROFILES.get(key, {}))
        if profile:
            profile["label"] = label or profile["label"]
            profile["rank"] = int(resolution_rank or profile.get("rank") or 0)
            profile["is_known"] = True
            return profile
        return {
            "code": key or "unknown",
            "label": label,
            "bucket": "unknown",
            "rank": int(resolution_rank or 0),
            "badge_label": None,
            "is_known": False,
        }

    @classmethod
    def _build_named_profile(cls, value, mapping):
        label = str(value or '').strip() or 'Unknown'
        key = cls._normalize_media_value(label)
        profile = dict(mapping.get(key, {}))
        if profile:
            profile["label"] = label or profile["label"]
            profile["is_known"] = True
            return profile
        return {
            "code": key or "unknown",
            "label": label,
            "is_known": False,
        }

    @classmethod
    def _build_container_profile(cls, container):
        label = str(container or '').strip()
        if not label:
            return {
                "code": "unknown",
                "label": "Unknown",
                "is_known": False,
            }
        return {
            "code": cls._normalize_media_value(label),
            "label": label.upper(),
            "is_known": True,
        }

    @classmethod
    def _build_quality_profile(cls, quality_tier, quality_label, flags):
        label = str(quality_label or '').strip() or 'Unknown'
        tier = str(quality_tier or '').strip() or 'standard'
        key = cls._normalize_media_value(tier)
        profile = dict(cls.QUALITY_TIER_PROFILES.get(key, {}))
        if not profile:
            profile = {
                "code": key or "standard",
                "label": tier or "standard",
                "rank": 0,
            }
        profile.update({
            "tier": key or "standard",
            "summary_label": label,
            "is_reference": (key == 'reference'),
            "is_original_quality": bool((flags or {}).get('is_original_quality')),
        })
        return profile

    @classmethod
    def _build_bit_depth_profile(cls, flags):
        if (flags or {}).get('ten_bit'):
            return {
                "code": "10bit",
                "label": "10bit",
                "value": 10,
                "detected": True,
            }
        return {
            "code": "unknown",
            "label": "Unknown",
            "value": None,
            "detected": False,
        }

    @classmethod
    def _detect_audio_channels(cls, text):
        match = re.search(r'(?<!\d)([1-9](?:\.[0-9]))(?!\d)', text or '')
        if not match:
            return None, None
        layout = match.group(1)
        major, minor = layout.split('.', 1)
        return layout, int(major) + int(minor)

    @classmethod
    def _normalize_resource_source(cls, source, text):
        key = cls._normalize_media_value(source)
        has_remux = bool(re.search(r'\b(?:REMUX|REMUNX|REMUXED)\b', text or '', re.I))
        has_uhd_bluray = bool(re.search(r'\b(?:UHD|4K)[ ._-]*BLU(?:-?RAY)?\b|\bUHD[ ._-]*BLU(?:-?RAY)?\b', text or '', re.I))
        if has_remux and has_uhd_bluray:
            return "UHD Blu-ray Remux"
        if has_remux:
            return "Blu-ray Remux"
        if has_uhd_bluray and key in {"unknown", "blu_ray", "uhd_blu_ray", ""}:
            return "UHD Blu-ray"
        return source

    @classmethod
    def _normalize_resource_audio_codec(cls, audio_codec, text):
        normalized = cls._normalize_media_value(audio_codec)
        has_truehd = bool(re.search(r'\bTRUEHD(?:[ ._-]*\d(?:\.\d)?)?\b', text or '', re.I))
        has_atmos = bool(re.search(r'\b(?:ATMOS|DOLBY[ ._-]*ATMOS)\b', text or '', re.I))
        if has_truehd and has_atmos:
            return "Dolby TrueHD Atmos"
        if has_truehd:
            return "Dolby TrueHD"
        if normalized == "truehd_atmos":
            return "Dolby TrueHD Atmos"
        if normalized == "truehd":
            return "Dolby TrueHD"
        return audio_codec

    @classmethod
    def _build_audio_summary_label(cls, audio_codec_profile, channels_label, is_atmos):
        code = audio_codec_profile.get("code")
        label = audio_codec_profile.get("label") or "Unknown"
        if code == "truehd_atmos":
            base = "Dolby TrueHD"
            return f"{base} {channels_label} Atmos" if channels_label else f"{base} Atmos"
        if code == "truehd":
            return f"Dolby TrueHD {channels_label}" if channels_label else "Dolby TrueHD"
        if channels_label and label != "Unknown":
            if is_atmos and "Atmos" not in label:
                return f"{label} {channels_label} Atmos"
            return f"{label} {channels_label}"
        return label

    @classmethod
    def _build_badges(cls, tags, resolution_profile, hdr_profile, audio_profile, source_profile, flags):
        badges = []
        seen = set()

        def add_badge(label):
            key = cls._normalize_media_value(label)
            if not key or key in seen:
                return
            badge = dict(cls.BADGE_PROFILES.get(key, {}))
            if not badge:
                badge = {
                    "code": key,
                    "label": str(label).strip(),
                    "category": "custom",
                    "priority": 10,
                }
            badge["is_known"] = key in cls.BADGE_PROFILES
            badges.append(badge)
            seen.add(key)

        for raw_tag in tags or []:
            add_badge(raw_tag)

        if resolution_profile.get("badge_label"):
            add_badge(resolution_profile["badge_label"])
        if hdr_profile.get("is_hdr") and hdr_profile.get("label"):
            add_badge(hdr_profile["label"])
        if audio_profile.get("is_atmos"):
            add_badge('Atmos')
        if source_profile.get("is_remux"):
            add_badge('REMUX')
        if (flags or {}).get('imax'):
            add_badge('IMAX')
        if (flags or {}).get('ten_bit'):
            add_badge('10bit')

        badges.sort(key=lambda item: (-item.get("priority", 0), item.get("label", "")))
        return badges

    @classmethod
    def _build_media_profile(cls, media_features, container):
        flags = dict(media_features.get('flags') or {})
        resolution_profile = cls._build_resolution_profile(
            media_features.get('resolution'),
            media_features.get('resolution_rank'),
        )
        video_codec_profile = cls._build_named_profile(
            media_features.get('video_codec'),
            cls.VIDEO_CODEC_PROFILES,
        )
        audio_codec_profile = cls._build_named_profile(
            media_features.get('audio_codec'),
            cls.AUDIO_CODEC_PROFILES,
        )
        audio_channels_label = media_features.get('audio_channels')
        audio_channel_count = media_features.get('audio_channel_count')
        audio_is_atmos = bool(audio_codec_profile.get("is_atmos"))
        audio_is_lossless = bool(audio_codec_profile.get("is_lossless") or flags.get("is_lossless_audio"))
        audio_summary_label = cls._build_audio_summary_label(
            audio_codec_profile,
            audio_channels_label,
            audio_is_atmos,
        )
        source_profile = cls._build_named_profile(
            media_features.get('source'),
            cls.SOURCE_PROFILES,
        )
        hdr_profile = cls._build_named_profile(
            media_features.get('hdr_format'),
            cls.HDR_PROFILES,
        )
        quality_profile = cls._build_quality_profile(
            media_features.get('quality_tier'),
            media_features.get('quality_label'),
            flags,
        )
        badges = cls._build_badges(
            media_features.get('tags') or [],
            resolution_profile,
            hdr_profile,
            audio_codec_profile,
            source_profile,
            flags,
        )

        return {
            "summary_label": quality_profile["summary_label"],
            "badges": badges,
            "container": cls._build_container_profile(container),
            "video": {
                "resolution": resolution_profile,
                "codec": video_codec_profile,
                "dynamic_range": hdr_profile,
                "bit_depth": cls._build_bit_depth_profile(flags),
            },
            "audio": {
                "codec": audio_codec_profile,
                "channels_label": audio_channels_label,
                "channel_count": audio_channel_count,
                "is_atmos": audio_is_atmos,
                "is_lossless": audio_is_lossless,
                "summary_label": audio_summary_label,
            },
            "source": source_profile,
            "quality": quality_profile,
            "flags": flags,
        }

    @classmethod
    def _normalize_resource_hdr_format(cls, hdr_format, filename, path, tags):
        value = str(hdr_format or '').strip() or 'Unknown'
        text = " ".join(str(part or '') for part in [filename, path])
        key = cls._normalize_media_value(value)
        if key in {'dolby_vision', 'dv'}:
            return 'Dolby Vision'
        if key in {'hdr10_plus', 'hdr10plus'} or re.search(r'\bHDR10(?:[ ._-]*\+|PLUS)(?=[^A-Z0-9]|$)', text, re.I):
            return 'HDR10+'
        if key in {'hdr', 'hdr10'} or re.search(r'\b(?:HDR10|HDR)\b', text, re.I):
            return 'HDR10'
        if key == 'hlg' or re.search(r'\bHLG\b', text, re.I):
            return 'HLG'
        if key != 'sdr':
            return value

        has_explicit_sdr = bool(re.search(r'\bSDR\b', text, re.I))
        has_sdr_tag = any(cls._normalize_media_value(tag) == 'sdr' for tag in (tags or []))
        return 'SDR' if has_explicit_sdr or has_sdr_tag else 'Unknown'

    @classmethod
    def _build_extra_technical_tags(cls, media_features, media_profile):
        tags = media_features.get("tags") or []
        flags = dict(media_profile.get("flags") or {})
        video = media_profile.get("video") or {}
        audio = media_profile.get("audio") or {}
        source = media_profile.get("source") or {}

        represented_codes = set()
        resolution = video.get("resolution") or {}
        if resolution.get("bucket"):
            represented_codes.add(resolution["bucket"])
        if resolution.get("code"):
            represented_codes.add(resolution["code"])

        dynamic_range = video.get("dynamic_range") or {}
        if dynamic_range.get("code"):
            represented_codes.add(dynamic_range["code"])
        if dynamic_range.get("is_hdr"):
            represented_codes.add("hdr")
            represented_codes.add("hdr10")
            represented_codes.add("hdr10_plus")
            represented_codes.add("hlg")

        if audio.get("is_atmos"):
            represented_codes.add("atmos")
        if source.get("is_remux"):
            represented_codes.add("remux")
        if source.get("is_uhd_bluray"):
            represented_codes.add("uhd")
            represented_codes.add("uhd_blu_ray")
            represented_codes.add("uhd_bluray")
        if flags.get("ten_bit"):
            represented_codes.add("10bit")

        extra_tags = []
        for tag in tags:
            tag_code = cls._normalize_media_value(tag)
            if not tag_code or tag_code in represented_codes:
                continue
            if tag not in extra_tags:
                extra_tags.append(tag)
        return extra_tags

    @staticmethod
    def _build_resource_quality_info(quality_profile):
        return {
            "tier": quality_profile.get("tier"),
            "label": quality_profile.get("label"),
            "rank": quality_profile.get("rank"),
            "is_reference": quality_profile.get("is_reference", False),
            "is_original_quality": quality_profile.get("is_original_quality", False),
        }

    @classmethod
    def _build_resource_technical_info(cls, media_features, media_profile):
        video = media_profile.get("video") or {}
        resolution = video.get("resolution") or {}
        video_codec = video.get("codec") or {}
        dynamic_range = video.get("dynamic_range") or {}
        bit_depth = video.get("bit_depth") or {}
        audio = media_profile.get("audio") or {}
        audio_codec = audio.get("codec") or {}
        source = media_profile.get("source") or {}
        quality = cls._build_resource_quality_info(media_profile.get("quality") or {})
        flags = dict(media_profile.get("flags") or {})

        return {
            "video_resolution_code": resolution.get("code"),
            "video_resolution_label": resolution.get("label"),
            "video_resolution_bucket": resolution.get("bucket"),
            "video_resolution_rank": resolution.get("rank", 0),
            "video_resolution_badge_label": resolution.get("badge_label"),
            "video_resolution_is_known": bool(resolution.get("is_known")),
            "video_codec_code": video_codec.get("code"),
            "video_codec_label": video_codec.get("label"),
            "video_codec_is_known": bool(video_codec.get("is_known")),
            "video_dynamic_range_code": dynamic_range.get("code"),
            "video_dynamic_range_label": dynamic_range.get("label"),
            "video_dynamic_range_is_hdr": bool(dynamic_range.get("is_hdr")),
            "video_dynamic_range_is_known": bool(dynamic_range.get("is_known")),
            "video_bit_depth_code": bit_depth.get("code"),
            "video_bit_depth_label": bit_depth.get("label"),
            "video_bit_depth_value": bit_depth.get("value"),
            "video_bit_depth_detected": bool(bit_depth.get("detected")),
            "audio_codec_code": audio_codec.get("code"),
            "audio_codec_label": audio_codec.get("label"),
            "audio_codec_is_atmos": bool(audio_codec.get("is_atmos")),
            "audio_codec_is_known": bool(audio_codec.get("is_known")),
            "audio_is_atmos": bool(audio.get("is_atmos")),
            "audio_channels_label": audio.get("channels_label"),
            "audio_channel_count": audio.get("channel_count"),
            "audio_is_lossless": bool(audio.get("is_lossless")),
            "audio_summary_label": audio.get("summary_label"),
            "source_code": source.get("code"),
            "source_label": source.get("label"),
            "source_kind": source.get("kind"),
            "source_is_remux": bool(source.get("is_remux")),
            "source_is_uhd_bluray": bool(source.get("is_uhd_bluray")),
            "source_is_known": bool(source.get("is_known")),
            "quality_tier": quality.get("tier"),
            "quality_tier_label": quality.get("label"),
            "quality_rank": quality.get("rank"),
            "quality_is_reference": bool(quality.get("is_reference")),
            "quality_is_original_quality": bool(quality.get("is_original_quality")),
            "flag_is_4k": bool(flags.get("is_4k")),
            "flag_is_1080p": bool(flags.get("is_1080p")),
            "flag_is_hdr": bool(flags.get("is_hdr")),
            "flag_is_hdr10": bool(flags.get("is_hdr10")),
            "flag_is_hdr10_plus": bool(flags.get("is_hdr10_plus")),
            "flag_is_hlg": bool(flags.get("is_hlg")),
            "flag_is_dolby_vision": bool(flags.get("is_dolby_vision")),
            "flag_is_remux": bool(flags.get("is_remux")),
            "flag_is_uhd_bluray": bool(flags.get("is_uhd_bluray")),
            "flag_is_original_quality": bool(flags.get("is_original_quality")),
            "flag_is_lossless_audio": bool(flags.get("is_lossless_audio")),
            "flag_is_movie_feature": bool(flags.get("is_movie_feature")),
            "flag_imax": bool(flags.get("imax")),
            "flag_ten_bit": bool(flags.get("ten_bit")),
            "extra_tags": cls._build_extra_technical_tags(media_features, media_profile),
        }

    def _build_resource_info(self, container, media_features, media_profile):
        return {
            "file": {
                "filename": self.filename,
                "relative_path": self.path,
                "size_bytes": self.size,
                "container": container,
                "storage_source": {
                    "id": self.source_id,
                    "name": self.source.name if self.source else "Unknown",
                    "type": self.source.type if self.source else "local",
                },
            },
            "display": {
                "title": self.get_display_title(),
                "label": self.label,
                "season": self.season,
                "episode": self.episode,
                "episode_label": self.get_episode_label(),
                "sort_key": self.get_sort_key(),
                "has_manual_metadata": self.has_manual_metadata(),
                "metadata_edited_at": self.metadata_edited_at.isoformat() if self.metadata_edited_at else None,
            },
            "technical": self._build_resource_technical_info(media_features, media_profile),
        }

    def to_dict(self):
        """返回资源详情；只输出当前 API 结构，不再携带旧兼容字段。"""
        specs = self.tech_specs if self.tech_specs else {}
        metadata_trace = specs.get('metadata_trace', {}) if isinstance(specs, dict) else {}
        analysis = specs.get('analysis', {}) if isinstance(specs, dict) else {}
        feature_flags = specs.get('features', {}) if isinstance(specs.get('features'), dict) else {}
        tags = specs.get('tags', []) if isinstance(specs.get('tags'), list) else []
        detection_text = " ".join(str(part or '') for part in [self.filename, self.path])
        hdr_format = self._normalize_resource_hdr_format(
            specs.get('hdr_format'),
            self.filename,
            self.path,
            tags,
        )
        audio_channels = specs.get('audio_channels')
        audio_channel_count = specs.get('audio_channel_count')
        if not audio_channels:
            audio_channels, audio_channel_count = self._detect_audio_channels(detection_text)
        normalized_audio_codec = self._normalize_resource_audio_codec(specs.get('audio_codec', 'Unknown'), detection_text)
        normalized_source = self._normalize_resource_source(specs.get('source', 'Unknown'), detection_text)
        source_key = self._normalize_media_value(normalized_source)
        audio_key = self._normalize_media_value(normalized_audio_codec)
        if hdr_format in {'Dolby Vision', 'HDR10', 'HDR10+', 'HLG'}:
            feature_flags['is_hdr'] = True
        if hdr_format == 'HDR10':
            feature_flags['is_hdr10'] = True
        if hdr_format == 'HDR10+':
            feature_flags['is_hdr10_plus'] = True
        if hdr_format == 'HLG':
            feature_flags['is_hlg'] = True
        if source_key in {'uhd_blu_ray_remux', 'uhd_blu_ray'}:
            feature_flags['is_uhd_bluray'] = True
        if source_key in {'uhd_blu_ray_remux', 'blu_ray_remux'}:
            feature_flags['is_remux'] = True
            feature_flags['is_original_quality'] = True
        if audio_key in {'dolby_truehd_atmos', 'truehd_atmos', 'dolby_truehd', 'truehd', 'dts_hd_ma'}:
            feature_flags['is_lossless_audio'] = True
        media_features = {
            "resolution": specs.get('resolution', 'Unknown'),
            "resolution_rank": specs.get('resolution_rank', 0),
            "video_codec": specs.get('video_codec') or specs.get('codec', 'Unknown'),
            "audio_codec": normalized_audio_codec,
            "audio_channels": audio_channels,
            "audio_channel_count": audio_channel_count,
            "source": normalized_source,
            "quality_tier": specs.get('quality_tier', 'standard'),
            "quality_label": specs.get('quality_label') or self.label,
            "hdr_format": hdr_format,
            "tags": tags,
            "flags": feature_flags,
        }
        # 简单推断容器格式
        container = self.filename.split('.')[-1].lower() if self.filename else None
        media_profile = self._build_media_profile(media_features, container)
        resource_info = self._build_resource_info(container, media_features, media_profile)
        edit_context = {
            "parse_layer": metadata_trace.get('parse_layer'),
            "parse_strategy": metadata_trace.get('parse_strategy'),
            "scrape_layer": metadata_trace.get('scrape_layer'),
            "scrape_strategy": metadata_trace.get('scrape_strategy'),
            "scrape_reason": metadata_trace.get('scrape_reason'),
            "media_type_hint": metadata_trace.get('media_type_hint'),
            "confidence": metadata_trace.get('confidence'),
            "has_nfo_candidates": bool(metadata_trace.get('has_nfo_candidates')),
            "has_inferred_episode": self.episode is not None,
            "has_inferred_season": self.season is not None,
        }

        return {
            "id": self.id,
            "resource_info": resource_info,
            "playback": build_resource_playback(self, resource_info=resource_info),
            "metadata": {
                "trace": metadata_trace,
                "analysis": analysis,
                "edit_context": edit_context,
            }
        }
