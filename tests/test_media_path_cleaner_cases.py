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

    def test_standard_movie_filename_preserves_sequel_number(self):
        self.assert_metadata(
            "Movies/Despicable.Me.2.2013.2160p.BluRay.REMUX.mkv",
            title="Despicable Me 2",
            year=2013,
            season=None,
            episode=None,
            parse_mode="standard",
            parse_strategy="movie_filename_year",
            needs_review=False,
        )

    def test_parent_movie_folder_preserves_sequel_number(self):
        self.assert_metadata(
            "Movies/Final Destination 5 2011 BluRay 2160p/feature.mkv",
            title="Final Destination 5",
            year=2011,
            season=None,
            episode=None,
            parse_mode="standard",
            parse_strategy="movie_parent",
            needs_review=False,
        )

    def test_group_title_repair_preserves_sequel_number(self):
        repaired = self.cleaner.repair_group_title(
            "Kung Fu Panda 3",
            "Movies/Kung.Fu.Panda.3.2016/Kung.Fu.Panda.3.2016.mkv",
            current_year=2016,
        )

        self.assertEqual("Kung Fu Panda 3", repaired.title)
        self.assertEqual(2016, repaired.year)

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

    def test_spaced_season_parenthesized_episode_is_tv_episode(self):
        self.assert_metadata(
            "Shows/Tang Changan/tang.2025.2160p.WEB-DL.S03 (1).mkv",
            title="Tang Changan",
            year=None,
            season=3,
            episode=1,
            parse_mode="standard",
            parse_strategy="flat_episode",
            needs_review=False,
        )

    def test_metadata_pipeline_parser_matches_spaced_season_parenthesized_episode(self):
        parser = PathMetadataParser()
        parsed = parser.parse("Shows/Tang Changan/tang.2025.2160p.WEB-DL.S03 (10).mkv")

        self.assertEqual("Tang Changan", parsed.title)
        self.assertEqual(3, parsed.season)
        self.assertEqual(10, parsed.episode)
        self.assertEqual("tv", parsed.media_type_hint)
        self.assertEqual("strict", parsed.parse_layer)
        self.assertEqual("flat_sxxexx", parsed.parse_strategy)

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

    def test_metadata_pipeline_parser_does_not_treat_dts_channel_as_season(self):
        parser = PathMetadataParser()
        path = (
            "天翼铂金18T/我的视频/"
            "【高清影视之家发布 www.WHATMV.com】落凡尘[60帧率版本][高码版][国粤多音轨+中文字幕]."
            "2024.2160p.HQ.WEB-DL.DTS5.1.H264.60fps.2Audio-ParkHD/"
            "落凡尘.Into.The.Mortal.World.2024.2160p.HQ.WEB-DL.DTS5.1.H264.60fps.2Audio-ParkHD.mkv"
        )

        parsed = parser.parse(path)
        cleaned = self.cleaner.parse_path_metadata(path)

        self.assertEqual("movie", parsed.media_type_hint)
        self.assertIsNone(parsed.season)
        self.assertIsNone(parsed.episode)
        self.assertIn(parsed.parse_strategy, {"movie_parent_folder", "movie_filename_with_year"})
        self.assertEqual("落凡尘 Into The Mortal World", cleaned.title)
        self.assertIsNone(cleaned.season)
        self.assertIsNone(cleaned.episode)
        self.assertEqual("movie_filename_year", cleaned.parse_strategy)

    def test_metadata_pipeline_parser_keeps_numeric_movie_title_and_last_year(self):
        parser = PathMetadataParser()
        parsed = parser.parse("Movies/2012.2009.2160p.BluRay.REMUX.mkv")

        self.assertEqual("2012", parsed.title)
        self.assertEqual(2009, parsed.year)
        self.assertEqual("movie", parsed.media_type_hint)
        self.assertEqual("movie_filename_with_year", parsed.parse_strategy)

    def test_metadata_pipeline_parser_uses_last_year_for_title_with_year_number(self):
        parser = PathMetadataParser()
        parsed = parser.parse(
            "Movies/Wonder.Woman.1984.2020.PROPER.IMAX.2160p.BluRay.REMUX/"
            "Wonder.Woman.1984.2020.PROPER.IMAX.2160p.BluRay.REMUX.mkv"
        )

        self.assertEqual(2020, parsed.year)
        self.assertEqual("movie", parsed.media_type_hint)
        self.assertEqual("movie_parent_folder", parsed.parse_strategy)

    def test_metadata_pipeline_parser_ignores_resolution_as_year(self):
        parser = PathMetadataParser()
        parsed = parser.parse(
            "[KMTeams] Legend of LuoXiaohei 1-40+movie (Bilibili 1920x1080 x264 AAC)/"
            "S1_1-28/[KMTeams] Legend of LuoXiaohei 01 (Bilibili 1280x1024 x264 AAC).mp4"
        )

        self.assertEqual("Legend of LuoXiaohei 1 40+movie", parsed.title)
        self.assertIsNone(parsed.year)
        self.assertEqual(1, parsed.episode)
        self.assertEqual("tv", parsed.media_type_hint)
        self.assertEqual("season_folder", parsed.parse_strategy)

    def test_release_site_prefix_removed_from_mixed_season_folder(self):
        parser = PathMetadataParser()
        path = (
            "来自：分享/来自：云添加/"
            "【高清剧集网发布 www.BPHDTV.com】指环王：力量之戒 第二季"
            "[杜比视界版本][全8集][简繁英字幕].2024.2160p.AMZN.WEB-DL.H265.DV.DDP5.1.Atmos-ZeroTV/"
            "The.Lord.of.the.Rings.The.Rings.of.Power.S02E01.2024.2160p.AMZN.WEB-DL.H265.DV.DDP5.1.Atmos-ZeroTV.mkv"
        )

        cleaned = self.cleaner.parse_path_metadata(path)
        parsed = parser.parse(path)

        self.assertEqual("指环王：力量之戒", cleaned.title)
        self.assertEqual(2024, cleaned.year)
        self.assertEqual(2, cleaned.season)
        self.assertEqual(1, cleaned.episode)
        self.assertEqual("mixed_season_folder", cleaned.parse_strategy)
        self.assertEqual("指环王：力量之戒", parsed.title)
        self.assertEqual(2024, parsed.year)
        self.assertEqual(2, parsed.season)
        self.assertEqual(1, parsed.episode)

    def test_release_group_prefix_removed_from_nested_season_folder(self):
        path = (
            "来自：分享/来自：云添加/"
            "[KMTeams] Legend of LuoXiaohei 1-40+movie (Bilibili 1920x1080 x264 AAC)/"
            "S1_1-28/[KMTeams] Legend of LuoXiaohei 01 (Bilibili 1280x1024 x264 AAC).mp4"
        )

        cleaned = self.cleaner.parse_path_metadata(path)

        self.assertEqual("Legend of LuoXiaohei 1 40+movie", cleaned.title)
        self.assertIsNone(cleaned.year)
        self.assertEqual(1, cleaned.season)
        self.assertEqual(1, cleaned.episode)
        self.assertEqual("nested_season", cleaned.parse_strategy)

    def test_release_group_episode_allows_ampersand_suffix(self):
        path = (
            "来自：分享/来自：云添加/"
            "[KMTeams] Legend of LuoXiaohei 1-40+movie (Bilibili 1920x1080 x264 AAC)/"
            "S1_1-28/[KMTeams] Legend of LuoXiaohei 28&movie-pv (Bilibili 1920x1080 x264 AAC).mp4"
        )

        parsed = PathMetadataParser().parse(path)
        cleaned = self.cleaner.parse_path_metadata(path)

        self.assertEqual(1, parsed.season)
        self.assertEqual(28, parsed.episode)
        self.assertEqual(1, cleaned.season)
        self.assertEqual(28, cleaned.episode)

    def test_release_site_prefix_removed_from_movie_parent_folder(self):
        path = (
            "来自：分享/来自：云添加/"
            "【更多高清电影访问 www.mkvhome.com】西游[共2部合集][国粤英多音轨+简繁英字幕]."
            "Journey.to.the.West.2013-2017.BluRay.1080p.2Audio.DTS-HD.MA.7.1.x265.10bit-ALT/"
            "〔 高清电影下载 www.mkvhome.com 〕.mkv"
        )

        cleaned = self.cleaner.parse_path_metadata(path)

        self.assertEqual("西游 共2部合集 Journey to the West 2Audio ALT", cleaned.title)
        self.assertEqual(2017, cleaned.year)
        self.assertEqual("movie_parent", cleaned.parse_strategy)

    def test_movie_title_keeps_dance_and_ignores_truehd_channel(self):
        parser = PathMetadataParser()
        path = (
            "来自：分享/来自：云添加/"
            "Venom The Last Dance 2024 2160p UHD Blu-ray Remux HEVC DV TrueHD 7.1 Atmos-HDT/"
            "Venom The Last Dance 2024 2160p UHD Blu-ray Remux HEVC DV TrueHD 7.1 Atmos-HDT.mkv"
        )

        parsed = parser.parse(path)
        cleaned = self.cleaner.parse_path_metadata(path)

        self.assertEqual("Venom The Last Dance", parsed.title)
        self.assertEqual(2024, parsed.year)
        self.assertIsNone(parsed.season)
        self.assertIsNone(parsed.episode)
        self.assertEqual("movie", parsed.media_type_hint)
        self.assertEqual("movie_parent_folder", parsed.parse_strategy)
        self.assertEqual("Venom The Last Dance", cleaned.title)
        self.assertEqual(2024, cleaned.year)
        self.assertIsNone(cleaned.season)
        self.assertIsNone(cleaned.episode)
        self.assertEqual("movie_filename_year", cleaned.parse_strategy)

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

    def test_scanner_maps_continuous_episode_numbers_to_metadata_season_window(self):
        scanner = CyberScanner()
        season, episode, normalization = scanner._normalize_episode_for_season_metadata(
            2,
            29,
            {
                "season_metadata": [
                    {"season": 1, "episode_count": 41},
                    {"season": 2, "episode_count": 1},
                ],
            },
        )

        self.assertEqual(1, season)
        self.assertEqual(29, episode)
        self.assertEqual("absolute_episode_offset", normalization["strategy"])
        self.assertEqual(2, normalization["original_season"])
        self.assertEqual(1, normalization["normalized_season"])

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
