from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.services.online_subtitle_providers import srtku_core, subhd_core


class FakeResponse:
    def __init__(self, *, body=b"", text="", payload=None, status_code=200, headers=None):
        self.body = body
        self.text = text
        self.payload = payload
        self.status_code = status_code
        self.reason = "OK"
        self.headers = dict(headers or {})
        self.closed = False

    def json(self):
        if self.payload is None:
            raise ValueError("missing payload")
        return self.payload

    def iter_content(self, chunk_size=64 * 1024):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSubhdSession:
    def __init__(self, download_response):
        self.download_response = download_response
        self.get_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if "/a/" in url:
            return FakeResponse(text="<html></html>")
        if "/down/" in url:
            return FakeResponse(text='<button class="down" sid="sid-1"></button>')
        return self.download_response

    def post(self, url, **kwargs):
        return FakeResponse(payload={
            "success": True,
            "pass": True,
            "url": "https://cdn.example/subtitle.zip",
        })


class FakeSrtkuSession:
    def __init__(self, response):
        self.response = response
        self.cookies = {}
        self.get_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.response


class OnlineSubtitleProviderDownloadLimitTests(unittest.TestCase):
    def test_subhd_stops_before_reading_oversized_content_length(self):
        response = FakeResponse(
            body=b"x" * 1024,
            headers={
                "Content-Type": "application/zip",
                "Content-Length": "1024",
            },
        )
        session = FakeSubhdSession(response)

        result = subhd_core.download_subtitle(
            "candidate",
            session=session,
            max_retries=1,
            max_bytes=8,
        )

        self.assertFalse(result["success"])
        self.assertEqual("download_too_large", result["reason"])
        self.assertTrue(response.closed)
        self.assertTrue(session.get_calls[-1][1]["stream"])

    def test_srtku_stops_streaming_and_removes_partial_oversized_file(self):
        response = FakeResponse(
            body=b"x" * 1024,
            headers={"Content-Type": "application/octet-stream"},
        )
        session = FakeSrtkuSession(response)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = srtku_core.download_subtitle(
                "https://cdn.example/feature.srt",
                outdir=tmpdir,
                session=session,
                retries=1,
                auto_extract=False,
                max_bytes=8,
            )

            self.assertEqual([], list(Path(tmpdir).iterdir()))

        self.assertFalse(result["ok"])
        self.assertEqual("download_too_large", result["error"])
        self.assertTrue(response.closed)
        self.assertTrue(session.get_calls[0][1]["stream"])

    def test_srtku_confines_content_disposition_filename_to_output_directory(self):
        response = FakeResponse(
            body=b"x" * 128,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="../outside.srt"',
            },
        )
        session = FakeSrtkuSession(response)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outdir = root / "downloads"
            result = srtku_core.download_subtitle(
                "https://cdn.example/download",
                outdir=str(outdir),
                session=session,
                retries=1,
                auto_extract=False,
                max_bytes=1024,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(outdir / "outside.srt", Path(result["saved_path"]))
            self.assertFalse((root / "outside.srt").exists())


if __name__ == "__main__":
    unittest.main()
