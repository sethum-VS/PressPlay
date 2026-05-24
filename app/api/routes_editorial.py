from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps_guest import get_guest_id
from app.domain.errors import PressPlayError, ResultsNotFoundError
from app.domain.models import RegeneratePart, WorkflowStatus
from app.repositories.factory import get_results_repo
from app.services.regen import get_regen_service

router = APIRouter(tags=["editorial"])


def _templates(request: Request):
    from fastapi.templating import Jinja2Templates

    return Jinja2Templates(directory=str(request.app.state.templates_dir))


async def _require_kit(job_id: str, request: Request) -> None:
    repo = get_results_repo()
    await repo.load_for_guest(job_id, get_guest_id(request))


@router.post("/newsroom/{job_id}/save", response_class=HTMLResponse)
async def save_newsroom_edits(
    request: Request,
    job_id: str,
    blog_post: str = Form(...),
    tweet_1: str = Form(...),
    tweet_2: str = Form(...),
    tweet_3: str = Form(...),
):
    repo = get_results_repo()
    try:
        await _require_kit(job_id, request)
        await repo.save_blog(job_id, blog_post)
        await repo.save_tweets(job_id, [tweet_1, tweet_2, tweet_3])
    except ResultsNotFoundError:
        return _templates(request).TemplateResponse(
            request,
            "partials/job_error.html",
            {"message": "Press kit not found."},
            status_code=404,
        )
    return RedirectResponse(url=f"/newsroom/{job_id}", status_code=303)


@router.post("/newsroom/{job_id}/workflow", response_class=HTMLResponse)
async def update_workflow(
    request: Request,
    job_id: str,
    workflow_status: str = Form(...),
):
    repo = get_results_repo()
    try:
        await _require_kit(job_id, request)
        status = WorkflowStatus(workflow_status)
        await repo.update_workflow_status(job_id, status)
    except (ResultsNotFoundError, ValueError) as exc:
        return _templates(request).TemplateResponse(
            request,
            "partials/job_error.html",
            {"message": str(exc)},
            status_code=400,
        )
    return RedirectResponse(url=f"/newsroom/{job_id}", status_code=303)


@router.post("/api/jobs/{job_id}/regenerate", response_class=HTMLResponse)
async def regenerate_part(
    request: Request,
    job_id: str,
    part: str = Form(...),
):
    try:
        await _require_kit(job_id, request)
        regen_part = RegeneratePart(part.lower())
        await get_regen_service().regenerate(job_id, regen_part)
    except (ResultsNotFoundError, PressPlayError, ValueError) as exc:
        return _templates(request).TemplateResponse(
            request,
            "partials/job_error.html",
            {"message": str(exc)},
            status_code=400,
        )
    return RedirectResponse(url=f"/newsroom/{job_id}", status_code=303)
