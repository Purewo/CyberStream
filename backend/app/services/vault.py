from __future__ import annotations

import re
from datetime import datetime, timedelta

from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

from backend.app.extensions import db
from backend.app.models import UserVaultSecret
from backend.app.security import get_current_user, is_user_management_enabled
from backend.app.services.audit import record_audit
from backend.app.services.users import verify_user_password


VAULT_PIN_RE = re.compile(r"^\d{6}$")
VAULT_PIN_CHANGE_LIMIT = 10
VAULT_PIN_CHANGE_WINDOW = timedelta(days=1)
_SESSION_SCOPE_KEY = "vault_unlocked_scope_key"
_SESSION_PIN_CHANGED_AT_KEY = "vault_unlocked_pin_changed_at"


class VaultAccessError(ValueError):
    def __init__(self, code, msg, http_status=403):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.http_status = http_status


def _current_admin_context():
    if not is_user_management_enabled():
        return "default", None

    user = get_current_user()
    if not user or not user.is_admin() or not user.is_enabled:
        return None
    return f"user:{user.id}", user


def _require_admin_context():
    context = _current_admin_context()
    if not context:
        raise VaultAccessError(40340, "Vault is available only to the default administrator or an authenticated administrator")
    return context


def _secret_for_scope(scope_key):
    return UserVaultSecret.query.filter_by(scope_key=scope_key).first()


def _clear_unlock_session():
    session.pop(_SESSION_SCOPE_KEY, None)
    session.pop(_SESSION_PIN_CHANGED_AT_KEY, None)


def _pin_version(secret):
    return secret.pin_changed_at.isoformat() if secret and secret.pin_changed_at else None


def _mark_unlocked(secret):
    session[_SESSION_SCOPE_KEY] = secret.scope_key
    session[_SESSION_PIN_CHANGED_AT_KEY] = _pin_version(secret)


def _refresh_lock_state(secret, now, commit=False):
    if not secret or not secret.is_locked or not secret.locked_until or secret.locked_until > now:
        return False
    secret.is_locked = False
    secret.locked_until = None
    secret.updated_at = now
    if commit:
        db.session.commit()
    return True


def _is_locked(secret, now):
    if not secret:
        return False
    _refresh_lock_state(secret, now, commit=False)
    return bool(secret.is_locked and (not secret.locked_until or secret.locked_until > now))


def _window_stats(secret, now):
    if not secret or not secret.pin_change_window_started_at:
        return 0, VAULT_PIN_CHANGE_LIMIT
    if now - secret.pin_change_window_started_at >= VAULT_PIN_CHANGE_WINDOW:
        return 0, VAULT_PIN_CHANGE_LIMIT
    used = max(0, int(secret.pin_change_count or 0))
    return used, max(0, VAULT_PIN_CHANGE_LIMIT - used)


def _validate_pin(value):
    pin = str(value or "")
    if not VAULT_PIN_RE.fullmatch(pin):
        raise VaultAccessError(40040, "Vault PIN must be exactly 6 digits", http_status=400)
    return pin


def _unlocked_with_secret(secret, scope_key, now):
    if not secret or _is_locked(secret, now):
        return False
    return (
        session.get(_SESSION_SCOPE_KEY) == scope_key
        and session.get(_SESSION_PIN_CHANGED_AT_KEY) == _pin_version(secret)
    )


def build_vault_status():
    scope_key, _actor = _require_admin_context()
    now = datetime.utcnow()
    secret = _secret_for_scope(scope_key)
    if secret and _refresh_lock_state(secret, now, commit=True):
        _clear_unlock_session()
    used, remaining = _window_stats(secret, now)
    locked = _is_locked(secret, now)
    unlocked = _unlocked_with_secret(secret, scope_key, now)
    return {
        "configured": bool(secret and secret.pin_hash),
        "unlocked": unlocked,
        "locked": locked,
        "locked_until": secret.locked_until.isoformat() if locked and secret.locked_until else None,
        "pin_change_limit_per_day": VAULT_PIN_CHANGE_LIMIT,
        "pin_changes_used_today": used,
        "pin_changes_remaining_today": remaining,
    }


def is_vault_unlocked():
    context = _current_admin_context()
    if not context:
        return False
    scope_key, _actor = context
    now = datetime.utcnow()
    secret = _secret_for_scope(scope_key)
    return _unlocked_with_secret(secret, scope_key, now)


def require_vault_unlocked():
    scope_key, _actor = _require_admin_context()
    now = datetime.utcnow()
    secret = _secret_for_scope(scope_key)
    if not secret:
        raise VaultAccessError(40341, "Vault PIN is not configured")
    if _is_locked(secret, now):
        raise VaultAccessError(42340, "Vault is locked due to excessive PIN changes", http_status=423)
    if not _unlocked_with_secret(secret, scope_key, now):
        raise VaultAccessError(40342, "Vault PIN unlock required")
    return secret


def verify_vault_pin(payload, audit_action="vault.pin.verify"):
    scope_key, actor = _require_admin_context()
    now = datetime.utcnow()
    secret = _secret_for_scope(scope_key)
    if not secret:
        raise VaultAccessError(40341, "Vault PIN is not configured")
    if _is_locked(secret, now):
        raise VaultAccessError(42340, "Vault is locked due to excessive PIN changes", http_status=423)
    pin = _validate_pin((payload or {}).get("pin"))
    if not check_password_hash(secret.pin_hash, pin):
        _clear_unlock_session()
        record_audit(
            audit_action,
            target_type="vault",
            target_id=secret.scope_key,
            outcome="failure",
            actor=actor,
            details={"reason": "invalid_pin"},
            commit=True,
        )
        raise VaultAccessError(40344, "Vault PIN is incorrect")
    record_audit(audit_action, target_type="vault", target_id=secret.scope_key, actor=actor)
    return secret


def _consume_pin_change(secret, now, actor):
    if (
        not secret.pin_change_window_started_at
        or now - secret.pin_change_window_started_at >= VAULT_PIN_CHANGE_WINDOW
    ):
        secret.pin_change_window_started_at = now
        secret.pin_change_count = 0
        secret.is_locked = False
        secret.locked_until = None
    if int(secret.pin_change_count or 0) >= VAULT_PIN_CHANGE_LIMIT:
        secret.is_locked = True
        secret.locked_until = secret.pin_change_window_started_at + VAULT_PIN_CHANGE_WINDOW
        secret.updated_at = now
        _clear_unlock_session()
        record_audit(
            "vault.pin.lock",
            target_type="vault",
            target_id=secret.scope_key,
            outcome="blocked",
            actor=actor,
            details={"reason": "daily_pin_change_limit", "limit": VAULT_PIN_CHANGE_LIMIT},
        )
        db.session.commit()
        raise VaultAccessError(42340, "Vault is locked due to excessive PIN changes", http_status=423)
    secret.pin_change_count = int(secret.pin_change_count or 0) + 1


def set_vault_pin(payload):
    scope_key, actor = _require_admin_context()
    now = datetime.utcnow()
    new_pin = _validate_pin(payload.get("new_pin", payload.get("pin")))
    if actor and verify_user_password(actor, new_pin):
        raise VaultAccessError(40041, "Vault PIN must not match the login password", http_status=400)

    secret = _secret_for_scope(scope_key)
    initial_setup = secret is None
    if secret and _is_locked(secret, now):
        raise VaultAccessError(42340, "Vault is locked due to excessive PIN changes", http_status=423)
    if secret:
        current_pin = _validate_pin(payload.get("current_pin"))
        if not check_password_hash(secret.pin_hash, current_pin):
            record_audit(
                "vault.pin.update",
                target_type="vault",
                target_id=secret.scope_key,
                outcome="failure",
                actor=actor,
                details={"reason": "invalid_current_pin"},
                commit=True,
            )
            raise VaultAccessError(40343, "Current vault PIN is incorrect")
        if check_password_hash(secret.pin_hash, new_pin):
            raise VaultAccessError(40042, "New vault PIN must differ from the current PIN", http_status=400)
    else:
        secret = UserVaultSecret(
            scope_key=scope_key,
            user_id=actor.id if actor else None,
            pin_hash="",
            pin_change_count=0,
            is_locked=False,
            created_at=now,
            updated_at=now,
        )
        db.session.add(secret)

    if not initial_setup:
        _consume_pin_change(secret, now, actor)
    secret.pin_hash = generate_password_hash(new_pin)
    secret.pin_changed_at = now
    secret.updated_at = now
    db.session.flush()
    _mark_unlocked(secret)
    record_audit(
        "vault.pin.update",
        target_type="vault",
        target_id=secret.scope_key,
        actor=actor,
        details={"initial_setup": initial_setup},
    )
    db.session.commit()
    return build_vault_status()


def unlock_vault(payload):
    scope_key, actor = _require_admin_context()
    now = datetime.utcnow()
    secret = _secret_for_scope(scope_key)
    if not secret:
        raise VaultAccessError(40341, "Vault PIN is not configured")
    if _is_locked(secret, now):
        raise VaultAccessError(42340, "Vault is locked due to excessive PIN changes", http_status=423)
    pin = _validate_pin(payload.get("pin"))
    if not check_password_hash(secret.pin_hash, pin):
        _clear_unlock_session()
        record_audit(
            "vault.unlock",
            target_type="vault",
            target_id=secret.scope_key,
            outcome="failure",
            actor=actor,
            details={"reason": "invalid_pin"},
            commit=True,
        )
        raise VaultAccessError(40344, "Vault PIN is incorrect")
    _mark_unlocked(secret)
    record_audit("vault.unlock", target_type="vault", target_id=secret.scope_key, actor=actor, commit=True)
    return build_vault_status()


def lock_vault():
    scope_key, actor = _require_admin_context()
    _clear_unlock_session()
    record_audit("vault.lock", target_type="vault", target_id=scope_key, actor=actor, commit=True)
    return build_vault_status()
