from backend.app.services.metadata_providers.local import LocalFallbackProvider
from backend.app.services.metadata_providers.nfo import NfoMetadataProvider
from backend.app.services.metadata_providers.tmdb import TmdbMetadataProvider


def build_default_metadata_providers():
    providers = [
        NfoMetadataProvider(),
        TmdbMetadataProvider(),
        LocalFallbackProvider(),
    ]
    return {
        provider.name: provider
        for provider in providers
    }
