from urllib.parse import urlsplit, urlunsplit

from flask import current_app, has_app_context, url_for


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _configured_backend_public_base_url():
    if not has_app_context():
        return None
    raw = str(current_app.config.get("BACKEND_PUBLIC_BASE_URL") or "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def _preferred_external_scheme():
    if not has_app_context():
        return None
    scheme = str(current_app.config.get("PREFERRED_URL_SCHEME") or "").strip().lower()
    return scheme if scheme in {"http", "https"} else None


def _is_local_netloc(netloc):
    hostname = netloc.rsplit("@", 1)[-1].split(":", 1)[0].strip("[]").lower()
    return hostname in LOCAL_HOSTS


def _normalize_external_url_scheme(url):
    preferred_scheme = _preferred_external_scheme()
    if preferred_scheme != "https":
        return url

    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.netloc or _is_local_netloc(parsed.netloc):
        return url

    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def api_url_for(endpoint, **values):
    public_base_url = _configured_backend_public_base_url()
    if public_base_url:
        path = url_for(endpoint, _external=False, **values)
        if not path.startswith("/"):
            path = f"/{path}"
        return _normalize_external_url_scheme(f"{public_base_url}{path}")
    return _normalize_external_url_scheme(url_for(endpoint, _external=True, **values))
