"""Guest session context and signed cookie tokens."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings, get_settings

COOKIE_NAME = "pressplay_session"
HEADER_NAME = "X-PressPlay-Session"


@dataclass(frozen=True)
class GuestContext:
    id: uuid.UUID
    expires_at: datetime
    is_new: bool = False
    session_token: str | None = None


def _serializer(settings: Settings | None = None) -> URLSafeTimedSerializer:
    s = settings or get_settings()
    secret = s.session_secret.strip() or "dev-insecure-change-me"
    return URLSafeTimedSerializer(secret, salt="pressplay-guest")


def max_age_seconds(settings: Settings | None = None) -> int:
    s = settings or get_settings()
    return s.guest_session_ttl_days * 86400


def sign_guest_id(guest_id: uuid.UUID, settings: Settings | None = None) -> str:
    return _serializer(settings).dumps({"guest_id": str(guest_id)})


def unsign_guest_token(token: str, settings: Settings | None = None) -> uuid.UUID | None:
    try:
        data = _serializer(settings).loads(token, max_age=max_age_seconds(settings))
        return uuid.UUID(data["guest_id"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def parse_guest_id_from_request(
    cookie_value: str | None,
    header_value: str | None,
    settings: Settings | None = None,
) -> uuid.UUID | None:
    if header_value:
        gid = unsign_guest_token(header_value.strip(), settings)
        if gid:
            return gid
    if cookie_value:
        return unsign_guest_token(cookie_value, settings)
    return None
