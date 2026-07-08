from contextlib import contextmanager
import logging
import os
import re
import sys
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit

from flask import Blueprint, current_app, request

from backend.app import config as backend_config
from backend.app.services.accounts import account_scope
from backend.app.services.scanner import scanner_engine
from backend.app.security import get_current_account_id
from backend.app.services.tmdb import scraper as tmdb_scraper
from backend.app.services.update_check import get_update_check_payload
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__, url_prefix='/api/v1')


def _scan_background_task(app, account_id=None):
    with app.app_context():
        with account_scope(account_id):
            try:
                scanner_engine.scan(lock_acquired=True)
            except Exception as e:
                logger.exception("Background scan failed error=%s", e)


@system_bp.route('/scan', methods=['GET'])
def get_scan_status():
    return api_response(data=scanner_engine.get_status())


@system_bp.route('/scan', methods=['POST'])
def trigger_scan():
    if not scanner_engine.try_start_scan():
        return api_error(code=42900, msg="Scanner is already running", http_status=429)

    account_id = get_current_account_id()
    if current_app.config.get("MULTI_TENANT_ENABLED") and not account_id:
        scanner_engine.finish_scan()
        return api_error(code=40340, msg="Current account required for scan", http_status=403)

    app = current_app._get_current_object()
    thread = threading.Thread(target=_scan_background_task, args=(app, account_id))
    thread.start()
    return api_response(msg="Scan task accepted", http_status=202)


# ---- Official client update check ----------------------------------------


@system_bp.route('/system/update-check', methods=['GET'])
def get_system_update_check():
    """Return the current official desktop release and CDN-only downloads.

    This is intentionally read-only and public: a desktop client must be able
    to check for an installer update before login or backend configuration.
    CDN publication remains an operational concern; the API only exposes
    URLs already present in the controlled release manifest.
    """
    return api_response(data=get_update_check_payload(
        current_version=request.args.get("current_version"),
        current_release=request.args.get("current_release"),
        channel=request.args.get("channel"),
        platform=request.args.get("platform"),
        arch=request.args.get("arch"),
        variant=request.args.get("variant"),
    ))


# ---- TMDB config ---------------------------------------------------------
#
# 桌面单机分发场景下，用户没有 NAS 那一套 systemd / docker env 注入流程，
# 必须能通过 UI 配置 TMDB Token + 代理。两端约定走 .env.local：
#   - 前端 PUT /system/tmdb-config 提交 { token?, proxy_enabled, proxy_url? }
#   - 后端把对应值写到 %LOCALAPPDATA%\CyberStream\.env.local
#   - 同时更新 os.environ + current_app.config + backend.config 模块属性
#     这样下一次扫描的 TmdbMetadataProvider 能立刻读到新值，无需重启 app
#   - GET 永远不回明文 token —— 只回 token_set:bool，避免 API 层泄露
#
# 之所以不存数据库：跟"用户系统/scope"耦合度低、且在用户看来 TMDB 配置
# 是"环境/凭证"性质（跟 storage source 凭证类比），更适合走 env 文件这种
# 半受信的本机存储；同时跟 NAS 部署保持一致 (.env.local 是双方都接受的
# 单一真值入口)。

_ENV_KEYS = {
    "token": "TMDB_TOKEN",
    "proxy_enabled": "TMDB_PROXY_ENABLED",
    "proxy_url": "TMDB_PROXY_URL",
}

# 仅允许这一组 key 通过 PUT 接口写入 .env.local，避免接口被滥用作"任意
# env 写入器"。后续要扩展（比如 BANGUMI 配置）就在这里加。
_WRITABLE_ENV_KEYS = set(_ENV_KEYS.values())
_ENV_UPDATE_LOCK = threading.RLock()
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_ALLOWED_PROXY_SCHEMES = {"http", "https", "socks5"}


def _data_dir():
    """跟 backend.config 的 DATA_DIR 保持一致 —— 冻结模式 LOCALAPPDATA、
    源码 dev 模式仓库根（.env.local 历来放仓库根）。直接复用 config 里
    已经算好的路径，避免双份解析逻辑漂移。
    """
    return backend_config.DATA_DIR


def _env_local_path():
    return os.path.join(_data_dir(), ".env.local")


def _read_env_file(path):
    """轻量 .env 解析：返回 [(key, line)] 保留原始行；非 KEY=VAL 行原样保留。
    PyInstaller 冻结时也能用，不依赖 dotenv 库自身的解析。
    """
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


@contextmanager
def _env_file_update_lock(path):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    lock_path = f"{path}.lock"
    with _ENV_UPDATE_LOCK:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
        with os.fdopen(lock_fd, "a+", encoding="utf-8") as lock_file:
            try:
                import fcntl
            except ImportError:
                fcntl = None
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_env_file(path, lines):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".env.local.", suffix=".tmp", dir=directory, text=True)
    try:
        os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for line in lines:
                f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def _upsert_env_lines(lines, updates):
    """把 updates 里的 KEY=VAL 合并进 .env 文本行。
    已有的行就替换，没有的追加在末尾。VALUE 为 None 时表示删除该 KEY 行。
    其它注释 / 空行一概保留。
    """
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
    new_lines = []
    seen = set()
    for raw in lines:
        match = pattern.match(raw)
        if not match:
            new_lines.append(raw)
            continue
        key = match.group(1)
        if key not in updates:
            new_lines.append(raw)
            continue
        seen.add(key)
        value = updates[key]
        if value is None:
            # 删除：完全不写回
            continue
        new_lines.append(f"{key}={value}")
    for key, value in updates.items():
        if key in seen or value is None:
            continue
        new_lines.append(f"{key}={value}")
    return new_lines


def _contains_unsafe_env_characters(value):
    return bool(_CONTROL_CHARACTER_RE.search(value)) or any(char.isspace() for char in value)


def _validate_proxy_url(value):
    stripped = value.strip()
    if len(stripped) > 2048 or _contains_unsafe_env_characters(stripped):
        return None
    try:
        parsed = urlsplit(stripped)
        if parsed.scheme.lower() not in _ALLOWED_PROXY_SCHEMES or not parsed.hostname:
            return None
        parsed.port
    except ValueError:
        return None
    return stripped


def _redact_proxy_url(value):
    raw = str(value or "").strip()
    if not raw:
        return "", False
    try:
        parsed = urlsplit(raw)
        if parsed.username is None and parsed.password is None:
            return raw, False
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        netloc = f"***@{host}" if parsed.password is None else f"***:***@{host}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)), True
    except ValueError:
        return "", False


def _runtime_tmdb_token_pool():
    cyber_pool = os.environ.get("CYBER_TMDB_TOKEN_POOL")
    legacy_pool = os.environ.get("TMDB_TOKEN_POOL")
    single_token = os.environ.get("TMDB_TOKEN")
    if cyber_pool in ("", None):
        cyber_pool = current_app.config.get("CYBER_TMDB_TOKEN_POOL", "")
    if legacy_pool in ("", None):
        legacy_pool = current_app.config.get("TMDB_TOKEN_POOL_RAW", "")
    if single_token in ("", None):
        single_token = current_app.config.get("TMDB_TOKEN", "")
    return backend_config._build_tmdb_token_pool(cyber_pool, legacy_pool, single_token)


def _tmdb_config_payload():
    token_pool = _runtime_tmdb_token_pool()
    proxy_url = os.environ.get("TMDB_PROXY_URL") or current_app.config.get("TMDB_PROXY_URL") or ""
    proxy_enabled_raw = os.environ.get("TMDB_PROXY_ENABLED")
    if proxy_enabled_raw not in ("", None):
        proxy_enabled = str(proxy_enabled_raw).strip().lower() in {"1", "true", "yes", "on"}
    else:
        proxy_enabled = current_app.config.get("TMDB_PROXY_ENABLED")
        if proxy_enabled is None:
            proxy_enabled = True
    visible_proxy_url, proxy_url_redacted = _redact_proxy_url(proxy_url)
    return {
        "token_set": bool(token_pool),
        "token_pool_size": len(token_pool),
        "token_pool_enabled": len(token_pool) > 1,
        "proxy_enabled": bool(proxy_enabled),
        "proxy_url": visible_proxy_url,
        "proxy_url_redacted": proxy_url_redacted,
    }


def _apply_environment_updates(updates):
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _refresh_runtime_config():
    """把 os.environ 的最新值同步到 current_app.config 和 backend.config 模块。

    后端各 provider 既有读 current_app.config 的、也有读 backend.config
    模块属性（比如 backend.config.TMDB_TOKEN）的；都要刷新一遍才能保证
    "保存即生效、不重启"。代理 map 是派生量，单独重算。
    """
    token = os.environ.get("TMDB_TOKEN", "")
    cyber_token_pool = os.environ.get("CYBER_TMDB_TOKEN_POOL", "")
    token_pool_raw = os.environ.get("TMDB_TOKEN_POOL", "")
    token_pool = backend_config._build_tmdb_token_pool(cyber_token_pool, token_pool_raw, token)
    proxy_url_raw = os.environ.get("TMDB_PROXY_URL", "")
    proxy_enabled_raw = os.environ.get("TMDB_PROXY_ENABLED", "")
    proxy_enabled = (
        str(proxy_enabled_raw).strip().lower() in {"1", "true", "yes", "on"}
        if proxy_enabled_raw not in ("", None)
        else True  # 默认 True，跟 backend.config 默认值一致
    )

    proxy_url = backend_config._normalize_proxy_url(proxy_url_raw)
    proxies = backend_config._build_http_proxy_map(proxy_url) if proxy_enabled else None

    # 模块属性 —— 直接拿模块对象写
    backend_config.TMDB_TOKEN = token
    backend_config.CYBER_TMDB_TOKEN_POOL = cyber_token_pool
    backend_config.TMDB_TOKEN_POOL_RAW = token_pool_raw
    backend_config.TMDB_TOKEN_POOL = token_pool
    backend_config.TMDB_PROXY_URL = proxy_url
    backend_config.TMDB_PROXY_ENABLED = proxy_enabled
    backend_config.TMDB_PROXIES = proxies
    # PROXIES 是别名（早期代码兼容），跟 TMDB_PROXIES 同步
    backend_config.PROXIES = proxies

    # current_app.config —— Flask 把 backend.config 的属性 from_object 进
    # 来过一次，但运行时不会跟踪原模块的变化，所以这里手工同步。
    current_app.config["TMDB_TOKEN"] = token
    current_app.config["CYBER_TMDB_TOKEN_POOL"] = cyber_token_pool
    current_app.config["TMDB_TOKEN_POOL_RAW"] = token_pool_raw
    current_app.config["TMDB_TOKEN_POOL"] = token_pool
    current_app.config["TMDB_PROXY_URL"] = proxy_url
    current_app.config["TMDB_PROXY_ENABLED"] = proxy_enabled
    current_app.config["TMDB_PROXIES"] = proxies
    current_app.config["PROXIES"] = proxies

    from backend.app.services import tmdb as tmdb_module
    tmdb_module.scraper.refresh_runtime_config(reset_session=True)


@system_bp.route('/system/tmdb-config', methods=['GET'])
def get_tmdb_config():
    """返回当前 TMDB 相关环境变量的"已配置"状态。
    永远不回明文 token —— 只回 token_set:bool。前端如需"清空 token"自己
    维护输入框 placeholder 即可。
    """
    return api_response(data=_tmdb_config_payload())


@system_bp.route('/system/tmdb-config/check', methods=['GET'])
def check_tmdb_config():
    """Actively verify that the configured TMDB token can authenticate.

    This endpoint intentionally returns a normal API response even when the
    token is missing, invalid, or TMDB is unreachable. The frontend can gate
    scraping on data.ready without treating expected configuration states as
    transport-level API failures.
    """
    try:
        _refresh_runtime_config()
    except Exception as e:
        logger.exception("Failed to refresh TMDB runtime config before check error=%s", e)
        return api_error(code=50011, msg="刷新 TMDB 运行配置失败", http_status=500)

    return api_response(data=tmdb_scraper.check_token_status())


@system_bp.route('/system/tmdb-config', methods=['PUT'])
def put_tmdb_config():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error(code=40027, msg="请求体必须是 JSON 对象")

    updates = {}
    response_data = {}

    # token：传了非空字符串就更新；传了空字符串视为"清空"；没传则保留。
    if "token" in payload:
        token_value = payload.get("token")
        if token_value is None or (isinstance(token_value, str) and not token_value.strip()):
            updates[_ENV_KEYS["token"]] = None  # 删除
        elif isinstance(token_value, str):
            stripped = token_value.strip()
            if len(stripped) > 4096:
                return api_error(code=40020, msg="TMDB token 过长（>4096 字符），请检查输入。")
            if _contains_unsafe_env_characters(stripped):
                return api_error(code=40028, msg="TMDB token 不得包含空白或控制字符")
            updates[_ENV_KEYS["token"]] = stripped
        else:
            return api_error(code=40021, msg="token 字段类型错误，应为字符串")

    if "proxy_enabled" in payload:
        v = payload.get("proxy_enabled")
        if not isinstance(v, bool):
            return api_error(code=40022, msg="proxy_enabled 字段类型错误，应为布尔")
        updates[_ENV_KEYS["proxy_enabled"]] = "true" if v else "false"
        response_data["proxy_enabled"] = v

    if "proxy_url" in payload:
        url = payload.get("proxy_url")
        if url is None or (isinstance(url, str) and not url.strip()):
            updates[_ENV_KEYS["proxy_url"]] = None
            response_data["proxy_url"] = ""
            response_data["proxy_url_redacted"] = False
        elif isinstance(url, str):
            stripped = url.strip()
            current_proxy_url = (
                os.environ.get(_ENV_KEYS["proxy_url"])
                or current_app.config.get(_ENV_KEYS["proxy_url"])
                or ""
            )
            visible_current_proxy, current_proxy_redacted = _redact_proxy_url(current_proxy_url)
            if current_proxy_redacted and stripped == visible_current_proxy:
                response_data["proxy_url"] = visible_current_proxy
                response_data["proxy_url_redacted"] = True
            else:
                normalized_url = _validate_proxy_url(stripped)
                if normalized_url is None:
                    return api_error(
                        code=40023,
                        msg="代理地址格式不对（仅支持 http://、https:// 或 socks5://，且不得包含空白或控制字符）",
                    )
                updates[_ENV_KEYS["proxy_url"]] = normalized_url
                visible_url, redacted = _redact_proxy_url(normalized_url)
                response_data["proxy_url"] = visible_url
                response_data["proxy_url_redacted"] = redacted
        else:
            return api_error(code=40024, msg="proxy_url 字段类型错误，应为字符串")

    if not updates:
        return api_error(code=40025, msg="没有要更新的字段（支持：token / proxy_enabled / proxy_url）")

    for key in updates:
        if key not in _WRITABLE_ENV_KEYS:
            return api_error(code=40026, msg=f"非法 env key: {key}")

    try:
        env_path = _env_local_path()
        with _env_file_update_lock(env_path):
            lines = _read_env_file(env_path)
            new_lines = _upsert_env_lines(lines, updates)
            _write_env_file(env_path, new_lines)
            _apply_environment_updates(updates)
    except Exception as e:
        logger.exception("Failed to write .env.local error=%s", e)
        return api_error(code=50010, msg="写入 .env.local 失败", http_status=500)

    try:
        _refresh_runtime_config()
    except Exception as e:
        logger.exception("Failed to refresh runtime config error=%s", e)
        result = _tmdb_config_payload()
        result.update(response_data)
        result["hot_reload"] = False
        return api_response(
            data=result,
            msg="配置已保存，但热更新失败。重启后自动生效。",
        )

    result = _tmdb_config_payload()
    result.update(response_data)
    result["hot_reload"] = True
    return api_response(data=result, msg="TMDB 配置已保存")
