import json
import os
import logging
from datetime import datetime
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from backend.app.extensions import db
from backend.app.models import (
    HomepageSetting,
    History,
    LibrarySource,
    LibraryMovieMembership,
    MediaResource,
    Movie,
    MovieMetadataLock,
    MovieSeasonMetadata,
    ResourceSubtitle,
    ResourceSubtitleSetting,
    StorageSource,
    UserFavorite,
    UserSubtitleSetting,
)
from backend.app.services.accounts import get_account_scoped

logger = logging.getLogger(__name__)

MOVIE_METADATA_FIELDS = (
    'title',
    'original_title',
    'year',
    'rating',
    'description',
    'cover',
    'background_cover',
    'category',
    'director',
    'actors',
    'country',
    'scraper_source',
)

SEASON_METADATA_FIELDS = (
    'title',
    'overview',
    'air_date',
    'poster',
    'episode_count',
    'aired_episode_count',
)


class MovieDatabaseAdapter:

    def init_db(self):
        pass

    def _build_resource_tech_specs(self, resource_info):
        tech_specs = dict(resource_info.get('tech_specs') or {})
        analysis = resource_info.get('analysis')
        if isinstance(analysis, dict) and analysis:
            tech_specs['analysis'] = analysis
        return tech_specs

    def get_movie_by_title_year(self, title, year, media_type=None):
        query = Movie.query.filter(Movie.title == title)
        if year:
            query = query.filter(Movie.year == year)
        media_type = (media_type or '').strip().lower()
        if media_type in {'movie', 'tv'}:
            query = query.filter(Movie.tmdb_id.like(f'{media_type}/%'))
        movie = query.first()
        if movie:
            return {"tmdb_id": movie.tmdb_id, "id": movie.id}
        return None

    def _apply_resource_fields(self, resource, movie, resource_info, rel_path, tech_specs):
        resource.movie_id = movie.id
        resource.path = rel_path
        resource.filename = os.path.basename(rel_path)
        resource.size = tech_specs.get('size', 0)
        resource.tech_specs = tech_specs
        resource.season = resource_info.get('season')
        resource.episode = resource_info.get('episode')
        resource.label = resource_info.get('label')

    def _apply_pending_review_default(self, movie, *, created=False, previously_visible=False):
        return movie.apply_pending_review_default(
            created=created,
            previously_visible=previously_visible,
        )

    def _normalize_resource_path(self, path):
        return str(path or '').replace('\\', '/').strip().strip('/')

    def _resource_parent_path(self, path):
        normalized = self._normalize_resource_path(path)
        if not normalized or '/' not in normalized:
            return ''
        return normalized.rsplit('/', 1)[0]

    def _is_local_fallback_identity(self, tmdb_id):
        return str(tmdb_id or '').strip().lower().startswith('loc-')

    def _find_replacement_resource(self, movie, resource_info, source_id, rel_path):
        episode = resource_info.get('episode')
        if episode is None:
            return None

        parent_path = self._resource_parent_path(rel_path)
        query = MediaResource.query.filter_by(
            movie_id=movie.id,
            source_id=source_id,
            season=resource_info.get('season'),
            episode=episode,
        )
        candidates = [
            resource for resource in query.all()
            if self._resource_parent_path(resource.path) == parent_path
            and self._normalize_resource_path(resource.path) != self._normalize_resource_path(rel_path)
        ]
        if len(candidates) != 1:
            return None
        return candidates[0]

    def _find_movie_by_replaced_local_resource(self, meta_data, resource_info, source_id):
        if not self._is_local_fallback_identity(meta_data.get('tmdb_id')):
            return None
        episode = resource_info.get('episode')
        if episode is None:
            return None

        rel_path = resource_info.get('path')
        parent_path = self._resource_parent_path(rel_path)
        query = MediaResource.query.filter_by(
            source_id=source_id,
            season=resource_info.get('season'),
            episode=episode,
        )
        candidate_movies = {}
        for resource in query.all():
            if (
                resource.movie
                and self._resource_parent_path(resource.path) == parent_path
                and self._normalize_resource_path(resource.path) != self._normalize_resource_path(rel_path)
            ):
                candidate_movies[resource.movie.id] = resource.movie
        if len(candidate_movies) != 1:
            return None
        return next(iter(candidate_movies.values()))

    def _merge_library_memberships(self, source_movie, target_movie):
        for row in LibraryMovieMembership.query.filter_by(movie_id=source_movie.id).all():
            duplicate = LibraryMovieMembership.query.filter_by(
                library_id=row.library_id,
                movie_id=target_movie.id,
            ).first()
            if duplicate:
                db.session.delete(row)
            else:
                row.movie_id = target_movie.id

    def _merge_user_favorites(self, source_movie, target_movie):
        for row in UserFavorite.query.filter_by(movie_id=source_movie.id).all():
            duplicate = UserFavorite.query.filter_by(
                scope_key=row.scope_key,
                movie_id=target_movie.id,
            ).first()
            if duplicate:
                db.session.delete(row)
            else:
                row.movie_id = target_movie.id

    def _replace_movie_id_in_homepage_sections(self, sections, source_movie_id, target_movie_id):
        if not isinstance(sections, list):
            return sections, False

        changed = False
        next_sections = []
        for section in sections:
            if not isinstance(section, dict):
                next_sections.append(section)
                continue
            movie_ids = section.get('movie_ids')
            if not isinstance(movie_ids, list):
                next_sections.append(section)
                continue

            section_changed = False
            next_movie_ids = []
            seen = set()
            for movie_id in movie_ids:
                next_movie_id = target_movie_id if movie_id == source_movie_id else movie_id
                if next_movie_id in seen:
                    section_changed = True
                    changed = True
                    continue
                seen.add(next_movie_id)
                next_movie_ids.append(next_movie_id)
                if next_movie_id != movie_id:
                    section_changed = True
                    changed = True

            if section_changed:
                section = dict(section)
                section['movie_ids'] = next_movie_ids
            next_sections.append(section)

        return next_sections, changed

    def _merge_homepage_settings(self, source_movie, target_movie):
        for setting in HomepageSetting.query.all():
            changed = False
            if setting.hero_movie_id == source_movie.id:
                setting.hero_movie_id = target_movie.id
                changed = True
            sections, sections_changed = self._replace_movie_id_in_homepage_sections(
                setting.sections,
                source_movie.id,
                target_movie.id,
            )
            if sections_changed:
                setting.sections = sections
                changed = True
            if changed:
                setting.updated_at = datetime.utcnow()

    def _merge_metadata_locks(self, source_movie, target_movie):
        source_lock = MovieMetadataLock.query.filter_by(movie_id=source_movie.id).first()
        if not source_lock:
            return
        target_movie.add_locked_fields(source_lock.get_locked_fields())

    def _merge_season_metadata(self, source_movie, target_movie):
        target_by_season = {
            item.season: item
            for item in MovieSeasonMetadata.query.filter_by(movie_id=target_movie.id).all()
        }
        for source_item in MovieSeasonMetadata.query.filter_by(movie_id=source_movie.id).all():
            target_item = target_by_season.get(source_item.season)
            if not target_item:
                target_item = MovieSeasonMetadata(
                    movie_id=target_movie.id,
                    season=source_item.season,
                    title=source_item.title,
                    overview=source_item.overview,
                    air_date=source_item.air_date,
                    poster=source_item.poster,
                    episode_count=source_item.episode_count,
                    metadata_edited_at=source_item.metadata_edited_at,
                )
                db.session.add(target_item)
                target_by_season[source_item.season] = target_item
                continue

            for field in SEASON_METADATA_FIELDS:
                if getattr(target_item, field) in (None, '', []):
                    value = getattr(source_item, field)
                    if value not in (None, '', []):
                        setattr(target_item, field, value)

    def _resource_payload(self, resource):
        return {
            field: getattr(resource, field)
            for field in (
                'source_id',
                'path',
                'filename',
                'size',
                'season',
                'episode',
                'title',
                'overview',
                'metadata_edited_at',
                'label',
                'tech_specs',
            )
        }

    def _copy_resource_payload(self, source_payload, target_resource):
        for field in (
            'source_id',
            'path',
            'filename',
            'size',
            'season',
            'episode',
            'title',
            'overview',
            'metadata_edited_at',
            'label',
            'tech_specs',
        ):
            setattr(target_resource, field, source_payload.get(field))

    def _merge_resource_subtitles(self, source_resource, target_resource):
        for row in ResourceSubtitle.query.filter_by(resource_id=source_resource.id).all():
            duplicate = ResourceSubtitle.query.filter_by(
                resource_id=target_resource.id,
                candidate_id=row.candidate_id,
            ).first()
            if duplicate:
                db.session.delete(row)
            else:
                row.resource_id = target_resource.id

    def _merge_resource_subtitle_settings(self, source_resource, target_resource):
        for row in ResourceSubtitleSetting.query.filter_by(resource_id=source_resource.id).all():
            duplicate = ResourceSubtitleSetting.query.filter_by(resource_id=target_resource.id).first()
            if duplicate:
                db.session.delete(row)
            else:
                row.resource_id = target_resource.id

        for row in UserSubtitleSetting.query.filter_by(resource_id=source_resource.id).all():
            duplicate = UserSubtitleSetting.query.filter_by(
                user_id=row.user_id,
                resource_id=target_resource.id,
            ).first()
            if duplicate:
                db.session.delete(row)
            else:
                row.resource_id = target_resource.id

    def _merge_resource_records(self, source_resource, target_resource):
        if not source_resource or not target_resource or source_resource.id == target_resource.id:
            return target_resource

        source_payload = self._resource_payload(source_resource)
        history_rows = History.query.filter_by(resource_id=source_resource.id).all()
        for row in history_rows:
            row.resource_id = target_resource.id
        self._merge_resource_subtitles(source_resource, target_resource)
        self._merge_resource_subtitle_settings(source_resource, target_resource)
        db.session.delete(source_resource)
        db.session.flush()
        for row in history_rows:
            row.resource_id = target_resource.id
        self._copy_resource_payload(source_payload, target_resource)
        return target_resource

    def _remove_movie_from_homepage_settings(self, movie_id):
        for setting in HomepageSetting.query.all():
            changed = False
            if setting.hero_movie_id == movie_id:
                setting.hero_movie_id = None
                changed = True

            sections = setting.sections
            if isinstance(sections, list):
                next_sections = []
                for section in sections:
                    if not isinstance(section, dict) or not isinstance(section.get('movie_ids'), list):
                        next_sections.append(section)
                        continue
                    next_movie_ids = [item for item in section['movie_ids'] if item != movie_id]
                    if len(next_movie_ids) != len(section['movie_ids']):
                        section = dict(section)
                        section['movie_ids'] = next_movie_ids
                        changed = True
                    next_sections.append(section)
                if changed:
                    setting.sections = next_sections

            if changed:
                setting.updated_at = datetime.utcnow()

    def _delete_resource_dependencies(self, resource_id):
        for model in (History, ResourceSubtitle, ResourceSubtitleSetting, UserSubtitleSetting):
            for row in model.query.filter_by(resource_id=resource_id).all():
                db.session.delete(row)

    def _delete_movie_dependencies(self, movie_id):
        for model in (LibraryMovieMembership, UserFavorite, MovieMetadataLock, MovieSeasonMetadata):
            for row in model.query.filter_by(movie_id=movie_id).all():
                db.session.delete(row)
        self._remove_movie_from_homepage_settings(movie_id)

    def merge_movie_records(self, source_movie, target_movie):
        if not source_movie or not target_movie:
            return {"merged": False}
        if source_movie.id == target_movie.id:
            return {"merged": False, "target_movie_id": target_movie.id}

        resource_ids = []
        for resource in MediaResource.query.filter_by(movie_id=source_movie.id).all():
            replacement = self._find_replacement_resource(
                target_movie,
                {"season": resource.season, "episode": resource.episode},
                resource.source_id,
                resource.path,
            )
            if replacement:
                replacement = self._merge_resource_records(resource, replacement)
                replacement.movie_id = target_movie.id
                resource_ids.append(replacement.id)
            else:
                resource.movie_id = target_movie.id
                resource_ids.append(resource.id)

        self._merge_library_memberships(source_movie, target_movie)
        self._merge_user_favorites(source_movie, target_movie)
        self._merge_homepage_settings(source_movie, target_movie)
        self._merge_metadata_locks(source_movie, target_movie)
        self._merge_season_metadata(source_movie, target_movie)

        db.session.flush()
        db.session.delete(source_movie)
        logger.info(
            "Merged movie records source_movie_id=%s target_movie_id=%s resources=%s",
            source_movie.id,
            target_movie.id,
            len(resource_ids),
        )
        return {
            "merged": True,
            "source_movie_id": source_movie.id,
            "target_movie_id": target_movie.id,
            "resource_ids": resource_ids,
        }

    def _retry_upsert_existing_resource_after_integrity_error(self, meta_data, resource_info, source_id, rel_path):
        movie = Movie.query.filter_by(tmdb_id=str(meta_data.get('tmdb_id'))).first()
        resource = MediaResource.query.filter_by(source_id=source_id, path=rel_path).first()
        if not movie or not resource:
            return None

        previously_visible = movie.is_visible_in_catalog()
        self._apply_movie_metadata(movie, meta_data, overwrite=False)
        self.sync_movie_season_metadata(movie, meta_data.get('season_metadata'), prune_missing=True)
        tech_specs = self._build_resource_tech_specs(resource_info)
        self._apply_resource_fields(resource, movie, resource_info, rel_path, tech_specs)
        self._apply_pending_review_default(movie, previously_visible=previously_visible)
        db.session.commit()
        logger.info("Recovered media resource upsert after duplicate race source_id=%s path=%s", source_id, rel_path)
        return {"msg": "Saved", "title": movie.title, "deduped": True}

    def upsert_movie(self, meta_data, resource_info, source_id):
        """
        source_id: 必须指定该文件来自哪个存储源
        """
        tmdb_id = str(meta_data.get('tmdb_id'))
        if not tmdb_id: return

        movie = Movie.query.filter_by(tmdb_id=tmdb_id).first()
        reused_local_replacement_movie = False
        created_movie = False
        previously_visible = False
        rel_path = resource_info['path']

        if not movie:
            movie = self._find_movie_by_replaced_local_resource(meta_data, resource_info, source_id)
            reused_local_replacement_movie = movie is not None

        if not movie:
            movie = Movie(tmdb_id=tmdb_id)
            self._apply_movie_metadata(movie, meta_data, overwrite=True)
            db.session.add(movie)
            db.session.commit()
            created_movie = True
            logger.info("Inserted movie title=%s id=%s", movie.title, movie.id)
        else:
            previously_visible = movie.is_visible_in_catalog()
            if not reused_local_replacement_movie:
                self._apply_movie_metadata(movie, meta_data, overwrite=False)
            else:
                logger.info(
                    "Reused existing movie for local replacement source_id=%s path=%s movie_id=%s",
                    source_id,
                    rel_path,
                    movie.id,
                )

        if not reused_local_replacement_movie:
            self.sync_movie_season_metadata(movie, meta_data.get('season_metadata'), prune_missing=True)

        # 处理资源：唯一键是 (source_id, path)
        resource = MediaResource.query.filter_by(source_id=source_id, path=rel_path).first()
        replacement_resource = self._find_replacement_resource(movie, resource_info, source_id, rel_path)
        if resource and replacement_resource and resource.id != replacement_resource.id:
            resource = self._merge_resource_records(resource, replacement_resource)
            resource.movie_id = movie.id
        elif not resource and replacement_resource:
            resource = replacement_resource
            logger.info(
                "Reused replaced media resource source_id=%s old_path=%s new_path=%s movie_id=%s",
                source_id,
                resource.path,
                rel_path,
                movie.id,
            )
        tech_specs = self._build_resource_tech_specs(resource_info)

        if resource:
            self._apply_resource_fields(resource, movie, resource_info, rel_path, tech_specs)
        else:
            resource = MediaResource(
                movie_id=movie.id,
                source_id=source_id,
                path=rel_path,
            )
            self._apply_resource_fields(resource, movie, resource_info, rel_path, tech_specs)
            db.session.add(resource)
        self._apply_pending_review_default(
            movie,
            created=created_movie,
            previously_visible=previously_visible,
        )

        try:
            db.session.commit()
            return {"msg": "Saved", "title": movie.title}
        except IntegrityError as e:
            db.session.rollback()
            try:
                recovered = self._retry_upsert_existing_resource_after_integrity_error(meta_data, resource_info, source_id, rel_path)
                if recovered:
                    return recovered
            except Exception:
                db.session.rollback()
            logger.exception("Database upsert duplicate recovery failed source_id=%s path=%s error=%s", source_id, rel_path, e)
            return {"msg": "Error"}
        except Exception as e:
            db.session.rollback()
            logger.exception("Database upsert failed source_id=%s path=%s error=%s", source_id, rel_path, e)
            return {"msg": "Error"}

    def _apply_movie_metadata(self, movie, meta_data, overwrite=False):
        locked_fields = set(movie.get_locked_fields()) if movie.id else set()

        for field in MOVIE_METADATA_FIELDS:
            if field == 'scraper_source' and field in locked_fields:
                continue
            if field in locked_fields:
                continue

            value = meta_data.get(field)

            if field in ('category', 'actors'):
                if value is None:
                    value = []
                if not overwrite and not value:
                    continue
            else:
                if not overwrite and value in (None, '', []):
                    continue

            setattr(movie, field, value)

    def update_movie_metadata(self, movie, payload, lock_fields=None, unlock_fields=None, respect_locked=False):
        updated_fields = []
        unchanged_fields = []
        active_locked_fields = set(movie.get_locked_fields())

        if unlock_fields:
            active_locked_fields.difference_update(
                field for field in unlock_fields if isinstance(field, str) and field
            )

        for field, value in payload.items():
            if respect_locked and field in active_locked_fields:
                unchanged_fields.append(field)
                continue

            current_value = getattr(movie, field)
            if current_value == value:
                unchanged_fields.append(field)
                continue

            setattr(movie, field, value)
            updated_fields.append(field)

        if lock_fields:
            movie.add_locked_fields(lock_fields)
        if unlock_fields:
            movie.remove_locked_fields(unlock_fields)

        return updated_fields, unchanged_fields

    def sync_movie_season_metadata(self, movie, season_items, prune_missing=False):
        if season_items is None:
            return {"upserted": 0, "deleted": 0}

        existing = {item.season: item for item in movie.season_metadata.all()}
        seen = set()
        upserted = 0
        deleted = 0

        for raw_item in season_items:
            normalized = self._normalize_season_metadata_item(raw_item)
            if not normalized:
                continue

            season = normalized.pop('season')
            seen.add(season)
            season_metadata = existing.get(season)
            created = False
            if not season_metadata:
                season_metadata = MovieSeasonMetadata(movie_id=movie.id, season=season)
                db.session.add(season_metadata)
                existing[season] = season_metadata
                created = True

            changed = False
            for field, value in normalized.items():
                if value in (None, '', []):
                    continue
                if getattr(season_metadata, field) == value:
                    continue
                setattr(season_metadata, field, value)
                changed = True

            if created or changed:
                upserted += 1

        if prune_missing:
            for season, season_metadata in existing.items():
                if season in seen:
                    continue
                db.session.delete(season_metadata)
                deleted += 1

        return {"upserted": upserted, "deleted": deleted}

    def _normalize_season_metadata_item(self, item):
        if not isinstance(item, dict):
            return None

        season_value = item.get('season')
        try:
            season = int(season_value)
        except (TypeError, ValueError):
            return None
        if season <= 0:
            return None

        normalized = {"season": season}
        for field in SEASON_METADATA_FIELDS:
            value = item.get(field)
            if field in {'episode_count', 'aired_episode_count'}:
                try:
                    value = int(value) if value not in (None, '') else None
                except (TypeError, ValueError):
                    value = None
            elif isinstance(value, str):
                value = value.strip() or None
            normalized[field] = value
        return normalized

    def is_file_processed(self, source_id, rel_path):
        return db.session.query(MediaResource.id).filter_by(source_id=source_id, path=rel_path).first() is not None

    def search_local(self, query):
        movies = Movie.query.filter(Movie.title.contains(query)).limit(20).all()
        return [m.to_simple_dict() for m in movies]

    def get_recommendations(self, source_path, limit=6, exclude_id=None):
        query = Movie.query
        if exclude_id:
            query = query.filter(Movie.id != exclude_id)
        movies = query.order_by(db.func.random()).limit(limit).all()
        return [m.to_detail_dict() for m in movies]

    # --- Storage Source Management ---
    def add_storage_source(self, name, type, config):
        source = StorageSource(name=name, type=type, config=config)
        db.session.add(source)
        db.session.commit()
        return source

    def delete_storage_source(self, source_id, keep_metadata=False):
        """
        删除存储源
        :param source_id: 存储源ID
        :param keep_metadata: 是否保留元数据。False=级联删除(默认), True=解除关联但不删电影
        """
        source = get_account_scoped(StorageSource, source_id)
        if not source:
            return False, "Source not found"

        try:
            for binding in LibrarySource.query.filter_by(source_id=source_id).all():
                db.session.delete(binding)

            if keep_metadata:
                # 保留元数据：仅解除关联，将 source_id 置空
                # 这会使资源变为"离线"或"未知来源"状态，但保留在库中
                MediaResource.query.filter_by(source_id=source_id).update({MediaResource.source_id: None})
            else:
                # 级联删除：删除该源下的所有资源 -> 检查孤儿电影 -> 删除电影
                resources = MediaResource.query.filter_by(source_id=source_id).all()
                movie_ids_check = set()

                # 1. 删除资源并记录受影响的电影ID
                for res in resources:
                    movie_ids_check.add(res.movie_id)
                    self._delete_resource_dependencies(res.id)
                    db.session.delete(res)

                # 刷新会话以确保资源删除生效
                db.session.flush()

                # 2. 检查电影是否变为空壳（无任何资源）
                for mid in movie_ids_check:
                    count = MediaResource.query.filter_by(movie_id=mid).count()
                    if count == 0:
                        self._delete_movie_dependencies(mid)
                        Movie.query.filter_by(id=mid).delete()

            # 最后删除源配置
            db.session.delete(source)
            db.session.commit()
            return True, "Deleted successfully"
        except Exception as e:
            db.session.rollback()
            logger.exception("Delete storage source failed source_id=%s keep_metadata=%s error=%s", source_id, keep_metadata, e)
            return False, str(e)

    def get_all_sources(self):
        return StorageSource.query.all()

    def get_source_by_id(self, sid):
        return get_account_scoped(StorageSource, sid)


scanner_adapter = MovieDatabaseAdapter()
