import logging
import os
import re
import sys
import threading

from flask import Blueprint, current_app, request

from backend.app import config as backend_config
from backend.app.extensions import db
from backend.app.models import LibrarySource
from backend.app.services.scanner import scanner_engine
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__, url_prefix='/api/v1')


def _scan_background_task(app):
    with app.app_context():
        try:
            scanner_engine.scan(lock_acquired=True)
        except Exception as e:
            logger.exception("Background scan failed error=%s", e)


@system_bp.route('/scan', methods=['GET'])
def get_scan_status():
    return api_response(data=scanner_engine.get_status())


@system_bp.route('/scan', methods=['POST'])
def trigger_scan():
    # 安全护栏：未配置任何媒体库的目录绑定时，拒绝触发"全盘扫描"。
    # 历史上 scanner_engine.scan() 不带参数 = 遍历所有 storage source 的根
    # 目录，当用户存储源指向云盘根（OneDrive / 天翼云 / AList 顶级）时
    # 会瞬间扫几千个 GB 的数据，触发限流 / 流量爆炸。**任何场景下**只要
    # 没有 enabled 的 library_sources 绑定就直接拒，前端正确引导用户去
    # 「资源库 → 添加目录」绑定具体路径。
    has_binding = db.session.query(LibrarySource.id).filter_by(is_enabled=True).first() is not None
    if not has_binding:
        return api_error(
            code=40013,
            msg="未配置任何媒体库的目录绑定，无法启动扫描。请先在「资源库」中绑定要扫描的具体目录。",
        )

    if not scanner_engine.try_start_scan():
        return api_error(code=42900, msg="Scanner is already running", http_status=429)

    app = current_app._get_current_object()
    thread = threading.Thread(target=_scan_background_task, args=(app,))
    thread.start()
    return api_response(msg="Scan task accepted", http_status=202)


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


def _write_env_file(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")


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


def _refresh_runtime_config():
    """把 os.environ 的最新值同步到 current_app.config 和 backend.config 模块。

    后端各 provider 既有读 current_app.config 的、也有读 backend.config
    模块属性（比如 backend.config.TMDB_TOKEN）的；都要刷新一遍才能保证
    "保存即生效、不重启"。代理 map 是派生量，单独重算。
    """
    token = os.environ.get("TMDB_TOKEN", "")
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
    backend_config.TMDB_PROXY_URL = proxy_url
    backend_config.TMDB_PROXY_ENABLED = proxy_enabled
    backend_config.TMDB_PROXIES = proxies
    # PROXIES 是别名（早期代码兼容），跟 TMDB_PROXIES 同步
    backend_config.PROXIES = proxies

    # current_app.config —— Flask 把 backend.config 的属性 from_object 进
    # 来过一次，但运行时不会跟踪原模块的变化，所以这里手工同步。
    current_app.config["TMDB_TOKEN"] = token
    current_app.config["TMDB_PROXY_URL"] = proxy_url
    current_app.config["TMDB_PROXY_ENABLED"] = proxy_enabled
    current_app.config["TMDB_PROXIES"] = proxies
    current_app.config["PROXIES"] = proxies


@system_bp.route('/system/tmdb-config', methods=['GET'])
def get_tmdb_config():
    """返回当前 TMDB 相关环境变量的"已配置"状态。
    永远不回明文 token —— 只回 token_set:bool。前端如需"清空 token"自己
    维护输入框 placeholder 即可。
    """
    token = os.environ.get("TMDB_TOKEN") or current_app.config.get("TMDB_TOKEN") or ""
    proxy_url = os.environ.get("TMDB_PROXY_URL") or current_app.config.get("TMDB_PROXY_URL") or ""
    proxy_enabled = current_app.config.get("TMDB_PROXY_ENABLED")
    if proxy_enabled is None:
        proxy_enabled = True  # 跟 backend.config 默认一致
    return api_response(data={
        "token_set": bool(token),
        "proxy_enabled": bool(proxy_enabled),
        "proxy_url": proxy_url or "",
    })


@system_bp.route('/system/tmdb-config', methods=['PUT'])
def put_tmdb_config():
    payload = request.get_json(silent=True) or {}

    updates = {}
    response_data = {}

    # token：传了非空字符串就更新；传了空字符串视为"清空"；没传则保留。
    if "token" in payload:
        token_value = payload.get("token")
        if token_value is None or (isinstance(token_value, str) and not token_value.strip()):
            updates[_ENV_KEYS["token"]] = None  # 删除
            os.environ.pop(_ENV_KEYS["token"], None)
            response_data["token_set"] = False
        elif isinstance(token_value, str):
            stripped = token_value.strip()
            if len(stripped) > 4096:
                return api_error(code=40020, msg="TMDB token 过长（>4096 字符），请检查输入。")
            updates[_ENV_KEYS["token"]] = stripped
            os.environ[_ENV_KEYS["token"]] = stripped
            response_data["token_set"] = True
        else:
            return api_error(code=40021, msg="token 字段类型错误，应为字符串")

    if "proxy_enabled" in payload:
        v = payload.get("proxy_enabled")
        if not isinstance(v, bool):
            return api_error(code=40022, msg="proxy_enabled 字段类型错误，应为布尔")
        updates[_ENV_KEYS["proxy_enabled"]] = "true" if v else "false"
        os.environ[_ENV_KEYS["proxy_enabled"]] = "true" if v else "false"
        response_data["proxy_enabled"] = v

    if "proxy_url" in payload:
        url = payload.get("proxy_url")
        if url is None or (isinstance(url, str) and not url.strip()):
            updates[_ENV_KEYS["proxy_url"]] = None
            os.environ.pop(_ENV_KEYS["proxy_url"], None)
            response_data["proxy_url"] = ""
        elif isinstance(url, str):
            stripped = url.strip()
            # 简单校验：必须是 http/https/socks5 开头，跟前端代理设置卡片
            # 的校验保持一致。
            if not re.match(r"^(https?|socks5):\/\/.+", stripped, flags=re.IGNORECASE):
                return api_error(
                    code=40023,
                    msg="代理地址格式不对（应以 http://、https:// 或 socks5:// 开头）",
                )
            updates[_ENV_KEYS["proxy_url"]] = stripped
            os.environ[_ENV_KEYS["proxy_url"]] = stripped
            response_data["proxy_url"] = stripped
        else:
            return api_error(code=40024, msg="proxy_url 字段类型错误，应为字符串")

    if not updates:
        return api_error(code=40025, msg="没有要更新的字段（支持：token / proxy_enabled / proxy_url）")

    # 校验：所有 key 都在白名单里（防御性，正常 reach 不到）
    for key in updates:
        if key not in _WRITABLE_ENV_KEYS:
            return api_error(code=40026, msg=f"非法 env key: {key}")

    try:
        env_path = _env_local_path()
        lines = _read_env_file(env_path)
        new_lines = _upsert_env_lines(lines, updates)
        _write_env_file(env_path, new_lines)
    except Exception as e:
        logger.exception("Failed to write .env.local error=%s", e)
        return api_error(code=50010, msg=f"写入 .env.local 失败：{e}", http_status=500)

    try:
        _refresh_runtime_config()
    except Exception as e:
        # 写盘已成功 —— 这里失败只是"运行时未热更新"，下次重启会读新值。
        # 给用户一个 warning 但不是 error。
        logger.exception("Failed to refresh runtime config error=%s", e)
        return api_response(
            data={**response_data, "hot_reload": False},
            msg=f"配置已保存，但热更新失败：{e}。重启后自动生效。",
        )

    return api_response(data={**response_data, "hot_reload": True}, msg="TMDB 配置已保存")
