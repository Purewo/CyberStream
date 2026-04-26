from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.utils.common import ResourceValidator


class MediaFeatureParserTests(unittest.TestCase):
    def test_detects_reference_quality_remux_features(self):
        specs = ResourceValidator.get_tech_specs(
            "Interstellar.2014.IMAX.UHD.Bluray.REMUX.2160p.HEVC.DV.HDR.TrueHD.7.1.Atmos.mkv"
        )

        self.assertEqual("2160P", specs["resolution"])
        self.assertEqual(2160, specs["resolution_rank"])
        self.assertEqual("HEVC", specs["video_codec"])
        self.assertEqual("Dolby TrueHD Atmos", specs["audio_codec"])
        self.assertEqual("7.1", specs["audio_channels"])
        self.assertEqual(8, specs["audio_channel_count"])
        self.assertEqual("UHD Blu-ray Remux", specs["source"])
        self.assertEqual("reference", specs["quality_tier"])
        self.assertEqual("Dolby Vision", specs["hdr_format"])
        self.assertTrue(specs["features"]["is_4k"])
        self.assertTrue(specs["features"]["is_remux"])
        self.assertTrue(specs["features"]["is_uhd_bluray"])
        self.assertTrue(specs["features"]["is_lossless_audio"])
        self.assertTrue(specs["features"]["is_original_quality"])
        self.assertIn("REMUX", specs["tags"])

    def test_detects_avatar_style_truehd_atmos_and_hdr10(self):
        specs = ResourceValidator.get_tech_specs(
            "Avatar.The.Way.of.Water.2022.V2.UHD.BluRay.REMUX.2160p.HEVC.HDR.Atmos.TrueHD7.1.3Audio-DreamHD.mkv"
        )

        self.assertEqual("UHD Blu-ray Remux", specs["source"])
        self.assertEqual("HDR10", specs["hdr_format"])
        self.assertEqual("Dolby TrueHD Atmos", specs["audio_codec"])
        self.assertEqual("7.1", specs["audio_channels"])
        self.assertEqual(8, specs["audio_channel_count"])
        self.assertEqual("4K Remux HDR10", specs["quality_label"])

    def test_detects_common_1080p_features(self):
        specs = ResourceValidator.get_tech_specs("Movie.Name.2020.1080p.WEB-DL.H264.AAC.mkv")

        self.assertEqual("1080P", specs["resolution"])
        self.assertEqual(1080, specs["resolution_rank"])
        self.assertEqual("AVC", specs["video_codec"])
        self.assertEqual("AAC", specs["audio_codec"])
        self.assertEqual("WEB-DL", specs["source"])
        self.assertEqual("hd", specs["quality_tier"])
        self.assertEqual("Unknown", specs["hdr_format"])

    def test_only_marks_sdr_when_explicit(self):
        specs = ResourceValidator.get_tech_specs("Movie.Name.2020.1080p.WEB-DL.H264.AAC.SDR.mkv")

        self.assertEqual("SDR", specs["hdr_format"])


if __name__ == "__main__":
    unittest.main()
