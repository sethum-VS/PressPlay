"""Database-backed rate limiting."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import Settings, get_settings
from app.db.models import RateLimitEventRow
from app.db.session import get_session_factory
from app.domain.errors import RateLimitError


class DbRateLimiter:
    def __init__(self, limit_per_hour: int) -> None:
        self.limit_per_hour = limit_per_hour

    async def check(self, guest_session_id: uuid.UUID | None, client_ip: str) -> None:
        window_start = datetime.now(timezone.utc) - timedelta(hours=1)
        async with get_session_factory()() as session:
            await session.execute(
                delete(RateLimitEventRow).where(RateLimitEventRow.created_at < window_start)
            )
            q = select(func.count()).select_from(RateLimitEventRow).where(
                RateLimitEventRow.client_ip == client_ip,
                RateLimitEventRow.created_at >= window_start,
            )
            if guest_session_id is not None:
                q = q.where(RateLimitEventRow.guest_session_id == guest_session_id)
            result = await session.execute(q)
            count = int(result.scalar_one())
            if count >= self.limit_per_hour:
                raise RateLimitError("Rate limit exceeded (~5 jobs per hour). Try again later.")
            session.add(
                RateLimitEventRow(
                    guest_session_id=guest_session_id,
                    client_ip=client_ip[:64],
                )
            )
            await session.commit()


_rate_limiter: DbRateLimiter | None = None


def get_db_rate_limiter(settings: Settings | None = None) -> DbRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        s = settings or get_settings()
        _rate_limiter = DbRateLimiter(s.rate_limit_per_hour)
    return _rate_limiter
