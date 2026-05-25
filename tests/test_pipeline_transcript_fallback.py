"""Pipeline transcript-only ingest when download fails."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.domain.errors import DownloadError
from app.domain.models import JobStatus, ProcessingMode
from app.services.pipeline import PipelineRunner


@pytest.mark.asyncio
async def test_pipeline_uses_transcript_fallback_when_download_fails() -> None:
    settings = Settings(youtube_download_provider="auto", ingest_transcript_fallback="1")
    runner = PipelineRunner()
    runner.settings = settings
    runner.youtube = MagicMock()
    runner.memvid = MagicMock()
    runner.job_store = AsyncMock()
    runner.watcher = AsyncMock()
    runner.strategist = AsyncMock()
    runner.writer = AsyncMock()
    runner.editor = MagicMock()
    runner.graphify = AsyncMock()
    runner.results_repo = AsyncMock()

    job = MagicMock()
    job.id = "job-transcript-fb"
    job.youtube_url = "https://www.youtube.com/watch?v=d6dp_dwgpYQ"
    job.mode = ProcessingMode.QUICK
    job.quick_minutes = 10
    job.vertical = MagicMock()
    job.vertical.value = "general"
    job.guest_session_id = "00000000-0000-4000-8000-000000000001"
    job.webhook_url = None
    runner.job_store.get.return_value = job

    runner.youtube.download = AsyncMock(
        side_effect=DownloadError("YouTube blocked automated download")
    )
    runner.youtube.fetch_transcript_unified_context = MagicMock(
        return_value="## Transcript (YouTube — transcript-only ingest)\nHello"
    )
    runner.watcher.run.return_value = MagicMock(summary="s", claims=[])
    runner.strategist.run.return_value = MagicMock()
    runner.writer.run.return_value = MagicMock(blog_post="# Title\n\nBody", tweets=[])
    runner.editor.lint.return_value = MagicMock()
    runner.graphify.build_graph_with_source.return_value = ({}, "heuristic")

    with patch("app.services.pipeline.get_settings", return_value=settings):
        with patch("app.services.pipeline.pipeline_skips_ingest", return_value=False):
            await runner.run("job-transcript-fb")

    runner.youtube.fetch_transcript_unified_context.assert_called_once()
    runner.memvid.extract_context.assert_not_called()
    statuses = [c.args[1] for c in runner.job_store.update_status.call_args_list]
    assert JobStatus.MEMVID in statuses
    assert JobStatus.WATCHING in statuses
