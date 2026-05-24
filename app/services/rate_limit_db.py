"""Database-backed rate limiting (delegates to abuse_guard)."""

from __future__ import annotations

import uuid

from app.config import Settings, get_settings
from app.services.abuse_guard import get_db_abuse_guard


class DbRateLimiter:
    """Backward-compatible wrapper."""

    def __init__(self, limit_per_hour: int) -> None:
        self.limit_per_hour = limit_per_hour

    async def check(self, guest_session_id: uuid.UUID | None, client_ip: str) -> None:
        await get_db_abuse_guard().check(guest_session_id, client_ip)


_rate_limiter: DbRateLimiter | None = None


def get_db_rate_limiter(settings: Settings | None = None) -> DbRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        s = settings or get_settings()
        _rate_limiter = DbRateLimiter(s.rate_limit_per_hour)
    return _rate_limiter
