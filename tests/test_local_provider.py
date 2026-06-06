from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.providers.local import LocalProvider, LocalProviderPathError


class LocalProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.root = self.base / "library"
        self.outside = self.base / "outside"
        self.root.mkdir()
        self.outside.mkdir()
        (self.root / "movie.mkv").write_bytes(b"movie")
        (self.root / "movie.nfo").write_text("nfo text", encoding="utf-8")
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")
        self.provider = LocalProvider({"root_path": str(self.root)})

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_local_provider_serves_paths_inside_root(self):
        items = self.provider.list_items("")

        self.assertEqual(["movie.mkv", "movie.nfo"], sorted(item["name"] for item in items))
        self.assertEqual("nfo text", self.provider.read_text("movie.nfo"))
        stream, status, length, content_range = self.provider.get_stream_data("movie.mkv")
        self.assertEqual(200, status)
        self.assertEqual(5, length)
        self.assertEqual("bytes 0-4/5", content_range)
        self.assertEqual(b"movie", b"".join(stream))

    def test_local_provider_blocks_parent_directory_escape(self):
        escape_path = "../outside/secret.txt"

        self.assertEqual([], self.provider.list_items("../outside"))
        self.assertFalse(self.provider.path_exists("../outside"))
        self.assertIsNone(self.provider.read_text(escape_path))
        stream, status, length, content_range = self.provider.get_stream_data(escape_path)
        self.assertIsNone(stream)
        self.assertEqual(404, status)
        self.assertEqual(0, length)
        self.assertIsNone(content_range)
        with self.assertRaises(LocalProviderPathError):
            self.provider.get_ffmpeg_input(escape_path)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink is not supported")
    def test_local_provider_blocks_symlink_escape(self):
        link_path = self.root / "outside-link"
        try:
            os.symlink(self.outside, link_path)
        except OSError as exc:
            self.skipTest(f"symlink unavailable: {exc}")

        self.assertEqual([], self.provider.list_items("outside-link"))
        self.assertFalse(self.provider.path_exists("outside-link"))
        self.assertIsNone(self.provider.read_text("outside-link/secret.txt"))
        stream, status, _length, _content_range = self.provider.get_stream_data(
            "outside-link/secret.txt"
        )
        self.assertIsNone(stream)
        self.assertEqual(404, status)

    def test_local_provider_health_reports_escape_as_offline(self):
        result = self.provider.health_check("../outside")

        self.assertEqual("offline", result["status"])
        self.assertFalse(result["path_exists"])
        self.assertEqual("Path escapes storage root", result["error"])


if __name__ == "__main__":
    unittest.main()
