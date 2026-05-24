from flask import current_app, has_app_context, url_for


def _configured_backend_public_base_url():
    if not has_app_context():
        return None
    raw = str(current_app.config.get("BACKEND_PUBLIC_BASE_URL") or "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def api_url_for(endpoint, **values):
    public_base_url = _configured_backend_public_base_url()
    if public_base_url:
        path = url_for(endpoint, _external=False, **values)
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{public_base_url}{path}"
    return url_for(endpoint, _external=True, **values)
