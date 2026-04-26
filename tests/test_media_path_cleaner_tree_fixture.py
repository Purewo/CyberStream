from __future__ import annotations

import unittest
from pathlib import Path

from tests.path_cleaner_test_utils import load_video_paths_from_markdown


class MediaPathCleanerTreeFixtureTests(unittest.TestCase):
    def test_sample_tree_fixture_can_be_parsed(self):
        fixture_path = Path(__file__).with_name("fixtures") / "tianyi_baijin18T_my_videos_tree_sample.md"
        video_paths = load_video_paths_from_markdown(fixture_path)

        self.assertEqual(
            video_paths,
            [
                "我的视频/[haimian.eu.org]星际穿越.Interstellar.2014.IMAX.UHD.Bluray.REMUX.2160p.HEVC.DV.HDR.TrueHD.7.1.Atmos-LGNB.mkv.iso",
                "我的视频/A.阿凡达.2009.REMUX/Avatar.2009.Extended.UHD.Re-Grade.4000nit.2160p.HEVC.HDR.IVA(RUS.UKR.ENG).ExKinoRay.mkv",
                "我的视频/Jason.Bourne.2016.2160p.BluRay.REMUX.HEVC.DTS-X.7.1-FGT/Jason.Bourne.2016.2160p.BluRay.REMUX.HEVC.DTS-X.7.1-FGT.mkv",
                "我的视频/绿色星球/Green Planet 1.m2ts",
            ],
        )


if __name__ == "__main__":
    unittest.main()

