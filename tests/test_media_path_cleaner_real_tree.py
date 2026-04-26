from __future__ import annotations

import re
import unittest
from collections import Counter
from pathlib import Path

from tests.path_cleaner_test_utils import PROJECT_ROOT, load_video_paths_from_markdown

if str(PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PROJECT_ROOT))

from backend.app.services.media_path_cleaner import MediaPathCleaner


REAL_TREE_EXPORT = Path("/home/pureworld/.codex/赛博影视/tianyi_baijin18T_my_videos_tree.md")
SEASON_EPISODE_RE = re.compile(r"(?i)S\d+[.\s_-]*E\d+")


class MediaPathCleanerRealTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REAL_TREE_EXPORT.exists():
            raise unittest.SkipTest(f"未找到真实目录导出: {REAL_TREE_EXPORT}")

        cls.cleaner = MediaPathCleaner()
        cls.video_paths = load_video_paths_from_markdown(REAL_TREE_EXPORT)
        cls.parsed = {path: cls.cleaner.parse_path_metadata(path) for path in cls.video_paths}

    def test_real_tree_has_enough_video_samples(self):
        self.assertGreaterEqual(len(self.video_paths), 1000)

    def test_real_tree_fallback_count_stays_low(self):
        fallback_paths = [
            path
            for path, metadata in self.parsed.items()
            if metadata.parse_mode == "fallback"
        ]
        self.assertLessEqual(
            len(fallback_paths),
            10,
            msg=f"fallback 数量异常: {len(fallback_paths)}，样本: {fallback_paths[:10]}",
        )

    def test_real_tree_no_resolution_year_pollution(self):
        suspicious_paths = [
            path
            for path, metadata in self.parsed.items()
            if metadata.year in {1280, 1920, 2160, 3840, 4096}
        ]
        self.assertEqual([], suspicious_paths[:10], msg=f"疑似把分辨率识别成年份: {suspicious_paths[:10]}")

    def test_real_tree_keeps_all_sxxeyy_episode_tags(self):
        missing = [
            path
            for path, metadata in self.parsed.items()
            if SEASON_EPISODE_RE.search(path) and (metadata.season is None or metadata.episode is None)
        ]
        self.assertEqual([], missing[:10], msg=f"SxxEyy 样本有季集丢失: {missing[:10]}")

    def test_real_tree_regression_summary_is_in_expected_band(self):
        strategies = Counter(metadata.parse_strategy for metadata in self.parsed.values())
        self.assertGreater(strategies.get("movie_parent", 0), 500)
        self.assertGreater(strategies.get("movie_filename_year", 0), 30)
        self.assertLessEqual(strategies.get("dirty_release_group", 0), 10)


if __name__ == "__main__":
    unittest.main()

