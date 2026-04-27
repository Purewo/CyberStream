import logging
import math
from datetime import datetime

from flask import Blueprint, current_app, request

from backend.app.api.helpers import build_history_item, build_pagination_meta
from backend.app.extensions import db
from backend.app.models import History, MediaResource, Movie
from backend.app.services.audio_transcode import (
    AudioTranscodeValidationError,
    DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
    parse_audio_transcode_session_id,
    record_audio_transcode_history_heartbeat,
)
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

history_bp = Blueprint('history', __name__, url_prefix='/api/v1')


def _get_json_payload():
    return request.get_json(silent=True) or {}


def _normalize_page_args():
    page = request.args.get('page', 1, type=int) or 1
    page_size = request.args.get('page_size', 20, type=int) or 20
    return max(page, 1), min(max(page_size, 1), 100)


def _coerce_non_negative_seconds(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a number")
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name} must be a non-negative number")
    return int(number)


def _normalize_optional_text(value, max_len=50):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _notify_audio_transcode_history_heartbeat(resource_id, payload):
    try:
        session_id = parse_audio_transcode_session_id(payload)
    except AudioTranscodeValidationError:
        session_id = None
    touched = record_audio_transcode_history_heartbeat(
        resource_id,
        session_id=session_id,
        inactive_timeout_seconds=current_app.config.get(
            "FFMPEG_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS",
            DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
        ),
    )
    if touched:
        logger.debug(
            "Audio transcode history heartbeat resource_id=%s session_id=%s touched=%s",
            resource_id,
            session_id,
            touched,
        )


@history_bp.route('/user/history', methods=['GET'])
def get_history():
    try:
        page, page_size = _normalize_page_args()
        query = History.query \
            .join(MediaResource, History.resource_id == MediaResource.id) \
            .join(Movie, MediaResource.movie_id == Movie.id) \
            .order_by(History.last_watched.desc(), History.id.desc())
        pagination = query.paginate(page=page, per_page=page_size, error_out=False)
        items = [item for item in (build_history_item(history_record) for history_record in pagination.items) if item]
        return api_response(data={
            "items": items,
            "pagination": build_pagination_meta(pagination, page, page_size)
        })
    except Exception as e:
        logger.exception("Get history failed error=%s", e)
        return api_error(code=50003, msg="Failed to get history", http_status=500)


@history_bp.route('/user/history', methods=['POST'])
def report_progress():
    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg="No input data")

    resource_id = payload.get('resource_id')
    position_sec = payload.get('position_sec')
    total_duration = payload.get('total_duration')
    device_id = payload.get('device_id')
    device_name = payload.get('device_name')
    if not resource_id or position_sec is None or total_duration is None:
        return api_error(code=40001, msg="Missing required fields: resource_id, position_sec, total_duration")

    try:
        resource = db.session.get(MediaResource, resource_id)
        if not resource:
            return api_error(code=40402, msg="Resource not found", http_status=404)

        try:
            position_sec = _coerce_non_negative_seconds(position_sec, 'position_sec')
            total_duration = _coerce_non_negative_seconds(total_duration, 'total_duration')
        except ValueError as e:
            return api_error(code=40002, msg=str(e))

        if total_duration > 0 and position_sec > total_duration:
            position_sec = total_duration

        device_id = _normalize_optional_text(device_id)
        device_name = _normalize_optional_text(device_name)
        history_records = History.query.filter_by(resource_id=resource_id) \
            .order_by(History.last_watched.desc(), History.id.desc()).all()
        history = history_records[0] if history_records else None

        if history:
            history.progress = position_sec
            history.duration = total_duration
            history.last_watched = datetime.utcnow()
            if device_id:
                history.device_id = device_id
            if device_name:
                history.device_name = device_name
        else:
            history = History(
                resource_id=resource_id,
                progress=position_sec,
                duration=total_duration,
                view_count=1,
                last_watched=datetime.utcnow(),
                device_id=device_id,
                device_name=device_name
            )
            db.session.add(history)

        for stale_history in history_records[1:]:
            db.session.delete(stale_history)

        db.session.commit()
        _notify_audio_transcode_history_heartbeat(resource_id, payload)
        return api_response(msg="Progress updated")
    except Exception as e:
        db.session.rollback()
        logger.exception("Report progress failed resource_id=%s error=%s", resource_id, e)
        return api_error(code=50004, msg="DB Error", http_status=500)


@history_bp.route('/user/history/<string:resource_id>', methods=['DELETE'])
def delete_history_item(resource_id):
    try:
        histories = History.query.filter_by(resource_id=resource_id).all()
        if not histories:
            return api_error(code=40401, msg="History not found", http_status=404)
        for history in histories:
            db.session.delete(history)
        db.session.commit()
        return api_response(msg="Deleted successfully")
    except Exception as e:
        db.session.rollback()
        logger.exception("Delete history failed resource_id=%s error=%s", resource_id, e)
        return api_error(code=50005, msg="DB Error", http_status=500)


@history_bp.route('/user/history', methods=['DELETE'])
def clear_all_history():
    try:
        db.session.query(History).delete()
        db.session.commit()
        return api_response(msg="History cleared")
    except Exception as e:
        db.session.rollback()
        logger.exception("Clear history failed error=%s", e)
        return api_error(code=50006, msg="DB Error", http_status=500)
