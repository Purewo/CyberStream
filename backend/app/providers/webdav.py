import os
import posixpath
import base64
import logging
import socket
from urllib.parse import quote, unquote
import requests
from webdav3.client import Client
from webdav3.exceptions import ConnectionException, MethodNotSupported, NoConnection, ResponseErrorCode
from .base import StorageProvider

logger = logging.getLogger(__name__)


class WebDAVProvider(StorageProvider):
    def __init__(self, config):
        super().__init__(config)
        self.host = config.get('host', 'localhost')
        self.port = int(config.get('port', 443))
        self.secure = config.get('secure', True)
        self.username = config.get('username', '')
        self.password = config.get('password', '')

        # 严格处理挂载根路径，确保以 / 开头，不以 / 结尾
        raw_root = config.get('root', '/').strip()
        if not raw_root.startswith('/'):
            raw_root = '/' + raw_root
        self.mount_root = unquote(raw_root).rstrip('/')

        protocol = 'https' if self.secure else 'http'
        self.base_url = f"{protocol}://{self.host}:{self.port}"

        self.client = self._init_client()

    def _init_client(self):
        """
        初始化 WebDAV 客户端 - 标准模式
        """
        options = {
            'webdav_hostname': self.base_url,
            'webdav_root': self.mount_root,
            'login': self.username,
            'password': self.password,
            'disable_check_exists': True,
            'timeout': 30,
            'verify': False  # 禁用 SSL 校验
        }

        client = Client(options)
        client.verify = False
        client.session.verify = False  # 确保底层 Session 也禁用 SSL 校验
        client.session.trust_env = False

        # 仅保留 UA 标识
        client.session.headers.update({
            'User-Agent': 'CyberPlayer/1.0 WebDAVClient'
        })

        return client

    def _build_health_result(self, status, reason, message):
        return {
            "status": status,
            "reason": reason,
            "message": message,
        }

    def _resolve_host_ips(self):
        try:
            infos = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise e

        addresses = []
        for info in infos:
            address = info[4][0]
            if address not in addresses:
                addresses.append(address)
        return addresses

    def _format_socket_error(self, error):
        if isinstance(error, socket.timeout):
            return self._build_health_result("offline", "timeout", f"Connection timed out when connecting to {self.base_url}")

        if isinstance(error, ConnectionRefusedError):
            return self._build_health_result("offline", "connection_refused", f"Connection refused by {self.base_url}")

        if isinstance(error, OSError):
            errno = getattr(error, 'errno', None)
            if errno in (101, 113):
                return self._build_health_result("offline", "network_unreachable", f"Network unreachable when connecting to {self.base_url}")

        return self._build_health_result("offline", "network_error", str(error))

    def _map_health_exception(self, error):
        if isinstance(error, socket.gaierror):
            return self._build_health_result(
                "offline",
                "dns_resolution_failed",
                f"Failed to resolve host {self.host}: {error}",
            )

        if isinstance(error, NoConnection):
            original_error = error.__cause__ or error.__context__
            if original_error:
                if isinstance(original_error, socket.gaierror):
                    return self._map_health_exception(original_error)
                if isinstance(original_error, requests.ConnectionError):
                    nested_error = original_error.__cause__ or original_error.__context__
                    if nested_error:
                        if isinstance(nested_error, socket.gaierror):
                            return self._map_health_exception(nested_error)
                        if isinstance(nested_error, OSError):
                            return self._format_socket_error(nested_error)
                if isinstance(original_error, OSError):
                    return self._format_socket_error(original_error)
            return self._build_health_result("offline", "connection_failed", str(error))

        if isinstance(error, requests.Timeout):
            return self._build_health_result("offline", "timeout", f"Connection timed out when connecting to {self.base_url}")

        if isinstance(error, requests.ConnectionError):
            original_error = error.__cause__ or error.__context__
            if original_error:
                if isinstance(original_error, socket.gaierror):
                    return self._map_health_exception(original_error)
                if isinstance(original_error, OSError):
                    return self._format_socket_error(original_error)
            return self._build_health_result("offline", "connection_failed", str(error))

        if isinstance(error, MethodNotSupported):
            return self._build_health_result("unknown", "method_not_supported", str(error))

        if isinstance(error, ResponseErrorCode):
            status_code = getattr(error, 'code', None)
            if status_code == 401:
                return self._build_health_result("offline", "auth_failed", "WebDAV authentication failed")
            if status_code == 403:
                return self._build_health_result("offline", "permission_denied", "WebDAV access denied")
            if status_code == 404:
                return self._build_health_result("offline", "root_not_found", "Configured WebDAV root does not exist")
            return self._build_health_result("offline", "http_error", f"WebDAV request failed with HTTP {status_code}")

        if isinstance(error, ConnectionException):
            original_error = error.__cause__ or error.__context__
            if original_error:
                if isinstance(original_error, requests.Timeout):
                    return self._map_health_exception(original_error)
                if isinstance(original_error, requests.ConnectionError):
                    return self._map_health_exception(original_error)
            return self._build_health_result("offline", "request_failed", str(error))

        if isinstance(error, OSError):
            return self._format_socket_error(error)

        return self._build_health_result("offline", "unknown_error", str(error))

    def list_items(self, relative_path):
        # Scanner 传来的 relative_path 是相对于 mount_root 的
        # 例如: "" (根目录), "Movies" (子目录)
        clean_path = relative_path.strip().strip('/')

        # 传递给 client 的路径。如果为空，则列出根目录 '/'
        # client 会自动将其与 mount_root 拼接
        client_path = clean_path if clean_path else '/'

        items = []
        try:
            # 标准调用
            files = self.client.list(client_path, get_info=True)

            # 计算当前目录在服务端的绝对路径，用于过滤自身
            # webdavclient3 返回的 path 通常是完整的服务端路径
            current_abs_path = posixpath.join(self.mount_root, clean_path).rstrip('/')

            for file_info in files:
                if not isinstance(file_info, dict): continue

                name = file_info.get('name')
                if not name: continue

                if name.startswith('.'): continue

                # 获取原始路径并标准化
                raw_item_path = file_info.get('path', '')
                item_full_path = unquote(raw_item_path).rstrip('/')

                # 排除目录自身 (WebDAV PROPFIND 标准行为会包含自身)
                if item_full_path == current_abs_path:
                    continue

                # 构造返回给上层的相对路径
                if not clean_path:
                    child_rel_path = name
                else:
                    child_rel_path = posixpath.join(clean_path, name)

                is_dir = file_info.get('isdir', False) or file_info.get('type') == 'directory'
                size = int(file_info.get('size', 0)) if file_info.get('size') else 0

                items.append({
                    'path': child_rel_path,
                    'name': name,
                    'isdir': is_dir,
                    'size': size
                })

        except Exception as e:
            logger.exception("WebDAV list_items failed client_path=%s error=%s", client_path, e)
            raise e

        return items

    def path_exists(self, relative_path):
        try:
            self.list_items(relative_path)
            return True
        except Exception:
            return False

    def health_check(self, relative_path=''):
        path = (relative_path or '').strip().strip('/')
        try:
            self.list_items(path)
            return {
                "status": "online",
                "path": path or "/",
                "path_exists": True,
                "base_url": self.base_url,
                "mount_root": self.mount_root or "/",
                "error": None,
            }
        except Exception as e:
            return {
                "status": "offline",
                "path": path or "/",
                "path_exists": False,
                "base_url": self.base_url,
                "mount_root": self.mount_root or "/",
                "error": str(e),
            }

    def get_stream_data(self, relative_path, range_header=None):
        try:
            path = relative_path.strip().strip('/')

            # 1. 路径拼接
            full_rel_path = posixpath.join(self.mount_root, path)
            if not full_rel_path.startswith('/'):
                full_rel_path = '/' + full_rel_path

            # 2. 编码处理 (explicitly safe='/', 避免将 / 编码为 %2F 导致某些服务器 404)
            encoded_path = quote(full_rel_path, safe='/')
            url = f"{self.base_url}{encoded_path}"

            logger.info("WebDAV stream request url=%s", url)

            # 3. Header 处理
            headers = self.client.session.headers.copy()

            # 核心修复: 强制使用 Preemptive Basic Auth
            # requests 默认是在收到 401 后才发送 Auth 头，但在 stream=True 和 allow_redirects=False 的组合下，
            # 某些服务器（如 Alist）可能无法正确完成协商，导致直接返回 401。
            # 我们手动构造 Auth 头，确保请求一开始就携带凭证。
            if self.username and self.password:
                auth_str = f"{self.username}:{self.password}"
                b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
                headers['Authorization'] = f"Basic {b64_auth}"

            if range_header:
                headers['Range'] = range_header
                logger.info("WebDAV stream range=%s", range_header)

            # 4. 发起请求
            r = self.client.session.get(
                url,
                stream=True,
                timeout=20,
                allow_redirects=False,
                headers=headers,
                auth=None  # 禁用 Session 自动 Auth，防止冲突，完全依赖我们的 Header
            )

            logger.info("WebDAV stream response status=%s", r.status_code)

            # 5. 处理重定向 (302 Found)
            if r.status_code in [301, 302, 303, 307, 308]:
                location = r.headers.get('Location')
                if location:
                    logger.info("WebDAV redirect passthrough location=%s", location[:60])
                    return None, 302, 0, location

            # 6. 处理错误
            if r.status_code >= 400:
                logger.warning("WebDAV stream error status=%s body=%s", r.status_code, r.text[:200])
                return None, r.status_code, 0, None

            # 7. 处理直连流 (Proxy Mode)
            cl = r.headers.get('content-length')
            cr = r.headers.get('content-range')

            return r.iter_content(chunk_size=64 * 1024), r.status_code, cl, cr

        except Exception as e:
            logger.exception("WebDAV stream exception relative_path=%s error=%s", relative_path, e)
            return None, 500, 0, None

    def get_ffmpeg_input(self, relative_path):
        path = relative_path.strip().strip('/')
        full_rel_path = posixpath.join(self.mount_root, path)
        if not full_rel_path.startswith('/'):
            full_rel_path = '/' + full_rel_path

        # FFmpeg 可能需要 URL 编码的路径
        encoded_path = quote(full_rel_path, safe='/').lstrip('/')

        u = quote(self.username)
        p = quote(self.password)

        protocol = 'https' if self.secure else 'http'
        return f"{protocol}://{u}:{p}@{self.host}:{self.port}/{encoded_path}"

    def read_text(self, relative_path, max_bytes=262144):
        path = relative_path.strip().strip('/')
        full_rel_path = posixpath.join(self.mount_root, path)
        if not full_rel_path.startswith('/'):
            full_rel_path = '/' + full_rel_path

        encoded_path = quote(full_rel_path, safe='/')
        url = f"{self.base_url}{encoded_path}"
        headers = self.client.session.headers.copy()

        if self.username and self.password:
            auth_str = f"{self.username}:{self.password}"
            b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
            headers['Authorization'] = f"Basic {b64_auth}"

        try:
            response = self.client.session.get(
                url,
                stream=True,
                timeout=20,
                allow_redirects=False,
                headers=headers,
                auth=None,
            )
            if response.status_code >= 400:
                logger.warning("WebDAV read_text failed relative_path=%s status=%s", relative_path, response.status_code)
                return None

            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    logger.warning("WebDAV text file too large relative_path=%s max_bytes=%s", relative_path, max_bytes)
                    return None
                chunks.append(chunk)

            data = b''.join(chunks)
            for encoding in ('utf-8-sig', 'utf-8', 'gb18030'):
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return data.decode('utf-8', errors='replace')
        except Exception as e:
            logger.exception("WebDAV read_text failed relative_path=%s error=%s", relative_path, e)
            return None

    def check_connection(self):
        try:
            resolved_ips = self._resolve_host_ips()
            health = self.health_check('')
            if health.get("status") != "online":
                return {
                    **self._build_health_result("offline", "root_not_found", health.get("error") or "WebDAV root is unavailable"),
                    **health,
                }
            ip_hint = f" (resolved: {', '.join(resolved_ips[:2])})" if resolved_ips else ""
            return {
                **self._build_health_result("online", "ok", f"WebDAV root is accessible{ip_hint}"),
                **health,
            }
        except Exception as e:
            logger.warning("WebDAV health check failed host=%s port=%s error=%s", self.host, self.port, e)
            return self._map_health_exception(e)
