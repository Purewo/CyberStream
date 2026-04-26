import ftplib
import logging
import posixpath
from urllib.parse import quote

from .base import StorageProvider

logger = logging.getLogger(__name__)


class FTPProvider(StorageProvider):
    def __init__(self, config):
        super().__init__(config)
        self.host = config.get('host', '')
        self.port = int(config.get('port', 21))
        self.username = config.get('username') or 'anonymous'
        self.password = config.get('password') or 'anonymous@'
        self.secure = bool(config.get('secure', False))
        self.passive = bool(config.get('passive', True))
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
        ftp_cls = ftplib.FTP_TLS if self.secure else ftplib.FTP
        ftp = ftp_cls()
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login(self.username, self.password)
        if self.secure:
            ftp.prot_p()
        ftp.set_pasv(self.passive)
        return ftp

    def _close(self, ftp):
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass

    def list_items(self, relative_path):
        remote_path = self._remote_path(relative_path)
        ftp = self._connect()

        try:
            try:
                items = []
                for name, facts in list(ftp.mlsd(remote_path)):
                    if not name or name in {'.', '..'} or name.startswith('.'):
                        continue
                    is_dir = facts.get('type') == 'dir'
                    items.append({
                        'path': self._child_relative_path(relative_path, name),
                        'name': name,
                        'isdir': is_dir,
                        'size': 0 if is_dir else int(facts.get('size') or 0),
                    })
                return items
            except (ftplib.error_perm, AttributeError):
                return self._list_items_fallback(ftp, relative_path, remote_path)
        finally:
            self._close(ftp)

    def _list_items_fallback(self, ftp, relative_path, remote_path):
        current_path = ftp.pwd()
        ftp.cwd(remote_path)
        names = ftp.nlst()
        items = []

        for raw_name in names:
            name = posixpath.basename(str(raw_name).rstrip('/')) or str(raw_name).strip('/')
            if not name or name in {'.', '..'} or name.startswith('.'):
                continue
            child_remote_path = posixpath.join(remote_path.rstrip('/'), name)
            is_dir = self._is_directory(ftp, child_remote_path, remote_path)
            size = 0
            if not is_dir:
                try:
                    size = int(ftp.size(child_remote_path) or 0)
                except Exception:
                    size = 0
            items.append({
                'path': self._child_relative_path(relative_path, name),
                'name': name,
                'isdir': is_dir,
                'size': size,
            })

        ftp.cwd(current_path)
        return items

    def _is_directory(self, ftp, path, restore_path):
        try:
            ftp.cwd(path)
            ftp.cwd(restore_path)
            return True
        except Exception:
            try:
                ftp.cwd(restore_path)
            except Exception:
                pass
            return False

    def path_exists(self, relative_path):
        ftp = self._connect()
        try:
            remote_path = self._remote_path(relative_path)
            ftp.cwd(remote_path)
            return True
        except Exception:
            return False
        finally:
            self._close(ftp)

    def health_check(self, relative_path=''):
        path = self._clean_relative_path(relative_path)
        try:
            exists = self.path_exists(path)
            return {
                "status": "online" if exists else "offline",
                "path": path or "/",
                "path_exists": exists,
                "host": self.host,
                "root": "/" + self.root if self.root else "/",
                "secure": self.secure,
                "error": None if exists else "Path not found or unavailable",
            }
        except Exception as e:
            return {
                "status": "offline",
                "path": path or "/",
                "path_exists": False,
                "host": self.host,
                "root": "/" + self.root if self.root else "/",
                "secure": self.secure,
                "error": str(e),
            }

    def read_text(self, relative_path, max_bytes=262144, encoding='utf-8'):
        remote_path = self._remote_path(relative_path)
        chunks = []
        ftp = self._connect()
        try:
            ftp.retrbinary(f"RETR {remote_path}", chunks.append)
            data = b''.join(chunks)
            if len(data) > max_bytes:
                logger.warning("FTP text file too large relative_path=%s max_bytes=%s", relative_path, max_bytes)
                return None
            return data.decode(encoding)
        finally:
            self._close(ftp)

    def _file_size(self, ftp, remote_path):
        try:
            ftp.voidcmd('TYPE I')
            return int(ftp.size(remote_path) or 0)
        except Exception:
            return 0

    def _parse_range(self, range_header, file_size):
        start, end = 0, file_size - 1
        if range_header:
            range_str = range_header.replace('bytes=', '', 1)
            range_parts = range_str.split('-', 1)
            if range_parts[0]:
                start = int(range_parts[0])
            if len(range_parts) > 1 and range_parts[1]:
                end = int(range_parts[1])
        if file_size and start >= file_size:
            return None, None, 416, f"bytes */{file_size}"
        if file_size and end >= file_size:
            end = file_size - 1
        return start, end, 206 if range_header else 200, f"bytes {start}-{end}/{file_size}" if file_size else None

    def get_stream_data(self, relative_path, range_header=None):
        try:
            remote_path = self._remote_path(relative_path)
            size_probe = self._connect()
            try:
                file_size = self._file_size(size_probe, remote_path)
            finally:
                self._close(size_probe)

            start, end, status_code, content_range = self._parse_range(range_header, file_size)
            if status_code == 416:
                return None, 416, 0, content_range

            content_length = (end - start + 1) if file_size else 0

            def generate():
                ftp = self._connect()
                data_sock = None
                remaining = content_length
                try:
                    ftp.voidcmd('TYPE I')
                    data_sock = ftp.transfercmd(f"RETR {remote_path}", rest=start if start else None)
                    while True:
                        read_size = 64 * 1024
                        if range_header and remaining > 0:
                            read_size = min(read_size, remaining)
                        data = data_sock.recv(read_size)
                        if not data:
                            break
                        if range_header:
                            remaining -= len(data)
                        yield data
                        if range_header and remaining <= 0:
                            break
                finally:
                    if data_sock:
                        try:
                            data_sock.close()
                        except Exception:
                            pass
                    try:
                        ftp.voidresp()
                    except Exception:
                        pass
                    self._close(ftp)

            return generate(), status_code, content_length, content_range if range_header else None
        except Exception as e:
            logger.exception("FTP stream failed relative_path=%s error=%s", relative_path, e)
            return None, 500, 0, None

    def get_ffmpeg_input(self, relative_path):
        remote_path = quote(self._remote_path(relative_path), safe='/')
        username = quote(self.username)
        password = quote(self.password)
        scheme = 'ftps' if self.secure else 'ftp'
        auth = f"{username}:{password}@" if username or password else ""
        return f"{scheme}://{auth}{self.host}:{self.port}{remote_path}"
