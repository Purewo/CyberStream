from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from backend.app.extensions import db
from backend.app.models import ReviewSnapshotItem, ReviewSnapshotState, ReviewSnapshotSummary
from backend.app.services.accounts import current_account_id


BUCKET_RESOURCE_GOVERNANCE = "resource_governance"
BUCKET_METADATA_QUALITY = "metadata_quality"
BUCKET_EPISODE_REVIEW = "episode_review"
BUCKET_OTHER_VIDEOS_ARCHIVE = "other_videos_archive"
BUCKET_PENDING_REVIEW = "pending_review"

ALL_REVIEW_SNAPSHOT_BUCKETS = (
    BUCKET_RESOURCE_GOVERNANCE,
    BUCKET_METADATA_QUALITY,
    BUCKET_EPISODE_REVIEW,
    BUCKET_OTHER_VIDEOS_ARCHIVE,
    BUCKET_PENDING_REVIEW,
)


def new_review_snapshot_revision(bucket):
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    return f"{bucket}:{timestamp}:{uuid4().hex[:8]}"


def _account_filtered_query(model):
    query = model.query.execution_options(include_all_accounts=True)
    account_id = current_account_id()
    if account_id:
        return query.filter(model.account_id == account_id)
    return query.filter(model.account_id.is_(None))


def _bucket_query(model, bucket):
    return _account_filtered_query(model).filter(model.bucket == bucket)


def get_review_snapshot_state(bucket):
    with db.session.no_autoflush:
        return _bucket_query(ReviewSnapshotState, bucket).order_by(ReviewSnapshotState.id.asc()).first()


def get_or_create_review_snapshot_state(bucket):
    state = get_review_snapshot_state(bucket)
    if state:
        return state

    now = datetime.utcnow()
    state = ReviewSnapshotState(
        account_id=current_account_id(),
        bucket=bucket,
        revision="",
        rebuilding=False,
        stale=True,
        item_count=0,
        created_at=now,
        updated_at=now,
    )
    db.session.add(state)
    return state


def get_review_snapshot_meta(bucket):
    state = get_review_snapshot_state(bucket)
    if not state:
        return {
            "revision": None,
            "updated_at": None,
            "rebuilding": False,
            "stale": True,
            "item_count": 0,
            "error": None,
        }
    return state.to_meta()


def attach_review_snapshot_meta(payload, bucket):
    payload.update(get_review_snapshot_meta(bucket))
    return payload


def review_snapshot_has_items(bucket):
    with db.session.no_autoflush:
        return _bucket_query(ReviewSnapshotItem, bucket).limit(1).first() is not None


def review_snapshot_needs_rebuild(bucket):
    state = get_review_snapshot_state(bucket)
    if not state:
        return True
    if state.rebuilding:
        return False
    if state.stale:
        return not review_snapshot_has_items(bucket)
    return not review_snapshot_has_items(bucket) and int(state.item_count or 0) > 0


def mark_review_snapshots_stale(buckets=None):
    selected = tuple(buckets or ALL_REVIEW_SNAPSHOT_BUCKETS)
    now = datetime.utcnow()
    for bucket in selected:
        state = get_or_create_review_snapshot_state(bucket)
        state.stale = True
        state.rebuilding = False
        state.error = None
        state.updated_at = now


def mark_review_snapshot_rebuilding(bucket):
    state = get_or_create_review_snapshot_state(bucket)
    state.rebuilding = True
    state.stale = True
    state.error = None
    state.updated_at = datetime.utcnow()
    return state


def mark_review_snapshot_error(bucket, error):
    state = get_or_create_review_snapshot_state(bucket)
    state.rebuilding = False
    state.stale = True
    state.error = str(error)[:2000]
    state.updated_at = datetime.utcnow()


def replace_review_snapshot(bucket, items, summaries=None, revision=None):
    revision = revision or new_review_snapshot_revision(bucket)
    now = datetime.utcnow()
    account_id = current_account_id()
    state = get_or_create_review_snapshot_state(bucket)

    _bucket_query(ReviewSnapshotItem, bucket).delete(synchronize_session=False)
    _bucket_query(ReviewSnapshotSummary, bucket).delete(synchronize_session=False)

    for item in items:
        db.session.add(ReviewSnapshotItem(
            account_id=account_id,
            bucket=bucket,
            entity_type=item.get("entity_type") or "item",
            entity_id=str(item.get("entity_id") or ""),
            issue_code=item.get("issue_code"),
            issue_codes=item.get("issue_codes") or [],
            issue_codes_text=item.get("issue_codes_text") or "",
            severity=item.get("severity"),
            status=item.get("status"),
            source_group=item.get("source_group"),
            review_priority=item.get("review_priority"),
            source_id=item.get("source_id"),
            movie_id=item.get("movie_id"),
            sort_key=item.get("sort_key") or "",
            search_text=item.get("search_text") or "",
            payload=item.get("payload") or {},
            revision=revision,
            created_at=now,
            updated_at=now,
        ))

    for summary in summaries or []:
        db.session.add(ReviewSnapshotSummary(
            account_id=account_id,
            bucket=bucket,
            summary_key=summary.get("summary_key") or "",
            count=int(summary.get("count") or 0),
            payload=summary.get("payload") or {},
            revision=revision,
            created_at=now,
            updated_at=now,
        ))

    state.revision = revision
    state.rebuilding = False
    state.stale = False
    state.item_count = len(items)
    state.error = None
    state.updated_at = now
    db.session.flush()
    return state


def review_snapshot_items_query(bucket):
    return _bucket_query(ReviewSnapshotItem, bucket)


def review_snapshot_summaries_query(bucket):
    return _bucket_query(ReviewSnapshotSummary, bucket)


def issue_codes_text(codes):
    normalized = [
        str(code).strip()
        for code in (codes or [])
        if str(code or "").strip()
    ]
    if not normalized:
        return ""
    return "|" + "|".join(sorted(set(normalized))) + "|"


def pagination_dict(total, page, page_size):
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "current_page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": total_pages,
    }
