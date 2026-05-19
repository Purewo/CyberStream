from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import History, MaintenanceJob, MediaResource, Movie, ResourceSubtitle, StorageSource
from backend.app.services.jobs import job_manager


class _FakeProvider:
    def __init__(self, directories):
        self.directories = directories

    def list_items(self, path):
        return self.directories.get(path or "", [])


class ResourceGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BACKGROUND_JOBS_INLINE": True,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.source = StorageSource(name="NAS", type="local", config={"root_path": "/media"})
        self.backup_source = StorageSource(name="Backup", type="local", config={"root_path": "/backup"})
        db.session.add_all([self.source, self.backup_source])
        db.session.commit()

    def tearDown(self):
        job_manager.clear()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _movie(self, title):
        movie = Movie(
            tmdb_id=f"movie/{title}",
            title=title,
            original_title=title,
            year=2026,
            cover="poster",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.commit()
        return movie

    def _resource(self, movie, source, path, size=100, season=None, episode=None, created_at=None):
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id if source else None,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            size=size,
            season=season,
            episode=episode,
        )
        if created_at is not None:
            resource.created_at = created_at
        db.session.add(resource)
        db.session.commit()
        return resource

    def test_governance_summary_detects_static_resource_issues(self):
        duplicate_movie = self._movie("重复资源")
        first = self._resource(duplicate_movie, self.source, "movies/main/movie.mkv", size=4096)
        second = self._resource(duplicate_movie, self.backup_source, "backup/movie.mkv", size=4096)

        detached_movie = self._movie("孤儿资源")
        detached = self._resource(detached_movie, None, "lost/file.mkv", size=128)
        empty_movie = self._movie("空壳影片")

        response = self.client.get("/api/v1/resources/governance-summary", query_string={"sample_size": 2})

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["dry_run"])
        issues = {item["code"]: item for item in data["issues"]}
        self.assertEqual(1, issues["duplicate_playback_resource"]["item_count"])
        self.assertEqual({first.id, second.id}, set(issues["duplicate_playback_resource"]["samples"][0]["resource_ids"]))
        self.assertEqual(1, issues["detached_source_resource"]["count"])
        self.assertEqual(detached.id, issues["detached_source_resource"]["samples"][0]["resource"]["resource_id"])
        self.assertEqual(1, issues["movie_without_resources"]["count"])
        self.assertEqual(empty_movie.id, issues["movie_without_resources"]["samples"][0]["movie"]["movie_id"])
        self.assertIn("live_check_skipped", issues)

    def test_governance_live_check_detects_missing_path_and_size_mismatch(self):
        movie = self._movie("路径检查")
        missing = self._resource(movie, self.source, "shows/Missing.S01E01.mkv", size=100)
        changed = self._resource(movie, self.source, "shows/Changed.S01E02.mkv", size=100)
        valid = self._resource(movie, self.source, "shows/Valid.S01E03.mkv", size=100)

        provider = _FakeProvider({
            "shows": [
                {"name": "Changed.S01E02.mkv", "path": "shows/Changed.S01E02.mkv", "isdir": False, "size": 200},
                {"name": "Valid.S01E03.mkv", "path": "shows/Valid.S01E03.mkv", "isdir": False, "size": 100},
            ]
        })

        with patch("backend.app.services.resource_governance.provider_factory.get_provider", return_value=provider):
            response = self.client.get(
                "/api/v1/resources/governance-items",
                query_string={"live_check": "true", "live_check_limit": 10, "page_size": 20},
            )

        self.assertEqual(200, response.status_code)
        items = response.get_json()["data"]["items"]
        by_code = {}
        for item in items:
            by_code.setdefault(item["issue_code"], []).append(item)
        self.assertEqual(missing.id, by_code["invalid_path"][0]["resource"]["resource_id"])
        self.assertEqual(changed.id, by_code["size_mismatch"][0]["resource"]["resource_id"])
        self.assertNotIn(valid.id, {
            item.get("resource", {}).get("resource_id")
            for values in by_code.values()
            for item in values
        })

    def test_governance_plan_previews_duplicate_cleanup_without_deleting(self):
        movie = self._movie("重复清理预览")
        older = self._resource(movie, self.source, "movies/copy/movie.mkv", size=4096, created_at=datetime.utcnow() - timedelta(minutes=2))
        newer = self._resource(movie, self.backup_source, "backup/movie.mkv", size=4096, created_at=datetime.utcnow())

        response = self.client.post("/api/v1/resources/governance/plan", json={
            "issue_codes": ["duplicate_playback_resource"],
        })

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertTrue(data["dry_run"])
        self.assertEqual(1, data["summary"]["planned"])
        self.assertEqual(1, len(data["apply_payload"]["items"]))
        action = data["apply_payload"]["items"][0]
        self.assertEqual("remove_resource_index", action["type"])
        self.assertEqual(older.id, action["resource_id"])
        self.assertEqual(newer.id, action["primary_resource_id"])
        self.assertFalse(data["pagination"]["paginated"])
        self.assertTrue(data["items"][0]["restore_snapshot_available"])
        self.assertIsNotNone(db.session.get(MediaResource, older.id))
        self.assertIsNotNone(db.session.get(MediaResource, newer.id))

    def test_governance_plan_supports_limit_for_large_payloads(self):
        movie = self._movie("重复清理限量")
        newest = self._resource(movie, self.backup_source, "limit/main/movie.mkv", size=4096, created_at=datetime.utcnow())
        first = self._resource(movie, self.source, "limit/copy-a/movie.mkv", size=4096, created_at=datetime.utcnow() - timedelta(minutes=1))
        second = self._resource(movie, self.source, "limit/copy-b/movie.mkv", size=4096, created_at=datetime.utcnow() - timedelta(minutes=2))

        response = self.client.post("/api/v1/resources/governance/plan", json={
            "issue_codes": ["duplicate_playback_resource"],
            "limit": 1,
        })

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(2, data["summary"]["planned"])
        self.assertEqual(1, data["returned_summary"]["planned"])
        self.assertEqual(2, data["pagination"]["total_items"])
        self.assertEqual(1, len(data["items"]))
        self.assertEqual(1, len(data["apply_payload"]["items"]))
        self.assertEqual(newest.id, data["apply_payload"]["items"][0]["primary_resource_id"])
        self.assertIn(data["apply_payload"]["items"][0]["resource_id"], {first.id, second.id})

    def test_governance_plan_applies_safety_guards(self):
        now = datetime.utcnow()
        history_movie = self._movie("历史保护")
        history_alternate = self._resource(history_movie, self.source, "history/movie.mkv", size=100, created_at=now - timedelta(minutes=4))
        self._resource(history_movie, self.backup_source, "history-copy/movie.mkv", size=100, created_at=now)
        db.session.add(History(resource_id=history_alternate.id, progress=10, duration=100))

        subtitle_movie = self._movie("字幕保护")
        subtitle_alternate = self._resource(subtitle_movie, self.source, "subtitle/movie.mkv", size=200, created_at=now - timedelta(minutes=4))
        self._resource(subtitle_movie, self.backup_source, "subtitle-copy/movie.mkv", size=200, created_at=now)
        db.session.add(ResourceSubtitle(
            resource_id=subtitle_alternate.id,
            source="online",
            provider_id="test",
            provider_name="Test",
            candidate_id="subtitle-candidate",
            filename="movie.srt",
            storage_path="/cache/movie.srt",
            format="srt",
            mime_type="text/plain",
        ))

        invalid_movie = self._movie("最后资源保护")
        last_resource = self._resource(invalid_movie, self.source, "missing/movie.mkv", size=300)
        db.session.commit()

        provider = _FakeProvider({
            "history": [{"name": "movie.mkv", "path": "history/movie.mkv", "isdir": False, "size": 100}],
            "history-copy": [{"name": "movie.mkv", "path": "history-copy/movie.mkv", "isdir": False, "size": 100}],
            "subtitle": [{"name": "movie.mkv", "path": "subtitle/movie.mkv", "isdir": False, "size": 200}],
            "subtitle-copy": [{"name": "movie.mkv", "path": "subtitle-copy/movie.mkv", "isdir": False, "size": 200}],
            "missing": [],
        })
        with patch("backend.app.services.resource_governance.provider_factory.get_provider", return_value=provider):
            response = self.client.post("/api/v1/resources/governance/plan", json={
                "issue_codes": ["duplicate_playback_resource", "invalid_path"],
                "live_check": True,
                "live_check_limit": 20,
            })

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertEqual(0, data["summary"]["planned"])
        skip_by_resource = {
            item["resource_id"]: item["skip_reason"]
            for item in data["items"]
            if item["status"] == "skipped"
        }
        self.assertEqual("has_history", skip_by_resource[history_alternate.id])
        self.assertEqual("has_bound_subtitles", skip_by_resource[subtitle_alternate.id])
        self.assertEqual("last_resource_for_movie", skip_by_resource[last_resource.id])

    def test_governance_job_applies_planned_duplicate_cleanup(self):
        movie = self._movie("重复清理执行")
        older = self._resource(movie, self.source, "execute/movie.mkv", size=4096, created_at=datetime.utcnow() - timedelta(minutes=2))
        newer = self._resource(movie, self.backup_source, "execute-copy/movie.mkv", size=4096, created_at=datetime.utcnow())
        older_id = older.id
        newer_id = newer.id
        movie_id = movie.id

        plan_response = self.client.post("/api/v1/resources/governance/plan", json={
            "issue_codes": ["duplicate_playback_resource"],
        })
        apply_payload = plan_response.get_json()["data"]["apply_payload"]

        response = self.client.post("/api/v1/resources/governance/jobs", json=apply_payload)

        self.assertEqual(202, response.status_code)
        job = response.get_json()["data"]["job"]
        self.assertEqual("succeeded", job["status"])
        self.assertEqual(1, job["result"]["summary"]["removed"])
        self.assertEqual(1, job["result"]["summary"]["restore_snapshot_count"])
        self.assertEqual(older_id, job["result"]["items"][0]["restore_snapshot"]["fields"]["id"])
        self.assertFalse(job["result"]["items"][0]["restore_snapshot"]["delete_physical_file"])
        self.assertIsNotNone(db.session.get(MaintenanceJob, job["id"]))
        with job_manager._lock:
            job_manager._jobs.clear()
            job_manager._order.clear()
        persisted_detail = self.client.get(f"/api/v1/jobs/{job['id']}")
        self.assertEqual(200, persisted_detail.status_code)
        self.assertTrue(persisted_detail.get_json()["data"]["persisted"])
        db.session.expire_all()
        self.assertIsNone(db.session.get(MediaResource, older_id))
        self.assertIsNotNone(db.session.get(MediaResource, newer_id))
        self.assertIsNotNone(db.session.get(Movie, movie_id))

    def test_governance_restore_plan_and_job_recreate_deleted_resource_index(self):
        movie = self._movie("资源索引恢复")
        older = self._resource(movie, self.source, "restore/movie.mkv", size=4096, created_at=datetime.utcnow() - timedelta(minutes=2))
        newer = self._resource(movie, self.backup_source, "restore-copy/movie.mkv", size=4096, created_at=datetime.utcnow())
        older_id = older.id
        newer_id = newer.id

        plan_response = self.client.post("/api/v1/resources/governance/plan", json={
            "issue_codes": ["duplicate_playback_resource"],
        })
        cleanup_response = self.client.post(
            "/api/v1/resources/governance/jobs",
            json=plan_response.get_json()["data"]["apply_payload"],
        )
        snapshot = cleanup_response.get_json()["data"]["job"]["result"]["items"][0]["restore_snapshot"]
        db.session.expire_all()
        self.assertIsNone(db.session.get(MediaResource, older_id))

        restore_plan_response = self.client.post("/api/v1/resources/governance/restore/plan", json={
            "restore_snapshots": [snapshot],
        })

        self.assertEqual(200, restore_plan_response.status_code)
        restore_plan = restore_plan_response.get_json()["data"]
        self.assertTrue(restore_plan["dry_run"])
        self.assertEqual(1, restore_plan["summary"]["planned"])
        self.assertEqual(1, len(restore_plan["apply_payload"]["items"]))

        restore_response = self.client.post(
            "/api/v1/resources/governance/restore/jobs",
            json=restore_plan["apply_payload"],
        )

        self.assertEqual(202, restore_response.status_code)
        restore_job = restore_response.get_json()["data"]["job"]
        self.assertEqual("resource_governance_restore", restore_job["type"])
        self.assertEqual("succeeded", restore_job["status"])
        self.assertEqual(1, restore_job["result"]["summary"]["restored"])
        db.session.expire_all()
        restored = db.session.get(MediaResource, older_id)
        self.assertIsNotNone(restored)
        self.assertEqual("restore/movie.mkv", restored.path)
        self.assertEqual(4096, restored.size)
        self.assertIsNotNone(db.session.get(MediaResource, newer_id))

    def test_governance_job_requires_confirmation(self):
        response = self.client.post("/api/v1/resources/governance/jobs", json={
            "items": [{
                "type": "remove_resource_index",
                "issue_code": "duplicate_playback_resource",
                "resource_id": "missing",
            }],
        })

        self.assertEqual(400, response.status_code)
        self.assertEqual(40101, response.get_json()["code"])

    def test_governance_live_check_job_returns_bounded_read_only_result(self):
        movie = self._movie("后台路径检查")
        missing = self._resource(movie, self.source, "job/Missing.S01E01.mkv", size=100)
        changed = self._resource(movie, self.source, "job/Changed.S01E02.mkv", size=100)
        self._resource(movie, self.source, "job/Valid.S01E03.mkv", size=100)

        provider = _FakeProvider({
            "job": [
                {"name": "Changed.S01E02.mkv", "path": "job/Changed.S01E02.mkv", "isdir": False, "size": 200},
                {"name": "Valid.S01E03.mkv", "path": "job/Valid.S01E03.mkv", "isdir": False, "size": 100},
            ]
        })

        with patch("backend.app.services.resource_governance.provider_factory.get_provider", return_value=provider):
            response = self.client.post("/api/v1/resources/governance/live-check/jobs", json={
                "live_check_limit": 10,
                "issue_code": "invalid_path",
                "page_size": 5,
            })

        self.assertEqual(202, response.status_code)
        job = response.get_json()["data"]["job"]
        self.assertEqual("resource_governance_live_check", job["type"])
        self.assertEqual("succeeded", job["status"])
        result = job["result"]
        self.assertTrue(result["dry_run"])
        self.assertEqual(3, result["summary"]["totals"]["live_path_checked_count"])
        self.assertEqual(1, result["pagination"]["total_items"])
        self.assertEqual(missing.id, result["items"][0]["resource"]["resource_id"])
        self.assertIsNotNone(db.session.get(MediaResource, changed.id))


if __name__ == "__main__":
    unittest.main()
