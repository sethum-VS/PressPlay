"""Async wrappers around filesystem ResultsRepository (legacy fallback)."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.domain.models import (
    EditorReport,
    GraphData,
    Manifest,
    PressKitResult,
    StrategistOutput,
    WorkflowStatus,
)
from app.services.results_repo import ResultsRepository


class AsyncFsResultsRepository:
    def __init__(self, repo: ResultsRepository | None = None) -> None:
        self._repo = repo or ResultsRepository()

    async def save(
        self,
        result: PressKitResult,
        *,
        guest_session_id: uuid.UUID,
        pipeline_mock: bool = False,
        llm_mock: bool = False,
        ingest_duration_sec: float | None = None,
        gemini_model: str | None = None,
        graph_source: str | None = None,
        unified_context: str | None = None,
        strategist_brief: StrategistOutput | None = None,
        editor_report: EditorReport | None = None,
        vertical: str | None = None,
    ) -> Path:
        del guest_session_id  # no ownership on filesystem
        return self._repo.save(
            result,
            pipeline_mock=pipeline_mock,
            llm_mock=llm_mock,
            ingest_duration_sec=ingest_duration_sec,
            gemini_model=gemini_model,
            graph_source=graph_source,
            unified_context=unified_context,
            strategist_brief=strategist_brief,
            editor_report=editor_report,
            vertical=vertical,
        )

    async def load(self, job_id: str) -> PressKitResult:
        return self._repo.load(job_id)

    async def load_for_guest(self, job_id: str, guest_session_id: uuid.UUID) -> PressKitResult:
        del guest_session_id
        return self._repo.load(job_id)

    async def load_manifest(self, job_id: str) -> Manifest:
        return self._repo.load_manifest(job_id)

    async def load_manifest_for_guest(
        self, job_id: str, guest_session_id: uuid.UUID
    ) -> Manifest:
        del guest_session_id
        return self._repo.load_manifest(job_id)

    async def update_workflow_status(self, job_id: str, status: WorkflowStatus) -> Manifest:
        return self._repo.update_workflow_status(job_id, status)

    async def save_blog(self, job_id: str, blog_post: str) -> None:
        self._repo.save_blog(job_id, blog_post)

    async def save_tweets(self, job_id: str, tweets: list[str]) -> None:
        self._repo.save_tweets(job_id, tweets)

    async def save_graph(
        self, job_id: str, graph: GraphData, graph_source: str | None = None
    ) -> None:
        del graph_source
        self._repo.save_graph(job_id, graph)

    async def load_summary(self, job_id: str) -> str:
        return self._repo.load_summary(job_id)

    async def list_recent(self, guest_session_id: uuid.UUID, limit: int = 20) -> list[Manifest]:
        del guest_session_id
        return self._repo.list_recent(limit=limit)
