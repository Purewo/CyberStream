from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from flask import current_app

from backend.app.extensions import db
from backend.app.models import User


class PlaybackTicketError(Exception):
    """Base class for playback ticket validation failures."""


class PlaybackTicketExpired(PlaybackTicketError):
    """Raised when a playback ticket is otherwise valid but expired."""


def playback_ticket_ttl_seconds():
    value = current_app.config.get("PLAYBACK_TICKET_TTL_SECONDS", 12 * 60 * 60)
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        ttl = 12 * 60 * 60
    return max(60, ttl)


def _secret_bytes():
    secret = (
        current_app.config.get("PLAYBACK_TICKET_SECRET")
        or current_app.config.get("SECRET_KEY")
        or current_app.config.get("SESSION_SECRET")
        or ""
    )
    secret = str(secret)
    if not secret:
        raise RuntimeError("Playback ticket secret is not configured")
    return secret.encode("utf-8")


def _b64encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value):
    raw = str(value or "").encode("ascii")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def _sign(body):
    digest = hmac.new(_secret_bytes(), body.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def _encode_payload(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _b64encode(raw)


def _decode_payload(body):
    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - all decode failures are invalid tickets.
        raise PlaybackTicketError("Invalid playback ticket") from exc
    if not isinstance(payload, dict):
        raise PlaybackTicketError("Invalid playback ticket")
    return payload


def issue_playback_ticket_for_user(user, ttl_seconds=None):
    if not user or not getattr(user, "id", None):
        raise PlaybackTicketError("Playback ticket requires a user")
    now = int(time.time())
    ttl = playback_ticket_ttl_seconds() if ttl_seconds is None else max(60, int(ttl_seconds))
    payload = {
        "v": 1,
        "purpose": "playback",
        "typ": "user",
        "uid": int(user.id),
        "sv": int(user.session_version or 1),
        "iat": now,
        "exp": now + ttl,
        "nonce": secrets.token_urlsafe(18),
    }
    body = _encode_payload(payload)
    return {
        "ticket": f"{body}.{_sign(body)}",
        "expires_at": payload["exp"],
        "ttl": ttl,
    }


def issue_admin_playback_ticket(ttl_seconds=None):
    now = int(time.time())
    ttl = playback_ticket_ttl_seconds() if ttl_seconds is None else max(60, int(ttl_seconds))
    payload = {
        "v": 1,
        "purpose": "playback",
        "typ": "admin",
        "role": User.ROLE_ADMIN,
        "iat": now,
        "exp": now + ttl,
        "nonce": secrets.token_urlsafe(18),
    }
    body = _encode_payload(payload)
    return {
        "ticket": f"{body}.{_sign(body)}",
        "expires_at": payload["exp"],
        "ttl": ttl,
    }


def validate_playback_ticket(ticket):
    raw = str(ticket or "").strip()
    if "." not in raw:
        raise PlaybackTicketError("Invalid playback ticket")
    body, signature = raw.rsplit(".", 1)
    if not body or not signature or not hmac.compare_digest(signature, _sign(body)):
        raise PlaybackTicketError("Invalid playback ticket")

    payload = _decode_payload(body)
    if payload.get("v") != 1 or payload.get("purpose") != "playback":
        raise PlaybackTicketError("Invalid playback ticket")

    try:
        expires_at = int(payload.get("exp"))
    except (TypeError, ValueError) as exc:
        raise PlaybackTicketError("Invalid playback ticket") from exc
    if expires_at < int(time.time()):
        raise PlaybackTicketExpired("Playback ticket expired")

    ticket_type = payload.get("typ")
    if ticket_type == "admin" and payload.get("role") == User.ROLE_ADMIN:
        return {
            "type": "admin",
            "role": User.ROLE_ADMIN,
            "payload": payload,
        }

    if ticket_type != "user":
        raise PlaybackTicketError("Invalid playback ticket")

    try:
        user_id = int(payload.get("uid"))
        session_version = int(payload.get("sv"))
    except (TypeError, ValueError) as exc:
        raise PlaybackTicketError("Invalid playback ticket") from exc

    user = db.session.get(User, user_id)
    if not user or not user.is_enabled:
        raise PlaybackTicketError("Invalid playback ticket")
    if int(user.session_version or 1) != session_version:
        raise PlaybackTicketError("Invalid playback ticket")
    return {
        "type": "user",
        "user": user,
        "payload": payload,
    }
