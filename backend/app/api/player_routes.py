import logging
from flask import Blueprint, Response, current_app, redirect, request, stream_with_context

from backend.app.extensions import db
from backend.app.models import MediaResource
from backend.app.providers.factory import provider_factory
from backend.app.services.audio_transcode import (
    DEFAULT_AUDIO_TRANSCODE_MAX_CONCURRENT,
    DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
    DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS,
    DEFAULT_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS,
    DEFAULT_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS,
    DEFAULT_AUDIO_TRANSCODE_REALTIME_INPUT,
    DEFAULT_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER,
    DEFAULT_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS,
    DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_BYTES,
    DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED,
    DEFAULT_HTTP_INPUT_PROXY_MAX_RETRIES,
    AudioTranscodeError,
    build_anonymous_audio_transcode_stream_key,
    build_audio_transcode_stream_key,
    create_audio_transcode_stream,
    finish_audio_transcode_diagnostics,
    get_audio_transcode_diagnostics,
    parse_audio_transcode_session_id,
    parse_audio_transcode_options,
    register_active_audio_transcode_stream,
    resolve_ffmpeg_binary,
    start_audio_transcode_diagnostics,
    stop_active_audio_transcode_stream,
)
from backend.app.services.playback import guess_video_mime_type
from backend.app.storage.source_registry import get_source_capabilities
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

player_bp = Blueprint('player', __name__, url_prefix='/api/v1')

_guess_video_mime_type = guess_video_mime_type


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
            'Content-Type': guess_video_mime_type(resource)
        }
        if length:
            headers['Content-Length'] = str(length)
        if content_range:
            headers['Content-Range'] = content_range

        return Response(stream_with_context(data_iter), status=status, headers=headers)

    except Exception as e:
        logger.exception("Unhandled stream error resource_id=%s error=%s", id, e)
        return Response("Internal Stream Error", status=500)


@player_bp.route('/resources/<uuid:id>/audio-transcode', methods=['GET'])
def transcode_resource_audio(id):
    try:
        options = parse_audio_transcode_options(request.args)
        session_id = parse_audio_transcode_session_id(request.args, request.headers)
    except AudioTranscodeError as e:
        return Response(str(e), status=e.status_code)

    resource = db.session.get(MediaResource, str(id))
    if not resource:
        logger.warning("Audio transcode resource not found id=%s", id)
        return Response("Resource not found", status=404)

    source = resource.source
    if not source:
        logger.error("Audio transcode storage source missing resource_id=%s", id)
        return Response("Storage Source Missing", status=500)

    try:
        _source_type, capabilities = get_source_capabilities(source.type)
    except Exception as e:
        logger.warning("Audio transcode unsupported source resource_id=%s source_type=%s error=%s", id, source.type, e)
        return Response("Storage source does not support ffmpeg input", status=400)

    if not capabilities.get("ffmpeg_input"):
        return Response("Storage source does not support ffmpeg input", status=400)

    ffmpeg_bin = resolve_ffmpeg_binary(current_app.config.get("FFMPEG_BIN"))
    if not ffmpeg_bin:
        logger.warning("Audio transcode requested but ffmpeg is not available resource_id=%s", id)
        return Response("ffmpeg is not available", status=503)

    try:
        logger.info(
            "Audio transcode start filename=%s source_type=%s start=%s audio_track=%s format=%s",
            resource.filename,
            source.type,
            options.start_seconds,
            options.audio_track,
            options.format,
        )
        resource_id = str(id)
        stream_key = (
            build_audio_transcode_stream_key(resource_id, session_id)
            if session_id
            else build_anonymous_audio_transcode_stream_key(resource_id)
        )
        if stream_key:
            # Seek replaces the current stream, but the same resource cache is
            # intentionally kept so nearby ffmpeg Range reads can be reused.
            stopped_existing = stop_active_audio_transcode_stream(stream_key, preserve_cache=True)
            if stopped_existing:
                logger.info(
                    "Audio transcode replaced active session resource_id=%s session_id=%s",
                    resource_id,
                    session_id,
                )
        provider = provider_factory.get_provider(source)
        input_url = provider.get_ffmpeg_input(resource.path)
        diagnostic_id = start_audio_transcode_diagnostics(
            resource_id,
            session_id=session_id,
            options=options,
            input_url=input_url,
            stream_key=stream_key,
        )
        stream = create_audio_transcode_stream(
            input_url,
            options=options,
            ffmpeg_bin=ffmpeg_bin,
            resource_id=resource_id,
            session_id=session_id,
            diagnostic_id=diagnostic_id,
            max_concurrent=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_MAX_CONCURRENT",
                DEFAULT_AUDIO_TRANSCODE_MAX_CONCURRENT,
            ),
            read_timeout_seconds=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS",
                DEFAULT_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS,
            ),
            history_timeout_seconds=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS",
                DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
            ),
            input_retries=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_INPUT_RETRIES",
                DEFAULT_HTTP_INPUT_PROXY_MAX_RETRIES,
            ),
            first_byte_timeout_seconds=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS",
                DEFAULT_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS,
            ),
            acquire_timeout_seconds=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS",
                DEFAULT_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS,
            ),
            realtime_input=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_REALTIME_INPUT",
                DEFAULT_AUDIO_TRANSCODE_REALTIME_INPUT,
            ),
            output_rate_multiplier=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER",
                DEFAULT_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER,
            ),
            output_initial_burst_seconds=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS",
                DEFAULT_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS,
            ),
            range_cache_enabled=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED",
                DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED,
            ),
            range_cache_bytes=current_app.config.get(
                "FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_BYTES",
                DEFAULT_AUDIO_TRANSCODE_RANGE_CACHE_BYTES,
            ),
        )
        stream.diagnostic_id = diagnostic_id
        if session_id:
            stream.headers["X-Cyber-Playback-Session"] = session_id
        if stream_key:
            register_active_audio_transcode_stream(stream_key, stream)
        return Response(
            stream_with_context(stream.iterator),
            status=200,
            headers=stream.headers,
            mimetype=stream.profile.mime_type,
            direct_passthrough=True,
        )
    except AudioTranscodeError as e:
        logger.warning("Audio transcode rejected resource_id=%s error=%s", id, e)
        if "diagnostic_id" in locals():
            finish_audio_transcode_diagnostics(diagnostic_id, reason=e.error_code)
        headers = {"Retry-After": "5"} if e.status_code == 429 else None
        return Response(str(e), status=e.status_code, headers=headers)
    except Exception as e:
        logger.exception("Unhandled audio transcode error resource_id=%s error=%s", id, e)
        if "diagnostic_id" in locals():
            finish_audio_transcode_diagnostics(diagnostic_id, reason="internal_error")
        return Response("Internal Audio Transcode Error", status=500)


@player_bp.route('/resources/<uuid:id>/audio-transcode', methods=['DELETE'])
def stop_resource_audio_transcode(id):
    try:
        session_id = parse_audio_transcode_session_id(request.args, request.headers)
    except AudioTranscodeError as e:
        return Response(str(e), status=e.status_code)
    if not session_id:
        return Response("session_id is required", status=400)

    stopped = stop_active_audio_transcode_stream(
        build_audio_transcode_stream_key(str(id), session_id)
    )
    return api_response(
        data={
            "resource_id": str(id),
            "session_id": session_id,
            "stopped": stopped,
        },
        msg="audio transcode stopped" if stopped else "audio transcode session not active",
    )


@player_bp.route('/resources/<uuid:id>/audio-transcode/diagnostics', methods=['GET'])
def get_resource_audio_transcode_diagnostics(id):
    try:
        session_id = parse_audio_transcode_session_id(request.args, request.headers)
    except AudioTranscodeError as e:
        return Response(str(e), status=e.status_code)

    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40402, msg="Resource not found", http_status=404)

    return api_response(
        data=get_audio_transcode_diagnostics(str(id), session_id=session_id),
        msg="audio transcode diagnostics",
    )
