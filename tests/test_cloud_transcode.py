from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models import MediaResource, StorageSource
from backend.app.services.cloud_transcode import (
    AliyundriveCloudTranscodeClient,
    CloudTranscodeError,
    build_streaming_qualities,
)


class FakeOpenListClient:
    timeout = 30

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def fs_other(self, path, method, data=None):
        self.calls.append({"path": path, "method": method, "data": data})
        return self.payload


class AliyundriveCloudTranscodeTests(unittest.TestCase):
    def _resource(self):
        source = StorageSource(
            id=1,
            name="Aliyundrive",
            type="aliyundrive",
            config={
                "auth_state": "ready",
                "openlist_storage_id": 33,
                "mount_path": "/cyberstream/aliyundrive/demo",
            },
        )
        return MediaResource(
            id="11111111-1111-1111-1111-111111111111",
            source=source,
            filename="Movie.mkv",
            path="Movies/Movie.mkv",
        )

    def test_aliyundrive_video_preview_returns_cloud_transcode_items(self):
        payload = {
            "video_preview_play_info": {
                "live_transcoding_task_list": [
                    {
                        "template_id": "LD",
                        "template_name": "LD",
                        "status": "finished",
                        "url": "https://provider.example/ld.m3u8",
                        "height": 360,
                    },
                    {
                        "template_id": "HD",
                        "template_name": "HD",
                        "status": "finished",
                        "url": "https://provider.example/hd.m3u8",
                        "height": 720,
                    },
                ],
            }
        }
        fake_openlist = FakeOpenListClient(payload)
        client = AliyundriveCloudTranscodeClient(openlist_client=fake_openlist)

        data = client.get_resource_streaming_qualities(self._resource(), selected_resolution="hd")

        self.assertEqual("aliyundrive", data["storage_type"])
        self.assertEqual("Aliyundrive", data["provider"])
        self.assertEqual("hd", data["selected_resolution"])
        self.assertEqual("https://provider.example/hd.m3u8", data["selected_item"]["url"])
        self.assertEqual(["ld", "hd"], [item["resolution"] for item in data["items"]])
        self.assertEqual(
            "/api/v1/resources/11111111-1111-1111-1111-111111111111/stream-transcoded?resolution=hd",
            data["selected_item"]["stream_url"],
        )
        self.assertEqual(
            [{"path": "/cyberstream/aliyundrive/demo/Movies/Movie.mkv", "method": "video_preview", "data": None}],
            fake_openlist.calls,
        )

    def test_aliyundrive_selection_rejects_unavailable_resolution(self):
        payload = {
            "video_preview_play_info": {
                "live_transcoding_task_list": [
                    {
                        "template_id": "HD",
                        "template_name": "HD",
                        "status": "finished",
                        "url": "https://provider.example/hd.m3u8",
                    },
                ],
            }
        }
        client = AliyundriveCloudTranscodeClient(openlist_client=FakeOpenListClient(payload))

        with self.assertRaises(CloudTranscodeError) as ctx:
            client.get_resource_streaming_qualities(self._resource(), selected_resolution="fhd")

        self.assertEqual(40913, ctx.exception.code)

    def test_build_streaming_qualities_dispatches_aliyundrive(self):
        payload = {
            "data": {
                "video_preview_play_info": {
                    "live_transcoding_task_list": [
                        {
                            "template_id": "FHD",
                            "template_name": "FHD",
                            "status": "finished",
                            "url": "https://provider.example/fhd.m3u8",
                            "height": 1080,
                        },
                    ],
                }
            }
        }
        fake_openlist = FakeOpenListClient(payload)

        original_init = AliyundriveCloudTranscodeClient.__init__
        try:
            AliyundriveCloudTranscodeClient.__init__ = lambda self: setattr(self, "openlist_client", fake_openlist)
            data = build_streaming_qualities(self._resource())
        finally:
            AliyundriveCloudTranscodeClient.__init__ = original_init

        self.assertEqual("fhd", data["selected_resolution"])


if __name__ == "__main__":
    unittest.main()
