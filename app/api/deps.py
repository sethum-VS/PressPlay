from fastapi import Header, Request

from app.config import Settings, get_settings
from app.domain.errors import AuthError, ConcurrentJobsError
from app.services.abuse_guard import enforce_job_creation_limits


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def check_rate_limit(request: Request, settings: Settings | None = None) -> None:
    """Per-guest+IP hourly cap, per-IP hourly cap, and minimum spacing between jobs."""
    s = settings or get_settings()
    ip = get_client_ip(request)
    guest_id = None
    guest = getattr(request.state, "guest", None)
    if guest is not None:
        guest_id = guest.id

    await enforce_job_creation_limits(guest_id, ip, s)


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
