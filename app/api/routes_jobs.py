from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from app.api.deps import (
    check_concurrent_cap,
    get_client_ip,
    get_rate_limiter,
    verify_demo_secret,
)
from app.config import get_settings
from app.domain.errors import (
    AuthError,
    ConcurrentJobsError,
    JobNotFoundError,
    PressPlayError,
    RateLimitError,
    ValidationError,
)
from app.domain.models import JobStatus, ProcessingMode
from app.services.job_store import get_job_store
from app.services.pipeline import schedule_pipeline
from app.services.youtube import YouTubeService

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
    secret: str | None = Form(None),
):
    settings = get_settings()
    store = get_job_store()
    yt = YouTubeService()

    try:
        verify_demo_secret(secret)
        get_rate_limiter(settings).check(get_client_ip(request))
        check_concurrent_cap(store.active_count(), settings)

        url = yt.validate_url(youtube_url)
        proc_mode = ProcessingMode(mode.lower())
        if proc_mode not in (ProcessingMode.QUICK, ProcessingMode.FULL):
            raise ValidationError("Mode must be 'quick' or 'full'.")

        qm: int | None = None
        if proc_mode == ProcessingMode.QUICK:
            qm = quick_minutes or settings.quick_minutes_default
            qm = yt.enforce_quick_window(
                qm, settings.quick_minutes_min, settings.quick_minutes_max
            )

        job = await store.create(url, proc_mode, qm)
        schedule_pipeline(job.id)

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
    try:
        job = await store.get(job_id)
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
