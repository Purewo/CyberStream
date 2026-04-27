import subprocess
import os
import re
import logging
from urllib.parse import unquote
from backend import config

logger = logging.getLogger(__name__)


class MediaFeatureParser:
    VIDEO_CODEC_PATTERNS = (
        ('AV1', r'\bAV1\b'),
        ('HEVC', r'\b(?:HEVC|H\.?265|X265)\b'),
        ('AVC', r'\b(?:AVC|H\.?264|X264)\b'),
        ('VC-1', r'\bVC-?1\b'),
        ('VP9', r'\bVP9\b'),
    )
    AUDIO_CODEC_PATTERNS = (
        ('Dolby TrueHD Atmos', r'\bTRUEHD(?:[ ._-]*\d(?:\.\d)?)?\b.*\bATMOS\b|\bATMOS\b.*\bTRUEHD(?:[ ._-]*\d(?:\.\d)?)?\b'),
        ('Dolby Atmos', r'\b(?:ATMOS|DOLBY[ ._-]*ATMOS)\b'),
        ('DTS:X', r'\bDTS[ ._-]*X\b'),
        ('DTS-HD MA', r'\bDTS[ ._-]*HD[ ._-]*MA\b|\bDTS[ ._-]*HD\b'),
        ('TrueHD', r'\bTRUEHD\b'),
        ('E-AC3', r'\b(?:E-?AC3|DDP|DD\+)\b'),
        ('AC3', r'\bAC3\b'),
        ('AAC', r'\bAAC\b'),
    )
    SOURCE_PATTERNS = (
        ('UHD Blu-ray Remux', r'\b(?:UHD|4K)[ ._-]*BLU(?:-?RAY)?\b.*\b(?:REMUX|REMUNX|REMUXED)\b|\b(?:REMUX|REMUNX|REMUXED)\b.*\b(?:UHD|4K)[ ._-]*BLU(?:-?RAY)?\b'),
        ('Blu-ray Remux', r'\b(?:REMUX|REMUNX|REMUXED)\b'),
        ('UHD Blu-ray', r'\bUHD(?:[ ._-]*BLU(?:-?RAY)?)?\b|\b4K[ ._-]*BLU(?:-?RAY)?\b'),
        ('Blu-ray', r'\b(?:BLU[ ._-]*RAY|BDRIP|BDREMUX|BDMV)\b'),
        ('WEB-DL', r'\bWEB[ ._-]*DL\b'),
        ('WEBRip', r'\bWEB[ ._-]*RIP\b'),
        ('HDTV', r'\bHDTV\b'),
    )

    @classmethod
    def parse(cls, filename, relative_path=None, size=0, movie_only=True):
        text = " ".join(part for part in [relative_path or "", filename or ""] if part)
        upper = text.upper()
        tags = []
        feature_flags = {}

        def add_tag(tag):
            if tag not in tags:
                tags.append(tag)

        resolution, resolution_rank = cls._detect_resolution(upper)
        if resolution_rank >= 2160:
            add_tag('4K')
        elif resolution_rank == 1080:
            add_tag('1080P')
        elif resolution_rank == 720:
            add_tag('720P')

        video_codec = cls._first_match(upper, cls.VIDEO_CODEC_PATTERNS) or 'Unknown'
        audio_codec = cls._first_match(upper, cls.AUDIO_CODEC_PATTERNS) or 'Unknown'
        audio_channels, audio_channel_count = cls._detect_audio_channels(upper)
        source = cls._first_match(upper, cls.SOURCE_PATTERNS) or 'Unknown'

        is_remux = bool(re.search(r'\b(?:REMUX|REMUNX|REMUXED)\b', upper))
        is_uhd_bluray = bool(re.search(r'\b(?:UHD|4K)[ ._-]*BLU(?:-?RAY)?\b|\bUHD[ ._-]*BLU(?:-?RAY)?\b', upper))
        if is_remux:
            source = 'UHD Blu-ray Remux' if is_uhd_bluray else 'Blu-ray Remux'
            add_tag('REMUX')

        has_hdr10_plus = bool(re.search(r'\bHDR10(?:[ ._-]*\+|PLUS)(?=[^A-Z0-9]|$)', upper))
        has_hdr10 = has_hdr10_plus or bool(re.search(r'\b(?:HDR10|HDR)\b', upper))
        has_hlg = bool(re.search(r'\bHLG\b', upper))
        has_dolby_vision = bool(re.search(r'\b(?:DOLBY[ ._-]*VISION|DV)\b', upper))
        has_sdr = bool(re.search(r'\bSDR\b', upper))
        if has_hdr10_plus:
            add_tag('HDR10+')
        elif has_hdr10:
            add_tag('HDR10')
        if has_hlg:
            add_tag('HLG')
        if has_dolby_vision:
            add_tag('Dolby Vision')
        if has_sdr:
            add_tag('SDR')
        if 'ATMOS' in upper:
            add_tag('Atmos')

        if re.search(r'\bIMAX\b', upper):
            add_tag('IMAX')
            feature_flags['imax'] = True

        if re.search(r'\b10[ ._-]*BIT\b|\b10BIT\b', upper):
            add_tag('10bit')
            feature_flags['ten_bit'] = True

        feature_flags.update({
            'is_4k': resolution_rank >= 2160,
            'is_1080p': resolution_rank == 1080,
            'is_hdr': has_hdr10 or has_hlg or has_dolby_vision,
            'is_hdr10': has_hdr10,
            'is_hdr10_plus': has_hdr10_plus,
            'is_hlg': has_hlg,
            'is_dolby_vision': has_dolby_vision,
            'is_remux': is_remux,
            'is_uhd_bluray': is_uhd_bluray,
            'is_original_quality': is_remux,
            'is_movie_feature': bool(movie_only),
            'is_lossless_audio': audio_codec in {'Dolby TrueHD Atmos', 'TrueHD', 'DTS-HD MA'},
        })

        hdr_format = cls._hdr_format(has_dolby_vision, has_hdr10_plus, has_hdr10, has_hlg, has_sdr)
        quality_tier = cls._quality_tier(resolution_rank, is_remux, hdr_format not in {'Unknown', 'SDR'})
        quality_label = cls._quality_label(resolution, is_remux, hdr_format)

        return {
            'resolution': resolution,
            'resolution_rank': resolution_rank,
            'codec': video_codec if video_codec != 'Unknown' else 'AVC',
            'video_codec': video_codec,
            'audio_codec': audio_codec,
            'audio_channels': audio_channels,
            'audio_channel_count': audio_channel_count,
            'source': source,
            'quality_tier': quality_tier,
            'quality_label': quality_label,
            'hdr_format': hdr_format,
            'tags': tags,
            'features': feature_flags,
            'size': int(size or 0),
        }

    @classmethod
    def _first_match(cls, text, patterns):
        for label, pattern in patterns:
            if re.search(pattern, text):
                return label
        return None

    @classmethod
    def _detect_resolution(cls, text):
        if re.search(r'\b(?:4320P|8K)\b|(?:7680\s*[X×]\s*4320)', text):
            return '8K', 4320
        if re.search(r'\b(?:2160P|4K|UHD)\b|(?:3840|4096)\s*[X×]\s*2160', text):
            return '2160P', 2160
        if re.search(r'\b(?:1080P|FHD)\b|1920\s*[X×]\s*1080', text):
            return '1080P', 1080
        if re.search(r'\b720P\b|1280\s*[X×]\s*720', text):
            return '720P', 720
        if re.search(r'\b480P\b', text):
            return '480P', 480
        return 'Unknown', 0

    @classmethod
    def _detect_audio_channels(cls, text):
        match = re.search(r'(?<!\d)([1-9](?:\.[0-9]))(?!\d)', text)
        if not match:
            return None, None
        layout = match.group(1)
        major, minor = layout.split('.', 1)
        return layout, int(major) + int(minor)

    @staticmethod
    def _hdr_format(has_dolby_vision, has_hdr10_plus, has_hdr10, has_hlg, has_sdr):
        if has_dolby_vision:
            return 'Dolby Vision'
        if has_hdr10_plus:
            return 'HDR10+'
        if has_hdr10:
            return 'HDR10'
        if has_hlg:
            return 'HLG'
        if has_sdr:
            return 'SDR'
        return 'Unknown'

    @classmethod
    def _quality_tier(cls, resolution_rank, is_remux, is_hdr):
        if is_remux and resolution_rank >= 2160:
            return 'reference'
        if is_remux:
            return 'remux'
        if resolution_rank >= 2160 and is_hdr:
            return 'premium'
        if resolution_rank >= 2160:
            return 'uhd'
        if resolution_rank >= 1080:
            return 'hd'
        return 'standard'

    @classmethod
    def _quality_label(cls, resolution, is_remux, hdr_format):
        parts = []
        if resolution and resolution != 'Unknown':
            parts.append('4K' if resolution == '2160P' else resolution)
        if is_remux:
            parts.append('Remux')
        if hdr_format and hdr_format not in {'Unknown', 'SDR'}:
            parts.append(hdr_format)
        return ' '.join(parts) if parts else 'Unknown'

# --- 全局状态检测 ---
def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("FFmpeg detected. Audio transcoding enabled.")
        return True
    except Exception:
        logger.warning("FFmpeg not found. Audio transcoding disabled.")
        return False

# --- 资源校验与工具类 ---
class ResourceValidator:
    @staticmethod
    def normalize_path(raw_path):
        try:
            path = unquote(raw_path)
            if config.STORAGE_MODE == 'webdav':
                if path.startswith('/dav/'): path = path[4:]
            path = path.replace('\\', '/')
            return path
        except Exception:
            return raw_path

    @staticmethod
    def is_ignored_folder(folder_name):
        return folder_name.upper() in config.IGNORE_FOLDERS

    @staticmethod
    def is_valid_video(filename):
        u_name = filename.upper()
        if not u_name.endswith(config.VIDEO_EXTENSIONS): return False
        if any(k in u_name for k in config.IGNORE_FILES): return False
        return True

    @staticmethod
    def get_tech_specs(filename):
        return MediaFeatureParser.parse(filename)
