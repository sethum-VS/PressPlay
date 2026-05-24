"""Resolve or create guest session on each request."""

from __future__ import annotations

import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth.guest import (
    COOKIE_NAME,
    HEADER_NAME,
    GuestContext,
    parse_guest_id_from_request,
    sign_guest_id,
)
from app.config import get_settings
from app.services.guest_sessions import (
    create_guest_session,
    get_guest_session,
    is_session_expired,
    touch_guest_session,
)

logger = logging.getLogger(__name__)

SKIP_PREFIXES = ("/health", "/static", "/favicon.ico")


class GuestSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        path = request.url.path

        if not settings.use_database or any(path.startswith(p) for p in SKIP_PREFIXES):
            request.state.guest = None
            request.state.session_token = None
            return await call_next(request)

        cookie_val = request.cookies.get(COOKIE_NAME)
        header_val = request.headers.get(HEADER_NAME)
        guest_id = parse_guest_id_from_request(cookie_val, header_val, settings)

        is_new = False
        row = None
        if guest_id is not None:
            row = await get_guest_session(guest_id)
            if row is not None and not is_session_expired(row):
                row = await touch_guest_session(guest_id)

        if row is None:
            row = await create_guest_session(settings)
            is_new = True
            guest_id = row.id

        token = sign_guest_id(guest_id, settings)
        request.state.guest = GuestContext(
            id=guest_id,
            expires_at=row.expires_at,
            is_new=is_new,
            session_token=token,
        )
        request.state.session_token = token

        response = await call_next(request)

        if is_new or not cookie_val:
            response.set_cookie(
                key=COOKIE_NAME,
                value=token,
                max_age=settings.guest_session_ttl_days * 86400,
                httponly=True,
                secure=settings.session_cookie_secure,
                samesite="lax",
                path="/",
            )

        return response
