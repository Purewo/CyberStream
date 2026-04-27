import json
import os
import logging
from datetime import datetime
from sqlalchemy import or_
from backend.app.extensions import db
from backend.app.models import Movie, MediaResource, StorageSource, MovieSeasonMetadata

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

    def upsert_movie(self, meta_data, resource_info, source_id):
        """
        source_id: 必须指定该文件来自哪个存储源
        """
        tmdb_id = str(meta_data.get('tmdb_id'))
        if not tmdb_id: return

        movie = Movie.query.filter_by(tmdb_id=tmdb_id).first()

        if not movie:
            movie = Movie(
                tmdb_id=tmdb_id
            )
            self._apply_movie_metadata(movie, meta_data, overwrite=True)
            db.session.add(movie)
            db.session.commit()
            logger.info("Inserted movie title=%s id=%s", movie.title, movie.id)
        else:
            self._apply_movie_metadata(movie, meta_data, overwrite=False)

        self.sync_movie_season_metadata(movie, meta_data.get('season_metadata'), prune_missing=True)

        # 处理资源：唯一键是 (source_id, path)
        rel_path = resource_info['path']
        resource = MediaResource.query.filter_by(source_id=source_id, path=rel_path).first()
        tech_specs = self._build_resource_tech_specs(resource_info)

        if resource:
            resource.tech_specs = tech_specs
            resource.season = resource_info.get('season')
            resource.episode = resource_info.get('episode')
            resource.label = resource_info.get('label')
            resource.filename = os.path.basename(rel_path)
            resource.size = tech_specs.get('size', 0)
            if resource.movie_id != movie.id:
                resource.movie_id = movie.id
        else:
            resource = MediaResource(
                movie_id=movie.id,
                source_id=source_id,
                path=rel_path,
                filename=os.path.basename(rel_path),
                size=tech_specs.get('size', 0),
                tech_specs=tech_specs,
                season=resource_info.get('season'),
                episode=resource_info.get('episode'),
                label=resource_info.get('label')
            )
            db.session.add(resource)

        try:
            db.session.commit()
            return {"msg": "Saved", "title": movie.title}
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
            if field == 'episode_count':
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
        source = db.session.get(StorageSource, source_id)
        if not source:
            return False, "Source not found"

        try:
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
                    db.session.delete(res)

                # 刷新会话以确保资源删除生效
                db.session.flush()

                # 2. 检查电影是否变为空壳（无任何资源）
                for mid in movie_ids_check:
                    count = MediaResource.query.filter_by(movie_id=mid).count()
                    if count == 0:
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
        return db.session.get(StorageSource, sid)


scanner_adapter = MovieDatabaseAdapter()
