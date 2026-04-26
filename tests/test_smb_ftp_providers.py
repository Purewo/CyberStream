from __future__ import annotations

import io
import sys
import unittest
from unittest.mock import patch

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.providers.ftp import FTPProvider
from backend.app.providers.smb import SMBProvider


class FakeSMBEntry:
    def __init__(self, filename, is_dir, file_size=0):
        self.filename = filename
        self.isDirectory = is_dir
        self.file_size = file_size


class FakeSMBConnection:
    def __init__(self):
        self.closed = False

    def listPath(self, share, path, timeout=30):
        if path == "/movies":
            return [
                FakeSMBEntry(".", True),
                FakeSMBEntry("Movie A", True),
                FakeSMBEntry("Movie A.mkv", False, 123),
                FakeSMBEntry(".hidden", True),
            ]
        if path == "/movies/Movie A":
            return []
        raise FileNotFoundError(path)

    def getAttributes(self, share, path, timeout=30):
        if path in {"/movies", "/movies/Movie A"}:
            return FakeSMBEntry(path.rsplit("/", 1)[-1] or "movies", True)
        if path == "/movies/Movie A.mkv":
            return FakeSMBEntry("Movie A.mkv", False, 123)
        raise FileNotFoundError(path)

    def retrieveFile(self, share, path, buffer, timeout=30):
        buffer.write("nfo 内容".encode("utf-8"))

    def retrieveFileFromOffset(self, share, path, buffer, offset=0, max_length=-1, timeout=30):
        payload = b"0123456789"[offset: offset + max_length]
        buffer.write(payload)

    def close(self):
        self.closed = True


class FakeDataSocket:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0
        self.closed = False

    def recv(self, read_size):
        if self.offset >= len(self.payload):
            return b""
        chunk = self.payload[self.offset:self.offset + read_size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class FakeFTP:
    def __init__(self):
        self.cwd_path = "/"
        self.data_socket = None

    def connect(self, host, port, timeout=30):
        return "ok"

    def login(self, username, password):
        return "ok"

    def set_pasv(self, passive):
        return "ok"

    def prot_p(self):
        return "ok"

    def quit(self):
        return "ok"

    def close(self):
        return "ok"

    def mlsd(self, remote_path):
        if remote_path == "/videos":
            return iter(
                [
                    ("Movie B", {"type": "dir"}),
                    ("Movie B.mkv", {"type": "file", "size": "456"}),
                    (".hidden", {"type": "dir"}),
                ]
            )
        raise FileNotFoundError(remote_path)

    def pwd(self):
        return self.cwd_path

    def cwd(self, remote_path):
        if remote_path in {"/", "/videos", "/videos/Movie B"}:
            self.cwd_path = remote_path
            return "ok"
        raise FileNotFoundError(remote_path)

    def nlst(self):
        return []

    def size(self, remote_path):
        if remote_path == "/videos/Movie B.mkv":
            return 10
        raise FileNotFoundError(remote_path)

    def voidcmd(self, command):
        return "200"

    def retrbinary(self, command, callback):
        callback("ftp text".encode("utf-8"))

    def transfercmd(self, command, rest=None):
        payload = b"abcdefghij"
        if rest:
            payload = payload[rest:]
        self.data_socket = FakeDataSocket(payload)
        return self.data_socket

    def voidresp(self):
        return "226"


class SMBProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = SMBProvider(
            {
                "host": "nas.local",
                "share": "media",
                "root": "/movies",
            }
        )

    def test_list_items_filters_hidden_entries_and_keeps_relative_paths(self):
        with patch.object(self.provider, "_connect", return_value=FakeSMBConnection()):
            items = self.provider.list_items("")

        self.assertEqual(["Movie A", "Movie A.mkv"], [item["name"] for item in items])
        self.assertEqual("Movie A", items[0]["path"])
        self.assertTrue(items[0]["isdir"])
        self.assertEqual(123, items[1]["size"])

    def test_path_exists_only_accepts_directories(self):
        with patch.object(self.provider, "_connect", return_value=FakeSMBConnection()):
            self.assertTrue(self.provider.path_exists(""))
            self.assertTrue(self.provider.path_exists("Movie A"))
            self.assertFalse(self.provider.path_exists("Movie A.mkv"))
            self.assertFalse(self.provider.path_exists("missing"))

    def test_read_text(self):
        with patch.object(self.provider, "_connect", return_value=FakeSMBConnection()):
            text = self.provider.read_text("Movie A.nfo")

        self.assertEqual("nfo 内容", text)

    def test_stream_range(self):
        with patch.object(self.provider, "_connect", return_value=FakeSMBConnection()):
            stream, status, length, content_range = self.provider.get_stream_data("Movie A.mkv", "bytes=2-5")
            data = b"".join(stream)

        self.assertEqual(206, status)
        self.assertEqual(4, length)
        self.assertEqual("bytes 2-5/123", content_range)
        self.assertEqual(b"2345", data)


class FTPProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = FTPProvider(
            {
                "host": "ftp.example.com",
                "root": "/videos",
            }
        )

    def test_list_items_prefers_mlsd(self):
        with patch.object(self.provider, "_connect", return_value=FakeFTP()):
            items = self.provider.list_items("")

        self.assertEqual(["Movie B", "Movie B.mkv"], [item["name"] for item in items])
        self.assertEqual("Movie B", items[0]["path"])
        self.assertEqual(456, items[1]["size"])

    def test_path_exists_only_accepts_directories(self):
        with patch.object(self.provider, "_connect", return_value=FakeFTP()):
            self.assertTrue(self.provider.path_exists(""))
            self.assertTrue(self.provider.path_exists("Movie B"))
            self.assertFalse(self.provider.path_exists("Movie B.mkv"))
            self.assertFalse(self.provider.path_exists("missing"))

    def test_read_text(self):
        with patch.object(self.provider, "_connect", return_value=FakeFTP()):
            text = self.provider.read_text("Movie B.nfo")

        self.assertEqual("ftp text", text)

    def test_stream_range(self):
        with patch.object(self.provider, "_connect", side_effect=[FakeFTP(), FakeFTP()]):
            stream, status, length, content_range = self.provider.get_stream_data("Movie B.mkv", "bytes=3-6")
            data = b"".join(stream)

        self.assertEqual(206, status)
        self.assertEqual(4, length)
        self.assertEqual("bytes 3-6/10", content_range)
        self.assertEqual(b"defg", data)


if __name__ == "__main__":
    unittest.main()
