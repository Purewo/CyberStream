from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import MaintenanceJob
from backend.app.services.jobs import job_manager


class BackgroundJobPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BACKGROUND_JOBS_INLINE": True,
            "MAINTENANCE_JOB_RESULT_ITEM_LIMIT": 2,
            "MAINTENANCE_JOB_RETENTION_DAYS": 30,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        job_manager.clear()

    def tearDown(self):
        job_manager.clear()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_persisted_job_result_is_truncated_but_memory_result_is_full(self):
        def target(_job_id):
            return {
                "summary": {"total": 4},
                "items": [{"index": index} for index in range(4)],
            }

        job = job_manager.start(
            self.app,
            "test_large_result",
            target,
            title="Large result",
            request={"case": "truncate"},
            inline=True,
        )

        self.assertEqual("succeeded", job["status"])
        self.assertEqual(4, len(job["result"]["items"]))

        with job_manager._lock:
            job_manager._jobs.clear()
            job_manager._order.clear()

        response = self.client.get(f"/api/v1/jobs/{job['id']}")
        self.assertEqual(200, response.status_code)
        persisted_job = response.get_json()["data"]
        self.assertTrue(persisted_job["persisted"])
        self.assertTrue(persisted_job["result"]["result_truncated"])
        self.assertEqual(4, persisted_job["result"]["result_item_count"])
        self.assertEqual(2, persisted_job["result"]["persisted_item_limit"])
        self.assertEqual([{"index": 0}, {"index": 1}], persisted_job["result"]["items"])

    def test_prune_removes_only_old_terminal_jobs(self):
        old_finished = datetime.utcnow() - timedelta(days=40)
        recent_finished = datetime.utcnow() - timedelta(days=2)
        old_job = MaintenanceJob(
            id="old-job",
            type="resource_governance_apply",
            title="Old",
            status="succeeded",
            created_at=old_finished,
            started_at=old_finished,
            finished_at=old_finished,
            updated_at=old_finished,
            request={},
            progress={},
            result={"summary": {"removed": 1}},
        )
        recent_job = MaintenanceJob(
            id="recent-job",
            type="resource_governance_apply",
            title="Recent",
            status="failed",
            created_at=recent_finished,
            started_at=recent_finished,
            finished_at=recent_finished,
            updated_at=recent_finished,
            request={},
            progress={},
            error={"type": "RuntimeError", "message": "boom"},
        )
        running_job = MaintenanceJob(
            id="running-job",
            type="resource_governance_apply",
            title="Running",
            status="running",
            created_at=old_finished,
            started_at=old_finished,
            finished_at=None,
            updated_at=old_finished,
            request={},
            progress={},
        )
        db.session.add_all([old_job, recent_job, running_job])
        db.session.commit()

        dry_run = self.client.post("/api/v1/jobs/prune", json={
            "retention_days": 30,
            "type": "resource_governance_apply",
            "dry_run": True,
        })
        self.assertEqual(200, dry_run.status_code)
        dry_data = dry_run.get_json()["data"]
        self.assertTrue(dry_data["dry_run"])
        self.assertEqual(1, dry_data["matched"])
        self.assertEqual(["old-job"], dry_data["matched_ids"])
        self.assertIsNotNone(db.session.get(MaintenanceJob, "old-job"))

        response = self.client.post("/api/v1/jobs/prune", json={
            "retention_days": 30,
            "type": "resource_governance_apply",
        })

        self.assertEqual(200, response.status_code)
        data = response.get_json()["data"]
        self.assertFalse(data["dry_run"])
        self.assertEqual(1, data["removed"])
        self.assertEqual(["old-job"], data["removed_ids"])
        self.assertIsNone(db.session.get(MaintenanceJob, "old-job"))
        self.assertIsNotNone(db.session.get(MaintenanceJob, "recent-job"))
        self.assertIsNotNone(db.session.get(MaintenanceJob, "running-job"))


if __name__ == "__main__":
    unittest.main()
