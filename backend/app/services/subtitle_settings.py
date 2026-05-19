import re
from datetime import datetime

from flask import has_app_context, has_request_context

from backend.app.extensions import db
from backend.app.security import get_current_user, is_admin_request, is_user_management_enabled


DEFAULT_SUBTITLE_SETTINGS = {
    "zhSize": 28,
    "zhColor": "#FFFFFF",
    "enSize": 22,
    "enColor": "#FFFFFF",
    "gap": 6,
    "offset": 72,
}

SUBTITLE_SETTING_FIELDS = tuple(DEFAULT_SUBTITLE_SETTINGS.keys())

NUMERIC_FIELD_RANGES = {
    "zhSize": (8, 96),
    "enSize": (8, 96),
    "gap": (0, 120),
    "offset": (-500, 500),
}

COLOR_FIELDS = {"zhColor", "enColor"}
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class SubtitleSettingsError(ValueError):
    def __init__(self, message, code=40080, http_status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


def default_subtitle_settings():
    return dict(DEFAULT_SUBTITLE_SETTINGS)


def _resource_id(resource):
    value = getattr(resource, "id", None)
    return str(value) if value else None


def _get_settings_row(resource):
    resource_id = _resource_id(resource)
    if not resource_id or not has_app_context():
        return None

    from backend.app.models import ResourceSubtitleSetting

    return ResourceSubtitleSetting.query.filter_by(resource_id=resource_id).first()


def _current_request_user():
    if not has_request_context():
        return None
    return get_current_user()


def _use_user_settings():
    return bool(
        has_app_context()
        and has_request_context()
        and is_user_management_enabled()
        and _current_request_user()
        and not is_admin_request()
    )


def _get_user_settings_row(resource, user=None):
    resource_id = _resource_id(resource)
    user = user or _current_request_user()
    if not resource_id or not user or not has_app_context():
        return None

    from backend.app.models import UserSubtitleSetting

    return UserSubtitleSetting.query.filter_by(resource_id=resource_id, user_id=user.id).first()


def _row_to_settings(row):
    if not row:
        return default_subtitle_settings()
    return {
        "zhSize": int(row.zh_size),
        "zhColor": row.zh_color,
        "enSize": int(row.en_size),
        "enColor": row.en_color,
        "gap": int(row.gap),
        "offset": int(row.offset),
    }


def _isoformat(value):
    return value.isoformat() if value else None


def _build_user_subtitle_settings_payload(resource, user, row=None):
    customized = row is not None
    return {
        "resource_id": _resource_id(resource),
        "user_id": user.id if user else None,
        "settings": _row_to_settings(row),
        "customized": customized,
        "source": "user" if customized else "default",
        "updated_at": _isoformat(getattr(row, "updated_at", None)) if customized else None,
    }


def build_subtitle_settings_payload(resource, row=None):
    if row is None and _use_user_settings():
        user = _current_request_user()
        row = _get_user_settings_row(resource, user=user)
        return _build_user_subtitle_settings_payload(resource, user, row=row)

    if row is None:
        row = _get_settings_row(resource)
    customized = row is not None
    return {
        "resource_id": _resource_id(resource),
        "settings": _row_to_settings(row),
        "customized": customized,
        "source": "resource" if customized else "default",
        "updated_at": _isoformat(getattr(row, "updated_at", None)) if customized else None,
    }


def get_subtitle_settings_for_playback(resource):
    payload = build_subtitle_settings_payload(resource)
    return {
        "settings": payload["settings"],
        "settings_customized": payload["customized"],
        "settings_source": payload["source"],
        "settings_updated_at": payload["updated_at"],
    }


def _extract_settings_fields(payload):
    if not isinstance(payload, dict):
        raise SubtitleSettingsError("subtitle settings payload must be an object")

    raw_settings = payload.get("settings")
    sources = []
    if isinstance(raw_settings, dict):
        sources.append(raw_settings)
    sources.append(payload)

    extracted = {}
    for source in sources:
        for field in SUBTITLE_SETTING_FIELDS:
            if field in source:
                extracted[field] = source[field]
    if not extracted:
        raise SubtitleSettingsError("no supported subtitle settings fields to update")
    return extracted


def _normalize_integer(field, value):
    if isinstance(value, bool):
        raise SubtitleSettingsError(f"{field} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise SubtitleSettingsError(f"{field} must be an integer") from None

    minimum, maximum = NUMERIC_FIELD_RANGES[field]
    if normalized < minimum or normalized > maximum:
        raise SubtitleSettingsError(f"{field} must be between {minimum} and {maximum}")
    return normalized


def _normalize_color(field, value):
    if not isinstance(value, str):
        raise SubtitleSettingsError(f"{field} must be a hex color")
    normalized = value.strip()
    if not HEX_COLOR_RE.match(normalized):
        raise SubtitleSettingsError(f"{field} must be a hex color")
    if len(normalized) == 4:
        normalized = "#" + "".join(ch * 2 for ch in normalized[1:])
    return normalized.upper()


def normalize_subtitle_settings_payload(payload, current_settings=None):
    current = dict(DEFAULT_SUBTITLE_SETTINGS)
    if isinstance(current_settings, dict):
        for field in SUBTITLE_SETTING_FIELDS:
            if field in current_settings:
                current[field] = current_settings[field]

    updates = _extract_settings_fields(payload)
    for field, value in updates.items():
        if field in COLOR_FIELDS:
            current[field] = _normalize_color(field, value)
        else:
            current[field] = _normalize_integer(field, value)
    return current


def save_resource_subtitle_settings(resource, payload):
    resource_id = _resource_id(resource)
    if not resource_id:
        raise SubtitleSettingsError("resource id is required", code=40081)

    if _use_user_settings():
        return save_user_subtitle_settings(resource, payload)

    from backend.app.models import ResourceSubtitleSetting

    row = _get_settings_row(resource)
    settings = normalize_subtitle_settings_payload(payload, current_settings=_row_to_settings(row))
    if row is None:
        row = ResourceSubtitleSetting(resource_id=resource_id)
        db.session.add(row)

    row.zh_size = settings["zhSize"]
    row.zh_color = settings["zhColor"]
    row.en_size = settings["enSize"]
    row.en_color = settings["enColor"]
    row.gap = settings["gap"]
    row.offset = settings["offset"]
    row.updated_at = datetime.utcnow()

    db.session.commit()
    return build_subtitle_settings_payload(resource, row=row)


def save_user_subtitle_settings(resource, payload):
    resource_id = _resource_id(resource)
    user = get_current_user()
    if not resource_id or not user:
        raise SubtitleSettingsError("user and resource are required", code=40081)

    from backend.app.models import UserSubtitleSetting

    row = _get_user_settings_row(resource, user=user)
    settings = normalize_subtitle_settings_payload(payload, current_settings=_row_to_settings(row))
    if row is None:
        row = UserSubtitleSetting(resource_id=resource_id, user_id=user.id)
        db.session.add(row)

    row.zh_size = settings["zhSize"]
    row.zh_color = settings["zhColor"]
    row.en_size = settings["enSize"]
    row.en_color = settings["enColor"]
    row.gap = settings["gap"]
    row.offset = settings["offset"]
    row.updated_at = datetime.utcnow()

    db.session.commit()
    return _build_user_subtitle_settings_payload(resource, user, row=row)
