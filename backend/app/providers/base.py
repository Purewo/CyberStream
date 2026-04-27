
class StorageProviderError(ValueError):
    """Raised when a storage provider type or config is invalid."""

    def __init__(self, message, code=40030):
        super().__init__(message)
        self.message = message
        self.code = code


class StorageProvider:
    """
    存储协议的抽象基类。
    所有具体协议（Local, WebDAV, SMB等）都必须实现这些方法。
    """
    def __init__(self, config=None):
        self.config = config or {}

    def list_items(self, path):
        """
        列出目录下的文件和子目录
        path: 相对于 Root 的路径 (WebDAV) 或 绝对路径 (Local, 根据具体实现)
        返回格式: [{'path': str, 'name': str, 'isdir': bool, 'size': int}, ...]
        """
        raise NotImplementedError

    def path_exists(self, path):
        """
        检查相对路径是否可访问。默认通过 list_items 判断目录是否存在。
        """
        self.list_items(path)
        return True

    def health_check(self, path=''):
        """
        检查存储源是否可用，并返回轻量状态信息。
        """
        path = (path or '').strip().strip('/')
        try:
            exists = self.path_exists(path)
            return {
                "status": "online" if exists else "offline",
                "path": path or "/",
                "path_exists": exists,
                "error": None if exists else "Path not found or unavailable",
            }
        except Exception as e:
            return {
                "status": "offline",
                "path": path or "/",
                "path_exists": False,
                "error": str(e),
            }

    def get_stream_data(self, path, range_header=None):
        """
        获取文件流数据
        返回: (generator, status_code, content_length, content_range_header)
        """
        raise NotImplementedError

    def get_ffmpeg_input(self, path):
        """
        返回一个 FFmpeg 可以直接读取的字符串路径或 URL。
        """
        raise NotImplementedError

    def read_text(self, path, max_bytes=262144):
        """
        读取小文本文件内容。
        主要用于 sidecar 元数据文件（如 .nfo），调用方必须保证是定点读取而非全量扫描。
        """
        raise NotImplementedError

    def check_connection(self):
        """
        返回连接健康状态。
        默认实现为 unknown，具体 provider 可按需覆盖。
        """
        result = self.health_check('')
        return {
            "status": result.get("status", "unknown"),
            "reason": "ok" if result.get("status") == "online" else "request_failed",
            "message": result.get("error") or "Storage source checked",
            **result,
        }
