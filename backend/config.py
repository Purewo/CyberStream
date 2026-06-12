
import os
import sys
from datetime import timedelta


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


# --- 运行模式：源码 vs PyInstaller 冻结的 exe ---
# 冻结时 sys.frozen=True、sys._MEIPASS 指向解压后的 datas 目录（用于读
# openapi/ docs/ 这类只读资源）。可写数据 (DB / cache / .env.local) 必须
# 落到 %LOCALAPPDATA%\CyberStream\，否则 PyInstaller 单文件模式下每次运行
# 用的 _MEIPASS 是临时目录，下次重启就清空了。
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    # _MEIPASS 是 PyInstaller 解包后的临时根目录；onedir 模式没这个属性，
    # 退一步用 exe 同目录。
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    DATA_DIR = os.path.join(
        os.environ.get("LOCALAPPDATA")
        or os.path.expanduser(r"~\AppData\Local"),
        "CyberStream",
    )
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 源码模式保持仓库根目录 = data dir，跟现有 dev 流程兼容。
    DATA_DIR = BASE_DIR

os.makedirs(DATA_DIR, exist_ok=True)

DB_NAME = "cyber_library.db"
DB_PATH = os.path.join(DATA_DIR, DB_NAME)

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
    'hostname': _env('CYBER_WEBDAV_HOSTNAME', ""),
    'login': _env('CYBER_WEBDAV_LOGIN', ""),
    'password': _env('CYBER_WEBDAV_PASSWORD', "")
}
WEBDAV_BASE_URL = _env('CYBER_WEBDAV_BASE_URL', "")
WEBDAV_ROOT_PATH = _env('CYBER_WEBDAV_ROOT_PATH', "/")

# 兼容性路径计算（仅供历史逻辑使用）
TARGET_ROOT_PATH = LOCAL_ROOT_PATH if STORAGE_MODE == 'local' else WEBDAV_ROOT_PATH

# --- TMDB 配置 ---
# Secrets must come from the runtime environment, not source control.
TMDB_TOKEN = _env('TMDB_TOKEN', '')
TMDB_IMAGE_BASE = _env('TMDB_IMAGE_BASE', "https://image.tmdb.org/t/p/w500")
TMDB_BACKDROP_BASE = _env('TMDB_BACKDROP_BASE', "https://image.tmdb.org/t/p/original")
TMDB_PROXY_ENABLED = _env_bool('TMDB_PROXY_ENABLED', True)
TMDB_PROXY_URL = _normalize_proxy_url(_env('TMDB_PROXY_URL', 'http://127.0.0.1:17890'))
TMDB_PROXIES = _build_http_proxy_map(TMDB_PROXY_URL) if TMDB_PROXY_ENABLED else None

# --- Bangumi 配置 ---
BANGUMI_API_BASE = _env('BANGUMI_API_BASE', 'https://api.bgm.tv')
BANGUMI_USER_AGENT = _env('BANGUMI_USER_AGENT', 'Purewo/CyberStream/1.21.0 (https://github.com/Purewo/CyberStream)')
BANGUMI_TIMEOUT_SECONDS = _env_float('BANGUMI_TIMEOUT_SECONDS', 10)
BANGUMI_PROXY_ENABLED = _env_bool('BANGUMI_PROXY_ENABLED', False)
BANGUMI_PROXY_URL = _normalize_proxy_url(_env('BANGUMI_PROXY_URL', ''))
BANGUMI_PROXIES = _build_http_proxy_map(BANGUMI_PROXY_URL) if BANGUMI_PROXY_ENABLED else None

# --- AniList metadata provider ---
# Official no-auth GraphQL API. Not part of the default scan order; use
# provider_order/anilist explicitly for anime-focused libraries or manual match.
ANILIST_API_URL = _env('ANILIST_API_URL', 'https://graphql.anilist.co')
ANILIST_USER_AGENT = _env('ANILIST_USER_AGENT', 'Purewo/CyberStream/1.21.0 metadata matcher')
ANILIST_TIMEOUT_SECONDS = _env_float('ANILIST_TIMEOUT_SECONDS', 10)

# --- Tencent Video metadata manual matcher ---
# Manual-only fallback source for explicit metadata matching. It is intentionally
# not part of the default scan provider order.
TENCENT_VIDEO_TIMEOUT_SECONDS = _env_float('TENCENT_VIDEO_TIMEOUT_SECONDS', 8)
TENCENT_VIDEO_USER_AGENT = _env(
    'TENCENT_VIDEO_USER_AGENT',
    'Purewo/CyberStream/1.21.0 metadata manual matcher',
)

# --- 聚合搜索（外部影视资源站）---
# 抓取逻辑在 backend/app/services/aggregator/。每个请求只打一个 source，
# 不并发遍历所有源（契合各站点反爬限制）。部分站点在国内服务器上需经
# 本机代理访问，可用 CYBER_AGGREGATOR_PROXY_URL 统一配置。
AGGREGATOR_DEFAULT_SOURCE = _env('CYBER_AGGREGATOR_DEFAULT_SOURCE', 'rarbt')
AGGREGATOR_PROXY_URL = _normalize_proxy_url(_env('CYBER_AGGREGATOR_PROXY_URL', ''))
AGGREGATOR_BTBTLA_PROXY = _normalize_proxy_url(
    _env('CYBER_AGGREGATOR_BTBTLA_PROXY', AGGREGATOR_PROXY_URL or 'http://127.0.0.1:10808')
)
AGGREGATOR_RARBT_PROXY = _normalize_proxy_url(
    _env('CYBER_AGGREGATOR_RARBT_PROXY', AGGREGATOR_PROXY_URL or '')
)

# --- 缓存目录 ---
# 冻结模式下落 LOCALAPPDATA/CyberStream/cache（DATA_DIR 已经是它）；
# 源码模式保持仓库根目录的 cache/ 跟现有逻辑兼容。
CACHE_DIR = os.path.join(DATA_DIR, "cache")
IMAGE_ASSET_MAX_BYTES = _env_int('CYBER_IMAGE_ASSET_MAX_BYTES', 20 * 1024 * 1024)
IMAGE_ASSET_TIMEOUT_SECONDS = _env_float('CYBER_IMAGE_ASSET_TIMEOUT_SECONDS', 15)
IMAGE_ASSET_MAX_REDIRECTS = _env_int('CYBER_IMAGE_ASSET_MAX_REDIRECTS', 5)
IMAGE_ASSET_CACHE_MAX_AGE_SECONDS = _env_int('CYBER_IMAGE_ASSET_CACHE_MAX_AGE_SECONDS', 24 * 60 * 60)
IMAGE_ASSET_PUBLIC_BASE_URL = _env('CYBER_IMAGE_ASSET_PUBLIC_BASE_URL', None)
IMAGE_ASSET_CDN_PURGE_PROVIDER = _env('CYBER_IMAGE_ASSET_CDN_PURGE_PROVIDER', 'noop')

# --- Super CDN 静态资产加速 ---
# 视频主播放链路仍走原始 storage provider；这里仅用于海报、背景图、字幕等小型静态资产。
CDN_PROVIDER = _env('CYBER_CDN_PROVIDER', 'none')
SUPERCDN_ENABLED = _env_bool('CYBER_SUPERCDN_ENABLED', False)
SUPERCDN_URL = _env('CYBER_SUPERCDN_URL', _env('SUPERCDN_URL', None))
SUPERCDN_TOKEN = _env('CYBER_SUPERCDN_TOKEN', _env('SUPERCDN_TOKEN', None))
SUPERCDN_BUCKET = _env('CYBER_SUPERCDN_BUCKET', 'cyberstream-cn-assets')
SUPERCDN_BUCKET_NAME = _env('CYBER_SUPERCDN_BUCKET_NAME', 'CyberStream CN Assets')
SUPERCDN_BUCKET_DESCRIPTION = _env(
    'CYBER_SUPERCDN_BUCKET_DESCRIPTION',
    'CyberStream non-video static assets for domestic all-line acceleration',
)
SUPERCDN_ROUTE_PROFILE = _env('CYBER_SUPERCDN_ROUTE_PROFILE', 'china_all')
SUPERCDN_BUCKET_ALLOWED_TYPES = _env('CYBER_SUPERCDN_BUCKET_ALLOWED_TYPES', 'image,document')
SUPERCDN_BUCKET_CACHE_CONTROL = _env('CYBER_SUPERCDN_BUCKET_CACHE_CONTROL', 'public, max-age=86400')
SUPERCDN_AUTO_CREATE_BUCKET = _env_bool('CYBER_SUPERCDN_AUTO_CREATE_BUCKET', True)
SUPERCDN_AUTO_UPLOAD_IMAGES = _env_bool('CYBER_SUPERCDN_AUTO_UPLOAD_IMAGES', True)
SUPERCDN_AUTO_UPLOAD_SUBTITLES = _env_bool('CYBER_SUPERCDN_AUTO_UPLOAD_SUBTITLES', True)
SUPERCDN_SERVE_ASSET_URLS = _env_bool('CYBER_SUPERCDN_SERVE_ASSET_URLS', True)
SUPERCDN_WARMUP_AFTER_UPLOAD = _env_bool('CYBER_SUPERCDN_WARMUP_AFTER_UPLOAD', False)
SUPERCDN_WARMUP_METHOD = _env('CYBER_SUPERCDN_WARMUP_METHOD', 'HEAD')
SUPERCDN_TIMEOUT_SECONDS = _env_float('CYBER_SUPERCDN_TIMEOUT_SECONDS', 20)
SUPERCDN_MAX_FILE_SIZE_BYTES = _env_int('CYBER_SUPERCDN_MAX_FILE_SIZE_BYTES', 100 * 1024 * 1024)

# --- 官方客户端更新检查 ---
# 后端只暴露只读更新检查接口；真实下载地址由运行时发布清单提供，且必须是 CDN URL。
UPDATE_DEFAULT_CHANNEL = _env('CYBER_UPDATE_DEFAULT_CHANNEL', 'stable')
UPDATE_MANIFEST_PATH = _env('CYBER_UPDATE_MANIFEST_PATH', os.path.join(DATA_DIR, "update-manifest.json"))
UPDATE_CDN_URL_PREFIXES = _env('CYBER_UPDATE_CDN_URL_PREFIXES', SUPERCDN_URL or '')

# --- 反向代理 / 外部 URL ---
# 后端通常运行在反向代理之后。ProxyFix 让 Flask 信任标准 X-Forwarded-* 头，
# 避免 url_for(..., _external=True) 在 HTTPS 站点后面错误生成 http:// 链接。
TRUST_PROXY_HEADERS = _env_bool('CYBER_TRUST_PROXY_HEADERS', True)
PROXY_FIX_X_FOR = _env_int('CYBER_PROXY_FIX_X_FOR', 1)
PROXY_FIX_X_PROTO = _env_int('CYBER_PROXY_FIX_X_PROTO', 1)
PROXY_FIX_X_HOST = _env_int('CYBER_PROXY_FIX_X_HOST', 1)
PROXY_FIX_X_PORT = _env_int('CYBER_PROXY_FIX_X_PORT', 1)
PROXY_FIX_X_PREFIX = _env_int('CYBER_PROXY_FIX_X_PREFIX', 1)
PREFERRED_URL_SCHEME = _env('CYBER_PREFERRED_URL_SCHEME', _env('PREFERRED_URL_SCHEME', 'http'))
BACKEND_PUBLIC_BASE_URL = _env(
    'CYBER_BACKEND_PUBLIC_BASE_URL',
    _env('CYBER_PUBLIC_BASE_URL', None),
)

# --- 最小 API 鉴权 ---
# 设置 CYBER_API_TOKEN 后自动启用；未设置时保持本地开发与现有前端兼容。
API_TOKEN = _env('CYBER_API_TOKEN', _env('API_TOKEN', ''))
AUTH_ENABLED = _env_bool('CYBER_AUTH_ENABLED', bool(API_TOKEN))
AUTH_EXEMPT_MEDIA_GET = _env_bool('CYBER_AUTH_EXEMPT_MEDIA_GET', True)

# --- 托管 AList / 光鸭云盘 ---
# CyberStream 只暴露自己的 HTTPS API；AList 应绑定在本机地址，由后端通过
# 管理 API 创建光鸭挂载，并在播放时解析 localhost /d 的 302 直链。
MANAGED_ALIST_ENABLED = _env_bool('CYBER_MANAGED_ALIST_ENABLED', False)
MANAGED_ALIST_BASE_URL = _env('CYBER_MANAGED_ALIST_BASE_URL', 'http://127.0.0.1:5244')
MANAGED_ALIST_USERNAME = _env('CYBER_MANAGED_ALIST_USERNAME', 'admin')
MANAGED_ALIST_PASSWORD = _env('CYBER_MANAGED_ALIST_PASSWORD', '')
MANAGED_ALIST_TOKEN = _env('CYBER_MANAGED_ALIST_TOKEN', '')
MANAGED_ALIST_MOUNT_PREFIX = _env('CYBER_MANAGED_ALIST_MOUNT_PREFIX', '/cyberstream')
MANAGED_ALIST_TIMEOUT_SECONDS = _env_float('CYBER_MANAGED_ALIST_TIMEOUT_SECONDS', 30)
MANAGED_ALIST_VERIFY_SSL = _env_bool('CYBER_MANAGED_ALIST_VERIFY_SSL', False)

# --- 托管 OpenList / 天翼云盘 / QuarkTV / UCTV ---
# OpenList 与 AList 分开运行：当前 AList 负责光鸭，OpenList 负责 189CloudTV、
# QuarkTV、UCTV 扫码登录。OpenList 同样只绑定本机地址，由后端解析播放 302 直链。
MANAGED_OPENLIST_ENABLED = _env_bool('CYBER_MANAGED_OPENLIST_ENABLED', False)
MANAGED_OPENLIST_BASE_URL = _env('CYBER_MANAGED_OPENLIST_BASE_URL', 'http://127.0.0.1:5245')
MANAGED_OPENLIST_USERNAME = _env('CYBER_MANAGED_OPENLIST_USERNAME', 'admin')
MANAGED_OPENLIST_PASSWORD = _env('CYBER_MANAGED_OPENLIST_PASSWORD', '')
MANAGED_OPENLIST_TOKEN = _env('CYBER_MANAGED_OPENLIST_TOKEN', '')
MANAGED_OPENLIST_MOUNT_PREFIX = _env('CYBER_MANAGED_OPENLIST_MOUNT_PREFIX', '/cyberstream')
MANAGED_OPENLIST_TIMEOUT_SECONDS = _env_float('CYBER_MANAGED_OPENLIST_TIMEOUT_SECONDS', 30)
MANAGED_OPENLIST_VERIFY_SSL = _env_bool('CYBER_MANAGED_OPENLIST_VERIFY_SSL', False)
MANAGED_OPENLIST_ALIYUNDRIVE_AUTH_MODE = _env('CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_AUTH_MODE', 'auto')
MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_ID = _env('CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_ID', '')
MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_SECRET = _env('CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_SECRET', '')
MANAGED_OPENLIST_ALIYUNDRIVE_PUBLIC_API_BASE_URL = _env(
    'CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_PUBLIC_API_BASE_URL',
    'https://api.oplist.org/alicloud',
)
MANAGED_OPENLIST_ALIYUNDRIVE_QR_AUTHORIZE_URL = _env(
    'CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_QR_AUTHORIZE_URL',
    'https://openapi.aliyundrive.com/oauth/authorize/qrcode',
)
MANAGED_OPENLIST_ALIYUNDRIVE_QR_STATUS_URL_TEMPLATE = _env(
    'CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_QR_STATUS_URL_TEMPLATE',
    'https://openapi.aliyundrive.com/oauth/qrcode/{sid}/status',
)
MANAGED_OPENLIST_ALIYUNDRIVE_TOKEN_URL = _env(
    'CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_TOKEN_URL',
    'https://openapi.aliyundrive.com/oauth/access_token',
)
MANAGED_OPENLIST_ALIYUNDRIVE_RENEW_API_URL = _env(
    'CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_RENEW_API_URL',
    'https://api.oplist.org/alicloud/renewapi',
)
MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_ID = _env('CYBER_MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_ID', '')
MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_SECRET = _env('CYBER_MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_SECRET', '')
MANAGED_OPENLIST_BAIDUNETDISK_AUTHORIZE_URL = _env(
    'CYBER_MANAGED_OPENLIST_BAIDUNETDISK_AUTHORIZE_URL',
    'https://openapi.baidu.com/oauth/2.0/authorize',
)
MANAGED_OPENLIST_BAIDUNETDISK_TOKEN_URL = _env(
    'CYBER_MANAGED_OPENLIST_BAIDUNETDISK_TOKEN_URL',
    'https://openapi.baidu.com/oauth/2.0/token',
)
MANAGED_OPENLIST_BAIDUNETDISK_RENEW_API_URL = _env(
    'CYBER_MANAGED_OPENLIST_BAIDUNETDISK_RENEW_API_URL',
    'https://api.oplist.org/baiduyun/renewapi',
)

# --- 用户管理 ---
USER_MANAGEMENT_ENABLED = _env_bool('CYBER_USER_MANAGEMENT_ENABLED', False)
SESSION_SECRET = _env('CYBER_SESSION_SECRET', _env('SECRET_KEY', ''))
SECRET_KEY = SESSION_SECRET or _env('FLASK_SECRET_KEY', 'cyberstream-dev-session-secret')
SESSION_COOKIE_NAME = _env('CYBER_SESSION_COOKIE_NAME', 'cyberstream_session')
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = _env_bool('CYBER_SESSION_COOKIE_SECURE', False)
SESSION_COOKIE_SAMESITE = _env('CYBER_SESSION_COOKIE_SAMESITE', 'Lax')
SESSION_DAYS = _env_int('CYBER_SESSION_DAYS', 30)
PERMANENT_SESSION_LIFETIME = timedelta(days=SESSION_DAYS)
BOOTSTRAP_ADMIN_USERNAME = _env('CYBER_BOOTSTRAP_ADMIN_USERNAME', '')
BOOTSTRAP_ADMIN_PASSWORD = _env('CYBER_BOOTSTRAP_ADMIN_PASSWORD', '')
BOOTSTRAP_ADMIN_DISPLAY_NAME = _env('CYBER_BOOTSTRAP_ADMIN_DISPLAY_NAME', 'Administrator')
CORS_SUPPORTS_CREDENTIALS = _env_bool('CYBER_CORS_SUPPORTS_CREDENTIALS', USER_MANAGEMENT_ENABLED)
LOGIN_RATE_LIMIT_ENABLED = _env_bool('CYBER_LOGIN_RATE_LIMIT_ENABLED', True)
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = _env_int('CYBER_LOGIN_RATE_LIMIT_MAX_ATTEMPTS', 5)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = _env_int('CYBER_LOGIN_RATE_LIMIT_WINDOW_SECONDS', 5 * 60)
LOGIN_RATE_LIMIT_LOCK_SECONDS = _env_int('CYBER_LOGIN_RATE_LIMIT_LOCK_SECONDS', 15 * 60)
LOGIN_RATE_LIMIT_MAX_BUCKETS = _env_int('CYBER_LOGIN_RATE_LIMIT_MAX_BUCKETS', 10000)

# --- 在线字幕 ---
GET_SUBTITLES_SKILL_DIR = _env(
    'GET_SUBTITLES_SKILL_DIR',
    None,
)
ONLINE_SUBTITLE_SEARCH_TIMEOUT_SECONDS = _env_float('CYBER_ONLINE_SUBTITLE_SEARCH_TIMEOUT_SECONDS', 8.0)
ONLINE_SUBTITLE_SRTKU_SEARCH_TIMEOUT_SECONDS = _env_float('CYBER_ONLINE_SUBTITLE_SRTKU_SEARCH_TIMEOUT_SECONDS', 5.0)
ONLINE_SUBTITLE_PROXY_ENABLED = _env_bool('CYBER_ONLINE_SUBTITLE_PROXY_ENABLED', False)
ONLINE_SUBTITLE_PROXY_URL = _normalize_proxy_url(_env('CYBER_ONLINE_SUBTITLE_PROXY_URL', ''))
ONLINE_SUBTITLE_PROXIES = _build_http_proxy_map(ONLINE_SUBTITLE_PROXY_URL) if ONLINE_SUBTITLE_PROXY_ENABLED else None
SUBTITLE_MANUAL_UPLOAD_MAX_BYTES = _env_int('CYBER_SUBTITLE_MANUAL_UPLOAD_MAX_BYTES', 20 * 1024 * 1024)
SUBTITLE_WEBVTT_CONVERSION_MAX_BYTES = _env_int(
    'CYBER_SUBTITLE_WEBVTT_CONVERSION_MAX_BYTES',
    0,
)
ONLINE_SUBTITLE_EXTRACTED_MAX_BYTES = _env_int('CYBER_ONLINE_SUBTITLE_EXTRACTED_MAX_BYTES', 20 * 1024 * 1024)
ONLINE_SUBTITLE_NESTED_ARCHIVE_MAX_BYTES = _env_int('CYBER_ONLINE_SUBTITLE_NESTED_ARCHIVE_MAX_BYTES', 20 * 1024 * 1024)
ONLINE_SUBTITLE_DOWNLOAD_MAX_BYTES = _env_int('CYBER_ONLINE_SUBTITLE_DOWNLOAD_MAX_BYTES', 20 * 1024 * 1024)
ONLINE_SUBTITLE_ARCHIVE_MAX_ENTRIES = _env_int('CYBER_ONLINE_SUBTITLE_ARCHIVE_MAX_ENTRIES', 200)
ONLINE_SUBTITLE_ARCHIVE_TOTAL_MAX_BYTES = _env_int('CYBER_ONLINE_SUBTITLE_ARCHIVE_TOTAL_MAX_BYTES', 40 * 1024 * 1024)

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
IGNORE_FOLDERS = [
    'BDMV', 'CERTIFICATE', '@EADIR', '$RECYCLE.BIN', 'SYSTEM VOLUME INFORMATION', '__MACOSX',
    'BACKUP', 'RECOVERY', 'EXTRAS', 'SPECIAL FEATURES', 'DELETED SCENES', 'STORYBOARDS',
    'FEATURETTES', 'BONUS', 'BONUS FEATURES', 'SAMPLES',
]
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
APP_VERSION = "1.21.0"

# --- 维护任务持久化 ---
MAINTENANCE_JOB_RESULT_ITEM_LIMIT = _env_int('CYBER_MAINTENANCE_JOB_RESULT_ITEM_LIMIT', 20)
MAINTENANCE_JOB_RETENTION_DAYS = _env_int('CYBER_MAINTENANCE_JOB_RETENTION_DAYS', 30)
