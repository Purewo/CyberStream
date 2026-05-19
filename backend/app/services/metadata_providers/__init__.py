from backend.app.services.metadata_providers.bangumi import BangumiMetadataProvider
from backend.app.services.metadata_providers.local import LocalFallbackProvider
from backend.app.services.metadata_providers.nfo import NfoMetadataProvider
from backend.app.services.metadata_providers.tencent_video import TencentVideoMetadataProvider
from backend.app.services.metadata_providers.tmdb import TmdbMetadataProvider


def build_default_metadata_providers():
    providers = [
        NfoMetadataProvider(),
        TmdbMetadataProvider(),
        BangumiMetadataProvider(),
        TencentVideoMetadataProvider(),
        LocalFallbackProvider(),
    ]
    return {
        provider.name: provider
        for provider in providers
    }
