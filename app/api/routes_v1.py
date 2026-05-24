from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.deps import check_concurrent_cap, check_rate_limit, verify_demo_secret
from app.api.deps_guest import get_guest_id
from app.api.job_creation import (
    create_pressplay_job,
    parse_brand_vertical,
    parse_processing_mode,
)
from app.config import get_settings
from app.domain.errors import (
    AuthError,
    JobNotFoundError,
    PressPlayError,
    RateLimitError,
    ResultsNotFoundError,
)
from app.domain.models import JobCreateResponse, JobCreateV1, JobStatus
from app.repositories.factory import get_job_store, get_results_repo
from app.services.export import export_json_payload, export_markdown, export_slack_blocks

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.post("/jobs", response_model=JobCreateResponse)
async def create_job_v1(
    request: Request,
    body: JobCreateV1,
    x_pressplay_secret: str | None = Header(default=None, alias="X-PressPlay-Secret"),
):
    settings = get_settings()

    try:
        verify_demo_secret(body.secret, x_pressplay_secret, settings)
        await check_rate_limit(request, settings)
        await check_concurrent_cap(settings)
        mode = parse_processing_mode(body.mode.value)
        brand_vertical = parse_brand_vertical(body.vertical)
        job = await create_pressplay_job(
            youtube_url=body.youtube_url,
            mode=mode,
            quick_minutes=body.quick_minutes,
            settings=settings,
            guest_session_id=get_guest_id(request),
            webhook_url=body.webhook_url,
            vertical=brand_vertical,
        )
        session_token = getattr(request.state, "session_token", None)
        response = JobCreateResponse(
            id=job.id,
            status=job.status.value,
            poll_url=f"/api/v1/jobs/{job.id}",
            session_token=session_token,
        )
        return response
    except RateLimitError as exc:
        return JSONResponse({"error": str(exc)}, status_code=429)
    except AuthError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)
    except PressPlayError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/jobs/{job_id}")
async def poll_job_v1(request: Request, job_id: str):
    store = get_job_store()
    guest_id = get_guest_id(request)
    try:
        job = await store.get_for_guest(job_id, guest_id)
    except JobNotFoundError:
        return JSONResponse({"error": "Job not found."}, status_code=404)

    payload = job.to_poll_json()
    if job.status == JobStatus.DONE and job.result_url:
        payload["newsroom_url"] = job.result_url
        payload["export_url"] = f"/api/v1/newsroom/{job_id}/export?format=json"
    return payload


@router.get("/newsroom/{job_id}/export")
async def export_newsroom(request: Request, job_id: str, format: str = Query("json", alias="format")):
    repo = get_results_repo()
    guest_id = get_guest_id(request)
    try:
        result = await repo.load_for_guest(job_id, guest_id)
    except ResultsNotFoundError:
        return JSONResponse({"error": "Press kit not found."}, status_code=404)

    fmt = format.lower()
    if fmt == "markdown":
        return PlainTextResponse(
            export_markdown(result), media_type="text/markdown; charset=utf-8"
        )
    if fmt == "slack":
        return PlainTextResponse(
            export_slack_blocks(result), media_type="application/json; charset=utf-8"
        )
    if fmt == "json":
        return JSONResponse(content=export_json_payload(result))
    return JSONResponse(
        {"error": "format must be markdown, json, or slack"},
        status_code=400,
    )
