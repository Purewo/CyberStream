import logging
import threading

from flask import Blueprint, Response, current_app, request

from backend.app.db.database import scanner_adapter
from backend.app.extensions import db
from backend.app.models import StorageSource
from backend.app.providers.base import StorageProviderError
from backend.app.providers.factory import provider_factory
from backend.app.services.managed_alist import ManagedAListClient, ManagedAListError, ManagedOpenListClient
from backend.app.services.metadata_policy import ScraperPolicyError, normalize_scraper_policy_payload
from backend.app.services.scanner import scanner_engine
from backend.app.services.urls import api_url_for
from backend.app.services.vault import VaultAccessError, verify_vault_pin
from backend.app.storage.source_registry import (
    list_supported_source_types,
    get_source_capabilities,
    normalize_source_config,
    normalize_source_type,
    restore_masked_source_secrets,
)
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

storage_bp = Blueprint('storage', __name__, url_prefix='/api/v1')
BAIDUNETDISK_DEFAULT_DOWNLOAD_API = "crack_video"
QUARK_UC_OPENLIST_LINK_METHOD = "download"


def _normalize_relative_path(path_value):
    if path_value is None:
        return ''
    if not isinstance(path_value, str):
        path_value = str(path_value)
    return path_value.strip().strip('/')


def _display_relative_path(path_value):
    normalized = _normalize_relative_path(path_value)
    return normalized or '/'


def _build_parent_path(path_value):
    normalized = _normalize_relative_path(path_value)
    if not normalized:
        return None
    parent = normalized.rsplit('/', 1)[0] if '/' in normalized else ''
    return _display_relative_path(parent)


def _normalize_browse_item(item):
    normalized_path = _normalize_relative_path(item.get('path'))
    return {
        'name': item['name'],
        'path': _display_relative_path(normalized_path),
        'type': 'dir' if item['isdir'] else 'file',
        'size': item['size'],
    }


def _build_browse_payload(items, path, dirs_only=True):
    normalized_items = [_normalize_browse_item(item) for item in items]
    if dirs_only:
        normalized_items = [item for item in normalized_items if item['type'] == 'dir']

    normalized_items.sort(key=lambda item: (item['type'] != 'dir', item['name'].lower()))
    return {
        'current_path': _display_relative_path(path),
        'parent_path': _build_parent_path(path),
        'items': normalized_items,
    }


def _list_directory_or_invalid(provider, target_path):
    items = provider.list_items(target_path)
    if items:
        return items
    if provider.path_exists(target_path):
        return items
    raise StorageProviderError(
        f"Invalid preview path or source unavailable: {_display_relative_path(target_path)}",
        code=40015,
    )


def _coerce_bool(value, default=None):
    if value is None:
        return default, True
    if isinstance(value, bool):
        return value, True
    if isinstance(value, int) and value in (0, 1):
        return bool(value), True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'y', 'on'}:
            return True, True
        if normalized in {'false', '0', 'no', 'n', 'off'}:
            return False, True
    return value, False


def _normalize_storage_config(storage_type, config):
    """兼容旧测试/调用方的配置归一化入口。新逻辑实际委托 source_registry。"""
    try:
        normalized_type = normalize_source_type(storage_type)
        normalized_config = normalize_source_config(normalized_type, config)
        return normalized_config, None
    except StorageProviderError as e:
        normalized_type = str(storage_type or '').strip().lower()
        if normalized_type == 'smb' and e.code == 40034 and 'share' in e.message:
            return None, api_error(code=40007, msg=e.message)
        return None, api_error(code=e.code, msg=e.message)


def _get_json_payload():
    """统一读取 JSON 请求体；空 body 时返回空字典。"""
    return request.get_json(silent=True) or {}


def _managed_alist_error_response(error):
    http_status = 502 if error.code >= 500 else 400
    return api_error(code=error.code, msg=error.message, http_status=http_status)


def _parse_source_id(payload):
    source_id = payload.get('source_id') or payload.get('id')
    if not source_id:
        return None, api_error(code=40001, msg="Missing required field: source_id")
    try:
        return int(source_id), None
    except (TypeError, ValueError):
        return None, api_error(code=40036, msg="Invalid field type: source_id should be integer")


def _load_managed_source(payload, source_type, display_name):
    source_id, error_response = _parse_source_id(payload)
    if error_response:
        return None, None, error_response
    source = db.session.get(StorageSource, source_id)
    if not source:
        return source_id, None, api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != source_type:
        return source_id, source, api_error(code=40061, msg=f"Storage source is not a managed {display_name} source")
    return source_id, source, None


def _config_int(config, key):
    try:
        value = int((config or {}).get(key) or 0)
    except (TypeError, ValueError):
        return None
    return value or None


def _delete_replaced_runtime_storage(client, display_name, source_id, storage_id, new_storage_id=None):
    if not storage_id:
        return False
    try:
        if new_storage_id is not None and int(storage_id) == int(new_storage_id):
            return False
    except (TypeError, ValueError):
        pass
    try:
        client.delete_storage(storage_id)
        return True
    except Exception:
        logger.exception(
            "Delete replaced managed %s runtime storage failed source_id=%s storage_id=%s",
            display_name,
            source_id,
            storage_id,
        )
        return False


def _vault_error_response(error):
    return api_error(code=error.code, msg=error.msg, http_status=error.http_status)


def _build_guangyapan_source_config(state, auth_state):
    return {
        "alist_storage_id": int(state["storage_id"]),
        "mount_path": state["mount_path"],
        "auth_state": auth_state,
        "phone_number_masked": state.get("phone_number_masked"),
        "cloud_root_path": state.get("cloud_root_path") or "/",
    }


def _build_tianyicloud_source_config(state, auth_state):
    config = {
        "openlist_storage_id": int(state["storage_id"]),
        "mount_path": state["mount_path"],
        "auth_state": auth_state,
        "cloud_type": state.get("cloud_type") or "personal",
        "cloud_root_path": state.get("cloud_root_path") or "/",
        "root_folder_id": str(state.get("root_folder_id") or ""),
    }
    if state.get("login_mode"):
        config["login_mode"] = state["login_mode"]
    return config


def _build_115cloud_source_config(state, auth_state):
    config = {
        "openlist_storage_id": int(state["storage_id"]),
        "mount_path": state["mount_path"],
        "auth_state": auth_state,
        "cloud_root_path": state.get("cloud_root_path") or "/",
        "root_folder_id": str(state.get("root_folder_id") or "0"),
        "qrcode_source": state.get("qrcode_source") or ManagedOpenListClient.DEFAULT_115_QRCODE_SOURCE,
    }
    for key in ("qr_uid", "qr_sign", "qr_time"):
        if state.get(key) is not None:
            config[key] = state[key]
    return config


def _build_aliyundrive_source_config(state, auth_state):
    config = {
        "auth_state": auth_state,
        "cloud_root_path": state.get("cloud_root_path") or "/",
        "root_folder_id": state.get("root_folder_id") or "root",
        "drive_type": state.get("drive_type") or "resource",
        "alipan_type": state.get("alipan_type") or "default",
    }
    if state.get("storage_id") is not None:
        config["openlist_storage_id"] = int(state["storage_id"])
    if state.get("mount_path"):
        config["mount_path"] = state["mount_path"]
    if state.get("qr_sid"):
        config["qr_sid"] = state["qr_sid"]
    if state.get("auth_provider"):
        config["auth_provider"] = state["auth_provider"]
    return config


def _build_baidunetdisk_source_config(state, auth_state):
    config = {
        "auth_state": auth_state,
        "cloud_root_path": state.get("cloud_root_path") or "/",
        "root_folder_path": state.get("root_folder_path") or state.get("cloud_root_path") or "/",
        "download_api": state.get("download_api") or BAIDUNETDISK_DEFAULT_DOWNLOAD_API,
    }
    if state.get("storage_id") is not None:
        config["openlist_storage_id"] = int(state["storage_id"])
    if state.get("mount_path"):
        config["mount_path"] = state["mount_path"]
    if state.get("oauth_state"):
        config["oauth_state"] = state["oauth_state"]
    if state.get("oauth_callback_mode"):
        config["oauth_callback_mode"] = state["oauth_callback_mode"]
    if state.get("oauth_redirect_uri"):
        config["oauth_redirect_uri"] = state["oauth_redirect_uri"]
    if state.get("oauth_error"):
        config["oauth_error"] = state["oauth_error"]
    return config


def _select_baidunetdisk_download_api(raw_value=None, current_value=None):
    allowed = {"official", "crack", "crack_video"}
    raw_text = str(raw_value or "").strip().lower()
    if raw_text:
        return raw_text
    current_text = str(current_value or "").strip().lower()
    if current_text in allowed and current_text != "official":
        return current_text
    return BAIDUNETDISK_DEFAULT_DOWNLOAD_API


def _build_123pan_source_config(state, auth_state):
    return {
        "openlist_storage_id": int(state["storage_id"]),
        "mount_path": state["mount_path"],
        "auth_state": auth_state,
        "cloud_root_path": state.get("cloud_root_path") or "/",
        "root_folder_id": state.get("root_folder_id") or "0",
        "account_name_masked": state.get("account_name_masked"),
        "platform": state.get("platform") or "web",
    }


def _find_managed_source_by_oauth_state(source_type, oauth_state):
    normalized_state = str(oauth_state or "").strip()
    if not normalized_state:
        return None
    for source in StorageSource.query.filter_by(type=source_type).all():
        if str((source.config or {}).get("oauth_state") or "").strip() == normalized_state:
            return source
    return None


def _oauth_html(title, message):
    escaped_title = str(title or "OAuth").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped_message = str(message or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Response(
        (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{escaped_title}</title></head><body>"
            f"<h1>{escaped_title}</h1><p>{escaped_message}</p>"
            "</body></html>"
        ),
        content_type="text/html; charset=utf-8",
    )


def _complete_baidunetdisk_oauth_source(source, code):
    source_config = source.config or {}
    old_storage_id = _config_int(source_config, "openlist_storage_id")
    callback_mode = str(source_config.get("oauth_callback_mode") or "redirect").strip().lower()
    redirect_uri = str(source_config.get("oauth_redirect_uri") or "").strip()
    if not redirect_uri:
        redirect_uri = "oob" if callback_mode == "oob" else api_url_for("storage.callback_managed_baidunetdisk_oauth")
    client = ManagedOpenListClient()
    login_state = client.complete_baidunetdisk_oauth(
        code=code,
        redirect_uri=redirect_uri,
        root_path=source_config.get("root_folder_path") or source_config.get("cloud_root_path") or "/",
        download_api=_select_baidunetdisk_download_api(current_value=source_config.get("download_api")),
    )
    next_config = dict(source_config)
    next_config.update(_build_baidunetdisk_source_config(login_state, auth_state='ready'))
    for key in ("oauth_state", "oauth_error", "oauth_callback_mode", "oauth_redirect_uri"):
        next_config.pop(key, None)
    source.config = normalize_source_config('baidunetdisk', next_config)
    db.session.commit()
    old_storage_deleted = _delete_replaced_runtime_storage(
        client,
        "Baidu Netdisk",
        source.id,
        old_storage_id,
        login_state.get("storage_id"),
    )
    login_state["replaced_openlist_storage_id"] = old_storage_id
    login_state["old_openlist_storage_deleted"] = old_storage_deleted
    return login_state


_MANAGED_QUARK_UC_PROVIDERS = {
    "quarktv": {
        "default_name": "QuarkTV",
        "display_name": "QuarkTV",
    },
    "uctv": {
        "default_name": "UCTV",
        "display_name": "UCTV",
    },
}


def _build_quark_uc_source_config(state, auth_state):
    return {
        "openlist_storage_id": int(state["storage_id"]),
        "mount_path": state["mount_path"],
        "auth_state": auth_state,
        "cloud_root_path": state.get("cloud_root_path") or "/",
        "root_folder_id": str(state.get("root_folder_id") or "0"),
    }


def _scan_background_task(app, source_id=None, root_path=None, content_type=None, scrape_enabled=True, scraper_policy=None):
    with app.app_context():
        try:
            scanner_engine.scan(
                source_id,
                root_path=root_path,
                content_type=content_type,
                scrape_enabled=scrape_enabled,
                scraper_policy=scraper_policy,
                lock_acquired=True,
            )
        except Exception as e:
            logger.exception("Background scan failed source_id=%s error=%s", source_id, e)


@storage_bp.route('/storage/sources', methods=['GET'])
def list_sources():
    sources = StorageSource.query.all()
    return api_response(data=[source.to_dict() for source in sources])


@storage_bp.route('/storage/sources/<int:id>', methods=['GET'])
def get_source(id):
    source = db.session.get(StorageSource, id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    return api_response(data=source.to_dict())


@storage_bp.route('/storage/sources/<int:id>/health', methods=['GET'])
def get_source_health(id):
    source = db.session.get(StorageSource, id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    return api_response(data=source.to_dict(include_health=True))


@storage_bp.route('/storage/provider-types', methods=['GET'])
def list_provider_types():
    return api_response(data=list_supported_source_types())


@storage_bp.route('/storage/capabilities', methods=['GET'])
def list_capabilities():
    provider_types = list_supported_source_types()
    return api_response(data={
        "supported_types": [item["type"] for item in provider_types],
        "items": [
            {
                "type": item["type"],
                "display_name": item["display_name"],
                "label": item["display_name"],
                "browse": item["capabilities"].get("preview", False),
                "validate_path": item["capabilities"].get("preview", False),
                "range_stream": item["capabilities"].get("range_stream", item["capabilities"].get("stream", False)),
                "library_root_path": item["capabilities"].get("preview", False),
                "config_root_key": "root_path" if item["type"] == "local" else "root",
                **item["capabilities"],
            }
            for item in provider_types
        ],
    })


@storage_bp.route('/storage/sources', methods=['POST'])
def add_source():
    payload = _get_json_payload()
    name = (payload.get('name') or '').strip()
    storage_type = payload.get('type')
    config = payload.get('config')

    if not name or storage_type is None or config is None:
        return api_error(code=40001, msg="Missing required fields")

    try:
        normalized_type = normalize_source_type(storage_type)
        normalized_config, error_response = _normalize_storage_config(normalized_type, config)
        if error_response:
            return error_response
        source = StorageSource(name=name, type=normalized_type, config=normalized_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data=source.to_dict())
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Add storage source failed type=%s error=%s", storage_type, e)
        return api_error(code=50014, msg="Create source failed", http_status=500)


@storage_bp.route('/storage/managed/guangyapan/sms/start', methods=['POST'])
def start_managed_guangyapan_sms():
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or 'GuangYaPan').strip()
    phone_number = (payload.get('phone_number') or '').strip()
    root_path = (payload.get('root_path') or payload.get('cloud_root_path') or '').strip()
    captcha_token = (payload.get('captcha_token') or '').strip()

    if not phone_number:
        return api_error(code=40001, msg="Missing required field: phone_number")
    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")

    storage_state = None
    try:
        client = ManagedAListClient()
        storage_state = client.create_guangyapan_storage(
            phone_number=phone_number,
            root_path=root_path,
            captcha_token=captcha_token,
        )
        source_config = normalize_source_config(
            'guangyapan',
            _build_guangyapan_source_config(storage_state, auth_state='sms_pending'),
        )
        source = StorageSource(name=name, type='guangyapan', config=source_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data={
            "verification_sent": True,
            "auth_state": "sms_pending",
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedAListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed AList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedAListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed AList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Start managed GuangYaPan SMS failed error=%s", e)
        return api_error(code=50016, msg="Start GuangYaPan SMS login failed", http_status=500)


@storage_bp.route('/storage/managed/guangyapan/sms/restart', methods=['POST'])
def restart_managed_guangyapan_sms():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, 'guangyapan', 'GuangYaPan')
    if error_response:
        return error_response

    phone_number = (payload.get('phone_number') or '').strip()
    if not phone_number:
        return api_error(code=40001, msg="Missing required field: phone_number")

    source_config = source.config or {}
    root_path = (
        payload.get('root_path')
        or payload.get('cloud_root_path')
        or source_config.get("cloud_root_path")
        or ""
    )
    root_path = str(root_path).strip()
    captcha_token = (payload.get('captcha_token') or '').strip()
    old_storage_id = _config_int(source_config, "alist_storage_id")

    storage_state = None
    old_storage_deleted = False
    try:
        client = ManagedAListClient()
        storage_state = client.create_guangyapan_storage(
            phone_number=phone_number,
            root_path=root_path,
            captcha_token=captcha_token,
        )
        next_config = dict(source_config)
        next_config.update(_build_guangyapan_source_config(storage_state, auth_state='sms_pending'))
        source.config = normalize_source_config('guangyapan', next_config)
        db.session.commit()
        old_storage_deleted = _delete_replaced_runtime_storage(
            client,
            "GuangYaPan",
            source_id,
            old_storage_id,
            storage_state["storage_id"],
        )
        return api_response(data={
            "verification_restarted": True,
            "verification_sent": True,
            "auth_state": "sms_pending",
            "replaced_alist_storage_id": old_storage_id,
            "old_alist_storage_deleted": old_storage_deleted,
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedAListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed AList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedAListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed AList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Restart managed GuangYaPan SMS failed source_id=%s error=%s", source_id, e)
        return api_error(code=50016, msg="Restart GuangYaPan SMS login failed", http_status=500)


@storage_bp.route('/storage/managed/guangyapan/sms/verify', methods=['POST'])
def verify_managed_guangyapan_sms():
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    verify_code = (payload.get('verify_code') or payload.get('code') or '').strip()
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")
    if not verify_code:
        return api_error(code=40001, msg="Missing required field: verify_code")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != 'guangyapan':
        return api_error(code=40061, msg="Storage source is not a managed GuangYaPan source")

    try:
        source_config = source.config or {}
        storage_id = int(source_config.get("alist_storage_id") or 0)
        if not storage_id:
            return api_error(code=40061, msg="Managed GuangYaPan source has no AList storage id")
        client = ManagedAListClient()
        verified_state = client.verify_guangyapan_storage(storage_id, verify_code)
        next_config = dict(source_config)
        next_config.update({
            "alist_storage_id": storage_id,
            "mount_path": verified_state["mount_path"],
            "auth_state": "ready",
        })
        source.config = normalize_source_config('guangyapan', next_config)
        db.session.commit()
        return api_response(data={
            "verified": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Verify managed GuangYaPan SMS failed source_id=%s error=%s", source_id, e)
        return api_error(code=50017, msg="Verify GuangYaPan SMS login failed", http_status=500)


@storage_bp.route('/storage/managed/tianyicloud/qr/start', methods=['POST'])
def start_managed_tianyicloud_qr():
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or 'TianYiCloud').strip()
    cloud_type = str(payload.get('cloud_type') or 'personal').strip().lower()
    root_folder_id = str(payload.get('root_folder_id') or '').strip()

    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")

    storage_state = None
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_tianyicloud_storage(
            root_folder_id=root_folder_id,
            cloud_type=cloud_type,
        )
        source_config = normalize_source_config(
            'tianyicloud',
            _build_tianyicloud_source_config(storage_state, auth_state='qr_pending'),
        )
        source = StorageSource(name=name, type='tianyicloud', config=source_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data={
            "qr_started": True,
            "auth_state": "qr_pending",
            "qr_code_data_url": storage_state["qr_code_data_url"],
            "qr_content": storage_state.get("qr_content"),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Start managed TianYiCloud QR failed error=%s", e)
        return api_error(code=50018, msg="Start TianYiCloud QR login failed", http_status=500)


@storage_bp.route('/storage/managed/tianyicloud/qr/restart', methods=['POST'])
def restart_managed_tianyicloud_qr():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, 'tianyicloud', 'TianYiCloud')
    if error_response:
        return error_response

    source_config = source.config or {}
    cloud_type = str(payload.get('cloud_type') or source_config.get("cloud_type") or 'personal').strip().lower()
    root_folder_id = str(
        payload.get('root_folder_id')
        if payload.get('root_folder_id') is not None
        else source_config.get("root_folder_id") or ''
    ).strip()
    old_storage_id = _config_int(source_config, "openlist_storage_id")

    storage_state = None
    old_storage_deleted = False
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_tianyicloud_storage(
            root_folder_id=root_folder_id,
            cloud_type=cloud_type,
        )
        next_config = dict(source_config)
        next_config.update(_build_tianyicloud_source_config(storage_state, auth_state='qr_pending'))
        source.config = normalize_source_config('tianyicloud', next_config)
        db.session.commit()
        old_storage_deleted = _delete_replaced_runtime_storage(
            client,
            "TianYiCloud",
            source_id,
            old_storage_id,
            storage_state["storage_id"],
        )
        return api_response(data={
            "qr_restarted": True,
            "qr_started": True,
            "auth_state": "qr_pending",
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": old_storage_deleted,
            "qr_code_data_url": storage_state["qr_code_data_url"],
            "qr_content": storage_state.get("qr_content"),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Restart managed TianYiCloud QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50018, msg="Restart TianYiCloud QR login failed", http_status=500)


@storage_bp.route('/storage/managed/tianyicloud/qr/poll', methods=['POST'])
def poll_managed_tianyicloud_qr():
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != 'tianyicloud':
        return api_error(code=40061, msg="Storage source is not a managed TianYiCloud source")

    try:
        source_config = source.config or {}
        storage_id = int(source_config.get("openlist_storage_id") or 0)
        if not storage_id:
            return api_error(code=40061, msg="Managed TianYiCloud source has no OpenList storage id")
        client = ManagedOpenListClient()
        login_state = client.poll_tianyicloud_storage(storage_id)
        if not login_state.get("authenticated"):
            data = {
                "authenticated": False,
                "auth_state": "qr_pending",
                "pending_reason": login_state.get("pending_reason") or "waiting_for_scan",
                "source": source.to_dict(),
            }
            if login_state.get("qr_code_data_url"):
                data["qr_code_data_url"] = login_state["qr_code_data_url"]
                data["qr_content"] = login_state.get("qr_content")
            return api_response(data=data)

        next_config = dict(source_config)
        next_config.update({
            "openlist_storage_id": storage_id,
            "mount_path": login_state["mount_path"],
            "auth_state": "ready",
            "cloud_type": login_state.get("cloud_type") or source_config.get("cloud_type") or "personal",
            "root_folder_id": str(login_state.get("root_folder_id") or source_config.get("root_folder_id") or ""),
        })
        source.config = normalize_source_config('tianyicloud', next_config)
        db.session.commit()
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Poll managed TianYiCloud QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50019, msg="Poll TianYiCloud QR login failed", http_status=500)


@storage_bp.route('/storage/managed/tianyicloud/pc-qr/start', methods=['POST'])
def start_managed_tianyicloud_pc_qr_experimental():
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or 'TianYiCloud PC QR').strip()
    cloud_type = str(payload.get('cloud_type') or 'personal').strip().lower()
    root_folder_id = str(payload.get('root_folder_id') or '').strip()

    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")

    storage_state = None
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_tianyicloud_pc_qr_storage(
            root_folder_id=root_folder_id,
            cloud_type=cloud_type,
        )
        auth_state = storage_state.get("auth_state") or "qr_pending"
        source_config = normalize_source_config(
            'tianyicloud',
            _build_tianyicloud_source_config(storage_state, auth_state=auth_state),
        )
        source = StorageSource(name=name, type='tianyicloud', config=source_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data={
            "experimental": True,
            "login_mode": "pc_qr",
            "qr_started": True,
            "auth_state": auth_state,
            "qr_code_data_url": storage_state["qr_code_data_url"],
            "qr_content": storage_state.get("qr_content"),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList PC QR storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList PC QR storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Start managed TianYiCloud PC QR failed error=%s", e)
        return api_error(code=50018, msg="Start TianYiCloud PC QR login failed", http_status=500)


@storage_bp.route('/storage/managed/tianyicloud/pc-qr/restart', methods=['POST'])
def restart_managed_tianyicloud_pc_qr_experimental():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, 'tianyicloud', 'TianYiCloud')
    if error_response:
        return error_response

    source_config = source.config or {}
    cloud_type = str(payload.get('cloud_type') or source_config.get("cloud_type") or 'personal').strip().lower()
    root_folder_id = str(
        payload.get('root_folder_id')
        if payload.get('root_folder_id') is not None
        else source_config.get("root_folder_id") or ''
    ).strip()
    old_storage_id = _config_int(source_config, "openlist_storage_id")

    storage_state = None
    old_storage_deleted = False
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_tianyicloud_pc_qr_storage(
            root_folder_id=root_folder_id,
            cloud_type=cloud_type,
        )
        auth_state = storage_state.get("auth_state") or "qr_pending"
        next_config = dict(source_config)
        next_config.update(_build_tianyicloud_source_config(storage_state, auth_state=auth_state))
        source.config = normalize_source_config('tianyicloud', next_config)
        db.session.commit()
        old_storage_deleted = _delete_replaced_runtime_storage(
            client,
            "TianYiCloud PC QR",
            source_id,
            old_storage_id,
            storage_state["storage_id"],
        )
        return api_response(data={
            "experimental": True,
            "login_mode": "pc_qr",
            "qr_restarted": True,
            "qr_started": True,
            "auth_state": auth_state,
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": old_storage_deleted,
            "qr_code_data_url": storage_state["qr_code_data_url"],
            "qr_content": storage_state.get("qr_content"),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList PC QR storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList PC QR storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Restart managed TianYiCloud PC QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50018, msg="Restart TianYiCloud PC QR login failed", http_status=500)


@storage_bp.route('/storage/managed/tianyicloud/pc-qr/poll', methods=['POST'])
def poll_managed_tianyicloud_pc_qr_experimental():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, 'tianyicloud', 'TianYiCloud')
    if error_response:
        return error_response

    try:
        source_config = source.config or {}
        if source_config.get("login_mode") != "pc_qr":
            return api_error(code=40061, msg="Storage source is not a TianYiCloud PC QR experimental source")
        storage_id = int(source_config.get("openlist_storage_id") or 0)
        if not storage_id:
            return api_error(code=40061, msg="Managed TianYiCloud source has no OpenList storage id")
        client = ManagedOpenListClient()
        login_state = client.poll_tianyicloud_pc_qr_storage(storage_id)
        if not login_state.get("authenticated"):
            auth_state = login_state.get("auth_state") or "qr_pending"
            if auth_state != source_config.get("auth_state"):
                next_config = dict(source_config)
                next_config["auth_state"] = auth_state
                source.config = normalize_source_config('tianyicloud', next_config)
                db.session.commit()
            data = {
                "experimental": True,
                "login_mode": "pc_qr",
                "authenticated": False,
                "auth_state": auth_state,
                "pending_reason": login_state.get("pending_reason") or "waiting_for_scan",
                "source": source.to_dict(),
            }
            if login_state.get("qr_code_data_url"):
                data["qr_code_data_url"] = login_state["qr_code_data_url"]
                data["qr_content"] = login_state.get("qr_content")
            return api_response(data=data)

        next_config = dict(source_config)
        next_config.update({
            "openlist_storage_id": storage_id,
            "mount_path": login_state["mount_path"],
            "auth_state": "ready",
            "cloud_type": login_state.get("cloud_type") or source_config.get("cloud_type") or "personal",
            "root_folder_id": str(login_state.get("root_folder_id") or source_config.get("root_folder_id") or ""),
            "login_mode": "pc_qr",
        })
        source.config = normalize_source_config('tianyicloud', next_config)
        db.session.commit()
        return api_response(data={
            "experimental": True,
            "login_mode": "pc_qr",
            "authenticated": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Poll managed TianYiCloud PC QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50019, msg="Poll TianYiCloud PC QR login failed", http_status=500)


@storage_bp.route('/storage/managed/115cloud/qr/start', methods=['POST'])
def start_managed_115cloud_qr():
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or '115 Cloud').strip()
    root_folder_id = str(payload.get('root_folder_id') or '').strip()
    qrcode_source = str(
        payload.get('qrcode_source') or ManagedOpenListClient.DEFAULT_115_QRCODE_SOURCE
    ).strip().lower()

    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")

    storage_state = None
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_115cloud_storage(
            root_folder_id=root_folder_id,
            qrcode_source=qrcode_source,
        )
        auth_state = storage_state.get("auth_state") or "qr_pending"
        source_config = normalize_source_config(
            '115cloud',
            _build_115cloud_source_config(storage_state, auth_state=auth_state),
        )
        source = StorageSource(name=name, type='115cloud', config=source_config)
        db.session.add(source)
        db.session.commit()
        data = {
            "qr_started": auth_state != "ready",
            "auth_state": auth_state,
            "source": source.to_dict(),
        }
        if storage_state.get("qr_code_data_url"):
            data["qr_code_data_url"] = storage_state["qr_code_data_url"]
            data["qr_content"] = storage_state.get("qr_content")
        return api_response(data=data)
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Start managed 115 Cloud QR failed error=%s", e)
        return api_error(code=50022, msg="Start 115 Cloud QR login failed", http_status=500)


@storage_bp.route('/storage/managed/115cloud/qr/restart', methods=['POST'])
def restart_managed_115cloud_qr():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, '115cloud', '115 Cloud')
    if error_response:
        return error_response

    source_config = source.config or {}
    root_folder_id = str(
        payload.get('root_folder_id')
        if payload.get('root_folder_id') is not None
        else source_config.get("root_folder_id") or ''
    ).strip()
    qrcode_source = str(
        payload.get('qrcode_source')
        or source_config.get("qrcode_source")
        or ManagedOpenListClient.DEFAULT_115_QRCODE_SOURCE
    ).strip().lower()
    old_storage_id = _config_int(source_config, "openlist_storage_id")

    storage_state = None
    old_storage_deleted = False
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_115cloud_storage(
            root_folder_id=root_folder_id,
            qrcode_source=qrcode_source,
        )
        auth_state = storage_state.get("auth_state") or "qr_pending"
        next_config = dict(source_config)
        next_config.update(_build_115cloud_source_config(storage_state, auth_state=auth_state))
        source.config = normalize_source_config('115cloud', next_config)
        db.session.commit()
        old_storage_deleted = _delete_replaced_runtime_storage(
            client,
            "115 Cloud",
            source_id,
            old_storage_id,
            storage_state["storage_id"],
        )
        data = {
            "qr_restarted": True,
            "qr_started": auth_state != "ready",
            "auth_state": auth_state,
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": old_storage_deleted,
            "source": source.to_dict(),
        }
        if storage_state.get("qr_code_data_url"):
            data["qr_code_data_url"] = storage_state["qr_code_data_url"]
            data["qr_content"] = storage_state.get("qr_content")
        return api_response(data=data)
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Restart managed 115 Cloud QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50022, msg="Restart 115 Cloud QR login failed", http_status=500)


@storage_bp.route('/storage/managed/115cloud/qr/poll', methods=['POST'])
def poll_managed_115cloud_qr():
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != '115cloud':
        return api_error(code=40061, msg="Storage source is not a managed 115 Cloud source")

    try:
        source_config = source.config or {}
        storage_id = int(source_config.get("openlist_storage_id") or 0)
        if not storage_id:
            return api_error(code=40061, msg="Managed 115 Cloud source has no OpenList storage id")

        qr_session = None
        if source_config.get("qr_uid") and source_config.get("qr_sign") and source_config.get("qr_time") is not None:
            qr_session = {
                "qr_uid": source_config.get("qr_uid"),
                "qr_sign": source_config.get("qr_sign"),
                "qr_time": source_config.get("qr_time"),
            }

        client = ManagedOpenListClient()
        login_state = client.poll_115cloud_storage(storage_id, qr_session=qr_session)
        if not login_state.get("authenticated"):
            auth_state = login_state.get("auth_state") or "qr_pending"
            next_config = dict(source_config)
            next_config.update({
                "openlist_storage_id": storage_id,
                "mount_path": login_state.get("mount_path") or source_config.get("mount_path"),
                "auth_state": auth_state,
                "cloud_root_path": login_state.get("cloud_root_path") or source_config.get("cloud_root_path") or "/",
                "root_folder_id": str(login_state.get("root_folder_id") or source_config.get("root_folder_id") or "0"),
                "qrcode_source": (
                    login_state.get("qrcode_source")
                    or source_config.get("qrcode_source")
                    or ManagedOpenListClient.DEFAULT_115_QRCODE_SOURCE
                ),
            })
            source.config = normalize_source_config('115cloud', next_config)
            db.session.commit()
            data = {
                "authenticated": False,
                "auth_state": auth_state,
                "pending_reason": login_state.get("pending_reason") or "waiting_for_scan",
                "source": source.to_dict(),
            }
            if login_state.get("qr_status") is not None:
                data["qr_status"] = login_state["qr_status"]
            if login_state.get("qr_code_data_url"):
                data["qr_code_data_url"] = login_state["qr_code_data_url"]
                data["qr_content"] = login_state.get("qr_content")
            return api_response(data=data)

        next_config = dict(source_config)
        next_config.update({
            "openlist_storage_id": storage_id,
            "mount_path": login_state["mount_path"],
            "auth_state": "ready",
            "cloud_root_path": login_state.get("cloud_root_path") or source_config.get("cloud_root_path") or "/",
            "root_folder_id": str(login_state.get("root_folder_id") or source_config.get("root_folder_id") or "0"),
            "qrcode_source": (
                login_state.get("qrcode_source")
                or source_config.get("qrcode_source")
                or ManagedOpenListClient.DEFAULT_115_QRCODE_SOURCE
            ),
        })
        for key in ("qr_uid", "qr_sign", "qr_time"):
            next_config.pop(key, None)
        source.config = normalize_source_config('115cloud', next_config)
        db.session.commit()
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Poll managed 115 Cloud QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50023, msg="Poll 115 Cloud QR login failed", http_status=500)


@storage_bp.route('/storage/managed/aliyundrive/qr/start', methods=['POST'])
def start_managed_aliyundrive_qr():
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or 'Aliyundrive').strip()
    root_folder_id = str(payload.get('root_folder_id') or '').strip()
    drive_type = str(payload.get('drive_type') or 'resource').strip().lower()
    alipan_type = str(payload.get('alipan_type') or 'default').strip()

    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")

    try:
        client = ManagedOpenListClient()
        login_state = client.start_aliyundrive_qr(
            root_folder_id=root_folder_id,
            drive_type=drive_type,
            alipan_type=alipan_type,
        )
        source_config = normalize_source_config(
            'aliyundrive',
            _build_aliyundrive_source_config(login_state, auth_state='qr_pending'),
        )
        source = StorageSource(name=name, type='aliyundrive', config=source_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data={
            "qr_started": True,
            "auth_state": "qr_pending",
            "pending_reason": login_state.get("pending_reason") or "waiting_for_scan",
            "qr_status": login_state.get("qr_status"),
            "qr_code_url": login_state["qr_code_url"],
            "qr_code_data_url": login_state["qr_code_data_url"],
            "qr_content": login_state.get("qr_content"),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Start managed Aliyundrive QR failed error=%s", e)
        return api_error(code=50024, msg="Start Aliyundrive QR login failed", http_status=500)


@storage_bp.route('/storage/managed/aliyundrive/qr/restart', methods=['POST'])
def restart_managed_aliyundrive_qr():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, 'aliyundrive', 'Aliyundrive')
    if error_response:
        return error_response

    source_config = source.config or {}
    root_folder_id = str(
        payload.get('root_folder_id')
        if payload.get('root_folder_id') is not None
        else source_config.get("root_folder_id") or 'root'
    ).strip()
    drive_type = str(payload.get('drive_type') or source_config.get("drive_type") or 'resource').strip().lower()
    alipan_type = str(payload.get('alipan_type') or source_config.get("alipan_type") or 'default').strip()
    old_storage_id = _config_int(source_config, "openlist_storage_id")

    try:
        client = ManagedOpenListClient()
        login_state = client.start_aliyundrive_qr(
            root_folder_id=root_folder_id,
            drive_type=drive_type,
            alipan_type=alipan_type,
        )
        next_config = dict(source_config)
        next_config.update(_build_aliyundrive_source_config(login_state, auth_state='qr_pending'))
        source.config = normalize_source_config('aliyundrive', next_config)
        db.session.commit()
        return api_response(data={
            "qr_restarted": True,
            "qr_started": True,
            "auth_state": "qr_pending",
            "pending_reason": login_state.get("pending_reason") or "waiting_for_scan",
            "qr_status": login_state.get("qr_status"),
            "qr_code_url": login_state["qr_code_url"],
            "qr_code_data_url": login_state["qr_code_data_url"],
            "qr_content": login_state.get("qr_content"),
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": False,
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Restart managed Aliyundrive QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50024, msg="Restart Aliyundrive QR login failed", http_status=500)


@storage_bp.route('/storage/managed/aliyundrive/qr/poll', methods=['POST'])
def poll_managed_aliyundrive_qr():
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != 'aliyundrive':
        return api_error(code=40061, msg="Storage source is not a managed Aliyundrive source")

    try:
        source_config = source.config or {}
        old_storage_id = _config_int(source_config, "openlist_storage_id")
        if str(source_config.get("auth_state") or "").strip().lower() == "ready":
            return api_response(data={
                "authenticated": True,
                "auth_state": "ready",
                "source": source.to_dict(),
            })

        qr_sid = str(source_config.get("qr_sid") or "").strip()
        if not qr_sid:
            return api_error(code=40061, msg="Managed Aliyundrive source has no QR session")

        client = ManagedOpenListClient()
        login_state = client.poll_aliyundrive_storage(
            qr_sid=qr_sid,
            root_folder_id=source_config.get("root_folder_id") or "root",
            drive_type=source_config.get("drive_type") or "resource",
            alipan_type=source_config.get("alipan_type") or "default",
            auth_provider=source_config.get("auth_provider"),
        )
        if not login_state.get("authenticated"):
            auth_state = login_state.get("auth_state") or "qr_pending"
            next_config = dict(source_config)
            next_config.update(_build_aliyundrive_source_config(login_state, auth_state=auth_state))
            next_config["qr_sid"] = qr_sid
            source.config = normalize_source_config('aliyundrive', next_config)
            db.session.commit()
            data = {
                "authenticated": False,
                "auth_state": auth_state,
                "pending_reason": login_state.get("pending_reason") or "waiting_for_scan",
                "source": source.to_dict(),
            }
            if login_state.get("qr_status") is not None:
                data["qr_status"] = login_state["qr_status"]
            return api_response(data=data)

        next_config = dict(source_config)
        next_config.update(_build_aliyundrive_source_config(login_state, auth_state='ready'))
        for key in ("qr_sid", "auth_provider"):
            next_config.pop(key, None)
        source.config = normalize_source_config('aliyundrive', next_config)
        db.session.commit()
        old_storage_deleted = _delete_replaced_runtime_storage(
            client,
            "Aliyundrive",
            source_id,
            old_storage_id,
            login_state.get("storage_id"),
        )
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "qr_status": login_state.get("qr_status"),
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": old_storage_deleted,
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Poll managed Aliyundrive QR failed source_id=%s error=%s", source_id, e)
        return api_error(code=50025, msg="Poll Aliyundrive QR login failed", http_status=500)


@storage_bp.route('/storage/managed/baidunetdisk/oauth/start', methods=['POST'])
def start_managed_baidunetdisk_oauth():
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or 'Baidu Netdisk').strip()
    root_path = str(payload.get('root_path') or payload.get('cloud_root_path') or payload.get('root_folder_path') or '').strip()
    download_api = _select_baidunetdisk_download_api(payload.get('download_api'))

    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")

    try:
        redirect_uri = api_url_for("storage.callback_managed_baidunetdisk_oauth")
        client = ManagedOpenListClient()
        oauth_state = client.start_baidunetdisk_oauth(
            redirect_uri=redirect_uri,
            root_path=root_path,
            download_api=download_api,
        )
        source_config = normalize_source_config(
            'baidunetdisk',
            _build_baidunetdisk_source_config(oauth_state, auth_state='oauth_pending'),
        )
        source = StorageSource(name=name, type='baidunetdisk', config=source_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data={
            "oauth_started": True,
            "auth_state": "oauth_pending",
            "pending_reason": oauth_state.get("pending_reason") or "waiting_for_authorization",
            "authorization_url": oauth_state["authorization_url"],
            "callback_url": None if oauth_state.get("requires_authorization_code") else redirect_uri,
            "callback_mode": oauth_state.get("callback_mode") or "redirect",
            "requires_authorization_code": bool(oauth_state.get("requires_authorization_code")),
            "authorization_code_submit_url": api_url_for("storage.complete_managed_baidunetdisk_oauth")
            if oauth_state.get("requires_authorization_code")
            else None,
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Start managed Baidu Netdisk OAuth failed error=%s", e)
        return api_error(code=50026, msg="Start Baidu Netdisk OAuth failed", http_status=500)


@storage_bp.route('/storage/managed/baidunetdisk/oauth/restart', methods=['POST'])
def restart_managed_baidunetdisk_oauth():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, 'baidunetdisk', 'Baidu Netdisk')
    if error_response:
        return error_response

    source_config = source.config or {}
    root_path = str(
        payload.get('root_path')
        or payload.get('cloud_root_path')
        or payload.get('root_folder_path')
        or source_config.get("root_folder_path")
        or source_config.get("cloud_root_path")
        or ''
    ).strip()
    download_api = _select_baidunetdisk_download_api(
        payload.get('download_api'),
        current_value=source_config.get("download_api"),
    )
    old_storage_id = _config_int(source_config, "openlist_storage_id")

    try:
        redirect_uri = api_url_for("storage.callback_managed_baidunetdisk_oauth")
        client = ManagedOpenListClient()
        oauth_state = client.start_baidunetdisk_oauth(
            redirect_uri=redirect_uri,
            root_path=root_path,
            download_api=download_api,
        )
        next_config = dict(source_config)
        next_config.update(_build_baidunetdisk_source_config(oauth_state, auth_state='oauth_pending'))
        next_config.pop("oauth_error", None)
        source.config = normalize_source_config('baidunetdisk', next_config)
        db.session.commit()
        return api_response(data={
            "oauth_restarted": True,
            "oauth_started": True,
            "auth_state": "oauth_pending",
            "pending_reason": oauth_state.get("pending_reason") or "waiting_for_authorization",
            "authorization_url": oauth_state["authorization_url"],
            "callback_url": None if oauth_state.get("requires_authorization_code") else redirect_uri,
            "callback_mode": oauth_state.get("callback_mode") or "redirect",
            "requires_authorization_code": bool(oauth_state.get("requires_authorization_code")),
            "authorization_code_submit_url": api_url_for("storage.complete_managed_baidunetdisk_oauth")
            if oauth_state.get("requires_authorization_code")
            else None,
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": False,
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Restart managed Baidu Netdisk OAuth failed source_id=%s error=%s", source_id, e)
        return api_error(code=50026, msg="Restart Baidu Netdisk OAuth failed", http_status=500)


@storage_bp.route('/storage/managed/baidunetdisk/oauth/poll', methods=['POST'])
def poll_managed_baidunetdisk_oauth():
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != 'baidunetdisk':
        return api_error(code=40061, msg="Storage source is not a managed Baidu Netdisk source")

    source_config = source.config or {}
    auth_state = str(source_config.get("auth_state") or "oauth_pending").strip().lower()
    if auth_state == "ready":
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })
    if auth_state == "oauth_failed":
        return api_response(data={
            "authenticated": False,
            "auth_state": "oauth_failed",
            "pending_reason": "oauth_failed",
            "error_message": source_config.get("oauth_error") or "Baidu Netdisk authorization failed",
            "source": source.to_dict(),
        })
    return api_response(data={
        "authenticated": False,
        "auth_state": "oauth_pending",
        "pending_reason": "waiting_for_authorization",
        "source": source.to_dict(),
    })


@storage_bp.route('/storage/managed/baidunetdisk/oauth/complete', methods=['POST'])
def complete_managed_baidunetdisk_oauth():
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    authorization_code = str(payload.get('authorization_code') or payload.get('code') or '').strip()
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")
    if not authorization_code:
        return api_error(code=40001, msg="Missing required field: authorization_code")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != 'baidunetdisk':
        return api_error(code=40061, msg="Storage source is not a managed Baidu Netdisk source")

    source_config = source.config or {}
    if str(source_config.get("auth_state") or "").strip().lower() == "ready":
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })

    try:
        login_state = _complete_baidunetdisk_oauth_source(source, authorization_code)
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "replaced_openlist_storage_id": login_state.get("replaced_openlist_storage_id"),
            "old_openlist_storage_deleted": bool(login_state.get("old_openlist_storage_deleted")),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        try:
            next_config = dict(source_config)
            next_config.update({
                "auth_state": "oauth_failed",
                "oauth_error": e.message,
            })
            source.config = normalize_source_config('baidunetdisk', next_config)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Persist Baidu Netdisk OAuth complete failure failed source_id=%s", source.id)
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Complete managed Baidu Netdisk OAuth failed source_id=%s error=%s", source_id, e)
        return api_error(code=50027, msg="Complete Baidu Netdisk OAuth failed", http_status=500)


@storage_bp.route('/storage/managed/baidunetdisk/oauth/callback', methods=['GET'])
def callback_managed_baidunetdisk_oauth():
    oauth_state = str(request.args.get("state") or "").strip()
    code = str(request.args.get("code") or "").strip()
    error = str(request.args.get("error") or request.args.get("error_description") or "").strip()
    source = _find_managed_source_by_oauth_state('baidunetdisk', oauth_state)
    if not source:
        return _oauth_html("Baidu Netdisk authorization failed", "OAuth state is invalid or expired"), 404

    source_config = source.config or {}
    try:
        if error:
            next_config = dict(source_config)
            next_config.update({
                "auth_state": "oauth_failed",
                "oauth_error": error,
            })
            source.config = normalize_source_config('baidunetdisk', next_config)
            db.session.commit()
            return _oauth_html("Baidu Netdisk authorization failed", error), 400
        if not code:
            next_config = dict(source_config)
            next_config.update({
                "auth_state": "oauth_failed",
                "oauth_error": "missing_authorization_code",
            })
            source.config = normalize_source_config('baidunetdisk', next_config)
            db.session.commit()
            return _oauth_html("Baidu Netdisk authorization failed", "Missing authorization code"), 400

        _complete_baidunetdisk_oauth_source(source, code)
        return _oauth_html(
            "Baidu Netdisk authorization completed",
            "Authorization completed. You can return to CyberStream.",
        )
    except ManagedAListError as e:
        db.session.rollback()
        try:
            next_config = dict(source_config)
            next_config.update({
                "auth_state": "oauth_failed",
                "oauth_error": e.message,
            })
            source.config = normalize_source_config('baidunetdisk', next_config)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Persist Baidu Netdisk OAuth failure failed source_id=%s", source.id)
        return _oauth_html("Baidu Netdisk authorization failed", e.message), 502 if e.code >= 500 else 400
    except StorageProviderError as e:
        db.session.rollback()
        return _oauth_html("Baidu Netdisk authorization failed", e.message), 400
    except Exception as e:
        db.session.rollback()
        logger.exception("Baidu Netdisk OAuth callback failed source_id=%s error=%s", source.id, e)
        return _oauth_html("Baidu Netdisk authorization failed", "Internal server error"), 500


@storage_bp.route('/storage/managed/123pan/login', methods=['POST'])
def login_managed_123pan():
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or '123Pan').strip()
    username = str(payload.get('username') or payload.get('account') or '').strip()
    password = str(payload.get('password') or '')
    root_folder_id = str(payload.get('root_folder_id') or '').strip()
    platform = str(payload.get('platform') or 'web').strip()

    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")
    if not username:
        return api_error(code=40001, msg="Missing required field: username")
    if not password:
        return api_error(code=40001, msg="Missing required field: password")

    storage_state = None
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_123pan_storage(
            username=username,
            password=password,
            root_folder_id=root_folder_id,
            platform=platform,
        )
        source_config = normalize_source_config(
            '123pan',
            _build_123pan_source_config(storage_state, auth_state='ready'),
        )
        source = StorageSource(name=name, type='123pan', config=source_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Login managed 123Pan failed error=%s", e)
        return api_error(code=50028, msg="Login 123Pan failed", http_status=500)


@storage_bp.route('/storage/managed/123pan/login/restart', methods=['POST'])
def restart_managed_123pan_login():
    payload = _get_json_payload()
    source_id, source, error_response = _load_managed_source(payload, '123pan', '123Pan')
    if error_response:
        return error_response

    username = str(payload.get('username') or payload.get('account') or '').strip()
    password = str(payload.get('password') or '')
    if not username:
        return api_error(code=40001, msg="Missing required field: username")
    if not password:
        return api_error(code=40001, msg="Missing required field: password")

    source_config = source.config or {}
    root_folder_id = str(
        payload.get('root_folder_id')
        if payload.get('root_folder_id') is not None
        else source_config.get("root_folder_id") or ''
    ).strip()
    platform = str(payload.get('platform') or source_config.get("platform") or 'web').strip()
    old_storage_id = _config_int(source_config, "openlist_storage_id")

    storage_state = None
    old_storage_deleted = False
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_123pan_storage(
            username=username,
            password=password,
            root_folder_id=root_folder_id,
            platform=platform,
        )
        next_config = dict(source_config)
        next_config.update(_build_123pan_source_config(storage_state, auth_state='ready'))
        source.config = normalize_source_config('123pan', next_config)
        db.session.commit()
        old_storage_deleted = _delete_replaced_runtime_storage(
            client,
            "123Pan",
            source_id,
            old_storage_id,
            storage_state["storage_id"],
        )
        return api_response(data={
            "login_restarted": True,
            "authenticated": True,
            "auth_state": "ready",
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": old_storage_deleted,
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Restart managed 123Pan login failed source_id=%s error=%s", source_id, e)
        return api_error(code=50028, msg="Restart 123Pan login failed", http_status=500)


def _start_managed_quark_uc_qr(source_type):
    provider_meta = _MANAGED_QUARK_UC_PROVIDERS[source_type]
    payload = _get_json_payload()
    name = (payload.get('name') or payload.get('source_name') or provider_meta["default_name"]).strip()
    root_folder_id = str(payload.get('root_folder_id') or '').strip()

    if not name:
        return api_error(code=40038, msg="Invalid field value: name cannot be empty")

    storage_state = None
    try:
        client = ManagedOpenListClient()
        storage_state = client.create_quark_uc_tv_storage(
            kind=source_type,
            root_folder_id=root_folder_id,
            link_method=QUARK_UC_OPENLIST_LINK_METHOD,
        )
        source_config = normalize_source_config(
            source_type,
            _build_quark_uc_source_config(storage_state, auth_state='qr_pending'),
        )
        source = StorageSource(name=name, type=source_type, config=source_config)
        db.session.add(source)
        db.session.commit()
        return api_response(data={
            "qr_started": True,
            "auth_state": "qr_pending",
            "qr_code_data_url": storage_state["qr_code_data_url"],
            "qr_content": storage_state.get("qr_content"),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Start managed %s QR failed error=%s", provider_meta["display_name"], e)
        return api_error(code=50020, msg=f"Start {provider_meta['display_name']} QR login failed", http_status=500)


def _restart_managed_quark_uc_qr(source_type):
    provider_meta = _MANAGED_QUARK_UC_PROVIDERS[source_type]
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != source_type:
        return api_error(code=40061, msg=f"Storage source is not a managed {provider_meta['display_name']} source")

    source_config = source.config or {}
    root_folder_id = str(
        payload.get('root_folder_id')
        if payload.get('root_folder_id') is not None
        else source_config.get("root_folder_id") or "0"
    ).strip() or "0"
    old_storage_id = None
    try:
        old_storage_id = int(source_config.get("openlist_storage_id") or 0) or None
    except (TypeError, ValueError):
        old_storage_id = None

    storage_state = None
    old_storage_deleted = False
    try:
        client = ManagedOpenListClient()
        if old_storage_id:
            old_storage_deleted = _delete_replaced_runtime_storage(
                client,
                provider_meta["display_name"],
                source_id,
                old_storage_id,
            )
        storage_state = client.create_quark_uc_tv_storage(
            kind=source_type,
            root_folder_id=root_folder_id,
            link_method=QUARK_UC_OPENLIST_LINK_METHOD,
        )
        next_config = dict(source_config)
        next_config.update(_build_quark_uc_source_config(storage_state, auth_state='qr_pending'))
        source.config = normalize_source_config(source_type, next_config)
        db.session.commit()
        return api_response(data={
            "qr_restarted": True,
            "qr_started": True,
            "auth_state": "qr_pending",
            "replaced_openlist_storage_id": old_storage_id,
            "old_openlist_storage_deleted": old_storage_deleted,
            "qr_code_data_url": storage_state["qr_code_data_url"],
            "qr_content": storage_state.get("qr_content"),
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        if storage_state and storage_state.get("storage_id"):
            try:
                ManagedOpenListClient().delete_storage(storage_state["storage_id"])
            except Exception:
                logger.exception("Rollback managed OpenList storage failed id=%s", storage_state.get("storage_id"))
        logger.exception("Restart managed %s QR failed source_id=%s error=%s", provider_meta["display_name"], source_id, e)
        return api_error(code=50020, msg=f"Restart {provider_meta['display_name']} QR login failed", http_status=500)


@storage_bp.route('/storage/managed/quarktv/qr/start', methods=['POST'])
def start_managed_quarktv_qr():
    return _start_managed_quark_uc_qr('quarktv')


@storage_bp.route('/storage/managed/quarktv/qr/restart', methods=['POST'])
def restart_managed_quarktv_qr():
    return _restart_managed_quark_uc_qr('quarktv')


@storage_bp.route('/storage/managed/uctv/qr/start', methods=['POST'])
def start_managed_uctv_qr():
    return _start_managed_quark_uc_qr('uctv')


@storage_bp.route('/storage/managed/uctv/qr/restart', methods=['POST'])
def restart_managed_uctv_qr():
    return _restart_managed_quark_uc_qr('uctv')


def _poll_managed_quark_uc_qr(source_type):
    provider_meta = _MANAGED_QUARK_UC_PROVIDERS[source_type]
    payload = _get_json_payload()
    source_id = payload.get('source_id') or payload.get('id')
    if not source_id:
        return api_error(code=40001, msg="Missing required field: source_id")

    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return api_error(code=40036, msg="Invalid field type: source_id should be integer")

    source = db.session.get(StorageSource, source_id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)
    if source.type != source_type:
        return api_error(code=40061, msg=f"Storage source is not a managed {provider_meta['display_name']} source")

    try:
        source_config = source.config or {}
        storage_id = int(source_config.get("openlist_storage_id") or 0)
        if not storage_id:
            return api_error(code=40061, msg=f"Managed {provider_meta['display_name']} source has no OpenList storage id")
        client = ManagedOpenListClient()
        login_state = client.poll_quark_uc_tv_storage(storage_id, source_type)
        if not login_state.get("authenticated"):
            auth_state = login_state.get("auth_state") or "qr_pending"
            if auth_state == "device_limit":
                next_config = dict(source_config)
                next_config["auth_state"] = "device_limit"
                source.config = normalize_source_config(source_type, next_config)
                db.session.commit()
            data = {
                "authenticated": False,
                "auth_state": auth_state,
                "pending_reason": login_state.get("pending_reason") or (
                    "qr_expired" if auth_state == "qr_expired" else "waiting_for_scan"
                ),
                "source": source.to_dict(),
            }
            if login_state.get("qr_code_data_url"):
                data["qr_code_data_url"] = login_state["qr_code_data_url"]
                data["qr_content"] = login_state.get("qr_content")
            return api_response(data=data)

        next_config = dict(source_config)
        next_config.update({
            "openlist_storage_id": storage_id,
            "mount_path": login_state["mount_path"],
            "auth_state": "ready",
            "cloud_root_path": login_state.get("cloud_root_path") or source_config.get("cloud_root_path") or "/",
            "root_folder_id": str(login_state.get("root_folder_id") or source_config.get("root_folder_id") or "0"),
        })
        source.config = normalize_source_config(source_type, next_config)
        db.session.commit()
        return api_response(data={
            "authenticated": True,
            "auth_state": "ready",
            "source": source.to_dict(),
        })
    except ManagedAListError as e:
        db.session.rollback()
        return _managed_alist_error_response(e)
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Poll managed %s QR failed source_id=%s error=%s", provider_meta["display_name"], source_id, e)
        return api_error(code=50021, msg=f"Poll {provider_meta['display_name']} QR login failed", http_status=500)


@storage_bp.route('/storage/managed/quarktv/qr/poll', methods=['POST'])
def poll_managed_quarktv_qr():
    return _poll_managed_quark_uc_qr('quarktv')


@storage_bp.route('/storage/managed/uctv/qr/poll', methods=['POST'])
def poll_managed_uctv_qr():
    return _poll_managed_quark_uc_qr('uctv')


@storage_bp.route('/storage/sources/<int:id>', methods=['PATCH'])
def update_storage_source(id):
    """v1.9.0 新增: 更新存储源配置 (支持 name, config 修改)。"""
    source = db.session.get(StorageSource, id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)

    payload = _get_json_payload()
    if not payload:
        return api_error(code=40000, msg="No input data")

    try:
        guards = source.get_mutation_guards()
        current_type = normalize_source_type(source.type)
        if 'name' in payload:
            name = (payload.get('name') or '').strip()
            if not name:
                return api_error(code=40038, msg="Invalid field value: name cannot be empty")
            source.name = name
        next_type = current_type
        next_config = source.config

        if 'type' in payload:
            next_type = normalize_source_type(payload.get('type'))
            if next_type != source.type and not guards["can_change_type"]:
                return api_error(
                    code=40039,
                    msg="Cannot change source type while resources or library bindings still reference this source",
                )
        if 'config' in payload:
            next_config = payload['config']
            if next_type == current_type:
                _, next_config = restore_masked_source_secrets(next_type, next_config, source.config)

        if 'type' in payload or 'config' in payload:
            source.type = next_type
            source.config = normalize_source_config(next_type, next_config)

        db.session.commit()
        return api_response(msg="Source updated successfully")
    except StorageProviderError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        db.session.rollback()
        logger.exception("Update storage source failed id=%s error=%s", id, e)
        return api_error(code=50007, msg="Update failed", http_status=500)


@storage_bp.route('/storage/sources/<int:id>', methods=['DELETE'])
def delete_source(id):
    if scanner_engine.is_scanning:
        return api_error(code=42900, msg="Scanner is running, cannot delete source", http_status=429)

    payload = _get_json_payload()
    keep_metadata, keep_metadata_ok = _coerce_bool(
        payload.get('keepMetadata', payload.get('keep_metadata')),
        default=None,
    )
    if not keep_metadata_ok:
        return api_error(code=40041, msg="Invalid field value: keepMetadata should be boolean")
    if keep_metadata is None:
        keep_metadata = request.args.get('keep_metadata', 'false').lower() == 'true'
    source = db.session.get(StorageSource, id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)

    guards = source.get_mutation_guards()
    if guards["has_dependents"] and not keep_metadata:
        try:
            verify_vault_pin(payload, audit_action="storage.source.delete.verify_pin")
        except VaultAccessError as e:
            db.session.rollback()
            return _vault_error_response(e)

    managed_storage_id = None
    managed_client_class = None
    if source.type == 'guangyapan':
        managed_storage_id = (source.config or {}).get('alist_storage_id')
        managed_client_class = ManagedAListClient
    elif source.type in {'tianyicloud', '115cloud', 'aliyundrive', 'baidunetdisk', '123pan', 'quarktv', 'uctv'}:
        managed_storage_id = (source.config or {}).get('openlist_storage_id')
        managed_client_class = ManagedOpenListClient
    success, msg = scanner_adapter.delete_storage_source(id, keep_metadata)
    if not success:
        return api_error(code=40003, msg=msg, http_status=404 if 'not found' in msg else 500)

    if managed_storage_id:
        try:
            managed_client_class().delete_storage(managed_storage_id)
        except Exception:
            logger.exception("Delete managed storage runtime entry failed source_id=%s storage_id=%s", id, managed_storage_id)

    return api_response(msg="Source deleted successfully")


@storage_bp.route('/storage/sources/<int:id>/scan', methods=['POST'])
def scan_specific_source(id):
    # 安全护栏（要早于 scanner_engine.try_start_scan，避免占着扫描锁不放）：
    # 没传 root_path 时，必须存在指向这个 source 的 library_sources 绑定，
    # 否则拒绝。否则 scanner_engine.scan_source(source) 会从存储源根开始
    # 全盘扫，云盘场景下分分钟扫掉几万个文件。
    payload = _get_json_payload()
    root_path = _normalize_relative_path(payload.get('root_path') or payload.get('target_path'))
    if not root_path:
        from backend.app.models import LibrarySource
        has_binding = (
            db.session.query(LibrarySource.id)
            .filter_by(source_id=id, is_enabled=True)
            .first()
            is not None
        )
        if not has_binding:
            return api_error(
                code=40013,
                msg=(
                    "该存储源未被任何媒体库绑定，且未指定要扫描的子目录。"
                    "请先在「资源库」中把该存储源绑定到具体的媒体库目录，"
                    "或在请求体里通过 root_path 字段显式指定要扫描的子路径。"
                ),
            )

    if not scanner_engine.try_start_scan():
        return api_error(code=42900, msg="Scanner is busy", http_status=429)

    source = db.session.get(StorageSource, id)
    if not source:
        scanner_engine.finish_scan()
        return api_error(code=40402, msg="Source not found", http_status=404)

    content_type = payload.get('content_type')
    scrape_enabled, ok = _coerce_bool(payload.get('scrape_enabled'), default=True)
    if not ok:
        scanner_engine.finish_scan()
        return api_error(code=40041, msg="Invalid field value: scrape_enabled should be boolean")
    try:
        scraper_policy = normalize_scraper_policy_payload(
            raw_policy=payload.get('scraper_policy'),
            provider_order=payload.get('provider_order') or payload.get('providers'),
        )
    except ScraperPolicyError as e:
        scanner_engine.finish_scan()
        return api_error(code=e.code, msg=e.msg)

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_scan_background_task,
        args=(app, id, root_path, content_type, scrape_enabled, scraper_policy),
    )
    thread.start()
    return api_response(
        data={
            "source_id": id,
            "root_path": _display_relative_path(root_path),
            "content_type": content_type,
            "scrape_enabled": scrape_enabled,
            "scraper_policy": scraper_policy,
        },
        msg="Scan started",
        http_status=202,
    )


@storage_bp.route('/storage/sources/<int:id>/browse', methods=['GET'])
def browse_storage_source(id):
    """浏览已保存存储源的目录，主要用于资源库绑定时选择 root_path。"""
    source = db.session.get(StorageSource, id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)

    target_path = _normalize_relative_path(request.args.get('path'))
    dirs_only, ok = _coerce_bool(request.args.get('dirs_only'), default=True)
    if not ok:
        return api_error(code=40041, msg="Invalid query value: dirs_only should be boolean")

    try:
        provider = provider_factory.get_provider(source)
        items = _list_directory_or_invalid(provider, target_path)
        return api_response(data={
            "source": source.to_dict(),
            **_build_browse_payload(items, target_path, dirs_only=dirs_only),
        })
    except StorageProviderError as e:
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        err_msg = str(e)
        logger.exception("Browse storage source failed source_id=%s path=%s error=%s", id, target_path, e)
        return api_error(code=50002, msg=f"Browse failed: {err_msg}", http_status=500)


@storage_bp.route('/storage/sources/<int:id>/refresh', methods=['POST'])
def refresh_storage_source_directory(id):
    """刷新支持目录缓存的已保存存储源目录，不触发扫描或刮削。"""
    source = db.session.get(StorageSource, id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)

    payload = _get_json_payload()
    target_path = _normalize_relative_path(
        payload.get('path') or payload.get('target_path') or payload.get('root_path')
    )
    dirs_only, ok = _coerce_bool(payload.get('dirs_only'), default=False)
    if not ok:
        return api_error(code=40041, msg="Invalid field value: dirs_only should be boolean")

    try:
        provider = provider_factory.get_provider(source)
        items = provider.refresh_directory(target_path)
        return api_response(data={
            "source": source.to_dict(),
            "refreshed": True,
            "refresh_path": _display_relative_path(target_path),
            **_build_browse_payload(items, target_path, dirs_only=dirs_only),
        })
    except StorageProviderError as e:
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        err_msg = str(e)
        logger.exception("Refresh storage source failed source_id=%s path=%s error=%s", id, target_path, e)
        return api_error(code=50015, msg=f"Refresh failed: {err_msg}", http_status=500)


@storage_bp.route('/storage/preview', methods=['POST'])
def preview_storage():
    """无需保存即可预览目录结构。"""
    payload = _get_json_payload()
    storage_type = payload.get('type')
    config = payload.get('config')
    target_path = _normalize_relative_path(payload.get('target_path', '/'))
    dirs_only, ok = _coerce_bool(payload.get('dirs_only'), default=True)

    if not storage_type or not config:
        return api_error(code=40001, msg="Missing type or config")
    if not ok:
        return api_error(code=40041, msg="Invalid field value: dirs_only should be boolean")

    try:
        normalized_config, error_response = _normalize_storage_config(storage_type, config)
        if error_response:
            return error_response
        provider = provider_factory.create(storage_type, normalized_config)
        items = _list_directory_or_invalid(provider, target_path)
        normalized_type, capabilities = get_source_capabilities(storage_type)
        preview_data = {
            "storage_type": normalized_type,
            "capabilities": capabilities,
            **_build_browse_payload(items, target_path, dirs_only=dirs_only),
        }
        return api_response(data=preview_data)
    except StorageProviderError as e:
        return api_error(code=e.code, msg=e.message)
    except Exception as e:
        err_msg = str(e)
        logger.exception("Preview storage failed type=%s target_path=%s error=%s", storage_type, target_path, e)
        return api_error(code=50001, msg=f"Connect failed: {err_msg}", http_status=500)
