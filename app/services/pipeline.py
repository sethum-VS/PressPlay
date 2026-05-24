import asyncio
import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.domain.models import JobStatus, PressKitResult
from app.services.agents.watcher import WatcherAgent
from app.services.agents.writer import WriterAgent
from app.services.graphify import GraphifyService
from app.services.job_store import JobStore, get_job_store
from app.services.memvid import MemvidService
from app.services.mock_mode import pipeline_skips_ingest, should_mock_llm
from app.services.results_repo import ResultsRepository, get_results_repo
from app.services.youtube import YouTubeService

logger = logging.getLogger(__name__)

STUB_STAGE_DELAY_SEC = 0.35


class PipelineRunner:
    def __init__(
        self,
        job_store: JobStore | None = None,
        results_repo: ResultsRepository | None = None,
    ) -> None:
        self.job_store = job_store or get_job_store()
        self.results_repo = results_repo or get_results_repo()
        self.youtube = YouTubeService()
        self.memvid = MemvidService()
        self.watcher = WatcherAgent()
        self.writer = WriterAgent()
        self.graphify = GraphifyService()
        self.settings = get_settings()

    async def _stage(self, job_id: str, status: JobStatus) -> None:
        await self.job_store.update_status(job_id, status)
        if pipeline_skips_ingest():
            await asyncio.sleep(STUB_STAGE_DELAY_SEC)

    async def run(self, job_id: str) -> None:
        job = await self.job_store.get(job_id)
        try:
            await self._stage(job_id, JobStatus.DOWNLOADING)
            if pipeline_skips_ingest():
                unified = await self.memvid.extract_context_stub(
                    job.youtube_url, job.quick_minutes
                )
            else:
                video = await self.youtube.download(
                    job.id,
                    job.youtube_url,
                    job.mode,
                    job.quick_minutes,
                )
                await self._stage(job_id, JobStatus.MEMVID)
                unified = await self.memvid.extract_context(video)

            if pipeline_skips_ingest():
                await self._stage(job_id, JobStatus.MEMVID)

            await self._stage(job_id, JobStatus.WATCHING)
            summary = await self.watcher.run(unified)

            await self._stage(job_id, JobStatus.WRITING)
            writer_out = await self.writer.run(summary)

            await self._stage(job_id, JobStatus.MAPPING)
            graph = await self.graphify.build_graph(writer_out.blog_post)

            title_line = writer_out.blog_post.strip().split("\n", 1)[0]
            title = title_line.lstrip("# ").strip() or "Press Kit"

            result = PressKitResult(
                id=job_id,
                youtube_url=job.youtube_url,
                mode=job.mode,
                title=title,
                blog_post=writer_out.blog_post,
                tweets=writer_out.tweets,
                graph=graph,
                watcher_summary=summary,
                created_at=datetime.now(timezone.utc),
            )
            self.results_repo.save(
                result,
                pipeline_mock=pipeline_skips_ingest(),
                llm_mock=should_mock_llm(),
            )

            await self.job_store.update_status(
                job_id,
                JobStatus.DONE,
                result_url=f"/newsroom/{job_id}",
            )
        except Exception as exc:
            logger.exception("Pipeline failed for job %s", job_id)
            await self.job_store.update_status(
                job_id, JobStatus.FAILED, error=str(exc)
            )


_running_tasks: set[asyncio.Task] = set()


def schedule_pipeline(job_id: str) -> None:
    runner = PipelineRunner()
    task = asyncio.create_task(runner.run(job_id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
