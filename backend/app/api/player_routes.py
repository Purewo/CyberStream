import logging
from urllib.parse import quote
from flask import Blueprint, Response, current_app, redirect, request, send_file, stream_with_context

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
from backend.app.services.online_subtitles import (
    OnlineSubtitleError,
    bind_online_subtitle,
    download_online_subtitle,
    search_online_subtitles,
)
from backend.app.services.playback import (
    build_external_playback_m3u,
    build_external_playback_manifest,
    guess_video_mime_type,
)
from backend.app.services.subtitle_settings import (
    SubtitleSettingsError,
    build_subtitle_settings_payload,
    save_resource_subtitle_settings,
)
from backend.app.services.subtitles import (
    ResourceSubtitleError,
    cached_subtitle_file_path,
    convert_subtitle_bytes_to_vtt,
    delete_bound_resource_subtitle,
    find_resource_subtitle,
    set_default_bound_resource_subtitle,
    upload_resource_subtitle,
)
from backend.app.storage.source_registry import get_source_capabilities
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

player_bp = Blueprint('player', __name__, url_prefix='/api/v1')

_guess_video_mime_type = guess_video_mime_type


def _split_online_subtitle_keywords(value):
    raw = str(value or "").strip()
    if not raw:
        return []
    for separator in ("\n", ",", "，"):
        raw = raw.replace(separator, "\n")
    return [item.strip() for item in raw.split("\n") if item.strip()]


def _online_subtitle_search_keywords():
    keywords = []
    for value in request.args.getlist("keyword"):
        if str(value or "").strip():
            keywords.append(value)
    for value in request.args.getlist("keywords"):
        keywords.extend(_split_online_subtitle_keywords(value))
    for value in request.args.getlist("query"):
        if str(value or "").strip():
            keywords.append(value)
    return keywords or None


@player_bp.route('/resources/<uuid:id>/subtitle-settings', methods=['GET'])
def get_resource_subtitle_settings(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    return api_response(data=build_subtitle_settings_payload(resource), msg="resource subtitle settings")


@player_bp.route('/resources/<uuid:id>/subtitle-settings', methods=['PUT', 'PATCH'])
def update_resource_subtitle_settings(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    payload = request.get_json(silent=True) or {}
    try:
        data = save_resource_subtitle_settings(resource, payload)
        return api_response(data=data, msg="resource subtitle settings updated")
    except SubtitleSettingsError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception as e:
        logger.exception("Subtitle settings update failed resource_id=%s error=%s", resource.id, e)
        return api_error(code=50080, msg="Subtitle settings update failed", http_status=500)


def _stream_resource_subtitle(resource, subtitle_id):
    subtitle, _payload = find_resource_subtitle(resource, subtitle_id)
    if not subtitle:
        logger.warning("Subtitle not found resource_id=%s subtitle_id=%s", resource.id, subtitle_id)
        return Response("Subtitle not found", status=404)

    output_format = str(request.args.get("format") or "").strip().lower()
    if output_format and output_format != "vtt":
        return Response("Unsupported subtitle output format", status=400)

    if subtitle.get("source") in {"online_bound", "manual_upload"}:
        cache_path = cached_subtitle_file_path(subtitle)
        if not cache_path or not cache_path.exists() or not cache_path.is_file():
            logger.warning("Bound subtitle file missing resource_id=%s subtitle_id=%s", resource.id, subtitle_id)
            return Response("Subtitle not found", status=404)
        if output_format == "vtt":
            try:
                vtt_content = convert_subtitle_bytes_to_vtt(
                    cache_path.read_bytes(),
                    subtitle.get("format"),
                )
            except ResourceSubtitleError as e:
                return Response(e.message, status=e.http_status)
            return Response(
                vtt_content,
                status=200,
                headers={
                    "Content-Type": "text/vtt; charset=utf-8",
                    "Cache-Control": "private, max-age=60",
                    "X-Cyber-Subtitle-Format": "vtt",
                    "X-Cyber-Subtitle-Source-Format": subtitle.get("format") or "",
                },
            )
        return send_file(
            cache_path,
            mimetype=subtitle.get("mime_type") or "text/plain; charset=utf-8",
            download_name=subtitle.get("filename") or "subtitle",
            conditional=True,
            max_age=60,
        )

    source = resource.source
    if not source:
        logger.error("Subtitle storage source missing resource_id=%s", resource.id)
        return Response("Storage Source Missing", status=500)

    try:
        provider = provider_factory.get_provider(source)
        data_iter, status, length, content_range = provider.get_stream_data(subtitle["path"], None)

        if status in [301, 302, 303, 307, 308]:
            redirect_url = content_range
            if redirect_url:
                if output_format == "vtt":
                    logger.warning(
                        "Subtitle conversion unavailable for redirected source resource_id=%s subtitle_id=%s",
                        resource.id,
                        subtitle_id,
                    )
                    return Response("Subtitle conversion unavailable for redirected source", status=502)
                logger.info("Subtitle redirect location=%s", redirect_url[:50])
                return redirect(redirect_url, code=302)

        if status >= 400:
            logger.warning(
                "Subtitle provider error status=%s resource_id=%s subtitle_id=%s",
                status,
                resource.id,
                subtitle_id,
            )
            return Response(f"Subtitle Error: {status}", status=status)

        if output_format == "vtt":
            try:
                chunks = []
                for chunk in data_iter:
                    chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
                vtt_content = convert_subtitle_bytes_to_vtt(
                    b"".join(chunks),
                    subtitle.get("format"),
                )
            except ResourceSubtitleError as e:
                return Response(e.message, status=e.http_status)
            return Response(
                vtt_content,
                status=200,
                headers={
                    "Content-Type": "text/vtt; charset=utf-8",
                    "Cache-Control": "private, max-age=60",
                    "X-Cyber-Subtitle-Format": "vtt",
                    "X-Cyber-Subtitle-Source-Format": subtitle.get("format") or "",
                },
            )

        headers = {
            "Content-Type": subtitle.get("mime_type") or "text/plain; charset=utf-8",
            "Cache-Control": "private, max-age=60",
        }
        if length:
            headers["Content-Length"] = str(length)
        if content_range:
            headers["Content-Range"] = content_range

        return Response(stream_with_context(data_iter), status=status, headers=headers)
    except Exception as e:
        logger.exception(
            "Unhandled subtitle stream error resource_id=%s subtitle_id=%s error=%s",
            resource.id,
            subtitle_id,
            e,
        )
        return Response("Internal Subtitle Stream Error", status=500)


@player_bp.route('/resources/<uuid:id>/stream', methods=['GET'])
def stream_resource(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        logger.warning("Stream resource not found id=%s", id)
        return Response("Resource not found", status=404)

    subtitle_id = request.args.get("subtitle_id")
    if subtitle_id:
        return _stream_resource_subtitle(resource, subtitle_id)

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


@player_bp.route('/resources/<uuid:id>/external-playback', methods=['GET'])
def get_resource_external_playback(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    output_format = str(request.args.get("format") or "json").strip().lower()
    if output_format not in {"json", "m3u"}:
        return api_error(code=40073, msg="Unsupported external playback format")

    resource_payload = resource.to_dict(include_subtitle_discovery=True)
    manifest = build_external_playback_manifest(resource, resource_payload=resource_payload)

    if output_format == "m3u":
        if not manifest["handoff"]["supported"]:
            return api_error(code=40910, msg="Resource stream is not available for external playback", http_status=409)
        playlist = build_external_playback_m3u(manifest)
        filename = f"cyberstream-{resource.id}.m3u"
        encoded_filename = quote(filename)
        return Response(
            playlist,
            status=200,
            headers={
                "Content-Type": "audio/x-mpegurl; charset=utf-8",
                "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{encoded_filename}",
                "Cache-Control": "private, max-age=60",
            },
        )

    return api_response(data=manifest, msg="external playback manifest")


@player_bp.route('/resources/<uuid:id>/subtitles/online/search', methods=['GET'])
def search_resource_online_subtitles(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    try:
        data = search_online_subtitles(
            resource,
            query=_online_subtitle_search_keywords(),
            providers=request.args.get("providers"),
            limit=request.args.get("limit", 50),
            max_query_attempts=request.args.get("max_query_attempts"),
        )
        return api_response(data=data, msg="online subtitles searched")
    except OnlineSubtitleError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception as e:
        logger.exception("Online subtitle search failed resource_id=%s error=%s", resource.id, e)
        return api_error(code=50060, msg="Online subtitle search failed", http_status=500)


@player_bp.route('/resources/<uuid:id>/subtitles/online/download', methods=['POST'])
def download_resource_online_subtitle(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    payload = request.get_json(silent=True) or {}
    candidate_id = payload.get("candidate_id") if isinstance(payload, dict) else None
    download_index = payload.get("download_index", 0) if isinstance(payload, dict) else 0
    if not candidate_id:
        return api_error(code=40060, msg="candidate_id is required")

    try:
        result = download_online_subtitle(
            resource,
            candidate_id=candidate_id,
            download_index=download_index,
        )
        encoded_filename = quote(result["filename"])
        extracted = result["meta"].get("extracted") or result["meta"].get("source_extracted")
        headers = {
            "Content-Type": result["mime_type"],
            "Content-Disposition": f"attachment; filename=\"subtitle\"; filename*=UTF-8''{encoded_filename}",
            "Cache-Control": "private, max-age=60",
            "X-Cyber-Subtitle-Provider": result["meta"].get("provider_id", ""),
            "X-Cyber-Subtitle-Extracted": "true" if extracted else "false",
        }
        archive_kind = result["meta"].get("archive_kind")
        if archive_kind:
            headers["X-Cyber-Subtitle-Archive-Kind"] = archive_kind
        return Response(result["content"], status=200, headers=headers)
    except OnlineSubtitleError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception as e:
        logger.exception("Online subtitle download failed resource_id=%s error=%s", resource.id, e)
        return api_error(code=50061, msg="Online subtitle download failed", http_status=500)


@player_bp.route('/resources/<uuid:id>/subtitles/online/bind', methods=['POST'])
def bind_resource_online_subtitle(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    payload = request.get_json(silent=True) or {}
    candidate_id = payload.get("candidate_id") if isinstance(payload, dict) else None
    download_index = payload.get("download_index", 0) if isinstance(payload, dict) else 0
    confirm = payload.get("confirm") if isinstance(payload, dict) else False
    if not candidate_id:
        return api_error(code=40060, msg="candidate_id is required")

    try:
        data = bind_online_subtitle(
            resource,
            candidate_id=candidate_id,
            download_index=download_index,
            confirm=confirm,
        )
        return api_response(data=data, msg="online subtitle bound")
    except OnlineSubtitleError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception as e:
        logger.exception("Online subtitle bind failed resource_id=%s error=%s", resource.id, e)
        return api_error(code=50062, msg="Online subtitle bind failed", http_status=500)


@player_bp.route('/resources/<uuid:id>/subtitles/<subtitle_id>', methods=['DELETE'])
def delete_resource_subtitle(id, subtitle_id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    try:
        data = delete_bound_resource_subtitle(resource, subtitle_id)
        return api_response(data=data, msg="resource subtitle removed")
    except ResourceSubtitleError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception as e:
        logger.exception("Subtitle delete failed resource_id=%s subtitle_id=%s error=%s", resource.id, subtitle_id, e)
        return api_error(code=50070, msg="Subtitle delete failed", http_status=500)


@player_bp.route('/resources/<uuid:id>/subtitles/<subtitle_id>/default', methods=['POST'])
def set_resource_default_subtitle(id, subtitle_id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    try:
        data = set_default_bound_resource_subtitle(resource, subtitle_id)
        return api_response(data=data, msg="resource default subtitle updated")
    except ResourceSubtitleError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception as e:
        logger.exception("Subtitle default update failed resource_id=%s subtitle_id=%s error=%s", resource.id, subtitle_id, e)
        return api_error(code=50071, msg="Subtitle default update failed", http_status=500)


@player_bp.route('/resources/<uuid:id>/subtitles/upload', methods=['POST'])
def upload_resource_subtitle_file(id):
    resource = db.session.get(MediaResource, str(id))
    if not resource:
        return api_error(code=40403, msg="Resource not found", http_status=404)

    file_storage = request.files.get("file") or request.files.get("subtitle")
    set_default = request.form.get("set_default", request.form.get("is_default", False))

    try:
        data = upload_resource_subtitle(resource, file_storage, set_default=set_default)
        return api_response(data=data, msg="resource subtitle uploaded")
    except ResourceSubtitleError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception as e:
        logger.exception("Subtitle upload failed resource_id=%s error=%s", resource.id, e)
        return api_error(code=50072, msg="Subtitle upload failed", http_status=500)


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
