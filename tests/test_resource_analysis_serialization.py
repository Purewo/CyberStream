from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models import MediaResource, StorageSource


class ResourceAnalysisSerializationTests(unittest.TestCase):
    def test_resource_to_dict_exposes_analysis(self):
        resource = MediaResource(
            filename="Green Planet 1.m2ts",
            path="我的视频/绿色星球/Green Planet 1.m2ts",
            source_id=1,
            size=1234,
            label="EP01 - 1080P",
            tech_specs={
                "resolution": "1080P",
                "codec": "REMUX",
                "size": 1234,
                "analysis": {
                    "path_cleaning": {
                        "title_hint": "Green Planet",
                        "parse_mode": "fallback",
                        "needs_review": True,
                    },
                    "scraping": {
                        "provider": "tmdb",
                        "final_title_source": "tmdb",
                    },
                },
            },
        )

        data = resource.to_dict()

        self.assertEqual("Green Planet", data["metadata"]["analysis"]["path_cleaning"]["title_hint"])
        self.assertTrue(data["metadata"]["analysis"]["path_cleaning"]["needs_review"])
        self.assertEqual("tmdb", data["metadata"]["analysis"]["scraping"]["provider"])

    def test_resource_to_dict_does_not_infer_sdr_without_marker(self):
        resource = MediaResource(
            filename="Spider-Man.No.Way.Home.mkv",
            path="电影/Spider-Man.No.Way.Home.mkv",
            source_id=1,
            size=1234,
            label="Movie - Unknown",
            tech_specs={
                "resolution": "Unknown",
                "hdr_format": "SDR",
                "tags": [],
            },
        )

        data = resource.to_dict()

        self.assertEqual("unknown", data["resource_info"]["technical"]["video_dynamic_range_code"])
        self.assertFalse(data["resource_info"]["technical"]["video_dynamic_range_is_known"])

    def test_resource_to_dict_exposes_media_features(self):
        resource = MediaResource(
            filename="Interstellar.2014.IMAX.UHD.BluRay.REMUX.2160p.HEVC.DV.HDR.TrueHD.7.1.Atmos.mkv",
            path="电影/Interstellar.2014.IMAX.UHD.BluRay.REMUX.2160p.HEVC.DV.HDR.TrueHD.7.1.Atmos.mkv",
            source_id=1,
            size=1234,
            label="Movie - 2160P",
            tech_specs={
                "resolution": "2160P",
                "resolution_rank": 2160,
                "codec": "HEVC",
                "video_codec": "HEVC",
                "audio_codec": "Dolby TrueHD Atmos",
                "source": "Blu-ray Remux",
                "quality_tier": "reference",
                "quality_label": "4K Remux HDR",
                "hdr_format": "Dolby Vision",
                "tags": ["4K", "HDR", "Dolby Vision", "Atmos", "REMUX", "IMAX"],
                "features": {
                    "is_4k": True,
                    "is_hdr": True,
                    "is_dolby_vision": True,
                    "is_remux": True,
                    "is_original_quality": True,
                    "is_movie_feature": True,
                },
            },
        )

        data = resource.to_dict()

        self.assertEqual({"id", "resource_info", "playback", "metadata"}, set(data.keys()))
        self.assertEqual("Movie - 2160P", data["resource_info"]["display"]["label"])
        self.assertEqual("Interstellar.2014.IMAX.UHD.BluRay.REMUX.2160p.HEVC.DV.HDR.TrueHD.7.1.Atmos.mkv", data["resource_info"]["file"]["filename"])
        self.assertEqual("mkv", data["resource_info"]["file"]["container"])
        self.assertEqual("4k", data["resource_info"]["technical"]["video_resolution_bucket"])
        self.assertEqual("2160P", data["resource_info"]["technical"]["video_resolution_label"])
        self.assertEqual("dolby_vision", data["resource_info"]["technical"]["video_dynamic_range_code"])
        self.assertEqual("truehd_atmos", data["resource_info"]["technical"]["audio_codec_code"])
        self.assertEqual("7.1", data["resource_info"]["technical"]["audio_channels_label"])
        self.assertEqual(8, data["resource_info"]["technical"]["audio_channel_count"])
        self.assertTrue(data["resource_info"]["technical"]["audio_is_lossless"])
        self.assertEqual("Dolby TrueHD 7.1 Atmos", data["resource_info"]["technical"]["audio_summary_label"])
        self.assertEqual("uhd_bluray_remux", data["resource_info"]["technical"]["source_code"])
        self.assertEqual("UHD Blu-ray Remux", data["resource_info"]["technical"]["source_label"])
        self.assertTrue(data["resource_info"]["technical"]["source_is_uhd_bluray"])
        self.assertEqual("reference", data["resource_info"]["technical"]["quality_tier"])
        self.assertEqual(["IMAX"], data["resource_info"]["technical"]["extra_tags"])
        self.assertIn("external_player", data["playback"])
        self.assertEqual([], data["playback"]["subtitles"]["items"])

    def test_resource_to_dict_exposes_playback_matrix_for_external_players(self):
        source = StorageSource(
            id=1,
            name="AList",
            type="alist",
            config={"base_url": "http://alist.local:5244", "token": "token"},
        )
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Concert.2024.TrueHD.7.1.Atmos.mkv",
            path="演唱会/Concert.2024.TrueHD.7.1.Atmos.mkv",
            size=1234,
            label="Movie - 2160P",
            tech_specs={
                "resolution": "2160P",
                "resolution_rank": 2160,
                "audio_codec": "Dolby TrueHD Atmos",
            },
        )

        playback = resource.to_dict()["playback"]

        self.assertEqual("/api/v1/resources/11111111-1111-1111-1111-111111111111/stream", playback["stream_url"])
        self.assertEqual("redirect", playback["default_mode"])
        self.assertIn("redirect", playback["playback_modes"])
        self.assertTrue(playback["external_player"]["supported"])
        self.assertEqual(playback["stream_url"], playback["external_player"]["url"])
        self.assertEqual([], playback["external_player"]["subtitle_urls"])
        self.assertFalse(playback["subtitles"]["supported"])
        self.assertEqual("subtitle_api_not_implemented", playback["subtitles"]["reason"])
        self.assertEqual("unsupported", playback["audio"]["web_decode_status"])
        self.assertTrue(playback["audio"]["server_transcode"]["supported"])

    def test_resource_to_dict_upgrades_legacy_specs_from_filename(self):
        resource = MediaResource(
            filename="Avatar.The.Way.of.Water.2022.V2.UHD.BluRay.REMUX.2160p.HEVC.HDR.Atmos.TrueHD7.1.3Audio-DreamHD.mkv",
            path="电影/Avatar.The.Way.of.Water.2022.V2.UHD.BluRay.REMUX.2160p.HEVC.HDR.Atmos.TrueHD7.1.3Audio-DreamHD.mkv",
            source_id=1,
            size=83167237393,
            label="Movie - 2160P",
            tech_specs={
                "resolution": "2160P",
                "resolution_rank": 2160,
                "video_codec": "HEVC",
                "audio_codec": "Dolby Atmos",
                "source": "Blu-ray Remux",
                "quality_tier": "reference",
                "quality_label": "4K Remux HDR",
                "hdr_format": "HDR",
                "tags": ["4K", "HDR", "Atmos", "REMUX"],
                "features": {
                    "is_4k": True,
                    "is_hdr": True,
                    "is_remux": True,
                    "is_original_quality": True,
                    "is_movie_feature": True,
                },
            },
        )

        technical = resource.to_dict()["resource_info"]["technical"]

        self.assertEqual("uhd_bluray_remux", technical["source_code"])
        self.assertEqual("UHD Blu-ray Remux", technical["source_label"])
        self.assertEqual("hdr10", technical["video_dynamic_range_code"])
        self.assertEqual("HDR10", technical["video_dynamic_range_label"])
        self.assertEqual("truehd_atmos", technical["audio_codec_code"])
        self.assertEqual("7.1", technical["audio_channels_label"])
        self.assertEqual("Dolby TrueHD 7.1 Atmos", technical["audio_summary_label"])


if __name__ == "__main__":
    unittest.main()
