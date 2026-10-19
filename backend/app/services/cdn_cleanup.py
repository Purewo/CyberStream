from __future__ import annotations

from copy import deepcopy

from backend.app.extensions import db
from backend.app.models import MediaResource, Movie, ResourceSubtitle
from backend.app.services.cdn_assets import delete_file_from_supercdn
from backend.app.services.image_assets import IMAGE_KINDS, _load_metadata
from backend.app.services.jobs import job_manager


CDN_CLEANUP_JOB_TYPE = "cdn_asset_cleanup"


def _normalize_asset_reference(asset: dict) -> dict | None:
    if not isinstance(asset, dict):
        return None
    if str(asset.get("provider") or "supercdn").strip().lower() != "supercdn":
        return None

    bucket = str(asset.get("bucket") or "").strip()
    logical_path = str(asset.get("logical_path") or "").strip().strip("/")
    if not bucket or not logical_path:
        return None

    return {
        "provider": "supercdn",
        "bucket": bucket,
        "logical_path": logical_path,
        "asset_type": str(asset.get("asset_type") or "").strip() or None,
        "references": deepcopy(asset.get("references") or []),
    }


def _append_upload_reference(assets: dict, upload: dict | None, *, default_bucket: str | None, reference: dict):
    if not isinstance(upload, dict):
        return
    if str(upload.get("provider") or "").strip().lower() != "supercdn":
        return

    normalized = _normalize_asset_reference({
        "provider": "supercdn",
        "bucket": upload.get("bucket") or default_bucket,
        "logical_path": upload.get("logical_path"),
        "asset_type": upload.get("asset_type"),
        "references": [reference],
    })
    if not normalized:
        return

    key = (normalized["bucket"], normalized["logical_path"])
    existing = assets.get(key)
    if existing:
        existing["references"].append(reference)
        return
    assets[key] = normalized


def _append_subtitle_assets(assets: dict, resource, row):
    metadata = getattr(row, "subtitle_metadata", None) or {}
    cdn = metadata.get("cdn") if isinstance(metadata, dict) else None
    if not isinstance(cdn, dict) or str(cdn.get("provider") or "").strip().lower() != "supercdn":
        return

    default_bucket = cdn.get("bucket")
    for variant, upload in (cdn.get("assets") or {}).items():
        _append_upload_reference(
            assets,
            upload,
            default_bucket=default_bucket,
            reference={
                "kind": "resource_subtitle",
                "resource_id": str(resource.id),
                "subtitle_id": str(row.id),
                "variant": str(variant),
            },
        )


def _append_movie_image_assets(assets: dict, movie):
    for kind in sorted(IMAGE_KINDS):
        metadata = _load_metadata(movie.id, kind)
        upload = metadata.get("cdn") if isinstance(metadata, dict) else None
        _append_upload_reference(
            assets,
            upload,
            default_bucket=None,
            reference={
                "kind": "movie_image",
                "movie_id": str(movie.id),
                "image_kind": kind,
            },
        )


def collect_storage_source_cdn_assets(source_id: int, *, keep_metadata: bool = False) -> dict:
    if keep_metadata:
        return {
            "source_id": source_id,
            "assets": [],
            "asset_count": 0,
            "subtitle_asset_count": 0,
            "movie_image_asset_count": 0,
            "orphan_movie_ids": [],
            "skipped": True,
            "reason": "keep_metadata",
        }

    assets = {}
    resources = MediaResource.query.filter_by(source_id=source_id).all()
    movie_ids = {str(resource.movie_id) for resource in resources if resource.movie_id}

    for resource in resources:
        for row in ResourceSubtitle.query.filter_by(resource_id=resource.id).all():
            _append_subtitle_assets(assets, resource, row)

    orphan_movies = []
    for movie_id in sorted(movie_ids):
        remaining = [
            row
            for row in MediaResource.query.filter_by(movie_id=movie_id).all()
            if row.source_id != source_id
        ]
        if remaining:
            continue
        movie = db.session.get(Movie, movie_id)
        if not movie:
            continue
        orphan_movies.append(movie)
        _append_movie_image_assets(assets, movie)

    items = list(assets.values())
    subtitle_assets = sum(
        1
        for item in items
        if any(reference.get("kind") == "resource_subtitle" for reference in item["references"])
    )
    movie_image_assets = sum(
        1
        for item in items
        if any(reference.get("kind") == "movie_image" for reference in item["references"])
    )
    return {
        "source_id": source_id,
        "assets": items,
        "asset_count": len(items),
        "subtitle_asset_count": subtitle_assets,
        "movie_image_asset_count": movie_image_assets,
        "orphan_movie_ids": [str(movie.id) for movie in orphan_movies],
        "skipped": False,
        "reason": None,
    }


def execute_cdn_cleanup_assets(assets, *, delete_remote=True, progress_callback=None) -> dict:
    normalized = {}
    for asset in assets or []:
        item = _normalize_asset_reference(asset)
        if item:
            normalized[(item["bucket"], item["logical_path"])] = item

    items = list(normalized.values())
    results = []
    for index, asset in enumerate(items, start=1):
        if progress_callback:
            progress_callback(index - 1, len(items), f"Deleting CDN asset {index}/{len(items)}")
        result = delete_file_from_supercdn(
            asset["logical_path"],
            bucket=asset["bucket"],
            delete_remote=delete_remote,
        )
        result["references"] = asset["references"]
        results.append(result)

    if progress_callback:
        progress_callback(len(items), len(items), "CDN cleanup finished")

    deleted = sum(1 for item in results if item.get("status") == "deleted")
    not_found = sum(1 for item in results if item.get("status") == "not_found")
    failed = sum(1 for item in results if item.get("status") in {"failed", "partial"})
    status = "completed"
    if failed and deleted + not_found:
        status = "partial"
    elif failed:
        status = "failed"

    return {
        "status": status,
        "delete_remote": bool(delete_remote),
        "summary": {
            "total": len(results),
            "deleted": deleted,
            "not_found": not_found,
            "failed": failed,
        },
        "items": results,
    }


def enqueue_storage_source_cdn_cleanup(app, plan: dict) -> dict:
    assets = plan.get("assets") if isinstance(plan, dict) else None
    if plan.get("skipped"):
        return {
            "requested": True,
            "status": "skipped",
            "reason": plan.get("reason"),
            "queued": 0,
            "job_id": None,
        }
    if not assets:
        return {
            "requested": True,
            "status": "nothing_to_delete",
            "reason": None,
            "queued": 0,
            "job_id": None,
        }

    request_payload = {
        "source_id": plan.get("source_id"),
        "delete_remote": True,
        "assets": deepcopy(assets),
    }

    def run_cleanup(job_id):
        return execute_cdn_cleanup_assets(
            assets,
            delete_remote=True,
            progress_callback=lambda current, total, message: job_manager.update_progress(
                job_id,
                current=current,
                total=total,
                message=message,
            ),
        )

    job = job_manager.start(
        app,
        CDN_CLEANUP_JOB_TYPE,
        run_cleanup,
        title=f"Clean CDN assets for storage source {plan.get('source_id')}",
        request=request_payload,
    )
    return {
        "requested": True,
        "status": job.get("status") or "queued",
        "reason": None,
        "queued": len(assets),
        "job_id": job.get("id"),
    }


def no_cdn_cleanup_requested() -> dict:
    return {
        "requested": False,
        "status": "not_requested",
        "reason": None,
        "queued": 0,
        "job_id": None,
    }
