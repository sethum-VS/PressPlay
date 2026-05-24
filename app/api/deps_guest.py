"""Guest session dependencies."""

from __future__ import annotations

import uuid

from fastapi import Request

from app.auth.guest import GuestContext
from app.config import get_settings
from app.domain.errors import AuthError


def get_current_guest(request: Request) -> GuestContext:
    guest = getattr(request.state, "guest", None)
    if guest is None:
        if get_settings().use_database:
            raise AuthError("Guest session required.")
        # Legacy mode: synthetic guest id (not persisted)
        import uuid as _uuid
        from datetime import datetime, timedelta, timezone

        return GuestContext(
            id=_uuid.UUID(int=0),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            is_new=False,
        )
    return guest


def get_guest_id(request: Request) -> uuid.UUID:
    return get_current_guest(request).id
