from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.api.deps import check_concurrent_cap, check_rate_limit, get_client_ip, verify_demo_secret
from app.api.job_ids import parse_job_id
from app.services.abuse_guard import check_honeypot
from app.api.deps_guest import get_guest_id
from app.api.job_creation import (
    create_pressplay_job,
    parse_brand_vertical,
    parse_processing_mode,
)
from app.config import get_settings
from app.domain.errors import (
    JobNotFoundError,
    PressPlayError,
    RateLimitError,
)
from app.domain.models import JobStatus
from app.repositories.factory import get_job_store

router = APIRouter(prefix="/api", tags=["jobs"])


def _templates(request: Request):
    from fastapi.templating import Jinja2Templates

    return Jinja2Templates(directory=str(request.app.state.templates_dir))


@router.post("/jobs", response_class=HTMLResponse)
async def create_job(
    request: Request,
    youtube_url: str = Form(...),
    mode: str = Form("quick"),
    quick_minutes: int | None = Form(None),
    vertical: str = Form("events"),
    secret: str | None = Form(None),
    website: str | None = Form(None),
):
    settings = get_settings()

    try:
        check_honeypot(website)
        verify_demo_secret(secret)
        await check_rate_limit(request, settings)
        await check_concurrent_cap(settings)

        proc_mode = parse_processing_mode(mode)
        brand_vertical = parse_brand_vertical(vertical)
        job = await create_pressplay_job(
            youtube_url=youtube_url,
            mode=proc_mode,
            quick_minutes=quick_minutes,
            settings=settings,
            guest_session_id=get_guest_id(request),
            vertical=brand_vertical,
            client_ip=get_client_ip(request),
        )

        return _templates(request).TemplateResponse(
            request,
            "partials/job_progress.html",
            {"job": job},
        )
    except PressPlayError as exc:
        return _templates(request).TemplateResponse(
            request,
            "partials/job_error.html",
            {"message": str(exc)},
            status_code=400 if not isinstance(exc, RateLimitError) else 429,
        )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def poll_job(request: Request, job_id: str):
    store = get_job_store()
    guest_id = get_guest_id(request)
    try:
        parse_job_id(job_id)
        job = await store.get_for_guest(job_id, guest_id)
    except JobNotFoundError:
        return _templates(request).TemplateResponse(
            request,
            "partials/job_error.html",
            {"message": "Job not found."},
            status_code=404,
        )

    if job.status == JobStatus.DONE:
        return _templates(request).TemplateResponse(
            request,
            "partials/job_progress.html",
            {"job": job, "done": True},
        )
    if job.status == JobStatus.FAILED:
        return _templates(request).TemplateResponse(
            request,
            "partials/job_error.html",
            {"message": job.error or "Job failed."},
            status_code=200,
        )

    return _templates(request).TemplateResponse(
        request,
        "partials/job_progress.html",
        {"job": job},
    )
