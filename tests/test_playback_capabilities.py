from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models import MediaResource, StorageSource
from backend.app.services.playback import (
    build_external_playback_manifest,
    build_resource_playback,
    guess_video_mime_type,
)


class PlaybackCapabilitiesTests(unittest.TestCase):
    def test_guess_video_mime_type_uses_resource_extension(self):
        cases = [
            ("movie.mp4", "video/mp4"),
            ("movie.mkv", "video/x-matroska"),
            ("movie.ts", "video/mp2t"),
            ("movie.m2ts", "video/mp2t"),
            ("movie.avi", "video/x-msvideo"),
            ("movie.iso", "application/octet-stream"),
        ]

        for filename, expected_mime in cases:
            with self.subTest(filename=filename):
                resource = MediaResource(filename=filename, path=f"movies/{filename}")
                self.assertEqual(expected_mime, guess_video_mime_type(resource))

    def test_hard_audio_requires_transcode_but_reports_missing_ffmpeg(self):
        source = StorageSource(id=1, name="AList", type="alist", config={})
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.TrueHD.7.1.Atmos.mkv",
            path="Movie.TrueHD.7.1.Atmos.mkv",
        )
        resource_info = {
            "technical": {
                "audio_codec_code": "truehd_atmos",
                "audio_summary_label": "Dolby TrueHD 7.1 Atmos",
            }
        }

        playback = build_resource_playback(resource, resource_info=resource_info, ffmpeg_available=False)

        self.assertEqual("redirect", playback["default_mode"])
        self.assertEqual("/api/v1/resources/11111111-1111-1111-1111-111111111111/stream", playback["stream_url"])
        self.assertTrue(playback["web_player"]["needs_server_audio_transcode"])
        self.assertEqual("unsupported", playback["audio"]["web_decode_status"])
        self.assertFalse(playback["audio"]["server_transcode"]["available"])
        self.assertEqual("ffmpeg_not_installed", playback["audio"]["server_transcode"]["reason"])
        self.assertIsNone(playback["audio"]["server_transcode"]["endpoint"])
        self.assertEqual("mp3", playback["audio"]["server_transcode"]["default_format"])
        self.assertEqual("audio/mpeg", playback["audio"]["server_transcode"]["mime_type"])
        self.assertEqual(2, playback["audio"]["server_transcode"]["channels"])
        self.assertEqual(48000, playback["audio"]["server_transcode"]["sample_rate"])
        self.assertTrue(playback["audio"]["server_transcode"]["requires_history_heartbeat"])
        self.assertEqual(180, playback["audio"]["server_transcode"]["history_timeout_seconds"])
        self.assertEqual("separate_audio_stream", playback["audio"]["server_transcode"]["mode"])
        self.assertEqual("forward_only", playback["audio"]["server_transcode"]["buffer_strategy"])
        self.assertEqual("use_buffered_audio_or_restart", playback["audio"]["server_transcode"]["seek_strategy"])
        self.assertFalse(playback["audio"]["server_transcode"]["frontend_should_rebuild_on_every_seek"])
        self.assertEqual([], playback["external_player"]["subtitle_urls"])
        self.assertEqual("subtitle_api_not_implemented", playback["subtitles"]["reason"])

    def test_hard_audio_exposes_transcode_endpoint_when_available(self):
        source = StorageSource(id=1, name="AList", type="alist", config={})
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.TrueHD.7.1.Atmos.mkv",
            path="Movie.TrueHD.7.1.Atmos.mkv",
        )
        resource_info = {
            "technical": {
                "audio_codec_code": "truehd_atmos",
                "audio_summary_label": "Dolby TrueHD 7.1 Atmos",
            }
        }

        playback = build_resource_playback(resource, resource_info=resource_info, ffmpeg_available=True)

        server_transcode = playback["audio"]["server_transcode"]
        self.assertTrue(server_transcode["available"])
        self.assertIsNone(server_transcode["reason"])
        self.assertEqual(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode",
            server_transcode["endpoint"],
        )
        self.assertEqual(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode?start=0&audio_track=0&format=mp3",
            server_transcode["url"],
        )
        self.assertTrue(server_transcode["seek_supported"])
        self.assertEqual("session_id", server_transcode["session_param"])
        self.assertEqual("video_audio_dual_element", server_transcode["sync_strategy"])

    def test_dolby_atmos_requires_server_audio_transcode(self):
        source = StorageSource(id=1, name="AList", type="alist", config={})
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.WEB-DL.DDP.7.1.Atmos.mkv",
            path="Movie.WEB-DL.DDP.7.1.Atmos.mkv",
        )
        resource_info = {
            "technical": {
                "audio_codec_code": "dolby_atmos",
                "audio_summary_label": "Dolby Atmos 7.1",
            }
        }

        playback = build_resource_playback(resource, resource_info=resource_info, ffmpeg_available=True)

        self.assertEqual("unsupported", playback["audio"]["web_decode_status"])
        self.assertTrue(playback["web_player"]["needs_server_audio_transcode"])
        self.assertTrue(playback["audio"]["server_transcode"]["available"])
        self.assertEqual(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode",
            playback["audio"]["server_transcode"]["endpoint"],
        )

    def test_unknown_audio_still_exposes_user_selectable_transcode_endpoint(self):
        source = StorageSource(id=1, name="AList", type="alist", config={})
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="蜘蛛侠.mkv",
            path="电影/蜘蛛侠.mkv",
        )
        resource_info = {
            "technical": {
                "audio_codec_code": "unknown",
                "audio_summary_label": "Unknown",
            }
        }

        playback = build_resource_playback(resource, resource_info=resource_info, ffmpeg_available=True)
        server_transcode = playback["audio"]["server_transcode"]

        self.assertEqual("unknown", playback["audio"]["web_decode_status"])
        self.assertFalse(playback["web_player"]["needs_server_audio_transcode"])
        self.assertFalse(server_transcode["recommended"])
        self.assertTrue(server_transcode["supported"])
        self.assertTrue(server_transcode["available"])
        self.assertIsNone(server_transcode["reason"])
        self.assertEqual(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/audio-transcode",
            server_transcode["endpoint"],
        )

    def test_likely_supported_audio_still_exposes_user_selectable_transcode_endpoint(self):
        source = StorageSource(id=1, name="AList", type="alist", config={})
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.mkv",
            path="Movie.mkv",
        )
        resource_info = {
            "technical": {
                "audio_codec_code": "aac",
                "audio_summary_label": "AAC 2.0",
            }
        }

        playback = build_resource_playback(resource, resource_info=resource_info, ffmpeg_available=True)

        self.assertEqual("likely_supported", playback["audio"]["web_decode_status"])
        self.assertFalse(playback["audio"]["server_transcode"]["recommended"])
        self.assertTrue(playback["audio"]["server_transcode"]["available"])

    def test_unknown_audio_reports_transcode_unavailable_when_ffmpeg_missing(self):
        source = StorageSource(id=1, name="AList", type="alist", config={})
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="蜘蛛侠.mkv",
            path="电影/蜘蛛侠.mkv",
        )

        playback = build_resource_playback(resource, resource_info={"technical": {}}, ffmpeg_available=False)

        self.assertFalse(playback["audio"]["server_transcode"]["available"])
        self.assertEqual("ffmpeg_not_installed", playback["audio"]["server_transcode"]["reason"])
        self.assertIsNone(playback["audio"]["server_transcode"]["endpoint"])

    def test_baidunetdisk_disables_web_playback_but_keeps_pc_handoff(self):
        source = StorageSource(
            id=1,
            name="Baidu",
            type="baidunetdisk",
            config={"auth_state": "ready", "download_api": "crack_video"},
        )
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.mkv",
            path="Movie.mkv",
        )

        playback = build_resource_playback(resource, resource_info={"technical": {}}, ffmpeg_available=True)

        self.assertEqual("baidunetdisk", playback["storage_type"])
        self.assertFalse(playback["web_player"]["supported"])
        self.assertIsNone(playback["web_player"]["url"])
        self.assertFalse(playback["web_player"]["range_supported"])
        self.assertEqual("baidunetdisk_requires_pc_client", playback["web_player"]["reason"])
        self.assertEqual("download_pc_client", playback["web_player"]["recommended_action"])
        self.assertIn("PC client", playback["web_player"]["message"])
        self.assertTrue(playback["external_player"]["supported"])
        self.assertTrue(playback["external_player"]["requires_local_backend"])
        self.assertTrue(playback["external_player"]["requires_user_agent_rewrite"])
        self.assertEqual(
            "baidunetdisk_requires_user_agent_rewrite",
            playback["external_player"]["reason"],
        )
        self.assertIn(
            "baidunetdisk_requires_pc_client",
            {warning["code"] for warning in playback["warnings"]},
        )

        manifest = build_external_playback_manifest(
            resource,
            resource_payload={"resource_info": {"technical": {}}, "playback": playback},
        )
        self.assertTrue(manifest["handoff"]["supported"])
        self.assertTrue(manifest["stream"]["requires_local_backend"])
        self.assertTrue(manifest["stream"]["requires_user_agent_rewrite"])
        self.assertEqual(
            "baidunetdisk_requires_user_agent_rewrite",
            manifest["stream"]["reason"],
        )

    def test_baidunetdisk_official_download_api_disables_pc_handoff(self):
        source = StorageSource(
            id=1,
            name="Baidu",
            type="baidunetdisk",
            config={"auth_state": "ready", "download_api": "official"},
        )
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.mkv",
            path="Movie.mkv",
        )

        playback = build_resource_playback(resource, resource_info={"technical": {}}, ffmpeg_available=True)

        self.assertFalse(playback["external_player"]["supported"])
        self.assertIsNone(playback["external_player"]["url"])
        self.assertFalse(playback["external_player"]["requires_user_agent_rewrite"])
        self.assertEqual(
            "baidunetdisk_official_download_api_sign_error",
            playback["external_player"]["reason"],
        )
        self.assertIn(
            "baidunetdisk_official_download_api_sign_error",
            {warning["code"] for warning in playback["warnings"]},
        )

        manifest = build_external_playback_manifest(
            resource,
            resource_payload={"resource_info": {"technical": {}}, "playback": playback},
        )
        self.assertFalse(manifest["handoff"]["supported"])
        self.assertIsNone(manifest["stream"]["url"])

    def test_quarktv_exposes_cloud_transcode_capability(self):
        source = StorageSource(
            id=1,
            name="QuarkTV",
            type="quarktv",
            config={
                "auth_state": "ready",
                "openlist_storage_id": 21,
                "mount_path": "/cyberstream/quarktv/fake",
            },
        )
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.mkv",
            path="Movies/Movie.mkv",
        )

        playback = build_resource_playback(resource, resource_info={"technical": {}}, ffmpeg_available=True)

        self.assertFalse(playback["web_player"]["supported"])
        self.assertIsNone(playback["web_player"]["url"])
        self.assertEqual("quark_uc_raw_download_not_web_playable", playback["web_player"]["reason"])
        self.assertEqual("use_cloud_transcode", playback["web_player"]["recommended_action"])
        self.assertTrue(playback["external_player"]["supported"])
        self.assertEqual(playback["stream_url"], playback["external_player"]["url"])
        self.assertTrue(playback["cloud_transcode"]["supported"])
        self.assertEqual("quarktv", playback["cloud_transcode"]["provider"])
        self.assertEqual(["web_player"], playback["cloud_transcode"]["recommended_for"])
        self.assertEqual(
            "provider_cloud_transcode_not_original_file",
            playback["cloud_transcode"]["quality_semantics"],
        )
        self.assertEqual(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/streaming-qualities",
            playback["cloud_transcode"]["qualities_endpoint"],
        )
        self.assertEqual(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/stream-transcoded",
            playback["cloud_transcode"]["stream_endpoint"],
        )
        self.assertIn("4k", playback["cloud_transcode"]["available_resolutions"])
        self.assertIn(
            "quark_uc_download_link_not_web_playable",
            {warning["code"] for warning in playback["warnings"]},
        )

    def test_aliyundrive_exposes_cloud_transcode_capability_without_disabling_raw_stream(self):
        source = StorageSource(
            id=1,
            name="Aliyundrive",
            type="aliyundrive",
            config={
                "auth_state": "ready",
                "openlist_storage_id": 33,
                "mount_path": "/cyberstream/aliyundrive/fake",
            },
        )
        resource = MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.mkv",
            path="Movies/Movie.mkv",
        )

        playback = build_resource_playback(resource, resource_info={"technical": {}}, ffmpeg_available=True)

        self.assertTrue(playback["web_player"]["supported"])
        self.assertEqual(playback["stream_url"], playback["web_player"]["url"])
        self.assertTrue(playback["cloud_transcode"]["supported"])
        self.assertEqual("aliyundrive", playback["cloud_transcode"]["provider"])
        self.assertEqual("Aliyundrive", playback["cloud_transcode"]["provider_name"])
        self.assertEqual(["web_player"], playback["cloud_transcode"]["recommended_for"])
        self.assertEqual(
            "provider_cloud_transcode_not_original_file",
            playback["cloud_transcode"]["quality_semantics"],
        )
        self.assertIn("fhd", playback["cloud_transcode"]["available_resolutions"])
        self.assertNotIn(
            "quark_uc_download_link_not_web_playable",
            {warning["code"] for warning in playback["warnings"]},
        )


if __name__ == "__main__":
    unittest.main()
