from __future__ import annotations

import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PROJECT_ROOT))

from backend.app.services.media_path_cleaner import MediaPathCleaner


class MediaPathCleanerCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cleaner = MediaPathCleaner()

    def assert_metadata(self, file_path: str, **expected):
        metadata = self.cleaner.parse_path_metadata(file_path)
        for key, value in expected.items():
            self.assertEqual(
                getattr(metadata, key),
                value,
                msg=f"{file_path} 的 {key} 结果不符合预期: {metadata.to_dict()}",
            )

    def test_numeric_title_keeps_movie_name(self):
        self.assert_metadata(
            "电影/1917.2019.1080p.mkv",
            title="1917",
            year=2019,
            season=None,
            episode=None,
            parse_mode="standard",
            parse_strategy="movie_filename_year",
            needs_review=False,
        )

    def test_episode_file_keeps_year_and_episode(self):
        self.assert_metadata(
            "剧集/Shogun.2024.S01E01.mkv",
            title="Shogun",
            year=2024,
            season=1,
            episode=1,
            parse_mode="standard",
            parse_strategy="flat_episode_filename",
            needs_review=False,
        )

    def test_parent_generic_folder_no_longer_overrides_tv_title(self):
        self.assert_metadata(
            "剧集/Show.Name.S01E02.1080p.mkv",
            title="Show Name",
            year=None,
            season=1,
            episode=2,
            parse_mode="standard",
            parse_strategy="flat_episode_filename",
            needs_review=False,
        )

    def test_release_group_anime_extracts_episode_without_fake_year(self):
        self.assert_metadata(
            "[NC-Raws] 葬送的芙莉莲 - 01 (B-Global 1920x1080 HEVC AAC MKV).mkv",
            title="葬送的芙莉莲",
            year=None,
            season=None,
            episode=1,
            parse_mode="fallback",
            parse_strategy="dirty_release_group",
            needs_review=True,
        )

    def test_generic_dirty_path_stays_in_fallback(self):
        self.assert_metadata(
            "VIDEO/0001.mp4",
            title="UNKNOWN",
            year=None,
            season=None,
            episode=None,
            parse_mode="fallback",
            parse_strategy="dirty_unresolved",
            needs_review=True,
        )


if __name__ == "__main__":
    unittest.main()
