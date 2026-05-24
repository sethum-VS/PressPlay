"""Job-creation abuse controls (rate limits, cooldowns, honeypot)."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import Settings, get_settings
from app.db.models import RateLimitEventRow
from app.db.session import get_session_factory
from app.domain.errors import RateLimitError, ValidationError


def check_honeypot(honeypot: str | None) -> None:
    """Reject bots that fill a hidden form field."""
    if honeypot and honeypot.strip():
        raise ValidationError("Invalid submission.")


class InMemoryAbuseGuard:
    def __init__(self, settings: Settings) -> None:
        self._per_guest_ip = settings.rate_limit_per_hour
        self._per_ip = settings.rate_limit_per_ip_per_hour
        self._min_interval = settings.rate_limit_min_interval_seconds
        self._guest_ip_hits: dict[str, deque[float]] = defaultdict(deque)
        self._ip_hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_submit: dict[str, float] = {}

    def check(self, guest_session_id: uuid.UUID | None, client_ip: str) -> None:
        now = time.time()
        window_start = now - 3600
        ip = client_ip[:64]

        last = self._last_submit.get(ip)
        if last is not None and now - last < self._min_interval:
            raise RateLimitError(
                "Please wait a few minutes before starting another job."
            )

        ip_hits = self._ip_hits[ip]
        while ip_hits and ip_hits[0] < window_start:
            ip_hits.popleft()
        if len(ip_hits) >= self._per_ip:
            raise RateLimitError(
                "Rate limit exceeded for this network. Try again later."
            )

        guest_key = f"{guest_session_id or 'anon'}:{ip}"
        guest_hits = self._guest_ip_hits[guest_key]
        while guest_hits and guest_hits[0] < window_start:
            guest_hits.popleft()
        if len(guest_hits) >= self._per_guest_ip:
            raise RateLimitError(
                "Rate limit exceeded. Try again in about an hour."
            )

        ip_hits.append(now)
        guest_hits.append(now)
        self._last_submit[ip] = now


_memory_guard: InMemoryAbuseGuard | None = None


def get_memory_abuse_guard(settings: Settings | None = None) -> InMemoryAbuseGuard:
    global _memory_guard
    if _memory_guard is None:
        _memory_guard = InMemoryAbuseGuard(settings or get_settings())
    return _memory_guard


class DbAbuseGuard:
    def __init__(self, settings: Settings) -> None:
        self._per_guest_ip = settings.rate_limit_per_hour
        self._per_ip = settings.rate_limit_per_ip_per_hour
        self._min_interval = settings.rate_limit_min_interval_seconds

    async def check(self, guest_session_id: uuid.UUID | None, client_ip: str) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=1)
        ip = client_ip[:64]

        async with get_session_factory()() as session:
            await session.execute(
                delete(RateLimitEventRow).where(RateLimitEventRow.created_at < window_start)
            )

            last_q = await session.execute(
                select(RateLimitEventRow.created_at)
                .where(RateLimitEventRow.client_ip == ip)
                .order_by(RateLimitEventRow.created_at.desc())
                .limit(1)
            )
            last_at = last_q.scalar_one_or_none()
            if last_at is not None:
                elapsed = (now - last_at).total_seconds()
                if elapsed < self._min_interval:
                    raise RateLimitError(
                        "Please wait a few minutes before starting another job."
                    )

            ip_count_q = await session.execute(
                select(func.count())
                .select_from(RateLimitEventRow)
                .where(
                    RateLimitEventRow.client_ip == ip,
                    RateLimitEventRow.created_at >= window_start,
                )
            )
            if int(ip_count_q.scalar_one()) >= self._per_ip:
                raise RateLimitError(
                    "Rate limit exceeded for this network. Try again later."
                )

            guest_q = (
                select(func.count())
                .select_from(RateLimitEventRow)
                .where(
                    RateLimitEventRow.client_ip == ip,
                    RateLimitEventRow.created_at >= window_start,
                )
            )
            if guest_session_id is not None:
                guest_q = guest_q.where(
                    RateLimitEventRow.guest_session_id == guest_session_id
                )
            guest_count = await session.execute(guest_q)
            if int(guest_count.scalar_one()) >= self._per_guest_ip:
                raise RateLimitError(
                    "Rate limit exceeded. Try again in about an hour."
                )

            session.add(
                RateLimitEventRow(
                    guest_session_id=guest_session_id,
                    client_ip=ip,
                )
            )
            await session.commit()


_db_guard: DbAbuseGuard | None = None


def get_db_abuse_guard(settings: Settings | None = None) -> DbAbuseGuard:
    global _db_guard
    if _db_guard is None:
        _db_guard = DbAbuseGuard(settings or get_settings())
    return _db_guard


async def enforce_job_creation_limits(
    guest_session_id: uuid.UUID | None,
    client_ip: str,
    settings: Settings | None = None,
) -> None:
    s = settings or get_settings()
    if s.use_database:
        await get_db_abuse_guard(s).check(guest_session_id, client_ip)
    else:
        get_memory_abuse_guard(s).check(guest_session_id, client_ip)
