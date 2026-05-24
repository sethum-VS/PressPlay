import time
import uuid
from collections import defaultdict, deque

from fastapi import Header, Request

from app.config import Settings, get_settings
from app.domain.errors import AuthError, ConcurrentJobsError, RateLimitError


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class RateLimiter:
    def __init__(self, limit_per_hour: int) -> None:
        self.limit_per_hour = limit_per_hour
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.time()
        window_start = now - 3600
        hits = self._hits[key]
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= self.limit_per_hour:
            raise RateLimitError("Rate limit exceeded (~5 jobs per hour). Try again later.")
        hits.append(now)


_rate_limiter: RateLimiter | None = None


def get_rate_limiter(settings: Settings | None = None) -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        s = settings or get_settings()
        _rate_limiter = RateLimiter(s.rate_limit_per_hour)
    return _rate_limiter


async def check_rate_limit(request: Request, settings: Settings | None = None) -> None:
    """Apply DB or in-memory rate limiting."""
    s = settings or get_settings()
    ip = get_client_ip(request)
    guest_id = None
    guest = getattr(request.state, "guest", None)
    if guest is not None:
        guest_id = guest.id

    if s.use_database:
        from app.services.rate_limit_db import get_db_rate_limiter

        await get_db_rate_limiter(s).check(guest_id, ip)
    else:
        key = f"{guest_id or 'anon'}:{ip}"
        get_rate_limiter(s).check(key)


async def get_active_job_count() -> int:
    from app.repositories.factory import get_job_store

    store = get_job_store()
    if hasattr(store, "active_count_async"):
        return await store.active_count_async()
    return store.active_count()


def verify_demo_secret(
    secret: str | None,
    header_secret: str | None = Header(default=None, alias="X-PressPlay-Secret"),
    settings: Settings | None = None,
) -> None:
    s = settings or get_settings()
    expected = s.pressplay_demo_secret
    if not expected:
        return
    provided = secret or header_secret
    if provided != expected:
        raise AuthError("Invalid or missing demo secret.")


async def check_concurrent_cap(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    active = await get_active_job_count()
    if active >= s.max_concurrent_jobs:
        raise ConcurrentJobsError(
            f"Server is busy ({s.max_concurrent_jobs} jobs running). Please try again shortly."
        )
