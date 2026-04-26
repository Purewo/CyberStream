import io
import logging
import posixpath
import socket
from urllib.parse import quote

from smb.SMBConnection import SMBConnection

from .base import StorageProvider

logger = logging.getLogger(__name__)


class SMBProvider(StorageProvider):
    def __init__(self, config):
        super().__init__(config)
        self.host = config.get('host', '')
        self.share = config.get('share', '')
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.port = int(config.get('port', 445))
        self.domain = config.get('domain') or config.get('workgroup') or ''
        self.remote_name = config.get('remote_name') or self.host
        self.client_name = config.get('client_name') or socket.gethostname() or 'cyberplayer'
        self.root = self._clean_relative_path(config.get('root', '/'))
        self.timeout = int(config.get('timeout', 30))

    def _clean_relative_path(self, value):
        raw = str(value or '').replace('\\', '/').strip().strip('/')
        if not raw:
            return ''
        normalized = posixpath.normpath('/' + raw).lstrip('/')
        return '' if normalized == '.' else normalized

    def _remote_path(self, relative_path):
        clean_path = self._clean_relative_path(relative_path)
        parts = [part for part in (self.root, clean_path) if part]
        if not parts:
            return '/'
        return '/' + posixpath.join(*parts)

    def _child_relative_path(self, relative_path, name):
        clean_path = self._clean_relative_path(relative_path)
        return posixpath.join(clean_path, name).strip('/') if clean_path else name

    def _connect(self):
        connection = SMBConnection(
            self.username,
            self.password,
            self.client_name,
            self.remote_name,
            domain=self.domain,
            use_ntlm_v2=True,
            is_direct_tcp=self.port == 445,
        )
        if not connection.connect(self.host, self.port, timeout=self.timeout):
            raise ConnectionError(f"Failed to connect SMB host: {self.host}:{self.port}")
        return connection

    def _close(self, connection):
        try:
            connection.close()
        except Exception:
            pass

    def _is_directory(self, entry):
        value = getattr(entry, 'isDirectory', False)
        return value() if callable(value) else bool(value)

    def list_items(self, relative_path):
        remote_path = self._remote_path(relative_path)
        connection = self._connect()
        items = []

        try:
            entries = connection.listPath(self.share, remote_path, timeout=self.timeout)
            for entry in entries:
                name = getattr(entry, 'filename', '')
                if not name or name in {'.', '..'} or name.startswith('.'):
                    continue

                is_dir = self._is_directory(entry)
                items.append({
                    'path': self._child_relative_path(relative_path, name),
                    'name': name,
                    'isdir': is_dir,
                    'size': 0 if is_dir else int(getattr(entry, 'file_size', 0) or 0),
                })
        finally:
            self._close(connection)

        return items

    def path_exists(self, relative_path):
        try:
            remote_path = self._remote_path(relative_path)
            connection = self._connect()
            try:
                attrs = connection.getAttributes(self.share, remote_path, timeout=self.timeout)
                is_dir = self._is_directory(attrs)
                if is_dir:
                    connection.listPath(self.share, remote_path, timeout=self.timeout)
                return is_dir
            finally:
                self._close(connection)
        except Exception:
            return False

    def health_check(self, relative_path=''):
        path = self._clean_relative_path(relative_path)
        try:
            self.list_items(path)
            return {
                "status": "online",
                "path": path or "/",
                "path_exists": True,
                "host": self.host,
                "share": self.share,
                "root": "/" + self.root if self.root else "/",
                "error": None,
            }
        except Exception as e:
            return {
                "status": "offline",
                "path": path or "/",
                "path_exists": False,
                "host": self.host,
                "share": self.share,
                "root": "/" + self.root if self.root else "/",
                "error": str(e),
            }

    def read_text(self, relative_path, max_bytes=262144, encoding='utf-8'):
        remote_path = self._remote_path(relative_path)
        connection = self._connect()
        buffer = io.BytesIO()

        try:
            connection.retrieveFile(self.share, remote_path, buffer, timeout=self.timeout)
            data = buffer.getvalue()
            if len(data) > max_bytes:
                logger.warning("SMB text file too large relative_path=%s max_bytes=%s", relative_path, max_bytes)
                return None
            return data.decode(encoding)
        finally:
            self._close(connection)

    def _file_size(self, remote_path):
        connection = self._connect()
        try:
            attrs = connection.getAttributes(self.share, remote_path, timeout=self.timeout)
            return int(getattr(attrs, 'file_size', 0) or 0)
        finally:
            self._close(connection)

    def _parse_range(self, range_header, file_size):
        start, end = 0, file_size - 1
        if range_header:
            range_str = range_header.replace('bytes=', '', 1)
            range_parts = range_str.split('-', 1)
            if range_parts[0]:
                start = int(range_parts[0])
            if len(range_parts) > 1 and range_parts[1]:
                end = int(range_parts[1])
        if start >= file_size:
            return None, None, 416, f"bytes */{file_size}"
        if end >= file_size:
            end = file_size - 1
        return start, end, 206 if range_header else 200, f"bytes {start}-{end}/{file_size}"

    def get_stream_data(self, relative_path, range_header=None):
        try:
            remote_path = self._remote_path(relative_path)
            file_size = self._file_size(remote_path)
            start, end, status_code, content_range = self._parse_range(range_header, file_size)
            if status_code == 416:
                return None, 416, 0, content_range

            chunk_length = end - start + 1

            def generate():
                connection = self._connect()
                current = start
                remaining = chunk_length
                try:
                    while remaining > 0:
                        read_size = min(64 * 1024, remaining)
                        buffer = io.BytesIO()
                        connection.retrieveFileFromOffset(
                            self.share,
                            remote_path,
                            buffer,
                            offset=current,
                            max_length=read_size,
                            timeout=self.timeout,
                        )
                        data = buffer.getvalue()
                        if not data:
                            break
                        current += len(data)
                        remaining -= len(data)
                        yield data
                finally:
                    self._close(connection)

            return generate(), status_code, chunk_length, content_range if range_header else None
        except Exception as e:
            logger.exception("SMB stream failed relative_path=%s error=%s", relative_path, e)
            return None, 500, 0, None

    def get_ffmpeg_input(self, relative_path):
        remote_path = self._remote_path(relative_path).lstrip('/')
        quoted_path = quote(posixpath.join(self.share, remote_path), safe='/')
        username = quote(self.username)
        password = quote(self.password)
        auth = f"{username}:{password}@" if username or password else ""
        return f"smb://{auth}{self.host}:{self.port}/{quoted_path}"
