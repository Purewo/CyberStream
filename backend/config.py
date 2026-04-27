
import os


def _env(key, default=None):
    value = os.getenv(key)
    return value if value not in (None, "") else default


def _env_bool(key, default=False):
    value = os.getenv(key)
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key, default):
    value = os.getenv(key)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_float(key, default):
    value = os.getenv(key)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_proxy_url(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw


def _build_http_proxy_map(url):
    proxy_url = _normalize_proxy_url(url)
    if not proxy_url:
        return None
    return {
        "http": proxy_url,
        "https": proxy_url,
    }


# --- 基础路径配置 ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = "cyber_library.db"
DB_PATH = os.path.join(BASE_DIR, DB_NAME)

# --- 数据库配置 (SQLAlchemy) ---
SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# --- 历史单存储配置（兼容保留，非主流程配置入口） ---
# 当前主流程实际以数据库 storage_sources.config 为准；
# 以下字段仅保留给历史兼容逻辑，避免旧代码路径直接失效。
# 可选值: 'webdav', 'local'
STORAGE_MODE = _env('CYBER_STORAGE_MODE', 'local')

# --- 历史本地存储配置（兼容保留） ---
LOCAL_ROOT_PATH = _env('CYBER_LOCAL_ROOT_PATH', r"E:/Movies")

# --- 历史 WebDAV 配置（兼容保留） ---
WEBDAV_CONFIG = {
    'hostname': _env('CYBER_WEBDAV_HOSTNAME', "http://gameuniverse.top:81/dav"),
    'login': _env('CYBER_WEBDAV_LOGIN', "admin"),
    'password': _env('CYBER_WEBDAV_PASSWORD', "A1234567890a!")
}
WEBDAV_BASE_URL = _env('CYBER_WEBDAV_BASE_URL', "http://gameuniverse.top:81")
WEBDAV_ROOT_PATH = _env('CYBER_WEBDAV_ROOT_PATH', "/天翼铂金18T/我的视频")

# 兼容性路径计算（仅供历史逻辑使用）
TARGET_ROOT_PATH = LOCAL_ROOT_PATH if STORAGE_MODE == 'local' else WEBDAV_ROOT_PATH

# --- TMDB 配置 ---
# 优先读取环境变量，未设置时回退到当前默认值，确保现有部署不被打断。
TMDB_TOKEN = _env('TMDB_TOKEN', 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI3MjgxOTU5ZTUzYjc0MjMyOGJjYzM0OTQ1MzA5MWZiMSIsIm5iZiI6MTc0Mzk5ODY5MC4xMzEsInN1YiI6IjY3ZjM0ZWUyZGRmOTE5NDM4N2Q5NjA2YyIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.YaASg_XbweU0PaDQNvU2jeCN-VP2HqWVfPqr73uJn0w')
TMDB_IMAGE_BASE = _env('TMDB_IMAGE_BASE', "https://image.tmdb.org/t/p/w500")
TMDB_BACKDROP_BASE = _env('TMDB_BACKDROP_BASE', "https://image.tmdb.org/t/p/original")
TMDB_PROXY_ENABLED = _env_bool('TMDB_PROXY_ENABLED', True)
TMDB_PROXY_URL = _normalize_proxy_url(_env('TMDB_PROXY_URL', 'http://127.0.0.1:17890'))
TMDB_PROXIES = _build_http_proxy_map(TMDB_PROXY_URL) if TMDB_PROXY_ENABLED else None

# --- 缓存目录 ---
CACHE_DIR = os.path.join(BASE_DIR, "cache")

# --- FFmpeg 实时转码 ---
FFMPEG_BIN = _env('CYBER_FFMPEG_BIN', _env('FFMPEG_BIN', None))
FFMPEG_AUDIO_TRANSCODE_MAX_CONCURRENT = _env_int('FFMPEG_AUDIO_TRANSCODE_MAX_CONCURRENT', 1)
FFMPEG_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS = _env_int('FFMPEG_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS', 60)
FFMPEG_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS = _env_int('FFMPEG_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS', 180)
FFMPEG_AUDIO_TRANSCODE_INPUT_RETRIES = _env_int('FFMPEG_AUDIO_TRANSCODE_INPUT_RETRIES', 2)
FFMPEG_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS = _env_int('FFMPEG_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS', 90)
FFMPEG_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS = _env_int('FFMPEG_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS', 3)
FFMPEG_AUDIO_TRANSCODE_REALTIME_INPUT = _env_bool('FFMPEG_AUDIO_TRANSCODE_REALTIME_INPUT', True)
FFMPEG_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER = _env_float('FFMPEG_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER', 1.5)
FFMPEG_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS = _env_int('FFMPEG_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS', 8)
FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED = _env_bool('FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED', True)
FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_BYTES = _env_int('FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_BYTES', 256 * 1024 * 1024)

# --- 扫描规则 ---
VIDEO_EXTENSIONS = ('.MKV', '.MP4', '.MOV', '.AVI', '.M2TS', '.TS', '.ISO', '.WMV', '.FLV', '.RMVB')
IGNORE_FOLDERS = ['BDMV', 'CERTIFICATE', '@EADIR', '$RECYCLE.BIN', 'SYSTEM VOLUME INFORMATION', '__MACOSX', 'BACKUP', 'RECOVERY']
# 移除了 NFO 以便后续支持本地元数据
IGNORE_FILES = ['SAMPLE', 'TRAILER', 'EXTRAS', 'FEATURETTE', 'TXT', 'JPG', 'PNG', 'SRT', 'ASS', 'SUB']

REGEX_PATTERNS = {
    'season': r'(?i)(?:Season|S)\s*(\d+)',
    'episode': r'(?i)[Ee](\d+)',
    'year': r'(19|20)\d{2}'
}

SCAN_INTERVAL_HOURS = 1
PROXIES = TMDB_PROXIES

# --- 应用版本 ---
# 统一版本源：健康检查、文档与发布说明均应以此为准
APP_VERSION = "1.17.0"
