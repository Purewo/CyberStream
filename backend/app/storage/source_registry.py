from backend.app.providers.base import StorageProviderError


SOURCE_TYPE_DEFINITIONS = {
    'local': {
        'display_name': 'Local Filesystem',
        'status': 'stable',
        'capabilities': {
            'preview': True,
            'scan': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
        },
        'secret_fields': [],
        'config_fields': [
            {
                'name': 'root_path',
                'type': 'string',
                'required': True,
                'description': '后端机器可访问的本地根目录',
            },
        ],
    },
    'webdav': {
        'display_name': 'WebDAV',
        'status': 'stable',
        'capabilities': {
            'preview': True,
            'scan': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
        },
        'secret_fields': ['password'],
        'config_fields': [
            {
                'name': 'host',
                'type': 'string',
                'required': True,
                'description': 'WebDAV 主机名或 IP',
            },
            {
                'name': 'port',
                'type': 'integer',
                'required': False,
                'default': 443,
                'description': 'WebDAV 端口',
            },
            {
                'name': 'secure',
                'type': 'boolean',
                'required': False,
                'default': True,
                'description': '是否使用 HTTPS',
            },
            {
                'name': 'username',
                'type': 'string',
                'required': False,
                'description': '认证用户名',
            },
            {
                'name': 'password',
                'type': 'string',
                'required': False,
                'description': '认证密码',
            },
            {
                'name': 'root',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': 'WebDAV 挂载根路径',
            },
        ],
    },
    'smb': {
        'display_name': 'SMB',
        'status': 'stable',
        'capabilities': {
            'preview': True,
            'scan': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': True,
            'range_stream': True,
        },
        'secret_fields': ['password'],
        'config_fields': [
            {
                'name': 'host',
                'type': 'string',
                'required': True,
                'description': 'SMB 主机名或 IP',
            },
            {
                'name': 'share',
                'type': 'string',
                'required': True,
                'description': 'SMB 共享名',
            },
            {
                'name': 'username',
                'type': 'string',
                'required': False,
                'default': '',
                'description': '认证用户名',
            },
            {
                'name': 'password',
                'type': 'string',
                'required': False,
                'default': '',
                'description': '认证密码',
            },
            {
                'name': 'domain',
                'type': 'string',
                'required': False,
                'default': '',
                'description': '域或工作组，可选',
            },
            {
                'name': 'workgroup',
                'type': 'string',
                'required': False,
                'default': '',
                'description': '工作组，可选',
            },
            {
                'name': 'remote_name',
                'type': 'string',
                'required': False,
                'description': 'SMB 远端 NetBIOS 名称，默认使用 host',
            },
            {
                'name': 'client_name',
                'type': 'string',
                'required': False,
                'default': '',
                'description': 'SMB 客户端名称，可选',
            },
            {
                'name': 'root',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '共享内根路径',
            },
            {
                'name': 'port',
                'type': 'integer',
                'required': False,
                'default': 445,
                'description': 'SMB 端口',
            },
            {
                'name': 'timeout',
                'type': 'integer',
                'required': False,
                'default': 30,
                'description': '请求超时时间，秒',
            },
        ],
    },
    'ftp': {
        'display_name': 'FTP',
        'status': 'stable',
        'capabilities': {
            'preview': True,
            'scan': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': True,
            'range_stream': True,
        },
        'secret_fields': ['password'],
        'config_fields': [
            {
                'name': 'host',
                'type': 'string',
                'required': True,
                'description': 'FTP 主机名或 IP',
            },
            {
                'name': 'username',
                'type': 'string',
                'required': False,
                'default': 'anonymous',
                'description': '认证用户名，默认 anonymous',
            },
            {
                'name': 'user',
                'type': 'string',
                'required': False,
                'description': 'username 的兼容别名',
            },
            {
                'name': 'password',
                'type': 'string',
                'required': False,
                'default': 'anonymous@',
                'description': '认证密码',
            },
            {
                'name': 'root',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': 'FTP 根路径',
            },
            {
                'name': 'port',
                'type': 'integer',
                'required': False,
                'default': 21,
                'description': 'FTP 端口',
            },
            {
                'name': 'secure',
                'type': 'boolean',
                'required': False,
                'default': False,
                'description': '是否使用 FTPS',
            },
            {
                'name': 'passive',
                'type': 'boolean',
                'required': False,
                'default': True,
                'description': '是否使用被动模式',
            },
            {
                'name': 'timeout',
                'type': 'integer',
                'required': False,
                'default': 30,
                'description': '请求超时时间，秒',
            },
        ],
    },
    'alist': {
        'display_name': 'AList',
        'status': 'stable',
        'capabilities': {
            'preview': True,
            'scan': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': True,
            'redirect_stream': True,
        },
        'secret_fields': ['token', 'password', 'path_password'],
        'config_fields': [
            {
                'name': 'base_url',
                'type': 'string',
                'required': False,
                'description': 'AList 根地址，可包含协议、端口和前缀路径',
            },
            {
                'name': 'host',
                'type': 'string',
                'required': False,
                'description': 'AList 主机名或 IP；未提供 base_url 时使用',
            },
            {
                'name': 'port',
                'type': 'integer',
                'required': False,
                'default': 5244,
                'description': 'AList 端口',
            },
            {
                'name': 'secure',
                'type': 'boolean',
                'required': False,
                'default': False,
                'description': '是否使用 HTTPS',
            },
            {
                'name': 'base_path',
                'type': 'string',
                'required': False,
                'default': '',
                'description': '部署在子路径时填写，例如 /alist',
            },
            {
                'name': 'root',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': 'AList 内部根路径',
            },
            {
                'name': 'token',
                'type': 'string',
                'required': False,
                'description': 'AList API token，优先于账号密码',
            },
            {
                'name': 'username',
                'type': 'string',
                'required': False,
                'description': '认证用户名',
            },
            {
                'name': 'password',
                'type': 'string',
                'required': False,
                'description': '认证密码',
            },
            {
                'name': 'otp_code',
                'type': 'string',
                'required': False,
                'description': '二步验证验证码，可选',
            },
            {
                'name': 'path_password',
                'type': 'string',
                'required': False,
                'description': '目录密码，可选',
            },
            {
                'name': 'timeout',
                'type': 'integer',
                'required': False,
                'default': 30,
                'description': '请求超时时间，秒',
            },
            {
                'name': 'verify_ssl',
                'type': 'boolean',
                'required': False,
                'default': False,
                'description': '是否校验证书',
            },
            {
                'name': 'proxy_stream',
                'type': 'boolean',
                'required': False,
                'default': False,
                'description': '兼容字段；AList/OpenList 播放默认返回 /d 域名入口，不做后端中转',
            },
        ],
    },
    'openlist': {
        'display_name': 'OpenList',
        'status': 'stable',
        'capabilities': {
            'preview': True,
            'scan': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': True,
            'redirect_stream': True,
        },
        'secret_fields': ['token', 'password', 'path_password'],
        'config_fields': [],
    },
}

SOURCE_TYPE_DEFINITIONS['openlist']['config_fields'] = SOURCE_TYPE_DEFINITIONS['alist']['config_fields']

REMOTE_ROOT_SOURCE_TYPES = {'webdav', 'smb', 'ftp', 'alist', 'openlist'}

LEGACY_CONFIG_ALIASES = {
    'path': 'root_path',
    'user': 'username',
}


def normalize_source_type(s_type):
    normalized = str(s_type or '').strip().lower()
    if not normalized:
        raise StorageProviderError("Storage type is required", code=40031)
    return normalized


def get_source_definition(s_type):
    normalized = normalize_source_type(s_type)
    definition = SOURCE_TYPE_DEFINITIONS.get(normalized)
    if not definition:
        raise StorageProviderError(f"Unsupported storage type: {normalized}", code=40032)
    return normalized, definition


def get_source_display_name(s_type):
    normalized_type, definition = get_source_definition(s_type)
    return normalized_type, definition['display_name']


def list_supported_source_types():
    items = []
    for source_type in sorted(SOURCE_TYPE_DEFINITIONS.keys()):
        definition = SOURCE_TYPE_DEFINITIONS[source_type]
        items.append({
            'type': source_type,
            'display_name': definition['display_name'],
            'status': definition.get('status', 'stable'),
            'capabilities': dict(definition.get('capabilities', {})),
            'config_fields': [dict(field) for field in definition.get('config_fields', [])],
        })
    return items


def get_source_capabilities(s_type):
    normalized_type, definition = get_source_definition(s_type)
    return normalized_type, dict(definition.get('capabilities', {}))


def normalize_source_config(s_type, config):
    normalized_type, definition = get_source_definition(s_type)
    if not isinstance(config, dict):
        raise StorageProviderError("Storage config should be object", code=40033)

    raw_config = dict(config)
    normalized = {}
    allowed_field_names = set()

    for field in definition.get('config_fields', []):
        field_name = field['name']
        allowed_field_names.add(field_name)

        raw_value = raw_config.get(field_name)
        if raw_value is None:
            legacy_key = next(
                (alias for alias, target in LEGACY_CONFIG_ALIASES.items() if target == field_name and alias in raw_config),
                None,
            )
            if legacy_key:
                raw_value = raw_config.get(legacy_key)

        value = _normalize_config_field_value(field, raw_value)

        if value is None and 'default' in field:
            value = field['default']

        if field.get('required') and value in (None, ''):
            raise StorageProviderError(f"Missing required config field: {field_name}", code=40034)

        if value is not None:
            normalized[field_name] = value

    unknown_keys = sorted([
        key for key in raw_config.keys()
        if key not in allowed_field_names and key not in LEGACY_CONFIG_ALIASES
    ])
    if unknown_keys:
        raise StorageProviderError(
            f"Unsupported config fields for {normalized_type}: {', '.join(unknown_keys)}",
            code=40035,
        )

    if normalized_type in {'alist', 'openlist'} and not normalized.get('base_url') and not normalized.get('host'):
        raise StorageProviderError(f"Missing required config field: base_url or host", code=40034)

    _normalize_post_config_fields(normalized_type, normalized)
    return normalized


def sanitize_source_config(s_type, config):
    normalized_type, definition = get_source_definition(s_type)
    normalized_config = normalize_source_config(normalized_type, config or {})
    masked = {}
    secret_fields = set(definition.get('secret_fields', []))

    for key, value in normalized_config.items():
        if key in secret_fields and value not in (None, ''):
            masked[key] = '***'
        else:
            masked[key] = value

    return normalized_type, masked


def build_source_display_root(s_type, config):
    try:
        normalized_type = normalize_source_type(s_type)
    except StorageProviderError:
        return "Unknown"

    display_config = _build_display_config(normalized_type, config)

    if normalized_type == 'local':
        return display_config.get('root_path', '')

    if normalized_type == 'webdav':
        protocol = 'https' if display_config.get('secure', True) else 'http'
        host = display_config.get('host', 'unknown')
        port = display_config.get('port', 443)
        root = display_config.get('root', '/')
        return f"{protocol}://{host}:{port}{root}"

    if normalized_type == 'smb':
        host = display_config.get('host', 'unknown')
        share = display_config.get('share', '')
        root = display_config.get('root', '/')
        suffix = root if isinstance(root, str) and root not in {'', '/'} else ''
        suffix = suffix.replace('/', '\\')
        return f"\\\\{host}\\{share}{suffix}"

    if normalized_type == 'ftp':
        scheme = 'ftps' if display_config.get('secure', False) else 'ftp'
        host = display_config.get('host', 'unknown')
        port = display_config.get('port', 21)
        root = display_config.get('root', '/')
        return f"{scheme}://{host}:{port}{root}"

    if normalized_type in {'alist', 'openlist'}:
        root = display_config.get('root', '/')
        base_url = display_config.get('base_url')
        if base_url:
            return f"{base_url.rstrip('/')}{root}"
        protocol = 'https' if display_config.get('secure', False) else 'http'
        host = display_config.get('host', 'unknown')
        port = display_config.get('port', 5244)
        base_path = str(display_config.get('base_path') or '').strip().strip('/')
        suffix = f"/{base_path}" if base_path else ''
        return f"{protocol}://{host}:{port}{suffix}{root}"

    return "Unknown"


def _build_display_config(s_type, config):
    raw_config = config if isinstance(config, dict) else {}

    try:
        _, definition = get_source_definition(s_type)
    except StorageProviderError:
        return raw_config

    display_config = {}

    for field in definition.get('config_fields', []):
        field_name = field['name']
        raw_value = raw_config.get(field_name)

        if raw_value is None:
            legacy_key = next(
                (alias for alias, target in LEGACY_CONFIG_ALIASES.items() if target == field_name and alias in raw_config),
                None,
            )
            if legacy_key:
                raw_value = raw_config.get(legacy_key)

        try:
            value = _normalize_config_field_value(field, raw_value)
        except StorageProviderError:
            value = raw_value

        if value is None and 'default' in field:
            value = field['default']

        if value is not None:
            display_config[field_name] = value

    _normalize_post_config_fields(s_type, display_config)
    return display_config


def _normalize_post_config_fields(s_type, config):
    if not isinstance(config, dict):
        return

    normalized_type = normalize_source_type(s_type)

    if normalized_type in REMOTE_ROOT_SOURCE_TYPES and 'root' in config:
        config['root'] = _normalize_remote_root(config.get('root'))

    if normalized_type in {'alist', 'openlist'}:
        if isinstance(config.get('base_url'), str):
            config['base_url'] = config['base_url'].rstrip('/')
        config.setdefault('host', '')

    if normalized_type == 'smb':
        config.setdefault('remote_name', config.get('host', ''))


def _normalize_remote_root(value):
    raw = str(value or '').replace('\\', '/').strip()
    if not raw or raw == '/':
        return '/'
    return '/' + raw.strip('/')


def _normalize_config_field_value(field, value):
    field_name = field['name']
    field_type = field.get('type', 'string')

    if value is None:
        return None

    if field_type == 'string':
        if not isinstance(value, str):
            raise StorageProviderError(f"Invalid config field type: {field_name} should be string", code=40036)
        value = value.strip()
        return value or None

    if field_type == 'integer':
        if isinstance(value, bool):
            raise StorageProviderError(f"Invalid config field type: {field_name} should be integer", code=40036)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if not value.isdigit():
                raise StorageProviderError(f"Invalid config field type: {field_name} should be integer", code=40036)
            value = int(value)
        if not isinstance(value, int):
            raise StorageProviderError(f"Invalid config field type: {field_name} should be integer", code=40036)
        return value

    if field_type == 'boolean':
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ('true', '1', 'yes', 'on'):
                return True
            if normalized in ('false', '0', 'no', 'off'):
                return False
        raise StorageProviderError(f"Invalid config field type: {field_name} should be boolean", code=40036)

    raise StorageProviderError(f"Unsupported config schema type: {field_type}", code=40037)
