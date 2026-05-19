from __future__ import annotations

from backend.app.services.metadata_scraper import metadata_scraper


class ScraperPolicyError(ValueError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def normalize_scraper_policy_payload(raw_policy=None, provider_order=None):
    if raw_policy in (None, "") and provider_order in (None, ""):
        return {}

    if raw_policy in (None, ""):
        raw_policy = {}
    if not isinstance(raw_policy, dict):
        raise ScraperPolicyError(40060, "Invalid field type: scraper_policy should be object")

    policy = dict(raw_policy)
    if provider_order not in (None, ""):
        policy["provider_order"] = provider_order

    normalized, warnings = metadata_scraper.normalize_scraper_policy(policy)
    unsupported = [
        warning.split(":", 1)[1]
        for warning in warnings
        if warning.startswith("unsupported_provider:")
    ]
    if unsupported:
        raise ScraperPolicyError(40061, f"Unsupported metadata providers: {', '.join(unsupported)}")
    return normalized
