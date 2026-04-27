from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.api.storage_routes import _normalize_storage_config
from backend.app.extensions import db
from backend.app.models import StorageSource


class StorageProtocolSupportTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_normalize_smb_config_supports_defaults(self):
        config, error = _normalize_storage_config(
            "smb",
            {
                "host": "nas.local",
                "share": "videos",
                "username": " demo ",
                "password": "secret",
                "root": "电影/蓝光",
                "port": "445",
            },
        )

        self.assertIsNone(error)
        self.assertEqual("nas.local", config["host"])
        self.assertEqual("videos", config["share"])
        self.assertEqual("demo", config["username"])
        self.assertEqual("/电影/蓝光", config["root"])
        self.assertEqual(445, config["port"])
        self.assertEqual(30, config["timeout"])
        self.assertEqual("nas.local", config["remote_name"])

    def test_normalize_ftp_config_supports_defaults(self):
        config, error = _normalize_storage_config(
            "ftp",
            {
                "host": "ftp.example.com",
                "user": " uploader ",
                "password": "pass",
                "root": "movies",
                "secure": "true",
                "passive": "false",
                "port": "2121",
            },
        )

        self.assertIsNone(error)
        self.assertEqual("ftp.example.com", config["host"])
        self.assertEqual("uploader", config["username"])
        self.assertEqual("pass", config["password"])
        self.assertEqual("/movies", config["root"])
        self.assertTrue(config["secure"])
        self.assertFalse(config["passive"])
        self.assertEqual(2121, config["port"])
        self.assertEqual(30, config["timeout"])

    def test_storage_capabilities_include_smb_and_ftp(self):
        response = self.client.get("/api/v1/storage/capabilities")
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        supported_types = payload["data"]["supported_types"]
        self.assertIn("smb", supported_types)
        self.assertIn("ftp", supported_types)

        items_by_type = {
            item["type"]: item
            for item in payload["data"]["items"]
        }
        self.assertTrue(items_by_type["smb"]["browse"])
        self.assertTrue(items_by_type["smb"]["range_stream"])
        self.assertEqual("root", items_by_type["smb"]["config_root_key"])
        self.assertTrue(items_by_type["ftp"]["stream"])
        self.assertTrue(items_by_type["ftp"]["library_root_path"])
        self.assertTrue(items_by_type["alist"]["redirect_stream"])
        self.assertTrue(items_by_type["openlist"]["browse"])

    def test_add_source_accepts_smb(self):
        response = self.client.post(
            "/api/v1/storage/sources",
            json={
                "name": "NAS SMB",
                "type": "smb",
                "config": {
                    "host": "nas.local",
                    "share": "media",
                    "root": "/电影",
                },
            },
        )
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        data = payload["data"]
        self.assertEqual("smb", data["type"])
        self.assertEqual(r"\\nas.local\media\电影", data["root_path"])
        source = StorageSource.query.first()
        self.assertEqual("/电影", source.config["root"])

    def test_add_source_accepts_ftp(self):
        response = self.client.post(
            "/api/v1/storage/sources",
            json={
                "name": "FTP Source",
                "type": "ftp",
                "config": {
                    "host": "ftp.example.com",
                    "root": "/videos",
                },
            },
        )
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        data = payload["data"]
        self.assertEqual("ftp", data["type"])
        self.assertEqual("ftp://ftp.example.com:21/videos", data["root_path"])
        source = StorageSource.query.first()
        self.assertEqual("anonymous", source.config["username"])
        self.assertEqual("anonymous@", source.config["password"])

    def test_preview_rejects_invalid_smb_config(self):
        response = self.client.post(
            "/api/v1/storage/preview",
            json={
                "type": "smb",
                "config": {
                    "host": "nas.local",
                },
            },
        )
        payload = response.get_json()

        self.assertEqual(400, response.status_code)
        self.assertEqual(40007, payload["code"])

    def test_normalize_alist_config_supports_base_url_and_token(self):
        config, error = _normalize_storage_config(
            "alist",
            {
                "base_url": " https://alist.example.com/ ",
                "token": " token ",
                "root": "媒体",
                "proxy_stream": "true",
            },
        )

        self.assertIsNone(error)
        self.assertEqual("https://alist.example.com", config["base_url"])
        self.assertEqual("", config["host"])
        self.assertEqual("/媒体", config["root"])
        self.assertEqual("token", config["token"])
        self.assertTrue(config["proxy_stream"])
        self.assertFalse(config["verify_ssl"])
        self.assertEqual(5244, config["port"])

    def test_normalize_openlist_config_normalizes_root_and_base_url(self):
        config, error = _normalize_storage_config(
            "openlist",
            {
                "base_url": " https://openlist.example.com/base/ ",
                "token": "token",
                "root": "媒体/电影",
            },
        )

        self.assertIsNone(error)
        self.assertEqual("https://openlist.example.com/base", config["base_url"])
        self.assertEqual("", config["host"])
        self.assertEqual("/媒体/电影", config["root"])

    def test_add_source_accepts_openlist(self):
        response = self.client.post(
            "/api/v1/storage/sources",
            json={
                "name": "OpenList Source",
                "type": "openlist",
                "config": {
                    "host": "openlist.local",
                    "secure": True,
                    "root": "/media",
                    "token": "token",
                },
            },
        )
        payload = response.get_json()

        self.assertEqual(200, response.status_code)
        data = payload["data"]
        self.assertEqual("openlist", data["type"])
        self.assertEqual("https://openlist.local:5244/media", data["root_path"])
        source = StorageSource.query.first()
        self.assertEqual("/media", source.config["root"])
        self.assertEqual("token", source.config["token"])

    def test_update_source_normalizes_alist_config_like_create(self):
        source = StorageSource(
            name="AList Source",
            type="alist",
            config={
                "base_url": "https://alist.example.com",
                "token": "token",
                "root": "/",
            },
        )
        db.session.add(source)
        db.session.commit()

        response = self.client.patch(
            f"/api/v1/storage/sources/{source.id}",
            json={
                "config": {
                    "base_url": "https://alist.example.com/",
                    "token": "token",
                    "root": "电影/华语",
                },
            },
        )

        self.assertEqual(200, response.status_code)
        refreshed = db.session.get(StorageSource, source.id)
        self.assertEqual("https://alist.example.com", refreshed.config["base_url"])
        self.assertEqual("/电影/华语", refreshed.config["root"])
        self.assertEqual("", refreshed.config["host"])


if __name__ == "__main__":
    unittest.main()
