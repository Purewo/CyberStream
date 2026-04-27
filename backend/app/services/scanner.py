import copy
import time
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from collections import defaultdict
from datetime import datetime, timezone
from flask import current_app
from backend.app.db.database import scanner_adapter as db
from backend.app.metadata import metadata_pipeline
from backend.app.services.media_path_cleaner import MediaPathCleaner
from backend.app.services.metadata_scraper import ScrapeContext, metadata_scraper
from backend.app.providers.factory import provider_factory
from backend.app.utils.common import ResourceValidator

logger = logging.getLogger(__name__)


class CyberScanner:
    STATUS_PUBLISH_INTERVAL = 0.35

    def __init__(self):
        self.is_scanning = False
        self._scan_run_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._status_stop_event = None
        self._status_reporter = None
        self._progress_state = self._build_progress_state()
        self.scan_status = self._snapshot_progress_state(self._progress_state)
        self.cleaner = MediaPathCleaner()
        logger.info("Scanner engine initialized (v2.7 Metadata Pipeline)")

    def get_status(self):
        with self._status_lock:
            return copy.deepcopy(self.scan_status)

    def try_start_scan(self):
        if not self._scan_run_lock.acquire(blocking=False):
            return False
        self.is_scanning = True
        return True

    def finish_scan(self):
        self.is_scanning = False
        if self._scan_run_lock.locked():
            self._scan_run_lock.release()

    def _utcnow(self):
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def _build_progress_state(self):
        return {
            "status": "idle",
            "phase": "idle",
            "current_source": "",
            "current_path": "",
            "current_item": "",
            "current_file": "",
            "total_items": 0,
            "processed_items": 0,
            "total_items_known": False,
            "discovered_files": 0,
            "total_files": 0,
            "total_files_known": False,
            "processed_files": 0,
            "indexed_dirs": 0,
            "active_items": {},
            "started_at": None,
            "updated_at": None,
        }

    def _snapshot_progress_state(self, state):
        active_items = sorted(
            state.get("active_items", {}).values(),
            key=lambda item: item.get("started_at") or "",
        )
        current_item = state.get("current_item") or (active_items[0]["label"] if active_items else "")
        current_file = state.get("current_file") or (active_items[0]["path"] if active_items else "")
        return {
            "status": state["status"],
            "phase": state["phase"],
            "current_source": state["current_source"],
            "current_path": state["current_path"],
            "current_item": current_item,
            "current_file": current_file,
            "total_items": state["total_items"],
            "processed_items": state["processed_items"],
            "total_items_known": state["total_items_known"],
            "discovered_files": state["discovered_files"],
            "total_files": state["total_files"],
            "total_files_known": state["total_files_known"],
            "processed_files": state["processed_files"],
            "indexed_dirs": state["indexed_dirs"],
            "active_items": [
                {
                    "label": item["label"],
                    "path": item["path"],
                    "file_count": item["file_count"],
                    "started_at": item["started_at"],
                }
                for item in active_items
            ],
            "started_at": state["started_at"],
            "updated_at": state["updated_at"],
        }

    def _touch_progress_locked(self):
        self._progress_state["updated_at"] = self._utcnow()

    def _publish_status_snapshot(self):
        with self._status_lock:
            self.scan_status = self._snapshot_progress_state(self._progress_state)

    def _status_reporter_loop(self, stop_event):
        while not stop_event.wait(self.STATUS_PUBLISH_INTERVAL):
            self._publish_status_snapshot()
        self._publish_status_snapshot()

    def _ensure_status_reporter(self):
        with self._status_lock:
            if self._status_reporter and self._status_reporter.is_alive():
                return
            self._status_stop_event = threading.Event()
            self._status_reporter = threading.Thread(
                target=self._status_reporter_loop,
                args=(self._status_stop_event,),
                daemon=True,
                name="scanner-status-reporter",
            )
            self._status_reporter.start()

    def _stop_status_reporter(self):
        reporter = None
        stop_event = None
        with self._status_lock:
            reporter = self._status_reporter
            stop_event = self._status_stop_event
            self._status_reporter = None
            self._status_stop_event = None
        if stop_event:
            stop_event.set()
        if reporter and reporter.is_alive():
            reporter.join(timeout=1)

    def _update_progress(self, **kwargs):
        with self._status_lock:
            for key, value in kwargs.items():
                self._progress_state[key] = value
            self._touch_progress_locked()

    def _increment_progress(self, **kwargs):
        with self._status_lock:
            for key, value in kwargs.items():
                self._progress_state[key] = self._progress_state.get(key, 0) + value
            self._touch_progress_locked()

    def _begin_scan_session(self, current_source=''):
        self._stop_status_reporter()
        with self._status_lock:
            self._progress_state = self._build_progress_state()
            self._progress_state.update({
                "status": "scanning",
                "phase": "preparing",
                "current_source": current_source,
                "started_at": self._utcnow(),
            })
            self._touch_progress_locked()
            self.scan_status = self._snapshot_progress_state(self._progress_state)
        self._ensure_status_reporter()

    def _finish_scan_session(self):
        with self._status_lock:
            started_at = self._progress_state.get("started_at")
            self._progress_state = self._build_progress_state()
            self._progress_state["started_at"] = started_at
            self._touch_progress_locked()
            self.scan_status = self._snapshot_progress_state(self._progress_state)
        self._stop_status_reporter()

    def _begin_source_progress(self, current_source, display_root='/'):
        self._update_progress(
            phase='indexing',
            current_source=current_source,
            current_path=display_root or '/',
            current_item='',
            current_file='',
            total_items=0,
            processed_items=0,
            total_items_known=False,
            discovered_files=0,
            total_files=0,
            total_files_known=False,
            processed_files=0,
            indexed_dirs=0,
            active_items={},
        )

    def _mark_processing_started(self, task_id, label, path, file_count):
        with self._status_lock:
            self._progress_state["active_items"][task_id] = {
                "label": label,
                "path": path,
                "file_count": file_count,
                "started_at": self._utcnow(),
            }
            self._progress_state["current_item"] = label
            self._progress_state["current_file"] = path
            self._touch_progress_locked()

    def _mark_processing_finished(self, task_id, processed_files=0, processed_items=0):
        with self._status_lock:
            self._progress_state["active_items"].pop(task_id, None)
            self._progress_state["processed_files"] += processed_files
            self._progress_state["processed_items"] += processed_items

            active_items = sorted(
                self._progress_state["active_items"].values(),
                key=lambda item: item.get("started_at") or "",
            )
            if active_items:
                self._progress_state["current_item"] = active_items[0]["label"]
                self._progress_state["current_file"] = active_items[0]["path"]
            else:
                self._progress_state["current_item"] = ""
                self._progress_state["current_file"] = ""
            self._touch_progress_locked()

    def _normalize_root_path(self, root_path):
        root_path = (root_path or '').strip().strip('/')
        return root_path

    def _display_progress_path(self, path):
        normalized = self._normalize_root_path(path)
        return f"/{normalized}" if normalized else "/"

    def _build_entity_progress_label(self, key):
        title, year = key
        if year:
            return f"{title} ({year})"
        return title or "Unknown"

    def _first_entity_file_path(self, files):
        if not files:
            return ""
        return files[0].get('path', '')

    def _prefix_relative_path(self, root_path, relative_path):
        root_path = self._normalize_root_path(root_path)
        relative_path = (relative_path or '').strip().strip('/')
        if root_path and relative_path:
            return f"{root_path}/{relative_path}"
        if root_path:
            return root_path
        return relative_path

    def _normalize_content_type_hint(self, content_type):
        content_type = (content_type or '').strip().lower()
        if content_type in {'movie', 'tv'}:
            return content_type
        return None

    def parse_path_metadata(self, file_path):
        """测试和扫描入口统一使用新的脏数据清洗器。"""
        return self.cleaner.parse_path_metadata(file_path).to_dict()

    # --- PHASE 1: 并发索引 ---
    def _phase_1_index(self, provider, start_path=''):
        logger.info("Scan phase 1 started: indexing file structure start_path=%s", start_path)
        start_time = time.time()
        self._update_progress(
            phase='indexing',
            current_path=self._display_progress_path(start_path),
            current_item='',
            current_file='',
            total_items=0,
            processed_items=0,
            total_items_known=False,
            discovered_files=0,
            total_files=0,
            total_files_known=False,
            processed_files=0,
        )

        all_files = []
        max_workers = 8 if provider.config.get('type') == 'webdav' else 4

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(provider.list_items, start_path): start_path}

            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)

                for future in done:
                    dir_path = futures.pop(future)
                    self._update_progress(current_path=self._display_progress_path(dir_path))
                    try:
                        items = future.result()
                        self._increment_progress(indexed_dirs=1)
                        for item in items:
                            if item['isdir']:
                                if not ResourceValidator.is_ignored_folder(item['name']):
                                    new_future = executor.submit(provider.list_items, item['path'])
                                    futures[new_future] = item['path']
                            else:
                                if ResourceValidator.is_valid_video(item['name']) or item['name'].lower().endswith('.nfo'):
                                    all_files.append(item)
                                    self._increment_progress(discovered_files=1)
                                    if ResourceValidator.is_valid_video(item['name']):
                                        self._increment_progress(total_files=1)

                    except Exception as e:
                        logger.exception("Scan indexing failed dir_path=%s error=%s", dir_path, e)

        duration = time.time() - start_time
        video_count = sum(1 for item in all_files if ResourceValidator.is_valid_video(item.get('name', '')))
        self._update_progress(
            discovered_files=len(all_files),
            total_files=video_count,
            total_files_known=True,
            current_path=self._display_progress_path(start_path),
        )
        logger.info("Scan phase 1 complete files=%s duration=%.2fs", len(all_files), duration)
        return all_files

    # --- PHASE 2: 智能分组 ---
    def _phase_2_group(self, all_files, source_id):
        logger.info("Scan phase 2 started: analyzing and grouping")
        self._update_progress(
            phase='grouping',
            total_items=len(all_files),
            processed_items=0,
            total_items_known=True,
            current_item='',
            current_file='',
        )

        entities = defaultdict(list)
        new_file_count = 0
        nfo_files = {}
        processed_count = 0

        for file_item in all_files:
            processed_count += 1
            path = file_item['path']
            self._update_progress(
                processed_items=processed_count,
                current_item=file_item.get('name', ''),
                current_file=path,
            )

            if file_item['name'].lower().endswith('.nfo'):
                nfo_files[path] = file_item
                continue

            if not ResourceValidator.is_valid_video(file_item['name']):
                continue

            if db.is_file_processed(source_id, path):
                continue

            new_file_count += 1
            clean_meta = self.parse_path_metadata(path)
            parsed_meta = metadata_pipeline.parse_path(path)

            key = (clean_meta['title'], clean_meta['year'])
            file_item['_meta'] = {
                'title': clean_meta['title'],
                'year': clean_meta['year'],
                'season': clean_meta['season'],
                'episode': clean_meta['episode'],
                'media_type_hint': parsed_meta.media_type_hint,
                'parse_layer': parsed_meta.parse_layer,
                'parse_strategy': parsed_meta.parse_strategy,
                'confidence': parsed_meta.confidence,
                'parse_mode': clean_meta.get('parse_mode'),
                'clean_parse_strategy': clean_meta.get('parse_strategy'),
                'needs_review': clean_meta.get('needs_review', False),
                'nfo_candidates': self._find_sidecar_nfo(all_files, file_item),
            }
            base_path = path.rsplit('.', 1)[0]
            parent_path = path.rsplit('/', 1)[0] if '/' in path else ''
            nfo_candidates = []
            seen_nfo_paths = set()
            for candidate_kind, candidate_path in [
                ('same_name', f'{base_path}.nfo'),
                ('movie', f'{parent_path}/movie.nfo' if parent_path else 'movie.nfo'),
                ('tvshow', f'{parent_path}/tvshow.nfo' if parent_path else 'tvshow.nfo'),
            ]:
                if candidate_path in seen_nfo_paths:
                    continue
                seen_nfo_paths.add(candidate_path)
                nfo_file = nfo_files.get(candidate_path)
                if nfo_file:
                    nfo_candidates.append({
                        "path": candidate_path,
                        "name": nfo_file['name'],
                        "kind": candidate_kind,
                    })
            file_item['_nfo_candidates'] = nfo_candidates
            entities[key].append(file_item)

        self._update_progress(current_item='', current_file='')
        return entities

    # --- PHASE 2.5: 分组优化与合并 ---
    def _optimize_entities(self, raw_entities):
        logger.info("Scan phase 2.5 started: optimizing entities")
        self._update_progress(
            phase='optimizing',
            total_items=len(raw_entities),
            processed_items=0,
            total_items_known=True,
            current_item='',
            current_file='',
        )
        optimized = defaultdict(list)
        processed_count = 0

        for key, files in raw_entities.items():
            processed_count += 1
            title, year = key
            self._update_progress(
                processed_items=processed_count,
                current_item=title,
                current_file=files[0].get('path', '') if files else '',
            )
            repaired = self.cleaner.repair_group_title(title, files[0]['path'], current_year=year)
            clean_title = repaired.title
            year = repaired.year

            if repaired.parse_mode == 'fallback':
                if clean_title.startswith('UNKNOWN_SHOW_'):
                    logger.warning("Scanner skipped unfixable title=%r marked_local_only=true", title)
                else:
                    logger.info(
                        "Scanner fallback title fixed original=%r inferred=%r strategy=%s",
                        title,
                        clean_title,
                        repaired.parse_strategy,
                    )

            new_key = (clean_title, year)
            optimized[new_key].extend(files)

            for file_item in files:
                file_item['_meta']['title'] = clean_title
                file_item['_meta']['year'] = year
                if repaired.parse_mode == 'fallback':
                    file_item['_meta']['parse_mode'] = repaired.parse_mode
                    file_item['_meta']['clean_parse_strategy'] = repaired.parse_strategy
                    file_item['_meta']['needs_review'] = repaired.needs_review

        self._update_progress(current_item='', current_file='')
        logger.info("Scan phase 2.5 complete raw_groups=%s optimized_entities=%s", len(raw_entities), len(optimized))
        return defaultdict(list, optimized)

    def _attach_metadata_trace(self, specs, entity_context, resolution):
        parsed_info = entity_context.to_parsed_media_info()
        specs = dict(specs or {})
        specs['metadata_trace'] = {
            "parse_layer": entity_context.parse_layer,
            "parse_strategy": entity_context.parse_strategy,
            "confidence": entity_context.confidence,
            "media_type_hint": parsed_info.media_type_hint,
            "has_nfo_candidates": bool(entity_context.nfo_candidates),
            "scrape_layer": resolution.scrape_layer,
            "scrape_strategy": resolution.scrape_strategy,
            "scrape_reason": resolution.reason,
        }
        return specs

    def _load_nfo_payloads(self, provider, entity_context):
        payloads = []
        seen = set()
        for path in entity_context.nfo_candidates:
            clean_path = (path or '').strip()
            if not clean_path or clean_path in seen:
                continue
            seen.add(clean_path)
            content = provider.read_text(clean_path)
            if not content:
                continue
            payloads.append({
                "path": clean_path,
                "content": content,
            })
        return payloads

    def _find_sidecar_nfo(self, files, video_item):
        video_path = video_item.get('path', '')
        video_name = video_item.get('name', '')
        video_base = os.path.splitext(video_name)[0].lower()
        video_dir = os.path.dirname(video_path).replace('\\', '/').strip('/')

        candidates = []
        for item in files:
            name = item.get('name', '')
            if not name.lower().endswith('.nfo'):
                continue

            item_path = item.get('path', '').replace('\\', '/').strip('/')
            item_dir = os.path.dirname(item_path).replace('\\', '/').strip('/')
            item_base = os.path.splitext(name)[0].lower()

            if item_dir != video_dir:
                continue

            if item_base == video_base or item_base in {'movie', 'tvshow', 'index'}:
                candidates.append(item.get('path', ''))

        return candidates

    # --- PHASE 3: 批量刮削与入库 ---
    def _phase_3_process(
        self,
        entities,
        source_id,
        app_instance,
        provider,
        scrape_enabled=True,
        content_type=None,
        root_path=None,
        library_id=None,
        library_source_id=None,
        scraper_policy=None,
    ):
        if not entities: return

        media_type_hint = self._normalize_content_type_hint(content_type)
        logger.info(
            "Scan phase 3 started: scraping and saving scrape_enabled=%s content_type=%s",
            scrape_enabled,
            media_type_hint or 'mixed',
        )
        entity_list = list(entities.items())
        total_entities = len(entity_list)

        self._update_progress(
            phase='processing',
            total_items=total_entities,
            processed_items=0,
            total_items_known=True,
            current_item='',
            current_file='',
            active_items={},
        )

        def _worker(k, f, sid, app, current_provider):
            task_id = f"{k[0]}::{k[1]}::{self._first_entity_file_path(f)}"
            self._mark_processing_started(
                task_id,
                self._build_entity_progress_label(k),
                self._first_entity_file_path(f),
                len(f),
            )
            if app:
                try:
                    with app.app_context():
                        self._process_single_entity(
                            k,
                            f,
                            sid,
                            current_provider,
                            scrape_enabled=scrape_enabled,
                            content_type=media_type_hint,
                            root_path=root_path,
                            library_id=library_id,
                            library_source_id=library_source_id,
                            scraper_policy=scraper_policy,
                        )
                finally:
                    self._mark_processing_finished(task_id, processed_files=len(f), processed_items=1)
            else:
                try:
                    self._process_single_entity(
                        k,
                        f,
                        sid,
                        current_provider,
                        scrape_enabled=scrape_enabled,
                        content_type=media_type_hint,
                        root_path=root_path,
                        library_id=library_id,
                        library_source_id=library_source_id,
                        scraper_policy=scraper_policy,
                    )
                finally:
                    self._mark_processing_finished(task_id, processed_files=len(f), processed_items=1)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_worker, key, files, source_id, app_instance, provider): key
                for key, files in entity_list
            }

            for future in as_completed(futures):
                try:
                    future.result()
                    status = self.get_status()
                    if status['processed_items'] % 5 == 0 and status['processed_items'] > 0:
                        logger.info(
                            "Scan phase 3 progress processed=%s total=%s files=%s/%s",
                            status['processed_items'],
                            total_entities,
                            status['processed_files'],
                            status['total_files'],
                        )
                except Exception as e:
                    key = futures[future]
                    logger.exception("Scan entity processing failed key=%s error=%s", key, e)

        self._update_progress(current_item='', current_file='', active_items={})

    def _process_single_entity(
        self,
        key,
        files,
        source_id,
        provider=None,
        scrape_enabled=True,
        content_type=None,
        root_path=None,
        library_id=None,
        library_source_id=None,
        scraper_policy=None,
    ):
        entity_context = metadata_pipeline.build_entity_context(key, files)
        parsed_info = entity_context.to_parsed_media_info()
        if provider is None:
            source = db.get_source_by_id(source_id)
            provider = provider_factory.get_provider(source) if source else None
        media_type_hint = self._normalize_content_type_hint(content_type)
        scrape_result = metadata_scraper.scrape(ScrapeContext(
            title=key[0],
            year=key[1],
            source_id=source_id,
            provider=provider,
            scrape_enabled=scrape_enabled,
            content_type=media_type_hint or parsed_info.media_type_hint,
            root_path=root_path,
            library_id=library_id,
            library_source_id=library_source_id,
            scraper_policy=scraper_policy or {},
            files=files,
        ))
        scrape_raw = scrape_result.raw if isinstance(scrape_result.raw, dict) else {}
        if provider is not None:
            parsed_info.extras['nfo_payloads'] = self._load_nfo_payloads(provider, entity_context)
        try:
            resolution = metadata_pipeline.resolve_metadata(parsed_info)
            meta_data = dict(resolution.meta_data)
        except Exception as e:
            logger.info(
                "Legacy metadata pipeline skipped title=%r year=%s error=%s",
                entity_context.title,
                entity_context.year,
                e,
            )
            resolution = None
            meta_data = {}
        if scrape_result.metadata:
            meta_data.update(scrape_result.metadata)
        logger.info(
            "Metadata resolved title=%r year=%s parse_layer=%s parse_strategy=%s scrape_layer=%s scrape_strategy=%s",
            entity_context.title,
            entity_context.year,
            entity_context.parse_layer,
            entity_context.parse_strategy,
            resolution.scrape_layer if resolution else 'provider',
            resolution.scrape_strategy if resolution else scrape_result.provider,
        )

        # 入库
        for file_item in files:
            path = file_item['path']
            meta = file_item['_meta']
            s = meta['season']
            e = meta['episode']

            is_movie_resource = (media_type_hint or parsed_info.media_type_hint) == 'movie' and s is None and e is None
            specs = ResourceValidator.get_tech_specs(file_item['name'])
            enhanced_specs = ResourceValidator.get_tech_specs(path)
            if isinstance(enhanced_specs, dict):
                specs.update({
                    key: value for key, value in enhanced_specs.items()
                    if key not in {'size'} and value not in (None, '', [], {})
                })
            specs['features'] = dict(specs.get('features') or {})
            specs['features']['is_movie_feature'] = bool(is_movie_resource)
            if resolution:
                specs = self._attach_metadata_trace(specs, entity_context, resolution)
            specs['size'] = file_item['size']

            label = "Movie"
            if s is not None and e is not None:
                label = f"S{s:02d}E{e:02d}"
            elif e is not None:
                label = f"EP{e:02d}"
            label += f" - {specs['resolution']}"

            res_data = {
                "path": path, "tech_specs": specs,
                "season": s, "episode": e, "label": label,
                "analysis": {
                    "path_cleaning": {
                        "title_hint": meta.get('title'),
                        "year_hint": meta.get('year'),
                        "season": s,
                        "episode": e,
                        "parse_mode": meta.get('parse_mode') or meta.get('parse_layer'),
                        "parse_strategy": meta.get('clean_parse_strategy') or meta.get('parse_strategy'),
                        "needs_review": bool(meta.get('needs_review')),
                    },
                    "scraping": {
                        "provider": scrape_result.provider,
                        "confidence": scrape_result.confidence,
                        "matched_id": scrape_result.matched_id,
                        "warnings": scrape_result.warnings,
                        "final_title_source": scrape_raw.get('final_title_source'),
                        "final_year_source": scrape_raw.get('final_year_source'),
                        "provider_order": scrape_raw.get('provider_order'),
                    },
                },
            }
            db.upsert_movie(meta_data, res_data, source_id)

    # --- 主入口 ---
    def scan_source(
        self,
        source_obj,
        app_instance=None,
        root_path=None,
        scrape_enabled=True,
        content_type=None,
        library_id=None,
        library_source_id=None,
        scraper_policy=None,
    ):
        try:
            display_root = self._normalize_root_path(root_path)
            media_type_hint = self._normalize_content_type_hint(content_type)
            current_source_name = source_obj.name if not display_root else f"{source_obj.name}:{display_root}"
            logger.info(
                "Scan source started name=%s type=%s root_path=%s scrape_enabled=%s content_type=%s",
                source_obj.name,
                source_obj.type,
                display_root or '/',
                scrape_enabled,
                media_type_hint or 'mixed',
            )
            self._begin_source_progress(current_source_name, self._display_progress_path(display_root))

            provider = provider_factory.get_provider(source_obj)

            start_path = display_root if display_root else ''
            all_files = self._phase_1_index(provider, start_path=start_path)
            if not all_files:
                logger.info("Scan source has no files name=%s root_path=%s", source_obj.name, display_root or '/')
                return

            if display_root:
                for file_item in all_files:
                    normalized_path = self._normalize_root_path(file_item['path'])
                    if normalized_path == display_root or normalized_path.startswith(f"{display_root}/"):
                        file_item['path'] = normalized_path
                    else:
                        file_item['path'] = self._prefix_relative_path(display_root, normalized_path)

            raw_entities = self._phase_2_group(all_files, source_obj.id)

            final_entities = self._optimize_entities(raw_entities)

            self._phase_3_process(
                final_entities,
                source_obj.id,
                app_instance,
                provider,
                scrape_enabled=scrape_enabled,
                content_type=media_type_hint,
                root_path=display_root or '/',
                library_id=library_id,
                library_source_id=library_source_id,
                scraper_policy=scraper_policy,
            )

            logger.info("Scan source completed name=%s root_path=%s", source_obj.name, display_root or '/')

        except Exception as e:
            logger.exception("Scan source failed name=%s root_path=%s error=%s", source_obj.name, root_path, e)

    def scan(self, specific_source_id=None, root_path=None, content_type=None, scrape_enabled=True, lock_acquired=False):
        if not lock_acquired and not self.try_start_scan():
            logger.warning("Scanner is already running")
            return False

        self._begin_scan_session()
        logger.info("Scan task started")

        app_instance = None
        try:
            app_instance = current_app._get_current_object()
        except RuntimeError:
            logger.warning("Scanner running outside application context")

        try:
            sources = db.get_all_sources()
            if specific_source_id:
                sources = [s for s in sources if s.id == specific_source_id]

            if not sources:
                logger.info("No storage sources configured")

            for source in sources:
                if specific_source_id:
                    self.scan_source(
                        source,
                        app_instance,
                        root_path=root_path,
                        content_type=content_type,
                        scrape_enabled=scrape_enabled,
                    )
                else:
                    self.scan_source(source, app_instance)

        except Exception as e:
            logger.exception("Global scan failed error=%s", e)
        finally:
            self.last_scan_time = time.time()
            self._finish_scan_session()
            self.finish_scan()
            logger.info("Scan task finished")
        return True


scanner_engine = CyberScanner()
