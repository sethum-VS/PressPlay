import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from app.config import get_settings
from app.domain.models import JobStatus, PressKitResult, WorkflowStatus
from app.repositories.factory import get_job_store, get_results_repo
from app.services.agents.editor import EditorLinter
from app.services.agents.strategist import StrategistAgent
from app.services.agents.watcher import WatcherAgent
from app.services.agents.writer import WriterAgent
from app.services.graphify import GraphifyService
from app.services.memvid import MemvidService
from app.services.mock_mode import pipeline_skips_ingest, should_mock_llm
from app.services.webhooks import schedule_webhook
from app.services.youtube import YouTubeService

logger = logging.getLogger(__name__)

STUB_STAGE_DELAY_SEC = 0.35


class PipelineRunner:
    def __init__(self) -> None:
        self.job_store = get_job_store()
        self.results_repo = get_results_repo()
        self.youtube = YouTubeService()
        self.memvid = MemvidService()
        self.watcher = WatcherAgent()
        self.strategist = StrategistAgent()
        self.writer = WriterAgent()
        self.editor = EditorLinter()
        self.graphify = GraphifyService()
        self.settings = get_settings()

    async def _stage(self, job_id: str, status: JobStatus) -> None:
        await self.job_store.update_status(job_id, status)
        if pipeline_skips_ingest():
            await asyncio.sleep(STUB_STAGE_DELAY_SEC)

    def _guest_uuid(self, job) -> uuid.UUID:
        if job.guest_session_id:
            return uuid.UUID(job.guest_session_id)
        raise RuntimeError(f"Job {job.id} missing guest_session_id")

    async def run(self, job_id: str) -> None:
        job = await self.job_store.get(job_id)
        ingest_started = time.monotonic()
        graph_source = "stub" if pipeline_skips_ingest() else "heuristic"

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

            ingest_duration_sec = time.monotonic() - ingest_started

            await self._stage(job_id, JobStatus.WATCHING)
            watcher_out = await self.watcher.run(
                unified, youtube_url=job.youtube_url
            )

            await self._stage(job_id, JobStatus.STRATEGIZING)
            strategy_out = await self.strategist.run(
                watcher_out.summary,
                claims=watcher_out.claims,
            )

            await self._stage(job_id, JobStatus.WRITING)
            writer_out = await self.writer.run(
                watcher_out.summary,
                claims=watcher_out.claims,
                strategy=strategy_out,
                vertical=job.vertical,
            )

            await self._stage(job_id, JobStatus.EDITING)
            editor_report = self.editor.lint(writer_out)

            await self._stage(job_id, JobStatus.MAPPING)
            graph, graph_source = await self.graphify.build_graph_with_source(
                writer_out.blog_post
            )

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
                watcher_summary=watcher_out.summary,
                claims=watcher_out.claims,
                workflow_status=WorkflowStatus.DRAFT,
                created_at=datetime.now(timezone.utc),
            )
            if not watcher_out.claims:
                logger.warning(
                    "Job %s completed with no Watcher claims — citations will be empty",
                    job_id,
                )
            else:
                logger.info(
                    "Job %s persisting %d claim(s) for audit",
                    job_id,
                    len(watcher_out.claims),
                )

            await self.results_repo.save(
                result,
                guest_session_id=self._guest_uuid(job),
                pipeline_mock=pipeline_skips_ingest(),
                llm_mock=should_mock_llm(),
                ingest_duration_sec=round(ingest_duration_sec, 2),
                gemini_model=self.settings.gemini_model,
                graph_source=graph_source,
                unified_context=unified,
                strategist_brief=strategy_out,
                editor_report=editor_report,
                vertical=job.vertical.value,
            )

            result_url = f"/newsroom/{job_id}"
            await self.job_store.update_status(
                job_id,
                JobStatus.DONE,
                result_url=result_url,
            )
            schedule_webhook(
                job.webhook_url,
                job_id=job_id,
                status=JobStatus.DONE.value,
                result_url=result_url,
                youtube_url=job.youtube_url,
            )
        except Exception as exc:
            logger.exception("Pipeline failed for job %s", job_id)
            await self.job_store.update_status(
                job_id, JobStatus.FAILED, error=str(exc)
            )
            schedule_webhook(
                job.webhook_url,
                job_id=job_id,
                status=JobStatus.FAILED.value,
                result_url=None,
                youtube_url=job.youtube_url,
            )


_running_tasks: set[asyncio.Task] = set()


def schedule_pipeline(job_id: str) -> None:
    runner = PipelineRunner()
    task = asyncio.create_task(runner.run(job_id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
