from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.scanner import CyberScanner


class ScannerStatusProgressTests(unittest.TestCase):
    def test_group_and_process_progress_fields_are_exposed(self):
        scanner = CyberScanner()
        scanner._begin_scan_session(current_source="Test Source")
        try:
            files = [
                {
                    "name": "Green Planet 1.m2ts",
                    "path": "我的视频/绿色星球/Green Planet 1.m2ts",
                    "size": 1,
                    "isdir": False,
                },
                {
                    "name": "movie.nfo",
                    "path": "我的视频/绿色星球/movie.nfo",
                    "size": 1,
                    "isdir": False,
                },
            ]

            with patch("backend.app.services.scanner.db.is_file_processed", return_value=False):
                raw_entities = scanner._phase_2_group(files, source_id=1)

            scanner._publish_status_snapshot()
            status = scanner.get_status()
            self.assertEqual("grouping", status["phase"])
            self.assertEqual(2, status["total_items"])
            self.assertTrue(status["total_items_known"])
            self.assertEqual(2, status["processed_items"])

            with patch.object(scanner, "_process_single_entity", return_value=None):
                scanner._phase_3_process(raw_entities, source_id=1, app_instance=None, provider=None)

            scanner._publish_status_snapshot()
            status = scanner.get_status()
            self.assertEqual("processing", status["phase"])
            self.assertEqual(1, status["total_items"])
            self.assertTrue(status["total_items_known"])
            self.assertEqual(1, status["processed_items"])
            self.assertEqual(1, status["processed_files"])
            self.assertEqual(0, len(status["active_items"]))
            self.assertEqual("", status["current_item"])
            self.assertEqual("", status["current_file"])
        finally:
            scanner._finish_scan_session()

    def test_progress_snapshot_contains_active_item_details(self):
        scanner = CyberScanner()
        scanner._begin_scan_session(current_source="Test Source")
        try:
            scanner._update_progress(phase="processing", total_items=3, total_items_known=True)
            scanner._mark_processing_started(
                "task-1",
                "The Green Planet (2022)",
                "我的视频/绿色星球/Green Planet 1.m2ts",
                2,
            )
            scanner._publish_status_snapshot()

            status = scanner.get_status()
            self.assertEqual("processing", status["phase"])
            self.assertEqual("The Green Planet (2022)", status["current_item"])
            self.assertEqual("我的视频/绿色星球/Green Planet 1.m2ts", status["current_file"])
            self.assertEqual(1, len(status["active_items"]))
            self.assertEqual("The Green Planet (2022)", status["active_items"][0]["label"])
            self.assertEqual(2, status["active_items"][0]["file_count"])

            scanner._mark_processing_finished("task-1", processed_files=2, processed_items=1)
            scanner._publish_status_snapshot()
            status = scanner.get_status()
            self.assertEqual(1, status["processed_items"])
            self.assertEqual(2, status["processed_files"])
            self.assertEqual(0, len(status["active_items"]))
        finally:
            scanner._finish_scan_session()


if __name__ == "__main__":
    unittest.main()
