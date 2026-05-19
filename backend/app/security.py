import hmac
import re

from flask import current_app, g, request, session

from backend.app.extensions import db
from backend.app.utils.response import api_error

ADMIN_ROLE = "admin"


PUBLIC_GET_PATH_PATTERNS = (
    re.compile(r"^/api/v1/resources/[^/]+/stream$"),
    re.compile(r"^/api/v1/resources/[^/]+/audio-transcode$"),
    re.compile(r"^/api/v1/movies/[^/]+/images/(?:poster|backdrop)$"),
)

PUBLIC_DOCUMENTATION_GET_PATH_PATTERNS = (
    re.compile(r"^/api/v1/openapi\.json$"),
    re.compile(r"^/api/v1/docs(?:/[^/]+)?$"),
)

AUTH_PUBLIC_PATHS = {
    "/",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
}

UUID_PATTERN = r"[0-9a-fA-F-]{36}"

NORMAL_USER_GET_PATTERNS = (
    re.compile(r"^/api/v1/homepage$"),
    re.compile(r"^/api/v1/featured$"),
    re.compile(r"^/api/v1/recommendations$"),
    re.compile(r"^/api/v1/filters$"),
    re.compile(r"^/api/v1/movies$"),
    re.compile(rf"^/api/v1/movies/{UUID_PATTERN}$"),
    re.compile(rf"^/api/v1/movies/{UUID_PATTERN}/recommendations$"),
    re.compile(rf"^/api/v1/movies/{UUID_PATTERN}/resources$"),
    re.compile(rf"^/api/v1/movies/{UUID_PATTERN}/seasons$"),
    re.compile(rf"^/api/v1/movies/{UUID_PATTERN}/images/(?:poster|backdrop)$"),
    re.compile(r"^/api/v1/libraries$"),
    re.compile(r"^/api/v1/libraries/\d+$"),
    re.compile(r"^/api/v1/libraries/\d+/(?:movies|featured|recommendations|filters)$"),
    re.compile(r"^/api/v1/user/profile$"),
    re.compile(r"^/api/v1/user/history$"),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/(?:stream|external-playback|audio-transcode|subtitle-settings)$"),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/subtitles/online/search$"),
)

NORMAL_USER_WRITE_PATTERNS = (
    re.compile(r"^/api/v1/user/profile$"),
    re.compile(r"^/api/v1/user/password$"),
    re.compile(r"^/api/v1/user/history$"),
    re.compile(rf"^/api/v1/user/history/{UUID_PATTERN}$"),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/subtitle-settings$"),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/audio-transcode$"),
)

MOVIE_PATH_PATTERNS = (
    re.compile(rf"^/api/v1/movies/(?P<id>{UUID_PATTERN})(?:$|/(?:recommendations|resources|seasons|images/(?:poster|backdrop)))"),
)

RESOURCE_PATH_PATTERNS = (
    re.compile(rf"^/api/v1/resources/(?P<id>{UUID_PATTERN})/(?:stream|external-playback|audio-transcode|subtitle-settings|subtitles/online/search)$"),
)

LIBRARY_PATH_PATTERNS = (
    re.compile(r"^/api/v1/libraries/(?P<id>\d+)(?:$|/(?:movies|featured|recommendations|filters))"),
)


def _configured_token():
    token = str(current_app.config.get("API_TOKEN") or "").strip()
    return token or None


def is_user_management_enabled():
    return bool(current_app.config.get("USER_MANAGEMENT_ENABLED"))


def is_api_auth_enabled():
    return bool(current_app.config.get("AUTH_ENABLED") and _configured_token())


def _request_token():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return str(request.headers.get("X-Cyber-API-Token") or "").strip()


def _is_public_request():
    if request.method == "OPTIONS":
        return True
    if request.path in AUTH_PUBLIC_PATHS:
        return True
    if request.method == "GET" and any(pattern.match(request.path) for pattern in PUBLIC_DOCUMENTATION_GET_PATH_PATTERNS):
        return True
    if request.method == "GET" and current_app.config.get("AUTH_EXEMPT_MEDIA_GET", True):
        return any(pattern.match(request.path) for pattern in PUBLIC_GET_PATH_PATTERNS)
    return False


def _is_user_management_public_request():
    if request.method == "OPTIONS" or request.path in AUTH_PUBLIC_PATHS:
        return True
    if request.method == "GET":
        return any(pattern.match(request.path) for pattern in PUBLIC_DOCUMENTATION_GET_PATH_PATTERNS)
    return False


def _reset_request_auth():
    g.current_user = None
    g.auth_role = None
    g.auth_via = None


def get_current_user():
    return getattr(g, "current_user", None)


def get_current_auth_role():
    return getattr(g, "auth_role", None)


def is_admin_request():
    return get_current_auth_role() == ADMIN_ROLE


def _authenticate_api_token():
    expected = _configured_token()
    supplied = _request_token()
    if expected and supplied and hmac.compare_digest(supplied, expected):
        g.current_user = None
        g.auth_role = ADMIN_ROLE
        g.auth_via = "api_token"
        return True
    return False


def _load_session_user():
    user_id = session.get("user_id")
    if not user_id:
        return False
    from backend.app.models import User

    user = db.session.get(User, user_id)
    if not user or not user.is_enabled:
        session.clear()
        return False
    expected_version = session.get("session_version")
    try:
        expected_version = int(expected_version)
        current_version = int(user.session_version or 1)
    except (TypeError, ValueError):
        session.clear()
        return False
    if expected_version != current_version:
        session.clear()
        return False
    g.current_user = user
    g.auth_role = user.role
    g.auth_via = "session"
    return True


def _normal_user_can_access_route():
    if request.method == "GET":
        return any(pattern.match(request.path) for pattern in NORMAL_USER_GET_PATTERNS)
    if request.path == "/api/v1/auth/logout" and request.method == "POST":
        return True
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        return any(pattern.match(request.path) for pattern in NORMAL_USER_WRITE_PATTERNS)
    return False


def _enforce_visibility_for_normal_user():
    if is_admin_request() or not is_user_management_enabled():
        return None

    from backend.app.services.user_access import (
        can_current_user_access_library_id,
        can_current_user_access_movie_id,
        can_current_user_access_resource_id,
    )

    for pattern in MOVIE_PATH_PATTERNS:
        match = pattern.match(request.path)
        if match and not can_current_user_access_movie_id(match.group("id")):
            return api_error(code=40320, msg="Movie is not visible for current user", http_status=403)

    for pattern in RESOURCE_PATH_PATTERNS:
        match = pattern.match(request.path)
        if match and not can_current_user_access_resource_id(match.group("id")):
            return api_error(code=40321, msg="Resource is not visible for current user", http_status=403)

    for pattern in LIBRARY_PATH_PATTERNS:
        match = pattern.match(request.path)
        if match and not can_current_user_access_library_id(int(match.group("id"))):
            return api_error(code=40322, msg="Library is not visible for current user", http_status=403)

    return None


def _require_user_session():
    if _is_user_management_public_request():
        _authenticate_api_token() or _load_session_user()
        return None
    if _authenticate_api_token():
        return None
    if _load_session_user():
        if not is_admin_request() and not _normal_user_can_access_route():
            return api_error(code=40310, msg="Admin permission required", http_status=403)
        return _enforce_visibility_for_normal_user()
    return api_error(code=40100, msg="Authentication required", http_status=401)


def require_api_token():
    _reset_request_auth()

    if is_user_management_enabled():
        return _require_user_session()

    if not is_api_auth_enabled() or _is_public_request():
        return None

    expected = _configured_token()
    supplied = _request_token()
    if not supplied:
        return api_error(code=40100, msg="Authentication required", http_status=401)
    if not hmac.compare_digest(supplied, expected):
        return api_error(code=40300, msg="Invalid API token", http_status=403)
    return None
