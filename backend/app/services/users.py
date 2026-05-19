from __future__ import annotations

import re
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from backend.app.extensions import db
from backend.app.models import Library, User, UserLibraryRule
from backend.app.services.user_access import clear_user_access_cache


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,80}$")


class UserValidationError(ValueError):
    def __init__(self, message, code=40090, http_status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


def normalize_username(value):
    username = str(value or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise UserValidationError("username must be 3-80 chars and use letters, numbers, dot, underscore, @ or dash")
    return username


def normalize_password(value):
    password = str(value or "")
    if len(password) < 8:
        raise UserValidationError("password must be at least 8 characters")
    return password


def normalize_role(value):
    role = User.normalize_role(value)
    if not role:
        raise UserValidationError("role must be admin or user")
    return role


def _password_matches(password_hash, password):
    if not password_hash:
        return False
    try:
        return check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        return False


def bump_user_session_version(user):
    user.session_version = int(user.session_version or 0) + 1
    user.updated_at = datetime.utcnow()
    return user.session_version


def set_user_password(user, password, invalidate_sessions=True):
    password = normalize_password(password)
    if _password_matches(getattr(user, "password_hash", None), password):
        if not getattr(user, "session_version", None):
            user.session_version = 1
        return False

    user.password_hash = generate_password_hash(password)
    user.password_changed_at = datetime.utcnow()
    if invalidate_sessions:
        bump_user_session_version(user)
    else:
        user.session_version = int(user.session_version or 1)
        user.updated_at = datetime.utcnow()
    return True


def verify_user_password(user, password):
    return bool(user and check_password_hash(user.password_hash, str(password or "")))


def count_enabled_admins(exclude_user_id=None):
    query = User.query.filter_by(role=User.ROLE_ADMIN, is_enabled=True)
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


def ensure_user_keeps_admin_access(user, target_role=None, target_enabled=None):
    target_role = user.role if target_role is None else target_role
    target_enabled = user.is_enabled if target_enabled is None else bool(target_enabled)
    currently_enabled_admin = bool(user.id and user.role == User.ROLE_ADMIN and user.is_enabled)
    will_be_enabled_admin = bool(target_role == User.ROLE_ADMIN and target_enabled)
    if currently_enabled_admin and not will_be_enabled_admin and count_enabled_admins(exclude_user_id=user.id) <= 0:
        raise UserValidationError("cannot remove or disable the last enabled admin", code=40901, http_status=409)
    return True


def bootstrap_admin(app):
    if not app.config.get("USER_MANAGEMENT_ENABLED"):
        return None

    username = str(app.config.get("BOOTSTRAP_ADMIN_USERNAME") or "").strip()
    password = str(app.config.get("BOOTSTRAP_ADMIN_PASSWORD") or "")
    display_name = str(app.config.get("BOOTSTRAP_ADMIN_DISPLAY_NAME") or "Administrator").strip()
    if not username or not password:
        return None

    username = normalize_username(username)
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username, role=User.ROLE_ADMIN, is_enabled=True)
        db.session.add(user)

    user.display_name = display_name or username
    user.role = User.ROLE_ADMIN
    user.is_enabled = True
    set_user_password(user, password)
    db.session.commit()
    clear_user_access_cache()
    return user


def normalize_library_rules_payload(payload):
    if not isinstance(payload, dict):
        raise UserValidationError("payload must be an object")

    if isinstance(payload.get("rules"), list):
        raw_rules = payload["rules"]
    else:
        raw_rules = []
        for library_id in payload.get("allow_library_ids") or []:
            raw_rules.append({"library_id": library_id, "mode": UserLibraryRule.MODE_ALLOW})
        for library_id in payload.get("deny_library_ids") or []:
            raw_rules.append({"library_id": library_id, "mode": UserLibraryRule.MODE_DENY})

    normalized = []
    seen = set()
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise UserValidationError("library rules must be objects")
        try:
            library_id = int(raw_rule.get("library_id"))
        except (TypeError, ValueError):
            raise UserValidationError("library_id must be an integer") from None
        mode = UserLibraryRule.normalize_mode(raw_rule.get("mode"))
        if not mode:
            raise UserValidationError("library rule mode must be allow or deny")
        if not db.session.get(Library, library_id):
            raise UserValidationError(f"library not found: {library_id}", code=40410, http_status=404)
        if library_id in seen:
            raise UserValidationError(f"duplicate library rule: {library_id}")
        seen.add(library_id)
        normalized.append({"library_id": library_id, "mode": mode})
    return normalized


def replace_user_library_rules(user, payload):
    rules = normalize_library_rules_payload(payload)
    UserLibraryRule.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    saved = []
    for item in rules:
        rule = UserLibraryRule(user_id=user.id, library_id=item["library_id"], mode=item["mode"])
        db.session.add(rule)
        saved.append(rule)
    db.session.commit()
    clear_user_access_cache()
    return saved
