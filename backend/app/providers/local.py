import os
import logging
from .base import StorageProvider

logger = logging.getLogger(__name__)


class LocalProvider(StorageProvider):
    def __init__(self, config):
        super().__init__(config)
        # 当前标准字段为 root_path；兼容旧字段 path
        self.root_path = config.get('root_path') or config.get('path', '')

    def _resolve_path(self, relative_path):
        # 拼接根目录和相对路径
        if not relative_path: return self.root_path
        clean_rel = relative_path.strip().strip('"').strip("'").lstrip('/')
        return os.path.normpath(os.path.join(self.root_path, clean_rel))

    def list_items(self, relative_path):
        items = []
        full_path = self._resolve_path(relative_path)

        if not os.path.exists(full_path):
            logger.warning("Local path not found: %s", full_path)
            return []

        try:
            with os.scandir(full_path) as entries:
                for entry in entries:
                    # 核心变更：过滤隐藏文件
                    if entry.name.startswith('.'):
                        continue

                    is_dir = entry.is_dir()
                    try:
                        size = entry.stat().st_size if not is_dir else 0
                    except:
                        size = 0

                    # 返回相对路径
                    child_rel_path = os.path.join(relative_path, entry.name).replace('\\', '/')

                    items.append({
                        'path': child_rel_path,
                        'name': entry.name,
                        'isdir': is_dir,
                        'size': size
                    })
        except PermissionError:
            logger.warning("Local path permission denied: %s", full_path)
        except Exception as e:
            logger.exception("Local list_items failed path=%s error=%s", full_path, e)

        return items

    def get_stream_data(self, relative_path, range_header=None):
        try:
            file_path = self._resolve_path(relative_path)

            if not os.path.exists(file_path):
                return None, 404, 0, None

            file_size = os.path.getsize(file_path)

            start, end = 0, file_size - 1
            if range_header:
                range_str = range_header.replace('bytes=', '')
                range_parts = range_str.split('-')
                if range_parts[0]: start = int(range_parts[0])
                if len(range_parts) > 1 and range_parts[1]: end = int(range_parts[1])

            if start >= file_size:
                return None, 416, 0, f"bytes */{file_size}"
            if end >= file_size:
                end = file_size - 1

            chunk_length = end - start + 1

            def generate():
                with open(file_path, 'rb') as f:
                    f.seek(start)
                    remaining = chunk_length
                    while remaining > 0:
                        chunk_size = min(64 * 1024, remaining)
                        data = f.read(chunk_size)
                        if not data: break
                        remaining -= len(data)
                        yield data

            content_range = f"bytes {start}-{end}/{file_size}"
            status_code = 206 if range_header else 200

            return generate(), status_code, chunk_length, content_range

        except Exception as e:
            logger.exception("Local stream failed relative_path=%s error=%s", relative_path, e)
            return None, 500, 0, None

    def get_ffmpeg_input(self, relative_path):
        return self._resolve_path(relative_path)

    def path_exists(self, relative_path):
        full_path = self._resolve_path(relative_path)
        return os.path.isdir(full_path)

    def health_check(self, relative_path=''):
        full_path = self._resolve_path(relative_path)
        exists = os.path.isdir(full_path)
        readable = os.access(full_path, os.R_OK) if exists else False

        status = "online" if exists and readable else "offline"
        error = None
        if not exists:
            error = "Path not found"
        elif not readable:
            error = "Path is not readable"

        return {
            "status": status,
            "path": (relative_path or '').strip().strip('/') or "/",
            "path_exists": exists,
            "readable": readable,
            "error": error,
        }

    def read_text(self, relative_path, max_bytes=262144, encoding=None):
        file_path = self._resolve_path(relative_path)
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            return None

        try:
            with open(file_path, 'rb') as f:
                data = f.read(max_bytes + 1)
            if len(data) > max_bytes:
                logger.warning("Local text file too large relative_path=%s max_bytes=%s", relative_path, max_bytes)
                return None
            if encoding:
                return data.decode(encoding)
            for encoding in ('utf-8-sig', 'utf-8', 'gb18030'):
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return data.decode('utf-8', errors='replace')
        except Exception as e:
            logger.exception("Local read_text failed relative_path=%s error=%s", relative_path, e)
            return None

    def check_connection(self):
        result = self.health_check('')
        if not self.root_path:
            return {
                "status": "offline",
                "reason": "invalid_config",
                "message": "Missing root_path",
            }

        if result["status"] != "online":
            reason = "path_not_found" if not result.get("path_exists") else "permission_denied"
            return {
                "status": "offline",
                "reason": reason,
                "message": result.get("error") or "Root path is unavailable",
                **result,
            }

        return {
            "status": "online",
            "reason": "ok",
            "message": "Root path is accessible",
            **result,
        }
