import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.api import routes_jobs, routes_pages
from app.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.jobs_path.mkdir(parents=True, exist_ok=True)
    settings.results_path.mkdir(parents=True, exist_ok=True)
    logger.info("PressPlay started — data dir: %s", settings.data_path)
    logger.info(
        "Gemini auth mode: %s (model=%s, project=%s)",
        settings.gcp_credentials_mode,
        settings.gemini_model,
        settings.effective_gcp_project or "(unset — MOCK_LLM)",
    )
    for warning in settings.gcp_credential_warnings():
        logger.warning(warning)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PressPlay — The Multimodal Newsroom",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.templates_dir = ROOT / "app" / "templates"

    static_dir = ROOT / "app" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(routes_pages.router)
    app.include_router(routes_jobs.router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "pressplay"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            '<rect width="32" height="32" rx="6" fill="#a83300"/>'
            '<path fill="#fff" d="M12 10h8v2h-3v10h-2V12h-3z"/>'
            "</svg>"
        )
        return Response(content=svg, media_type="image/svg+xml")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "app.main:app",
        host=s.host,
        port=s.port,
        reload=s.debug,
    )
