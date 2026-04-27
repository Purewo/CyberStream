import logging
import threading

from flask import Blueprint, current_app, request

from backend.app.db.database import scanner_adapter
from backend.app.extensions import db
from backend.app.models import StorageSource
from backend.app.providers.base import StorageProviderError
from backend.app.providers.factory import provider_factory
from backend.app.services.scanner import scanner_engine
from backend.app.storage.source_registry import (
    list_supported_source_types,
    get_source_capabilities,
    normalize_source_config,
    normalize_source_type,
)
from backend.app.utils.response import api_error, api_response

logger = logging.getLogger(__name__)

storage_bp = Blueprint('storage', __name__, url_prefix='/api/v1')


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


def _scan_background_task(app, source_id=None, root_path=None, content_type=None, scrape_enabled=True):
    with app.app_context():
        try:
            scanner_engine.scan(
                source_id,
                root_path=root_path,
                content_type=content_type,
                scrape_enabled=scrape_enabled,
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
        if 'name' in payload:
            name = (payload.get('name') or '').strip()
            if not name:
                return api_error(code=40038, msg="Invalid field value: name cannot be empty")
            source.name = name
        next_type = source.type
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

    keep_metadata = request.args.get('keep_metadata', 'false').lower() == 'true'
    source = db.session.get(StorageSource, id)
    if not source:
        return api_error(code=40402, msg="Source not found", http_status=404)

    guards = source.get_mutation_guards()
    if guards["requires_keep_metadata_on_delete"] and not keep_metadata:
        return api_error(
            code=40040,
            msg="Source still has resources; pass keep_metadata=true or migrate resources first",
        )

    success, msg = scanner_adapter.delete_storage_source(id, keep_metadata)
    if not success:
        return api_error(code=40003, msg=msg, http_status=404 if 'not found' in msg else 500)

    return api_response(msg="Source deleted successfully")


@storage_bp.route('/storage/sources/<int:id>/scan', methods=['POST'])
def scan_specific_source(id):
    if not scanner_engine.try_start_scan():
        return api_error(code=42900, msg="Scanner is busy", http_status=429)

    source = db.session.get(StorageSource, id)
    if not source:
        scanner_engine.finish_scan()
        return api_error(code=40402, msg="Source not found", http_status=404)

    payload = _get_json_payload()
    root_path = _normalize_relative_path(payload.get('root_path') or payload.get('target_path'))
    content_type = payload.get('content_type')
    scrape_enabled, ok = _coerce_bool(payload.get('scrape_enabled'), default=True)
    if not ok:
        scanner_engine.finish_scan()
        return api_error(code=40041, msg="Invalid field value: scrape_enabled should be boolean")

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_scan_background_task,
        args=(app, id, root_path, content_type, scrape_enabled),
    )
    thread.start()
    return api_response(
        data={
            "source_id": id,
            "root_path": _display_relative_path(root_path),
            "content_type": content_type,
            "scrape_enabled": scrape_enabled,
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
