"""Repository protocols for jobs and press kits."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

from app.domain.models import (
    GraphData,
    JobRecord,
    JobStatus,
    Manifest,
    PressKitResult,
    ProcessingMode,
    WorkflowStatus,
)


class JobStoreProtocol(Protocol):
    async def create(
        self,
        guest_session_id: uuid.UUID,
        youtube_url: str,
        mode: ProcessingMode,
        quick_minutes: int | None = None,
        webhook_url: str | None = None,
    ) -> JobRecord: ...

    async def get(self, job_id: str) -> JobRecord: ...

    async def get_for_guest(self, job_id: str, guest_session_id: uuid.UUID) -> JobRecord: ...

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        result_url: str | None = None,
        message: str | None = None,
    ) -> JobRecord: ...

    async def update_message(self, job_id: str, message: str) -> JobRecord: ...

    def active_count(self) -> int: ...

    async def active_count_async(self) -> int: ...


class ResultsRepoProtocol(Protocol):
    def save(
        self,
        result: PressKitResult,
        *,
        guest_session_id: uuid.UUID,
        pipeline_mock: bool = False,
        llm_mock: bool = False,
        ingest_duration_sec: float | None = None,
        gemini_model: str | None = None,
        graph_source: str | None = None,
    ) -> Path | None: ...

    def load(self, job_id: str) -> PressKitResult: ...

    def load_for_guest(self, job_id: str, guest_session_id: uuid.UUID) -> PressKitResult: ...

    def load_manifest(self, job_id: str) -> Manifest: ...

    def load_manifest_for_guest(self, job_id: str, guest_session_id: uuid.UUID) -> Manifest: ...

    def update_workflow_status(self, job_id: str, status: WorkflowStatus) -> Manifest: ...

    def save_blog(self, job_id: str, blog_post: str) -> None: ...

    def save_tweets(self, job_id: str, tweets: list[str]) -> None: ...

    def save_graph(self, job_id: str, graph: GraphData) -> None: ...

    def load_summary(self, job_id: str) -> str: ...

    def list_recent(self, guest_session_id: uuid.UUID, limit: int = 20) -> list[Manifest]: ...
