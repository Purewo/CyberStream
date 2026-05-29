from flask import current_app, has_app_context

from backend import config as default_config
from backend.app.providers.alist import AListProvider
from backend.app.providers.base import StorageProviderError


def _config_value(key, default=None):
    if has_app_context():
        return current_app.config.get(key, default)
    return getattr(default_config, key, default)


class GuangYaPanProvider(AListProvider):
    """CyberStream-managed GuangYaPan source backed by a localhost AList mount."""

    def __init__(self, config):
        source_config = dict(config or {})
        auth_state = str(source_config.get("auth_state") or "").strip().lower()
        if auth_state and auth_state != "ready":
            raise StorageProviderError("GuangYaPan source has not completed SMS verification", code=40061)
        if not bool(_config_value("MANAGED_ALIST_ENABLED", False)):
            raise StorageProviderError("Managed AList is disabled", code=40060)

        base_url = str(_config_value("MANAGED_ALIST_BASE_URL", "") or "").strip().rstrip("/")
        token = str(_config_value("MANAGED_ALIST_TOKEN", "") or "").strip()
        username = str(_config_value("MANAGED_ALIST_USERNAME", "") or "").strip()
        password = str(_config_value("MANAGED_ALIST_PASSWORD", "") or "").strip()
        if not base_url:
            raise StorageProviderError("Managed AList base URL is not configured", code=40060)
        if not token and not (username and password):
            raise StorageProviderError("Managed AList credentials are not configured", code=40060)

        mount_path = str(source_config.get("mount_path") or "").strip()
        if not mount_path:
            raise StorageProviderError("Missing GuangYaPan mount path", code=40034)

        runtime_config = {
            "base_url": base_url,
            "root": mount_path,
            "token": token,
            "username": username,
            "password": password,
            "timeout": int(_config_value("MANAGED_ALIST_TIMEOUT_SECONDS", 30) or 30),
            "verify_ssl": bool(_config_value("MANAGED_ALIST_VERIFY_SSL", False)),
            "proxy_stream": False,
            "resolve_redirect_stream": True,
        }
        super().__init__(runtime_config, platform="alist")

    def check_connection(self):
        result = super().check_connection()
        for internal_field in ("base_url", "root", "platform", "site_title", "version"):
            result.pop(internal_field, None)
        if result.get("status") == "online":
            result["message"] = "GuangYaPan reachable"
        return result


class ManagedOpenListProvider(AListProvider):
    """Base provider for CyberStream-managed OpenList mounts."""

    SOURCE_LABEL = "Managed OpenList"
    NOT_READY_MESSAGE = "Managed OpenList source has not completed QR login"
    MISSING_MOUNT_MESSAGE = "Missing managed OpenList mount path"
    HEALTH_MESSAGE = "Managed OpenList reachable"

    def __init__(self, config):
        source_config = dict(config or {})
        auth_state = str(source_config.get("auth_state") or "").strip().lower()
        if auth_state and auth_state != "ready":
            raise StorageProviderError(self.NOT_READY_MESSAGE, code=40061)
        if not bool(_config_value("MANAGED_OPENLIST_ENABLED", False)):
            raise StorageProviderError("Managed OpenList is disabled", code=40060)

        base_url = str(_config_value("MANAGED_OPENLIST_BASE_URL", "") or "").strip().rstrip("/")
        token = str(_config_value("MANAGED_OPENLIST_TOKEN", "") or "").strip()
        username = str(_config_value("MANAGED_OPENLIST_USERNAME", "") or "").strip()
        password = str(_config_value("MANAGED_OPENLIST_PASSWORD", "") or "").strip()
        if not base_url:
            raise StorageProviderError("Managed OpenList base URL is not configured", code=40060)
        if not token and not (username and password):
            raise StorageProviderError("Managed OpenList credentials are not configured", code=40060)

        mount_path = str(source_config.get("mount_path") or "").strip()
        if not mount_path:
            raise StorageProviderError(self.MISSING_MOUNT_MESSAGE, code=40034)

        runtime_config = {
            "base_url": base_url,
            "root": mount_path,
            "token": token,
            "username": username,
            "password": password,
            "timeout": int(_config_value("MANAGED_OPENLIST_TIMEOUT_SECONDS", 30) or 30),
            "verify_ssl": bool(_config_value("MANAGED_OPENLIST_VERIFY_SSL", False)),
            "proxy_stream": False,
            "resolve_redirect_stream": True,
        }
        super().__init__(runtime_config, platform="openlist")

    def check_connection(self):
        result = super().check_connection()
        for internal_field in ("base_url", "root", "platform", "site_title", "version"):
            result.pop(internal_field, None)
        if result.get("status") == "online":
            result["message"] = self.HEALTH_MESSAGE
        return result


class TianYiCloudProvider(ManagedOpenListProvider):
    """CyberStream-managed TianYiCloud source backed by a localhost OpenList mount."""

    NOT_READY_MESSAGE = "TianYiCloud source has not completed QR login"
    MISSING_MOUNT_MESSAGE = "Missing TianYiCloud mount path"
    HEALTH_MESSAGE = "TianYiCloud reachable"


class Cloud115Provider(ManagedOpenListProvider):
    """CyberStream-managed 115 Cloud source backed by a localhost OpenList mount."""

    NOT_READY_MESSAGE = "115 Cloud source has not completed QR login"
    MISSING_MOUNT_MESSAGE = "Missing 115 Cloud mount path"
    HEALTH_MESSAGE = "115 Cloud reachable"


class AliyundriveProvider(ManagedOpenListProvider):
    """CyberStream-managed Aliyundrive source backed by a localhost OpenList mount."""

    NOT_READY_MESSAGE = "Aliyundrive source has not completed QR login"
    MISSING_MOUNT_MESSAGE = "Missing Aliyundrive mount path"
    HEALTH_MESSAGE = "Aliyundrive reachable"


class BaiduNetdiskProvider(ManagedOpenListProvider):
    """CyberStream-managed Baidu Netdisk source backed by a localhost OpenList mount."""

    NOT_READY_MESSAGE = "Baidu Netdisk source has not completed OAuth login"
    MISSING_MOUNT_MESSAGE = "Missing Baidu Netdisk mount path"
    HEALTH_MESSAGE = "Baidu Netdisk reachable"


class Pan123Provider(ManagedOpenListProvider):
    """CyberStream-managed 123Pan source backed by a localhost OpenList mount."""

    NOT_READY_MESSAGE = "123Pan source has not completed password login"
    MISSING_MOUNT_MESSAGE = "Missing 123Pan mount path"
    HEALTH_MESSAGE = "123Pan reachable"


class QuarkTVProvider(ManagedOpenListProvider):
    """CyberStream-managed QuarkTV source backed by a localhost OpenList mount."""

    NOT_READY_MESSAGE = "QuarkTV source has not completed QR login"
    MISSING_MOUNT_MESSAGE = "Missing QuarkTV mount path"
    HEALTH_MESSAGE = "QuarkTV reachable"


class UCTVProvider(ManagedOpenListProvider):
    """CyberStream-managed UCTV source backed by a localhost OpenList mount."""

    NOT_READY_MESSAGE = "UCTV source has not completed QR login"
    MISSING_MOUNT_MESSAGE = "Missing UCTV mount path"
    HEALTH_MESSAGE = "UCTV reachable"
