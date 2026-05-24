import json

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps_guest import get_current_guest
from app.config import get_settings
from app.domain.errors import ResultsNotFoundError
from app.repositories.factory import get_results_repo
from app.services.mock_mode import manifest_pipeline_label, pipeline_label

router = APIRouter(tags=["pages"])


def _templates(request: Request) -> Jinja2Templates:
    return Jinja2Templates(directory=str(request.app.state.templates_dir))


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(request: Request):
    settings = request.app.state.settings
    if request.method == "HEAD":
        return HTMLResponse(status_code=200)
    repo = get_results_repo()
    guest = get_current_guest(request)
    past_runs = await repo.list_recent(guest.id)
    guest_expires = guest.expires_at.strftime("%Y-%m-%d") if settings.use_database else None
    return _templates(request).TemplateResponse(
        request,
        "index.html",
        {
            "past_runs": past_runs,
            "quick_minutes_default": settings.quick_minutes_default,
            "quick_minutes_min": settings.quick_minutes_min,
            "quick_minutes_max": settings.quick_minutes_max,
            "demo_secret_required": bool(settings.pressplay_demo_secret),
            "guest_expires": guest_expires,
            "guest_session_days": settings.guest_session_ttl_days,
        },
    )


@router.get("/newsroom/{job_id}", response_class=HTMLResponse)
async def newsroom(request: Request, job_id: str):
    repo = get_results_repo()
    guest = get_current_guest(request)
    try:
        result = await repo.load_for_guest(job_id, guest.id)
    except ResultsNotFoundError:
        return _templates(request).TemplateResponse(
            request,
            "error.html",
            {"message": "Press kit not found."},
            status_code=404,
        )

    blog_html = markdown.markdown(
        result.blog_post,
        extensions=["fenced_code", "tables", "nl2br"],
    )
    graph_json = json.dumps(result.graph.model_dump())
    pipeline_tag = pipeline_label()
    try:
        m = await repo.load_manifest_for_guest(job_id, guest.id)
        pipeline_tag = manifest_pipeline_label(
            pipeline_mock=m.pipeline_mock,
            llm_mock=m.llm_mock,
        )
    except ResultsNotFoundError:
        pass

    def claim_jump_url(claim) -> str | None:
        url = claim.youtube_url or result.youtube_url
        if claim.start_sec is None or not url:
            return None
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}t={int(claim.start_sec)}s"

    return _templates(request).TemplateResponse(
        request,
        "newsroom.html",
        {
            "result": result,
            "blog_html": blog_html,
            "graph_json": graph_json,
            "pipeline_label": pipeline_tag,
            "claim_jump_url": claim_jump_url,
            "workflow_statuses": ["draft", "in_review", "approved", "published"],
        },
    )
