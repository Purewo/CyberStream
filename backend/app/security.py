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
    re.compile(r"^/api/v1/openapi/modules(?:/[^/]+\.json)?$"),
    re.compile(r"^/api/v1/docs(?:/[^/]+)?$"),
)

PUBLIC_SYSTEM_GET_PATH_PATTERNS = (
    re.compile(r"^/api/v1/system/update-check$"),
)

PUBLIC_OAUTH_GET_PATH_PATTERNS = (
    re.compile(r"^/api/v1/storage/managed/baidunetdisk/oauth/callback$"),
)

AUTH_PUBLIC_PATHS = {
    "/",
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
    "/api/v1/auth/register",
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
    re.compile(r"^/api/v1/libraries/favorites(?:$|/(?:movies|featured|recommendations|filters))"),
    re.compile(r"^/api/v1/libraries/\d+$"),
    re.compile(r"^/api/v1/libraries/\d+/(?:movies|featured|recommendations|filters)$"),
    re.compile(r"^/api/v1/user/profile$"),
    re.compile(r"^/api/v1/user/history$"),
    re.compile(r"^/api/v1/user/achievements$"),
    re.compile(r"^/api/v1/user/favorites$"),
    re.compile(rf"^/api/v1/user/favorites/{UUID_PATTERN}$"),
    re.compile(r"^/api/v1/user/vault/status$"),
    re.compile(
        rf"^/api/v1/resources/{UUID_PATTERN}/"
        r"(?:stream|streaming-qualities|stream-transcoded|external-playback|audio-transcode|"
        r"audio-transcode/diagnostics|subtitle-settings)$"
    ),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/subtitles/online/search$"),
)

NORMAL_USER_WRITE_PATTERNS = (
    re.compile(r"^/api/v1/user/profile$"),
    re.compile(r"^/api/v1/user/password$"),
    re.compile(r"^/api/v1/user/history$"),
    re.compile(rf"^/api/v1/user/history/{UUID_PATTERN}$"),
    re.compile(r"^/api/v1/user/achievements/unlock$"),
    re.compile(rf"^/api/v1/user/favorites/{UUID_PATTERN}$"),
    re.compile(r"^/api/v1/user/vault/(?:password|unlock|lock)$"),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/subtitle-settings$"),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/audio-transcode$"),
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/subtitles/online/download$"),
)

HOSTED_MANAGED_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

HOSTED_MANAGED_LOCKED_WRITE_PATTERNS = (
    re.compile(r"^/api/v1/system/tmdb-config$"),
    re.compile(r"^/api/v1/images/(?:preload|refresh)$"),
    re.compile(rf"^/api/v1/movies/{UUID_PATTERN}/images/[^/]+$"),
)

HOSTED_MANAGED_LOCKED_REFRESH_GET_PATTERNS = (
    re.compile(rf"^/api/v1/movies/{UUID_PATTERN}/images/[^/]+$"),
)

MOVIE_PATH_PATTERNS = (
    re.compile(rf"^/api/v1/movies/(?P<id>{UUID_PATTERN})(?:$|/(?:recommendations|resources|seasons|images/(?:poster|backdrop)))"),
    re.compile(rf"^/api/v1/user/favorites/(?P<id>{UUID_PATTERN})$"),
)

RESOURCE_PATH_PATTERNS = (
    re.compile(
        rf"^/api/v1/resources/(?P<id>{UUID_PATTERN})/"
        r"(?:stream|streaming-qualities|stream-transcoded|external-playback|audio-transcode|"
        r"audio-transcode/diagnostics|subtitle-settings|subtitles/online/(?:search|download))$"
    ),
)

PLAYBACK_TICKET_GET_PATTERNS = (
    re.compile(
        rf"^/api/v1/resources/{UUID_PATTERN}/"
        r"(?:stream|streaming-qualities|stream-transcoded|audio-transcode|subtitles/online/search)$"
    ),
)

PLAYBACK_TICKET_POST_PATTERNS = (
    re.compile(rf"^/api/v1/resources/{UUID_PATTERN}/subtitles/online/download$"),
)

LIBRARY_PATH_PATTERNS = (
    re.compile(r"^/api/v1/libraries/(?P<id>\d+)(?:$|/(?:movies|featured|recommendations|filters))"),
)

ACCOUNT_OWNER_GET_PATTERNS = (
    re.compile(r"^/api/v1/storage(?:$|/)"),
    re.compile(r"^/api/v1/libraries(?:$|/)"),
    re.compile(r"^/api/v1/movies(?:$|/)"),
    re.compile(r"^/api/v1/resources(?:$|/)"),
    re.compile(r"^/api/v1/homepage$"),
    re.compile(r"^/api/v1/featured$"),
    re.compile(r"^/api/v1/recommendations$"),
    re.compile(r"^/api/v1/filters$"),
    re.compile(r"^/api/v1/user(?:$|/)"),
)

ACCOUNT_OWNER_WRITE_PATTERNS = (
    re.compile(r"^/api/v1/storage(?:$|/)"),
    re.compile(r"^/api/v1/scan$"),
    re.compile(r"^/api/v1/libraries(?:$|/)"),
    re.compile(r"^/api/v1/movies(?:$|/)"),
    re.compile(r"^/api/v1/resources(?:$|/)"),
    re.compile(r"^/api/v1/homepage$"),
    re.compile(r"^/api/v1/user(?:$|/)"),
)


def _configured_token():
    token = str(current_app.config.get("API_TOKEN") or "").strip()
    return token or None


def is_user_management_enabled():
    return bool(current_app.config.get("USER_MANAGEMENT_ENABLED"))


def is_hosted_managed_mode():
    return bool(current_app.config.get("HOSTED_MANAGED_MODE"))


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
    if request.method == "GET" and any(pattern.match(request.path) for pattern in PUBLIC_SYSTEM_GET_PATH_PATTERNS):
        return True
    if request.method == "GET" and any(pattern.match(request.path) for pattern in PUBLIC_OAUTH_GET_PATH_PATTERNS):
        return True
    if request.method == "GET" and current_app.config.get("AUTH_EXEMPT_MEDIA_GET", True):
        return any(pattern.match(request.path) for pattern in PUBLIC_GET_PATH_PATTERNS)
    return False


def _is_user_management_public_request():
    if request.method == "OPTIONS" or request.path in AUTH_PUBLIC_PATHS:
        return True
    if request.method == "GET":
        return (
            any(pattern.match(request.path) for pattern in PUBLIC_DOCUMENTATION_GET_PATH_PATTERNS)
            or any(pattern.match(request.path) for pattern in PUBLIC_SYSTEM_GET_PATH_PATTERNS)
            or any(pattern.match(request.path) for pattern in PUBLIC_OAUTH_GET_PATH_PATTERNS)
        )
    return False


def _reset_request_auth():
    g.current_user = None
    g.auth_role = None
    g.auth_via = None
    g.current_account = None
    g.current_account_id = None
    g.current_account_membership = None
    g.current_account_role = None


def get_current_user():
    return getattr(g, "current_user", None)


def get_current_auth_role():
    return getattr(g, "auth_role", None)


def is_admin_request():
    return get_current_auth_role() == ADMIN_ROLE


def get_current_account():
    return getattr(g, "current_account", None)


def get_current_account_id():
    return getattr(g, "current_account_id", None)


def get_current_account_role():
    return getattr(g, "current_account_role", None)


def is_account_owner_request():
    from backend.app.models import AccountMembership

    return get_current_account_role() == AccountMembership.ROLE_OWNER


def _authenticate_api_token():
    if not is_api_auth_enabled():
        return False
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
    if current_app.config.get("MULTI_TENANT_ENABLED"):
        from backend.app.services.accounts import resolve_or_provision_membership, set_request_account

        membership = resolve_or_provision_membership(user)
        set_request_account(membership)
    return True


def _authenticate_playback_ticket():
    if "ticket" not in request.args:
        return False, None
    if request.method == "GET":
        allowed = any(pattern.match(request.path) for pattern in PLAYBACK_TICKET_GET_PATTERNS)
    elif request.method == "POST":
        allowed = any(pattern.match(request.path) for pattern in PLAYBACK_TICKET_POST_PATTERNS)
    else:
        allowed = False
    if not allowed:
        return False, None

    from backend.app.services.playback_tickets import (
        PlaybackTicketError,
        PlaybackTicketExpired,
        validate_playback_ticket,
    )

    try:
        ticket_auth = validate_playback_ticket(request.args.get("ticket"))
    except PlaybackTicketExpired:
        return False, api_error(code=40130, msg="Playback ticket expired", http_status=401)
    except PlaybackTicketError:
        return False, api_error(code=40130, msg="Invalid playback ticket", http_status=401)

    if ticket_auth["type"] == "admin":
        g.current_user = None
        g.auth_role = ADMIN_ROLE
        g.auth_via = "playback_ticket"
        return True, None

    user = ticket_auth["user"]
    g.current_user = user
    g.auth_role = user.role
    g.auth_via = "playback_ticket"
    if current_app.config.get("MULTI_TENANT_ENABLED"):
        from backend.app.services.accounts import resolve_or_provision_membership, set_request_account

        membership = resolve_or_provision_membership(user)
        set_request_account(membership)
    return True, None


def _normal_user_can_access_route():
    if request.path == "/api/v1/auth/playback-ticket" and request.method == "POST":
        return True
    if is_account_owner_request():
        if request.method == "GET":
            return any(pattern.match(request.path) for pattern in ACCOUNT_OWNER_GET_PATTERNS)
        if request.path == "/api/v1/auth/logout" and request.method == "POST":
            return True
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return any(pattern.match(request.path) for pattern in ACCOUNT_OWNER_WRITE_PATTERNS)
        return False

    if request.method == "GET":
        return any(pattern.match(request.path) for pattern in NORMAL_USER_GET_PATTERNS)
    if request.path == "/api/v1/auth/logout" and request.method == "POST":
        return True
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        return any(pattern.match(request.path) for pattern in NORMAL_USER_WRITE_PATTERNS)
    return False


def _enforce_hosted_managed_mode():
    if not is_hosted_managed_mode():
        return None

    if request.method in HOSTED_MANAGED_WRITE_METHODS:
        if any(pattern.match(request.path) for pattern in HOSTED_MANAGED_LOCKED_WRITE_PATTERNS):
            return api_error(
                code=40390,
                msg="Hosted managed mode blocks server configuration changes",
                http_status=403,
            )
        return None

    refresh_requested = str(request.args.get("refresh") or "").strip().lower() in {"1", "true", "yes", "on"}
    if request.method != "GET" or not refresh_requested:
        return None
    if not any(pattern.match(request.path) for pattern in HOSTED_MANAGED_LOCKED_REFRESH_GET_PATTERNS):
        return None

    return api_error(
        code=40390,
        msg="Hosted managed mode blocks server configuration changes",
        http_status=403,
    )


def _enforce_visibility_for_normal_user():
    if is_admin_request() or not is_user_management_enabled():
        return None
    if is_account_owner_request():
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
        return _enforce_hosted_managed_mode()
    if _load_session_user():
        if current_app.config.get("MULTI_TENANT_ENABLED") and not get_current_account_id():
            return api_error(code=40340, msg="Current user has no active account", http_status=403)
        hosted_response = _enforce_hosted_managed_mode()
        if hosted_response:
            return hosted_response
        if not is_admin_request() and not _normal_user_can_access_route():
            return api_error(code=40310, msg="Admin permission required", http_status=403)
        return _enforce_visibility_for_normal_user()
    playback_ticket_ok, playback_ticket_error = _authenticate_playback_ticket()
    if playback_ticket_error:
        return playback_ticket_error
    if playback_ticket_ok:
        if current_app.config.get("MULTI_TENANT_ENABLED") and not get_current_account_id():
            return api_error(code=40340, msg="Current user has no active account", http_status=403)
        hosted_response = _enforce_hosted_managed_mode()
        if hosted_response:
            return hosted_response
        if not is_admin_request() and not _normal_user_can_access_route():
            return api_error(code=40310, msg="Admin permission required", http_status=403)
        return _enforce_visibility_for_normal_user()
    return api_error(code=40100, msg="Authentication required", http_status=401)


def require_api_token():
    _reset_request_auth()

    if is_user_management_enabled():
        return _require_user_session()

    if not is_api_auth_enabled() or _is_public_request():
        return _enforce_hosted_managed_mode()

    expected = _configured_token()
    supplied = _request_token()
    if not supplied:
        return api_error(code=40100, msg="Authentication required", http_status=401)
    if not hmac.compare_digest(supplied, expected):
        return api_error(code=40300, msg="Invalid API token", http_status=403)
    g.current_user = None
    g.auth_role = ADMIN_ROLE
    g.auth_via = "api_token"
    return _enforce_hosted_managed_mode()
