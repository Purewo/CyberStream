import copy
import logging
import threading
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEFAULT_PERSISTED_RESULT_ITEM_LIMIT = 20
DEFAULT_RETENTION_DAYS = 30


class BackgroundJobManager:
    """Small in-process job registry for operational batch tasks.

    This is intentionally lightweight: it tracks runtime jobs for the current
    backend process, without introducing a database migration or external queue.
    Long-term audit/history can be layered on top later.
    """

    def __init__(self, max_jobs=100):
        self.max_jobs = max_jobs
        self._jobs = {}
        self._order = []
        self._lock = threading.Lock()

    def _utcnow(self):
        return datetime.utcnow().isoformat()

    def _parse_datetime(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            return None

    def _snapshot_unlocked(self, job):
        return copy.deepcopy(job)

    def _config_int(self, key, default, minimum=0, maximum=10000):
        try:
            from flask import current_app
            value = current_app.config.get(key, default)
        except RuntimeError:
            value = default
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(number, maximum))

    def _persisted_result_item_limit(self):
        return self._config_int(
            "MAINTENANCE_JOB_RESULT_ITEM_LIMIT",
            DEFAULT_PERSISTED_RESULT_ITEM_LIMIT,
            minimum=0,
            maximum=1000,
        )

    def _retention_days(self, days=None):
        if days is not None:
            try:
                return max(0, min(int(days), 3650))
            except (TypeError, ValueError):
                return DEFAULT_RETENTION_DAYS
        return self._config_int(
            "MAINTENANCE_JOB_RETENTION_DAYS",
            DEFAULT_RETENTION_DAYS,
            minimum=0,
            maximum=3650,
        )

    def _summarize_for_persistence(self, result):
        result = copy.deepcopy(result)
        if not isinstance(result, dict):
            return result

        limit = self._persisted_result_item_limit()
        items = result.get("items")
        if isinstance(items, list) and len(items) > limit:
            result["items"] = items[:limit]
            result["result_truncated"] = True
            result["result_item_count"] = len(items)
            result["persisted_item_limit"] = limit
        elif isinstance(items, list):
            result["result_truncated"] = False
            result["result_item_count"] = len(items)
            result["persisted_item_limit"] = limit

        return result

    def _persist_job_snapshot(self, job):
        try:
            from backend.app.extensions import db
            from backend.app.models import MaintenanceJob

            row = db.session.get(MaintenanceJob, job["id"])
            if not row:
                row = MaintenanceJob(id=job["id"])
                db.session.add(row)
            row.type = job.get("type") or "unknown"
            row.title = job.get("title")
            row.status = job.get("status") or "queued"
            row.created_at = self._parse_datetime(job.get("created_at")) or datetime.utcnow()
            row.started_at = self._parse_datetime(job.get("started_at"))
            row.finished_at = self._parse_datetime(job.get("finished_at"))
            row.updated_at = datetime.utcnow()
            row.request = copy.deepcopy(job.get("request") or {})
            row.progress = copy.deepcopy(job.get("progress") or {})
            row.result = self._summarize_for_persistence(job.get("result"))
            row.error = copy.deepcopy(job.get("error"))
            db.session.commit()
        except RuntimeError:
            return
        except Exception as exc:
            try:
                from backend.app.extensions import db
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Background job persistence failed job_id=%s error=%s", job.get("id"), exc)

    def _load_persisted_job(self, job_id):
        try:
            from backend.app.extensions import db
            from backend.app.models import MaintenanceJob

            row = db.session.get(MaintenanceJob, job_id)
            return row.to_dict() if row else None
        except RuntimeError:
            return None
        except Exception as exc:
            logger.warning("Background job load failed job_id=%s error=%s", job_id, exc)
            return None

    def _list_persisted_jobs(self, job_type=None, limit=20):
        try:
            from backend.app.models import MaintenanceJob

            query = MaintenanceJob.query
            if job_type:
                query = query.filter_by(type=job_type)
            rows = query.order_by(MaintenanceJob.created_at.desc(), MaintenanceJob.id.desc()).limit(limit).all()
            return [row.to_dict() for row in rows]
        except RuntimeError:
            return None
        except Exception as exc:
            logger.warning("Background job list load failed type=%s error=%s", job_type, exc)
            return None

    def _delete_persisted_jobs(self):
        try:
            from backend.app.extensions import db
            from backend.app.models import MaintenanceJob

            MaintenanceJob.query.delete()
            db.session.commit()
        except RuntimeError:
            return
        except Exception as exc:
            try:
                from backend.app.extensions import db
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Background job clear persistence failed error=%s", exc)

    def prune(self, days=None, job_type=None, dry_run=False):
        retention_days = self._retention_days(days)
        cutoff = datetime.utcnow() - timedelta(days=retention_days)

        try:
            from backend.app.extensions import db
            from backend.app.models import MaintenanceJob

            query = MaintenanceJob.query.filter(
                MaintenanceJob.status.in_(["succeeded", "failed"]),
                MaintenanceJob.finished_at.isnot(None),
                MaintenanceJob.finished_at < cutoff,
            )
            if job_type:
                query = query.filter_by(type=job_type)

            rows = query.order_by(MaintenanceJob.finished_at.asc(), MaintenanceJob.id.asc()).all()
            removed_ids = [row.id for row in rows]
            removed_type_counts = {}
            removed_status_counts = {}
            for row in rows:
                removed_type_counts[row.type] = removed_type_counts.get(row.type, 0) + 1
                removed_status_counts[row.status] = removed_status_counts.get(row.status, 0) + 1

            if not dry_run:
                for row in rows:
                    db.session.delete(row)
                db.session.commit()
                removed_id_set = set(removed_ids)
                with self._lock:
                    for job_id in removed_ids:
                        self._jobs.pop(job_id, None)
                    self._order = [job_id for job_id in self._order if job_id not in removed_id_set]

            return {
                "dry_run": bool(dry_run),
                "retention_days": retention_days,
                "cutoff": cutoff.isoformat(),
                "type": job_type,
                "removed": 0 if dry_run else len(removed_ids),
                "matched": len(removed_ids),
                "removed_ids": removed_ids if not dry_run else [],
                "matched_ids": removed_ids,
                "type_counts": removed_type_counts,
                "status_counts": removed_status_counts,
            }
        except RuntimeError:
            return {
                "dry_run": bool(dry_run),
                "retention_days": retention_days,
                "type": job_type,
                "removed": 0,
                "matched": 0,
                "removed_ids": [],
                "matched_ids": [],
                "type_counts": {},
                "status_counts": {},
            }
        except Exception as exc:
            try:
                from backend.app.extensions import db
                db.session.rollback()
            except Exception:
                pass
            logger.exception("Background job prune failed error=%s", exc)
            raise

    def _trim_unlocked(self):
        while len(self._order) > self.max_jobs:
            old_id = self._order.pop(0)
            old_job = self._jobs.get(old_id)
            if old_job and old_job.get("status") in {"queued", "running"}:
                self._order.append(old_id)
                break
            self._jobs.pop(old_id, None)

    def create(self, job_type, title=None, request=None):
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "type": job_type,
            "title": title,
            "status": "queued",
            "created_at": self._utcnow(),
            "started_at": None,
            "finished_at": None,
            "request": copy.deepcopy(request or {}),
            "progress": {
                "current": 0,
                "total": 0,
                "message": None,
            },
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._trim_unlocked()
            snapshot = self._snapshot_unlocked(job)
        self._persist_job_snapshot(snapshot)
        return snapshot

    def start(self, app, job_type, target, title=None, request=None, inline=False):
        job = self.create(job_type, title=title, request=request)
        job_id = job["id"]

        def runner():
            with app.app_context():
                self.mark_running(job_id)
                try:
                    result = target(job_id)
                    self.mark_succeeded(job_id, result=result)
                except Exception as exc:
                    logger.exception("Background job failed job_id=%s type=%s error=%s", job_id, job_type, exc)
                    self.mark_failed(job_id, exc)
                finally:
                    try:
                        from backend.app.extensions import db
                        db.session.remove()
                    except Exception:
                        logger.debug("Background job session cleanup failed job_id=%s", job_id, exc_info=True)

        if inline:
            runner()
        else:
            thread = threading.Thread(target=runner, name=f"job-{job_type}-{job_id[:8]}", daemon=True)
            thread.start()

        return self.get(job_id)

    def mark_running(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job["status"] = "running"
            job["started_at"] = self._utcnow()
            snapshot = self._snapshot_unlocked(job)
        self._persist_job_snapshot(snapshot)
        return snapshot

    def update_progress(self, job_id, current=None, total=None, message=None):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            progress = job.setdefault("progress", {})
            if current is not None:
                progress["current"] = current
            if total is not None:
                progress["total"] = total
            if message is not None:
                progress["message"] = message
            snapshot = self._snapshot_unlocked(job)
        self._persist_job_snapshot(snapshot)
        return snapshot

    def mark_succeeded(self, job_id, result=None):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job["status"] = "succeeded"
            job["finished_at"] = self._utcnow()
            job["result"] = copy.deepcopy(result)
            job["error"] = None
            snapshot = self._snapshot_unlocked(job)
        self._persist_job_snapshot(snapshot)
        return snapshot

    def mark_failed(self, job_id, exc):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job["status"] = "failed"
            job["finished_at"] = self._utcnow()
            job["error"] = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            snapshot = self._snapshot_unlocked(job)
        self._persist_job_snapshot(snapshot)
        return snapshot

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return self._snapshot_unlocked(job)
        return self._load_persisted_job(job_id)

    def list(self, job_type=None, limit=20):
        persisted = self._list_persisted_jobs(job_type=job_type, limit=limit)
        if persisted is not None:
            return persisted

        with self._lock:
            job_ids = list(reversed(self._order))
            items = []
            for job_id in job_ids:
                job = self._jobs.get(job_id)
                if not job:
                    continue
                if job_type and job.get("type") != job_type:
                    continue
                items.append(self._snapshot_unlocked(job))
                if len(items) >= limit:
                    break
            return items

    def clear(self):
        with self._lock:
            self._jobs.clear()
            self._order.clear()
        self._delete_persisted_jobs()


job_manager = BackgroundJobManager()
