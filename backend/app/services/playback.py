import mimetypes
import os

from flask import has_request_context, url_for

from backend.app.services.audio_transcode import (
    DEFAULT_AUDIO_TRANSCODE_FORMAT,
    DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
    build_audio_transcode_url_params,
    get_audio_transcode_profile,
    is_ffmpeg_available as _is_ffmpeg_available,
)
from backend.app.storage.source_registry import get_source_capabilities


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

WEB_AUDIO_UNSAFE_CODECS = {
    'ac3': 'AC3 is not consistently supported by HTML5 video audio decoders',
    'eac3': 'E-AC3 is not consistently supported by HTML5 video audio decoders',
    'dolby_atmos': 'Dolby Atmos tracks are commonly carried as E-AC3 or TrueHD and are not consistently supported by HTML5 video audio decoders',
    'dts_x': 'DTS:X is not supported by common HTML5 video audio decoders',
    'dts_hd_ma': 'DTS-HD MA is not supported by common HTML5 video audio decoders',
    'truehd': 'TrueHD is not supported by common HTML5 video audio decoders',
    'truehd_atmos': 'TrueHD Atmos is not supported by common HTML5 video audio decoders',
}


def guess_video_mime_type(resource):
    filename = getattr(resource, 'filename', None) or getattr(resource, 'path', None) or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext in VIDEO_MIME_TYPES:
        return VIDEO_MIME_TYPES[ext]
    guessed_type, _ = mimetypes.guess_type(filename)
    return guessed_type or 'application/octet-stream'


def is_ffmpeg_available():
    return _is_ffmpeg_available()


def _stream_url(resource):
    resource_id = getattr(resource, 'id', None)
    if not resource_id:
        return None
    if has_request_context():
        return url_for('player.stream_resource', id=resource_id, _external=True)
    return f"/api/v1/resources/{resource_id}/stream"


def _audio_transcode_endpoint(resource):
    resource_id = getattr(resource, 'id', None)
    if not resource_id:
        return None
    if has_request_context():
        return url_for('player.transcode_resource_audio', id=resource_id, _external=True)
    return f"/api/v1/resources/{resource_id}/audio-transcode"


def _source_capabilities(resource):
    source = getattr(resource, 'source', None)
    source_type = getattr(source, 'type', None)
    if not source_type:
        return "unknown", {}
    try:
        normalized_type, capabilities = get_source_capabilities(source_type)
        return normalized_type, capabilities
    except Exception:
        return str(source_type or 'unknown'), {}


def _audio_web_decode_state(technical):
    codec_code = (technical or {}).get('audio_codec_code') or 'unknown'
    codec_label = (technical or {}).get('audio_summary_label') or (technical or {}).get('audio_codec_label') or 'Unknown'
    if codec_code in WEB_AUDIO_UNSAFE_CODECS:
        return {
            "codec_code": codec_code,
            "codec_label": codec_label,
            "web_decode_status": "unsupported",
            "web_decode_risk": True,
            "reason": WEB_AUDIO_UNSAFE_CODECS[codec_code],
        }
    if codec_code in {'unknown', '', None}:
        return {
            "codec_code": codec_code or "unknown",
            "codec_label": codec_label,
            "web_decode_status": "unknown",
            "web_decode_risk": False,
            "reason": "Audio codec is unknown",
        }
    return {
        "codec_code": codec_code,
        "codec_label": codec_label,
        "web_decode_status": "likely_supported",
        "web_decode_risk": False,
        "reason": None,
    }


def build_resource_playback(resource, resource_info=None, ffmpeg_available=None):
    source_type, source_capabilities = _source_capabilities(resource)
    technical = (resource_info or {}).get("technical") or {}
    stream_url = _stream_url(resource)
    audio_transcode_endpoint = _audio_transcode_endpoint(resource)
    default_transcode_profile = get_audio_transcode_profile(DEFAULT_AUDIO_TRANSCODE_FORMAT)
    default_transcode_params = build_audio_transcode_url_params()
    default_transcode_query = "&".join(
        f"{key}={value}" for key, value in default_transcode_params.items()
    )
    audio_transcode_url = (
        f"{audio_transcode_endpoint}?{default_transcode_query}"
        if audio_transcode_endpoint
        else None
    )
    mime_type = guess_video_mime_type(resource)
    redirect_supported = bool(source_capabilities.get("redirect_stream"))
    stream_supported = bool(source_capabilities.get("stream"))
    range_supported = bool(
        source_capabilities.get("range_stream")
        or redirect_supported
        or source_type in {"local", "webdav"}
    )
    ffmpeg_input_supported = bool(source_capabilities.get("ffmpeg_input"))
    ffmpeg_ready = is_ffmpeg_available() if ffmpeg_available is None else bool(ffmpeg_available)
    audio_state = _audio_web_decode_state(technical)
    needs_audio_transcode = bool(audio_state["web_decode_risk"])
    transcode_supported = bool(ffmpeg_input_supported)
    transcode_available = bool(transcode_supported and ffmpeg_ready)
    playback_modes = []

    if redirect_supported:
        playback_modes.append("redirect")
    elif stream_supported:
        playback_modes.append("proxy")

    transcode_reason = None
    if not transcode_available:
        if not ffmpeg_input_supported:
            transcode_reason = "provider_ffmpeg_input_not_supported"
        elif not ffmpeg_ready:
            transcode_reason = "ffmpeg_not_installed"
        else:
            transcode_reason = "audio_transcode_not_enabled"

    warnings = []
    if needs_audio_transcode:
        warnings.append({
            "code": "web_audio_decode_risk",
            "message": audio_state["reason"],
        })
    if needs_audio_transcode and transcode_reason:
        warnings.append({
            "code": transcode_reason,
            "message": "Server-side audio transcoding is not currently available",
        })

    playback = {
        "stream_url": stream_url,
        "mime_type": mime_type,
        "storage_type": source_type,
        "playback_modes": playback_modes,
        "default_mode": playback_modes[0] if playback_modes else None,
        "range_supported": range_supported,
        "ffmpeg_input_supported": ffmpeg_input_supported,
        "web_player": {
            "supported": bool(stream_supported and stream_url),
            "url": stream_url,
            "mime_type": mime_type,
            "range_supported": range_supported,
            "audio_decode_status": audio_state["web_decode_status"],
            "needs_server_audio_transcode": needs_audio_transcode,
        },
        "external_player": {
            "supported": bool(stream_supported and stream_url),
            "url": stream_url,
            "url_type": "http_stream",
            "subtitle_urls": [],
            "subtitle_placeholder_url": None,
        },
        "subtitles": {
            "supported": False,
            "items": [],
            "placeholder_url": None,
            "reason": "subtitle_api_not_implemented",
        },
        "audio": {
            **audio_state,
            "server_transcode": {
                "supported": transcode_supported,
                "available": transcode_available,
                "reason": transcode_reason,
                "seek_supported": transcode_available,
                "recommended": needs_audio_transcode,
                "endpoint": None,
                "url": None,
                "start_param": "start",
                "audio_track_param": "audio_track",
                "format_param": "format",
                "session_param": "session_id",
                "default_format": default_transcode_profile.format,
                "mime_type": default_transcode_profile.mime_type,
                "target_codec": default_transcode_profile.target_codec,
                "channels": default_transcode_profile.channels,
                "sample_rate": default_transcode_profile.sample_rate,
                "requires_history_heartbeat": True,
                "history_timeout_seconds": DEFAULT_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS,
                "mode": "separate_audio_stream",
                "sync_strategy": "video_audio_dual_element",
                "buffer_strategy": "forward_only",
                "seek_strategy": "use_buffered_audio_or_restart",
                "restart_policy": "restart_only_when_target_outside_buffer",
                "frontend_should_rebuild_on_every_seek": False,
            },
        },
        "warnings": warnings,
    }

    if transcode_available:
        playback["audio"]["server_transcode"]["endpoint"] = audio_transcode_endpoint
        playback["audio"]["server_transcode"]["url"] = audio_transcode_url

    return playback
