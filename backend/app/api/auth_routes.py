from datetime import datetime

from flask import Blueprint, g, request, session

from backend.app.extensions import db
from backend.app.models import AuditLog, User
from backend.app.security import get_current_auth_role, get_current_user, is_user_management_enabled
from backend.app.services.audit import record_audit
from backend.app.services.login_rate_limit import check_login_rate_limit, clear_login_failures, record_login_failure
from backend.app.services.user_access import build_user_visibility_preview, visible_library_ids_for_current_user
from backend.app.services.users import (
    UserValidationError,
    bump_user_session_version,
    ensure_user_keeps_admin_access,
    normalize_library_rules_payload,
    normalize_password,
    normalize_role,
    normalize_username,
    replace_user_library_rules,
    set_user_password,
    verify_user_password,
)
from backend.app.utils.response import api_error, api_response


auth_bp = Blueprint('auth', __name__, url_prefix='/api/v1')


def _json_payload():
    return request.get_json(silent=True) or {}


def _set_login_session(user):
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    session["session_version"] = int(user.session_version or 1)


def _auth_summary(user=None):
    role = get_current_auth_role() or (user.role if user else None)
    auth_via = getattr(g, "auth_via", None) or ("session" if user else None)
    authenticated = bool(role)
    data = {
        "user_management_enabled": is_user_management_enabled(),
        "authenticated": authenticated,
        "role": role,
        "auth_via": auth_via,
        "user": user.to_dict(include_rules=True) if user else None,
        "permissions": {
            "admin": role == User.ROLE_ADMIN,
            "read_catalog": authenticated,
            "manage_catalog": role == User.ROLE_ADMIN,
            "manage_users": role == User.ROLE_ADMIN,
            "personal_history": authenticated,
            "personal_subtitle_settings": authenticated,
        },
    }
    return data


def _profile_payload(user):
    data = _auth_summary(user)
    visible_library_ids = visible_library_ids_for_current_user()
    data["visible_library_ids"] = sorted(visible_library_ids) if visible_library_ids is not None else None
    return data


def _rate_limit_response(retry_after):
    response, status = api_error(
        code=42910,
        msg=f"Too many login attempts; retry after {retry_after} seconds",
        http_status=429,
    )
    response.headers["Retry-After"] = str(retry_after)
    return response, status


@auth_bp.before_request
def guard_disabled_user_management():
    if is_user_management_enabled() or request.path == "/api/v1/auth/me":
        return None
    return api_error(code=40490, msg="User management is not enabled", http_status=404)


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    payload = _json_payload()
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    retry_after = check_login_rate_limit(username)
    if retry_after:
        record_audit(
            "auth.login",
            target_type="user",
            target_username=username,
            outcome="rate_limited",
            details={"retry_after": retry_after},
            commit=True,
        )
        return _rate_limit_response(retry_after)

    user = User.query.filter_by(username=username).first()
    if not user or not user.is_enabled or not verify_user_password(user, password):
        retry_after = record_login_failure(username)
        record_audit(
            "auth.login",
            target_type="user",
            target_id=user.id if user else None,
            target_username=username,
            outcome="failure",
            details={"reason": "invalid_credentials", "rate_limited": bool(retry_after)},
            commit=True,
        )
        if retry_after:
            return _rate_limit_response(retry_after)
        return api_error(code=40110, msg="Invalid username or password", http_status=401)

    clear_login_failures(username)
    _set_login_session(user)
    user.last_login_at = datetime.utcnow()
    record_audit(
        "auth.login",
        target_type="user",
        target_id=user.id,
        target_username=user.username,
        outcome="success",
        actor=user,
    )
    db.session.commit()
    return api_response(data=_auth_summary(user), msg="Logged in")


@auth_bp.route('/auth/logout', methods=['POST'])
def logout():
    user = get_current_user()
    if user:
        record_audit(
            "auth.logout",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            actor=user,
            commit=True,
        )
    session.clear()
    return api_response(msg="Logged out")


@auth_bp.route('/auth/me', methods=['GET'])
def me():
    user = get_current_user()
    return api_response(data=_auth_summary(user), msg="current user")


@auth_bp.route('/user/profile', methods=['GET'])
def get_profile():
    user = get_current_user()
    if not user:
        return api_error(code=40100, msg="Authentication required", http_status=401)
    return api_response(data=_profile_payload(user), msg="current profile")


@auth_bp.route('/user/profile', methods=['PATCH'])
def update_profile():
    user = get_current_user()
    if not user:
        return api_error(code=40100, msg="Authentication required", http_status=401)

    payload = _json_payload()
    if "display_name" in payload:
        user.display_name = str(payload.get("display_name") or user.username).strip() or user.username
    record_audit(
        "user.profile.update",
        target_type="user",
        target_id=user.id,
        target_username=user.username,
        actor=user,
        details={"fields": sorted([key for key in payload.keys() if key in {"display_name"}])},
    )
    db.session.commit()
    return api_response(data=_profile_payload(user), msg="Profile updated")


@auth_bp.route('/user/password', methods=['POST'])
def update_own_password():
    user = get_current_user()
    if not user:
        return api_error(code=40100, msg="Authentication required", http_status=401)

    payload = _json_payload()
    current_password = str(payload.get("current_password") or "")
    new_password = payload.get("new_password", payload.get("password"))
    if not verify_user_password(user, current_password):
        record_audit(
            "user.password.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            outcome="failure",
            actor=user,
            details={"reason": "invalid_current_password"},
            commit=True,
        )
        return api_error(code=40330, msg="Current password is incorrect", http_status=403)
    try:
        set_user_password(user, new_password)
        session["session_version"] = int(user.session_version or 1)
        record_audit(
            "user.password.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            actor=user,
        )
        db.session.commit()
        return api_response(data=_auth_summary(user), msg="Password updated")
    except UserValidationError as e:
        db.session.rollback()
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)


@auth_bp.route('/admin/users', methods=['GET'])
def list_users():
    users = User.query.order_by(User.id.asc()).all()
    return api_response(data={"items": [user.to_dict(include_rules=True) for user in users]})


@auth_bp.route('/admin/users', methods=['POST'])
def create_user():
    payload = _json_payload()
    try:
        username = normalize_username(payload.get("username"))
        password = normalize_password(payload.get("password"))
        role = normalize_role(payload.get("role", User.ROLE_USER))
    except UserValidationError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)

    if User.query.filter_by(username=username).first():
        return api_error(code=40091, msg="username already exists")

    try:
        if any(key in payload for key in ("rules", "allow_library_ids", "deny_library_ids")):
            normalize_library_rules_payload(payload)
    except UserValidationError as e:
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)

    user = User(
        username=username,
        display_name=str(payload.get("display_name") or username).strip() or username,
        role=role,
        is_enabled=bool(payload.get("is_enabled", True)),
    )
    set_user_password(user, password)
    db.session.add(user)
    try:
        db.session.commit()
        if any(key in payload for key in ("rules", "allow_library_ids", "deny_library_ids")):
            replace_user_library_rules(user, payload)
        record_audit(
            "admin.user.create",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            details={"role": user.role, "is_enabled": bool(user.is_enabled)},
            commit=True,
        )
        return api_response(data=user.to_dict(include_rules=True), msg="User created", http_status=201)
    except UserValidationError as e:
        db.session.rollback()
        record_audit(
            "admin.user.create",
            target_type="user",
            target_username=username,
            outcome="failure",
            details={"reason": e.message},
            commit=True,
        )
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)
    except Exception:
        db.session.rollback()
        raise


@auth_bp.route('/admin/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return api_error(code=40490, msg="User not found", http_status=404)
    return api_response(data=user.to_dict(include_rules=True))


@auth_bp.route('/admin/users/<int:user_id>', methods=['PATCH'])
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return api_error(code=40490, msg="User not found", http_status=404)

    payload = _json_payload()
    try:
        next_role = user.role
        next_enabled = bool(user.is_enabled)
        if "display_name" in payload:
            user.display_name = str(payload.get("display_name") or user.username).strip() or user.username
        if "role" in payload:
            next_role = normalize_role(payload.get("role"))
        if "is_enabled" in payload:
            next_enabled = bool(payload.get("is_enabled"))
        ensure_user_keeps_admin_access(user, target_role=next_role, target_enabled=next_enabled)
        role_changed = next_role != user.role
        enabled_changed = next_enabled != bool(user.is_enabled)
        user.role = next_role
        user.is_enabled = next_enabled
        if role_changed or enabled_changed:
            bump_user_session_version(user)
            if get_current_user() and get_current_user().id == user.id:
                session["session_version"] = int(user.session_version or 1)
        record_audit(
            "admin.user.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            details={
                "fields": sorted([key for key in payload.keys() if key in {"display_name", "role", "is_enabled"}]),
                "role_changed": role_changed,
                "enabled_changed": enabled_changed,
            },
        )
        db.session.commit()
        return api_response(data=user.to_dict(include_rules=True), msg="User updated")
    except UserValidationError as e:
        db.session.rollback()
        record_audit(
            "admin.user.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            outcome="failure",
            details={"reason": e.message},
            commit=True,
        )
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)


@auth_bp.route('/admin/users/<int:user_id>/password', methods=['POST'])
def update_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return api_error(code=40490, msg="User not found", http_status=404)
    try:
        set_user_password(user, _json_payload().get("password"))
        if get_current_user() and get_current_user().id == user.id:
            session["session_version"] = int(user.session_version or 1)
        record_audit(
            "admin.user.password.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
        )
        db.session.commit()
        return api_response(msg="Password updated")
    except UserValidationError as e:
        db.session.rollback()
        record_audit(
            "admin.user.password.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            outcome="failure",
            details={"reason": e.message},
            commit=True,
        )
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)


@auth_bp.route('/admin/users/<int:user_id>/library-rules', methods=['PUT'])
def update_user_library_rules(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return api_error(code=40490, msg="User not found", http_status=404)
    try:
        normalize_library_rules_payload(_json_payload())
        replace_user_library_rules(user, _json_payload())
        record_audit(
            "admin.user.library_rules.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            details={"rules_count": user.library_rules.count()},
            commit=True,
        )
        return api_response(data=user.to_dict(include_rules=True), msg="User library rules updated")
    except UserValidationError as e:
        db.session.rollback()
        record_audit(
            "admin.user.library_rules.update",
            target_type="user",
            target_id=user.id,
            target_username=user.username,
            outcome="failure",
            details={"reason": e.message},
            commit=True,
        )
        return api_error(code=e.code, msg=e.message, http_status=e.http_status)


@auth_bp.route('/admin/users/<int:user_id>/visibility-preview', methods=['GET'])
def get_user_visibility_preview(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return api_error(code=40490, msg="User not found", http_status=404)
    try:
        sample_limit = int(request.args.get("sample_limit", 12))
    except (TypeError, ValueError):
        return api_error(code=40093, msg="sample_limit must be an integer")
    return api_response(
        data=build_user_visibility_preview(user, sample_limit=sample_limit),
        msg="User visibility preview",
    )


@auth_bp.route('/admin/audit-logs', methods=['GET'])
def list_audit_logs():
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 500))
    query = AuditLog.query
    if request.args.get("action"):
        query = query.filter_by(action=request.args.get("action"))
    if request.args.get("outcome"):
        query = query.filter_by(outcome=request.args.get("outcome"))
    if request.args.get("target_type"):
        query = query.filter_by(target_type=request.args.get("target_type"))
    if request.args.get("target_id"):
        query = query.filter_by(target_id=request.args.get("target_id"))
    if request.args.get("actor_user_id"):
        try:
            query = query.filter_by(actor_user_id=int(request.args.get("actor_user_id")))
        except (TypeError, ValueError):
            return api_error(code=40092, msg="actor_user_id must be an integer")

    items = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return api_response(data={"items": [item.to_dict() for item in items], "limit": limit})
