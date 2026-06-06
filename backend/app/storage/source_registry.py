from backend.app.providers.base import StorageProviderError


MASKED_SECRET_VALUE = '***'


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
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': True,
            'redirect_stream': True,
        },
        'secret_fields': ['token', 'password', 'otp_code', 'path_password'],
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
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': True,
            'redirect_stream': True,
        },
        'secret_fields': ['token', 'password', 'otp_code', 'path_password'],
        'config_fields': [],
    },
    'guangyapan': {
        'display_name': 'GuangYaPan',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'sms_login': True,
        },
        'secret_fields': [],
        'hidden_fields': ['alist_storage_id', 'mount_path'],
        'config_fields': [
            {
                'name': 'alist_storage_id',
                'type': 'integer',
                'required': True,
                'description': 'CyberStream 托管 AList 内部 storage id',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': True,
                'description': 'CyberStream 托管 AList 内部挂载路径',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'sms_pending',
                'description': '短信认证状态：sms_pending 或 ready',
            },
            {
                'name': 'phone_number_masked',
                'type': 'string',
                'required': False,
                'description': '脱敏手机号，仅用于展示',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '光鸭云盘侧根路径，仅用于展示',
            },
        ],
    },
    'tianyicloud': {
        'display_name': 'TianYiCloud',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'qr_login': True,
        },
        'secret_fields': [],
        'hidden_fields': ['openlist_storage_id', 'mount_path', 'login_mode'],
        'config_fields': [
            {
                'name': 'openlist_storage_id',
                'type': 'integer',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部 storage id',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部挂载路径',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'qr_pending',
                'description': '扫码认证状态：qr_pending 或 ready',
            },
            {
                'name': 'cloud_type',
                'type': 'string',
                'required': False,
                'default': 'personal',
                'description': '天翼云盘类型：personal 或 family',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '天翼云盘侧根路径，仅用于展示',
            },
            {
                'name': 'root_folder_id',
                'type': 'string',
                'required': False,
                'default': '-11',
                'description': 'OpenList 189CloudTV root_folder_id',
            },
            {
                'name': 'login_mode',
                'type': 'string',
                'required': False,
                'description': 'CyberStream internal TianYiCloud login mode; omitted for default TV QR, pc_qr for experimental PC QR.',
            },
        ],
    },
    '115cloud': {
        'display_name': '115 Cloud',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'qr_login': True,
        },
        'secret_fields': [],
        'hidden_fields': ['openlist_storage_id', 'mount_path', 'qr_uid', 'qr_sign', 'qr_time'],
        'config_fields': [
            {
                'name': 'openlist_storage_id',
                'type': 'integer',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部 storage id',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部挂载路径',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'qr_pending',
                'description': '扫码认证状态：qr_pending、qr_expired、qr_canceled 或 ready',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '115 云盘侧根路径，仅用于展示',
            },
            {
                'name': 'qrcode_source',
                'type': 'string',
                'required': False,
                'default': 'wechatmini',
                'description': '115 二维码登录端类型：web、android、ios、tv、alipaymini、wechatmini 或 qandroid',
            },
            {
                'name': 'root_folder_id',
                'type': 'string',
                'required': False,
                'default': '0',
                'description': 'OpenList 115 Cloud root_folder_id',
            },
            {
                'name': 'qr_uid',
                'type': 'string',
                'required': False,
                'description': '115 二维码会话 uid，后端隐藏字段',
            },
            {
                'name': 'qr_sign',
                'type': 'string',
                'required': False,
                'description': '115 二维码会话签名，后端隐藏字段',
            },
            {
                'name': 'qr_time',
                'type': 'integer',
                'required': False,
                'description': '115 二维码会话时间戳，后端隐藏字段',
            },
        ],
    },
    'aliyundrive': {
        'display_name': 'Aliyundrive',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'qr_login': True,
        },
        'secret_fields': [],
        'hidden_fields': ['openlist_storage_id', 'mount_path', 'qr_sid', 'auth_provider'],
        'config_fields': [
            {
                'name': 'openlist_storage_id',
                'type': 'integer',
                'required': False,
                'description': 'CyberStream 托管 OpenList 内部 storage id；扫码完成后才会生成',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': False,
                'description': 'CyberStream 托管 OpenList 内部挂载路径；扫码完成后才会生成',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'qr_pending',
                'description': '扫码认证状态：qr_pending、qr_expired、qr_canceled 或 ready',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '阿里云盘侧根路径，仅用于展示',
            },
            {
                'name': 'root_folder_id',
                'type': 'string',
                'required': False,
                'default': 'root',
                'description': 'OpenList AliyundriveOpen root_folder_id',
            },
            {
                'name': 'drive_type',
                'type': 'string',
                'required': False,
                'default': 'resource',
                'description': '阿里云盘 drive_type：default、resource 或 backup',
            },
            {
                'name': 'alipan_type',
                'type': 'string',
                'required': False,
                'default': 'default',
                'description': 'OpenList AliyundriveOpen alipan_type：default 或 alipanTV',
            },
            {
                'name': 'qr_sid',
                'type': 'string',
                'required': False,
                'description': '阿里云盘二维码会话 sid，后端隐藏字段',
            },
            {
                'name': 'auth_provider',
                'type': 'string',
                'required': False,
                'description': '阿里云盘授权提供方，后端隐藏字段',
            },
        ],
    },
    'baidunetdisk': {
        'display_name': 'Baidu Netdisk',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'oauth_login': True,
        },
        'secret_fields': [],
        'hidden_fields': [
            'openlist_storage_id',
            'mount_path',
            'oauth_state',
            'oauth_callback_mode',
            'oauth_redirect_uri',
            'oauth_error',
        ],
        'config_fields': [
            {
                'name': 'openlist_storage_id',
                'type': 'integer',
                'required': False,
                'description': 'CyberStream 托管 OpenList 内部 storage id；OAuth 完成后才会生成',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': False,
                'description': 'CyberStream 托管 OpenList 内部挂载路径；OAuth 完成后才会生成',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'oauth_pending',
                'description': 'OAuth 认证状态：oauth_pending、oauth_failed 或 ready',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '百度网盘侧根路径，仅用于展示',
            },
            {
                'name': 'root_folder_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': 'OpenList BaiduNetdisk root_folder_path',
            },
            {
                'name': 'download_api',
                'type': 'string',
                'required': False,
                'default': 'crack_video',
                'description': 'OpenList 下载接口：official、crack 或 crack_video',
            },
            {
                'name': 'oauth_state',
                'type': 'string',
                'required': False,
                'description': '百度 OAuth state，后端隐藏字段',
            },
            {
                'name': 'oauth_callback_mode',
                'type': 'string',
                'required': False,
                'description': '百度 OAuth 回调模式：redirect 或 oob，后端隐藏字段',
            },
            {
                'name': 'oauth_redirect_uri',
                'type': 'string',
                'required': False,
                'description': '百度 OAuth token exchange 使用的 redirect_uri，后端隐藏字段',
            },
            {
                'name': 'oauth_error',
                'type': 'string',
                'required': False,
                'description': '百度 OAuth 失败原因，后端隐藏字段',
            },
        ],
    },
    '123pan': {
        'display_name': '123Pan',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'password_login': True,
        },
        'secret_fields': [],
        'hidden_fields': ['openlist_storage_id', 'mount_path'],
        'config_fields': [
            {
                'name': 'openlist_storage_id',
                'type': 'integer',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部 storage id',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部挂载路径',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'ready',
                'description': '账号密码认证状态：ready',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '123 云盘侧根路径，仅用于展示',
            },
            {
                'name': 'root_folder_id',
                'type': 'string',
                'required': False,
                'default': '0',
                'description': 'OpenList 123Pan root_folder_id',
            },
            {
                'name': 'account_name_masked',
                'type': 'string',
                'required': False,
                'description': '脱敏后的 123 云盘账号，仅用于展示',
            },
            {
                'name': 'platform',
                'type': 'string',
                'required': False,
                'default': 'web',
                'description': 'OpenList 123Pan platform header，默认 web',
            },
        ],
    },
    'quarktv': {
        'display_name': 'QuarkTV',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'qr_login': True,
        },
        'secret_fields': [],
        'hidden_fields': ['openlist_storage_id', 'mount_path'],
        'legacy_config_fields': ['link_method'],
        'config_fields': [
            {
                'name': 'openlist_storage_id',
                'type': 'integer',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部 storage id',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部挂载路径',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'qr_pending',
                'description': '扫码认证状态：qr_pending 或 ready',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': '夸克网盘侧根路径，仅用于展示',
            },
            {
                'name': 'root_folder_id',
                'type': 'string',
                'required': False,
                'default': '0',
                'description': 'OpenList QuarkTV root_folder_id',
            },
        ],
    },
    'uctv': {
        'display_name': 'UCTV',
        'status': 'beta',
        'capabilities': {
            'preview': True,
            'scan': True,
            'refresh': True,
            'stream': True,
            'ffmpeg_input': True,
            'health_check': True,
            'credentials_required': False,
            'redirect_stream': True,
            'managed': True,
            'qr_login': True,
        },
        'secret_fields': [],
        'hidden_fields': ['openlist_storage_id', 'mount_path'],
        'legacy_config_fields': ['link_method'],
        'config_fields': [
            {
                'name': 'openlist_storage_id',
                'type': 'integer',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部 storage id',
            },
            {
                'name': 'mount_path',
                'type': 'string',
                'required': True,
                'description': 'CyberStream 托管 OpenList 内部挂载路径',
            },
            {
                'name': 'auth_state',
                'type': 'string',
                'required': False,
                'default': 'qr_pending',
                'description': '扫码认证状态：qr_pending 或 ready',
            },
            {
                'name': 'cloud_root_path',
                'type': 'string',
                'required': False,
                'default': '/',
                'description': 'UC 网盘侧根路径，仅用于展示',
            },
            {
                'name': 'root_folder_id',
                'type': 'string',
                'required': False,
                'default': '0',
                'description': 'OpenList UCTV root_folder_id',
            },
        ],
    },
}

SOURCE_TYPE_DEFINITIONS['openlist']['config_fields'] = SOURCE_TYPE_DEFINITIONS['alist']['config_fields']

REMOTE_ROOT_SOURCE_TYPES = {'webdav', 'smb', 'ftp', 'alist', 'openlist'}
MANAGED_CLOUD_ROOT_SOURCE_TYPES = {'guangyapan', 'tianyicloud', '115cloud', 'aliyundrive', 'baidunetdisk', '123pan', 'quarktv', 'uctv'}

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
    legacy_field_names = set(definition.get('legacy_config_fields', []))

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
        if key not in allowed_field_names and key not in legacy_field_names and key not in LEGACY_CONFIG_ALIASES
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
    hidden_fields = set(definition.get('hidden_fields', []))

    for key, value in normalized_config.items():
        if key in hidden_fields:
            continue
        if key in secret_fields and value not in (None, ''):
            masked[key] = MASKED_SECRET_VALUE
        else:
            masked[key] = value

    return normalized_type, masked


def restore_masked_source_secrets(s_type, config, existing_config):
    normalized_type, definition = get_source_definition(s_type)
    if not isinstance(config, dict):
        return normalized_type, config

    restored = dict(config)
    current = existing_config if isinstance(existing_config, dict) else {}
    for field_name in definition.get('secret_fields', []):
        if restored.get(field_name) != MASKED_SECRET_VALUE:
            continue
        current_value = current.get(field_name)
        if current_value in (None, ''):
            raise StorageProviderError(
                f"Masked secret placeholder has no existing value: {field_name}",
                code=40038,
            )
        restored[field_name] = current_value

    return normalized_type, restored


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

    if normalized_type == 'guangyapan':
        root = display_config.get('cloud_root_path') or '/'
        return f"GuangYaPan:{root}"

    if normalized_type == 'tianyicloud':
        root = display_config.get('cloud_root_path') or '/'
        return f"TianYiCloud:{root}"

    if normalized_type == '115cloud':
        root = display_config.get('cloud_root_path') or '/'
        return f"115 Cloud:{root}"

    if normalized_type == 'aliyundrive':
        root = display_config.get('cloud_root_path') or '/'
        return f"Aliyundrive:{root}"

    if normalized_type == 'baidunetdisk':
        root = display_config.get('cloud_root_path') or '/'
        return f"BaiduNetdisk:{root}"

    if normalized_type == '123pan':
        root = display_config.get('cloud_root_path') or '/'
        return f"123Pan:{root}"

    if normalized_type == 'quarktv':
        root = display_config.get('cloud_root_path') or '/'
        return f"QuarkTV:{root}"

    if normalized_type == 'uctv':
        root = display_config.get('cloud_root_path') or '/'
        return f"UCTV:{root}"

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

    if normalized_type in MANAGED_CLOUD_ROOT_SOURCE_TYPES and 'cloud_root_path' in config:
        config['cloud_root_path'] = _normalize_remote_root(config.get('cloud_root_path'))

    if normalized_type == 'tianyicloud' and 'cloud_type' in config and isinstance(config.get('cloud_type'), str):
        config['cloud_type'] = config['cloud_type'].strip().lower() or 'personal'
        if config['cloud_type'] not in {'personal', 'family'}:
            raise StorageProviderError("Invalid config field value: cloud_type should be personal or family", code=40038)
    if normalized_type == 'tianyicloud' and 'root_folder_id' in config and isinstance(config.get('root_folder_id'), str):
        default_root = '' if config.get('cloud_type') == 'family' else '-11'
        config['root_folder_id'] = config['root_folder_id'].strip() or default_root
    if normalized_type == 'tianyicloud' and 'login_mode' in config and isinstance(config.get('login_mode'), str):
        config['login_mode'] = config['login_mode'].strip().lower()
        if config['login_mode'] not in {'', 'pc_qr'}:
            raise StorageProviderError("Invalid config field value: login_mode should be pc_qr", code=40038)
        if not config['login_mode']:
            config.pop('login_mode', None)

    if normalized_type == '115cloud' and 'qrcode_source' in config and isinstance(config.get('qrcode_source'), str):
        config['qrcode_source'] = config['qrcode_source'].strip().lower() or 'wechatmini'
        if config['qrcode_source'] not in {'web', 'android', 'ios', 'tv', 'alipaymini', 'wechatmini', 'qandroid'}:
            raise StorageProviderError(
                "Invalid config field value: qrcode_source should be web, android, ios, tv, alipaymini, wechatmini or qandroid",
                code=40038,
            )
    if normalized_type == '115cloud' and 'root_folder_id' in config and isinstance(config.get('root_folder_id'), str):
        config['root_folder_id'] = config['root_folder_id'].strip() or '0'

    if normalized_type == 'aliyundrive':
        if 'root_folder_id' in config and isinstance(config.get('root_folder_id'), str):
            config['root_folder_id'] = config['root_folder_id'].strip() or 'root'
        if 'drive_type' in config and isinstance(config.get('drive_type'), str):
            config['drive_type'] = config['drive_type'].strip().lower() or 'resource'
            if config['drive_type'] not in {'default', 'resource', 'backup'}:
                raise StorageProviderError(
                    "Invalid config field value: drive_type should be default, resource or backup",
                    code=40038,
                )
        if 'alipan_type' in config and isinstance(config.get('alipan_type'), str):
            alipan_type = config['alipan_type'].strip()
            if alipan_type.lower() in {'', 'default'}:
                config['alipan_type'] = 'default'
            elif alipan_type.lower() in {'alipantv', 'tv'}:
                config['alipan_type'] = 'alipanTV'
            else:
                raise StorageProviderError(
                    "Invalid config field value: alipan_type should be default or alipanTV",
                    code=40038,
                )
        if 'auth_provider' in config and isinstance(config.get('auth_provider'), str):
            config['auth_provider'] = config['auth_provider'].strip().lower() or 'openlist'
            if config['auth_provider'] not in {'official', 'openlist', 'alistgo'}:
                raise StorageProviderError(
                    "Invalid config field value: auth_provider should be official, openlist or alistgo",
                    code=40038,
                )

    if normalized_type == 'baidunetdisk':
        if 'root_folder_path' in config and isinstance(config.get('root_folder_path'), str):
            config['root_folder_path'] = _normalize_remote_root(config.get('root_folder_path'))
        if 'download_api' in config and isinstance(config.get('download_api'), str):
            config['download_api'] = config['download_api'].strip().lower() or 'crack_video'
            if config['download_api'] not in {'official', 'crack', 'crack_video'}:
                raise StorageProviderError(
                    "Invalid config field value: download_api should be official, crack or crack_video",
                    code=40038,
                )

    if normalized_type == '123pan':
        if 'root_folder_id' in config and isinstance(config.get('root_folder_id'), str):
            config['root_folder_id'] = config['root_folder_id'].strip() or '0'
        if 'platform' in config and isinstance(config.get('platform'), str):
            config['platform'] = config['platform'].strip() or 'web'

    if normalized_type in {'quarktv', 'uctv'} and 'link_method' in config and isinstance(config.get('link_method'), str):
        config['link_method'] = config['link_method'].strip().lower() or 'download'
        if config['link_method'] not in {'download', 'streaming'}:
            raise StorageProviderError("Invalid config field value: link_method should be download or streaming", code=40038)
    if normalized_type in {'quarktv', 'uctv'} and 'root_folder_id' in config and isinstance(config.get('root_folder_id'), str):
        config['root_folder_id'] = config['root_folder_id'].strip() or '0'

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
