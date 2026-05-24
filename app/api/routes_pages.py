import json

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.domain.errors import ResultsNotFoundError
from app.services.mock_mode import manifest_pipeline_label, pipeline_label
from app.services.results_repo import get_results_repo

router = APIRouter(tags=["pages"])


def _templates(request: Request) -> Jinja2Templates:
    return Jinja2Templates(directory=str(request.app.state.templates_dir))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = request.app.state.settings
    past_runs = get_results_repo().list_recent()
    return _templates(request).TemplateResponse(
        request,
        "index.html",
        {
            "past_runs": past_runs,
            "quick_minutes_default": settings.quick_minutes_default,
            "quick_minutes_min": settings.quick_minutes_min,
            "quick_minutes_max": settings.quick_minutes_max,
            "demo_secret_required": bool(settings.pressplay_demo_secret),
        },
    )


@router.get("/newsroom/{job_id}", response_class=HTMLResponse)
async def newsroom(request: Request, job_id: str):
    repo = get_results_repo()
    try:
        result = repo.load(job_id)
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
        m = repo.load_manifest(job_id)
        pipeline_tag = manifest_pipeline_label(
            pipeline_mock=m.pipeline_mock,
            llm_mock=m.llm_mock,
        )
    except ResultsNotFoundError:
        pass

    return _templates(request).TemplateResponse(
        request,
        "newsroom.html",
        {
            "result": result,
            "blog_html": blog_html,
            "graph_json": graph_json,
            "pipeline_label": pipeline_tag,
        },
    )
