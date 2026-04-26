from backend.app.providers.base import StorageProviderError
from backend.app.storage.source_registry import normalize_source_config, normalize_source_type
from .alist import AListProvider
from .ftp import FTPProvider
from .local import LocalProvider
from .smb import SMBProvider
from .webdav import WebDAVProvider


class ProviderFactory:
    PROVIDER_CLASSES = {
        'local': LocalProvider,
        'webdav': WebDAVProvider,
        'smb': SMBProvider,
        'ftp': FTPProvider,
        'alist': AListProvider,
        'openlist': AListProvider,
    }

    @classmethod
    def create(cls, s_type, config):
        """
        根据类型和配置字典直接创建 Provider 实例
        用于预览等不需要数据库模型的场景
        """
        normalized_type = normalize_source_type(s_type)
        normalized_config = normalize_source_config(normalized_type, config or {})
        provider_class = cls.PROVIDER_CLASSES.get(normalized_type)
        if not provider_class:
            raise StorageProviderError(f"Unsupported storage type: {normalized_type}", code=40032)
        if normalized_type in {'alist', 'openlist'}:
            return provider_class(normalized_config, platform=normalized_type)
        return provider_class(normalized_config)

    @classmethod
    def get_provider(cls, storage_source):
        """
        根据 StorageSource 模型实例返回对应的 Provider
        """
        return cls.create(storage_source.type, storage_source.config)


# 全局工厂实例
provider_factory = ProviderFactory()
