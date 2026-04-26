from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models import MediaResource, StorageSource
from backend.app.services.playback import build_resource_playback, guess_video_mime_type


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
        self.assertEqual([], playback["external_player"]["subtitle_urls"])
        self.assertEqual("subtitle_api_not_implemented", playback["subtitles"]["reason"])


if __name__ == "__main__":
    unittest.main()
