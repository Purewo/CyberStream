from __future__ import annotations

from flask import g, has_request_context, request

from backend.app.extensions import db


def _request_ip():
    if not has_request_context():
        return None
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.remote_addr


def _request_user_agent():
    if not has_request_context():
        return None
    value = request.headers.get("User-Agent", "")
    return value[:255] if value else None


def _request_auth_via():
    return getattr(g, "auth_via", None) if has_request_context() else None


def _request_role():
    return getattr(g, "auth_role", None) if has_request_context() else None


def record_audit(
    action,
    target_type=None,
    target_id=None,
    target_username=None,
    outcome="success",
    details=None,
    actor=None,
    commit=False,
):
    from backend.app.models import AuditLog

    if actor is None and has_request_context():
        actor = getattr(g, "current_user", None)

    actor_user_id = getattr(actor, "id", None)
    actor_username = getattr(actor, "username", None)
    actor_role = getattr(actor, "role", None) or _request_role()
    log = AuditLog(
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        actor_role=actor_role,
        auth_via=_request_auth_via(),
        action=str(action or "unknown")[:80],
        target_type=str(target_type)[:40] if target_type else None,
        target_id=str(target_id)[:80] if target_id is not None else None,
        target_username=str(target_username)[:80] if target_username else None,
        outcome=str(outcome or "success")[:30],
        ip_address=_request_ip(),
        user_agent=_request_user_agent(),
        details=details if isinstance(details, dict) else {},
    )
    db.session.add(log)
    if commit:
        db.session.commit()
    return log
