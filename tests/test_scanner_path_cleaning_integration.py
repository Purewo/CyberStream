from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.path_cleaner_test_utils import (
    PROJECT_ROOT,
    build_scanner_file_items,
    load_video_paths_from_markdown,
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.scanner import CyberScanner


REAL_TREE_EXPORT = Path("/home/pureworld/.codex/赛博影视/tianyi_baijin18T_my_videos_tree.md")


class ScannerPathCleaningFixtureIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_path = Path(__file__).with_name("fixtures") / "tianyi_baijin18T_my_videos_tree_sample.md"
        cls.video_paths = load_video_paths_from_markdown(fixture_path)
        cls.file_items = build_scanner_file_items(cls.video_paths)
        cls.scanner = CyberScanner()

        with patch("backend.app.services.scanner.db.is_file_processed", return_value=False):
            cls.raw_entities = cls.scanner._phase_2_group(cls.file_items, 1)
            cls.optimized_entities = cls.scanner._optimize_entities(cls.raw_entities)

    def test_fixture_paths_group_into_expected_entities(self):
        self.assertIn(("星际穿越 Interstellar", 2014), self.optimized_entities)
        self.assertIn(("Avatar", 2009), self.optimized_entities)
        self.assertIn(("Jason Bourne", 2016), self.optimized_entities)
        self.assertIn(("Green Planet", None), self.optimized_entities)

    def test_fixture_dirty_sample_is_marked_for_review(self):
        green_planet_files = self.optimized_entities[("Green Planet", None)]
        self.assertEqual(1, len(green_planet_files))
        self.assertTrue(green_planet_files[0]["_meta"]["needs_review"])
        self.assertEqual("fallback", green_planet_files[0]["_meta"]["parse_mode"])


class ScannerPathCleaningRealTreeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REAL_TREE_EXPORT.exists():
            raise unittest.SkipTest(f"未找到真实目录导出: {REAL_TREE_EXPORT}")

        cls.video_paths = load_video_paths_from_markdown(REAL_TREE_EXPORT)
        cls.file_items = build_scanner_file_items(cls.video_paths)
        cls.scanner = CyberScanner()

        with patch("backend.app.services.scanner.db.is_file_processed", return_value=False):
            cls.raw_entities = cls.scanner._phase_2_group(cls.file_items, 1)
            cls.optimized_entities = cls.scanner._optimize_entities(cls.raw_entities)

    def test_real_tree_group_count_stays_reasonable(self):
        self.assertGreaterEqual(len(self.raw_entities), 80)
        self.assertLessEqual(len(self.optimized_entities), len(self.raw_entities))

    def test_real_tree_has_no_unknown_group_titles(self):
        unknown_titles = [
            title
            for title, _year in self.optimized_entities
            if str(title).startswith("UNKNOWN_SHOW_")
        ]
        self.assertEqual([], unknown_titles[:10], msg=f"仍有无法修复的分组标题: {unknown_titles[:10]}")

    def test_real_tree_review_file_count_stays_low(self):
        review_files = [
            file_item["path"]
            for files in self.optimized_entities.values()
            for file_item in files
            if file_item["_meta"].get("needs_review")
        ]
        self.assertLessEqual(
            len(review_files),
            10,
            msg=f"needs_review 数量异常: {len(review_files)}，样本: {review_files[:10]}",
        )

    def test_real_tree_expected_groups_survive_optimization(self):
        self.assertIn(("星际穿越 Interstellar", 2014), self.optimized_entities)
        self.assertIn(("Jason Bourne", 2016), self.optimized_entities)
        self.assertIn(("Avatar", 2009), self.optimized_entities)


if __name__ == "__main__":
    unittest.main()
