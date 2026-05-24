import time
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


def check_concurrent_cap(active_count: int, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    if active_count >= s.max_concurrent_jobs:
        raise ConcurrentJobsError(
            f"Server is busy ({s.max_concurrent_jobs} jobs running). Please try again shortly."
        )
