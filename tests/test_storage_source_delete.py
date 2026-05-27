from __future__ import annotations

import sys
import unittest

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import (
    HomepageSetting,
    History,
    Library,
    LibraryMovieMembership,
    LibrarySource,
    MediaResource,
    Movie,
    MovieMetadataLock,
    MovieSeasonMetadata,
    ResourceSubtitle,
    ResourceSubtitleSetting,
    StorageSource,
    UserFavorite,
)


class StorageSourceDeleteTests(unittest.TestCase):
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

    def _set_pin(self, pin="123456"):
        response = self.client.post("/api/v1/user/vault/password", json={"pin": pin})
        self.assertEqual(200, response.status_code)

    def _source(self, name="Local"):
        source = StorageSource(name=name, type="local", config={"root_path": "/tmp/media"})
        db.session.add(source)
        db.session.flush()
        return source

    def _library(self, source, root_path="movies"):
        library = Library(name=f"Library {source.id}", slug=f"library-{source.id}")
        db.session.add(library)
        db.session.flush()
        db.session.add(LibrarySource(library_id=library.id, source_id=source.id, root_path=root_path))
        db.session.flush()
        return library

    def _movie_with_resource(self, source, path="movies/Show.S01E01.mkv"):
        movie = Movie(
            tmdb_id=f"tv/{source.id}",
            title=f"Show {source.id}",
            original_title=f"Show {source.id}",
            year=2024,
            cover="poster",
            scraper_source="TMDB",
        )
        db.session.add(movie)
        db.session.flush()
        resource = MediaResource(
            movie_id=movie.id,
            source_id=source.id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            season=1,
            episode=1,
        )
        db.session.add(resource)
        db.session.flush()
        return movie, resource

    def test_delete_source_with_dependents_requires_configured_vault_pin(self):
        source = self._source()
        self._library(source)
        movie, resource = self._movie_with_resource(source)
        db.session.commit()

        source_payload = db.session.get(StorageSource, source.id).to_dict()
        self.assertTrue(source_payload["guards"]["can_delete"])
        self.assertFalse(source_payload["guards"]["can_delete_directly"])
        self.assertTrue(source_payload["guards"]["requires_pin_on_delete"])

        response = self.client.delete(f"/api/v1/storage/sources/{source.id}")

        self.assertEqual(403, response.status_code)
        self.assertEqual(40341, response.get_json()["code"])
        self.assertIsNotNone(db.session.get(StorageSource, source.id))
        self.assertIsNotNone(db.session.get(Movie, movie.id))
        self.assertIsNotNone(db.session.get(MediaResource, resource.id))

    def test_delete_source_with_wrong_pin_does_not_delete_dependents(self):
        self._set_pin()
        source = self._source()
        self._library(source)
        movie, resource = self._movie_with_resource(source)
        db.session.commit()

        response = self.client.delete(f"/api/v1/storage/sources/{source.id}", json={"pin": "654321"})

        self.assertEqual(403, response.status_code)
        self.assertEqual(40344, response.get_json()["code"])
        self.assertIsNotNone(db.session.get(StorageSource, source.id))
        self.assertIsNotNone(db.session.get(Movie, movie.id))
        self.assertIsNotNone(db.session.get(MediaResource, resource.id))

    def test_delete_source_with_pin_removes_bindings_resources_and_orphan_movie(self):
        self._set_pin()
        source = self._source()
        library = self._library(source)
        movie, resource = self._movie_with_resource(source)
        db.session.add_all([
            LibraryMovieMembership(library_id=library.id, movie_id=movie.id),
            UserFavorite(scope_key="default", movie_id=movie.id),
            MovieMetadataLock(movie_id=movie.id, locked_fields=["title"]),
            MovieSeasonMetadata(movie_id=movie.id, season=1, title="Season 1", episode_count=1),
            History(resource_id=resource.id, progress=30, duration=100),
            ResourceSubtitle(
                resource_id=resource.id,
                source="online",
                provider_id="sub",
                provider_name="Sub",
                candidate_id="sub-1",
                filename="sub.srt",
                storage_kind="cache",
                storage_path="/tmp/sub.srt",
                format="srt",
                mime_type="text/plain",
            ),
            ResourceSubtitleSetting(resource_id=resource.id),
            HomepageSetting(hero_movie_id=movie.id, sections=[{"id": "hero", "movie_ids": [movie.id]}]),
        ])
        db.session.commit()
        source_id = source.id
        movie_id = movie.id
        resource_id = resource.id

        response = self.client.delete(f"/api/v1/storage/sources/{source_id}", json={"pin": "123456"})

        self.assertEqual(200, response.status_code)
        self.assertIsNone(db.session.get(StorageSource, source_id))
        self.assertIsNone(db.session.get(MediaResource, resource_id))
        self.assertIsNone(db.session.get(Movie, movie_id))
        self.assertEqual(0, LibrarySource.query.filter_by(source_id=source_id).count())
        self.assertEqual(0, LibraryMovieMembership.query.filter_by(movie_id=movie_id).count())
        self.assertEqual(0, UserFavorite.query.filter_by(movie_id=movie_id).count())
        self.assertEqual(0, MovieMetadataLock.query.filter_by(movie_id=movie_id).count())
        self.assertEqual(0, MovieSeasonMetadata.query.filter_by(movie_id=movie_id).count())
        self.assertEqual(0, History.query.filter_by(resource_id=resource_id).count())
        self.assertEqual(0, ResourceSubtitle.query.filter_by(resource_id=resource_id).count())
        self.assertEqual(0, ResourceSubtitleSetting.query.filter_by(resource_id=resource_id).count())
        setting = HomepageSetting.query.first()
        self.assertIsNone(setting.hero_movie_id)
        self.assertEqual([], setting.sections[0]["movie_ids"])

    def test_delete_source_preserves_movie_that_still_has_other_source_resources(self):
        self._set_pin()
        source_a = self._source("A")
        source_b = self._source("B")
        library = self._library(source_a)
        db.session.add(LibrarySource(library_id=library.id, source_id=source_b.id, root_path="backup"))
        movie, resource_a = self._movie_with_resource(source_a, path="movies/Shared.S01E01.mkv")
        resource_b = MediaResource(
            movie_id=movie.id,
            source_id=source_b.id,
            path="backup/Shared.S01E01.mkv",
            filename="Shared.S01E01.mkv",
            season=1,
            episode=1,
        )
        db.session.add_all([
            resource_b,
            LibraryMovieMembership(library_id=library.id, movie_id=movie.id),
        ])
        db.session.commit()

        response = self.client.delete(f"/api/v1/storage/sources/{source_a.id}", json={"pin": "123456"})

        self.assertEqual(200, response.status_code)
        self.assertIsNone(db.session.get(StorageSource, source_a.id))
        self.assertIsNone(db.session.get(MediaResource, resource_a.id))
        self.assertIsNotNone(db.session.get(StorageSource, source_b.id))
        self.assertIsNotNone(db.session.get(MediaResource, resource_b.id))
        self.assertIsNotNone(db.session.get(Movie, movie.id))
        self.assertEqual(1, LibraryMovieMembership.query.filter_by(movie_id=movie.id).count())
        self.assertEqual(0, LibrarySource.query.filter_by(source_id=source_a.id).count())
        self.assertEqual(1, LibrarySource.query.filter_by(source_id=source_b.id).count())

    def test_keep_metadata_delete_removes_bindings_and_leaves_offline_resource(self):
        source = self._source()
        self._library(source)
        movie, resource = self._movie_with_resource(source)
        db.session.commit()

        response = self.client.delete(
            f"/api/v1/storage/sources/{source.id}",
            json={"keepMetadata": True},
        )

        self.assertEqual(200, response.status_code)
        self.assertIsNone(db.session.get(StorageSource, source.id))
        self.assertEqual(0, LibrarySource.query.filter_by(source_id=source.id).count())
        self.assertIsNotNone(db.session.get(Movie, movie.id))
        refreshed_resource = db.session.get(MediaResource, resource.id)
        self.assertIsNotNone(refreshed_resource)
        self.assertIsNone(refreshed_resource.source_id)


if __name__ == "__main__":
    unittest.main()
