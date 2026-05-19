from __future__ import annotations

import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PROJECT_ROOT))

from backend.app.services.media_path_cleaner import MediaPathCleaner
from backend.app.services.scanner import CyberScanner
from backend.app.metadata.parser import PathMetadataParser


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

    def test_inline_chinese_season_episode_uses_filename_title_before_uncategorized_folder(self):
        self.assert_metadata(
            "独立资源/未分类/剑来2-第01集.mp4",
            title="剑来",
            year=None,
            season=2,
            episode=1,
            parse_mode="standard",
            parse_strategy="inline_chinese_season_episode",
            needs_review=False,
        )

    def test_inline_chinese_season_episode_supports_explicit_season_marker(self):
        self.assert_metadata(
            "未分类/剑来 第2季 第16集.mp4",
            title="剑来",
            year=None,
            season=2,
            episode=16,
            parse_mode="standard",
            parse_strategy="inline_chinese_season_episode",
            needs_review=False,
        )

    def test_chinese_mixed_season_folder_overrides_conflicting_sxxexx_season(self):
        self.assert_metadata(
            "诛仙 第二季/[www.haimianxz.com]诛仙.Jade.Dynasty.S01E27.2024.2160p.WEB-DL.H265.DDP2.0-ZeroTV.mkv",
            title="诛仙",
            year=None,
            season=2,
            episode=27,
            parse_mode="standard",
            parse_strategy="mixed_season_folder",
            needs_review=True,
        )

    def test_numeric_file_inside_season_folder_uses_episode_number(self):
        self.assert_metadata(
            "基地/S03/01 4K.mp4",
            title="基地",
            year=None,
            season=3,
            episode=1,
            parse_mode="standard",
            parse_strategy="nested_season",
            needs_review=False,
        )

    def test_parent_season_alias_prefers_sxxexx_filename_title(self):
        self.assert_metadata(
            "基地3/Foundation.S03E01.2160p.DV.HDR.ATVP.WEB-DL.DDP5.1.H.265.mkv",
            title="Foundation",
            year=None,
            season=3,
            episode=1,
            parse_mode="standard",
            parse_strategy="flat_episode_filename",
            needs_review=False,
        )

    def test_metadata_pipeline_parser_matches_inline_chinese_season_episode(self):
        parser = PathMetadataParser()
        parsed = parser.parse("独立资源/未分类/剑来2-第01集.mp4")

        self.assertEqual("剑来", parsed.title)
        self.assertEqual(2, parsed.season)
        self.assertEqual(1, parsed.episode)
        self.assertEqual("tv", parsed.media_type_hint)
        self.assertEqual("strict", parsed.parse_layer)
        self.assertEqual("inline_chinese_season_episode", parsed.parse_strategy)

    def test_metadata_pipeline_parser_uses_chinese_parent_season(self):
        parser = PathMetadataParser()
        parsed = parser.parse(
            "诛仙 第二季/[www.haimianxz.com]诛仙.Jade.Dynasty.S01E27.2024.2160p.WEB-DL.H265.DDP2.0-ZeroTV.mkv"
        )

        self.assertEqual("诛仙", parsed.title)
        self.assertEqual(2, parsed.season)
        self.assertEqual(27, parsed.episode)
        self.assertEqual("mixed_season_folder", parsed.parse_strategy)
        self.assertEqual("medium", parsed.confidence)

    def test_metadata_pipeline_parser_prefers_filename_title_for_parent_season_alias(self):
        parser = PathMetadataParser()
        parsed = parser.parse("基地3/Foundation.S03E01.2160p.DV.HDR.ATVP.WEB-DL.DDP5.1.H.265.mkv")

        self.assertEqual("Foundation", parsed.title)
        self.assertEqual(3, parsed.season)
        self.assertEqual(1, parsed.episode)
        self.assertEqual("tv", parsed.media_type_hint)
        self.assertEqual("flat_sxxexx_filename", parsed.parse_strategy)

    def test_scanner_normalizes_absolute_episode_numbers_against_season_metadata(self):
        scanner = CyberScanner()
        season, episode, normalization = scanner._normalize_episode_for_season_metadata(
            2,
            27,
            {
                "season_metadata": [
                    {"season": 1, "episode_count": 26},
                    {"season": 2, "episode_count": 26},
                ],
            },
        )

        self.assertEqual(2, season)
        self.assertEqual(1, episode)
        self.assertEqual("absolute_episode_offset", normalization["strategy"])

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
