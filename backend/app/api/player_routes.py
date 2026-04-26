import logging
import mimetypes
import os

from flask import Blueprint, Response, redirect, request, stream_with_context

from backend.app.extensions import db
from backend.app.models import MediaResource
from backend.app.providers.factory import provider_factory

logger = logging.getLogger(__name__)

player_bp = Blueprint('player', __name__, url_prefix='/api/v1')

VIDEO_MIME_TYPES = {
    '.mp4': 'video/mp4',
    '.m4v': 'video/mp4',
    '.mkv': 'video/x-matroska',
    '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    '.ts': 'video/mp2t',
    '.m2ts': 'video/mp2t',
    '.iso': 'application/octet-stream',
    '.rmvb': 'application/vnd.rn-realmedia-vbr',
}


def _guess_video_mime_type(resource):
    filename = resource.filename or resource.path or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext in VIDEO_MIME_TYPES:
        return VIDEO_MIME_TYPES[ext]
    guessed_type, _ = mimetypes.guess_type(filename)
    return guessed_type or 'application/octet-stream'


@player_bp.route('/resources/<uuid:id>/stream', methods=['GET'])
def stream_resource(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        logger.warning("Stream resource not found id=%s", id)
        return Response("Resource not found", status=404)

    source = resource.source
    if not source:
        logger.error("Stream storage source missing resource_id=%s", id)
        return Response("Storage Source Missing", status=500)

    try:
        logger.info("Stream start filename=%s source_type=%s", resource.filename, source.type)
        provider = provider_factory.get_provider(source)

        range_header = request.headers.get('Range')

        # data_iter: 流生成器
        # status: HTTP状态码 (200, 206, 302...)
        # length: Content-Length
        # content_range: Content-Range 或 302跳转地址(当status=302时)
        data_iter, status, length, content_range = provider.get_stream_data(resource.path, range_header)

        # 处理 302 跳转 (Alist 直链模式)
        if status in [301, 302, 303, 307, 308]:
            redirect_url = content_range  # 此时 content_range 变量存的是 Location
            if redirect_url:
                logger.info("Stream redirect location=%s", redirect_url[:50])
                return redirect(redirect_url, code=302)

        if status >= 400:
            logger.warning("Stream provider error status=%s resource_id=%s", status, id)
            return Response(f"Stream Error: {status}", status=status)

        headers = {
            'Accept-Ranges': 'bytes',
            'Content-Type': _guess_video_mime_type(resource)
        }
        if length:
            headers['Content-Length'] = str(length)
        if content_range:
            headers['Content-Range'] = content_range

        return Response(stream_with_context(data_iter), status=status, headers=headers)

    except Exception as e:
        logger.exception("Unhandled stream error resource_id=%s error=%s", id, e)
        return Response("Internal Stream Error", status=500)
