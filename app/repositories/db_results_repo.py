"""Postgres-backed press kit repository."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.domain.errors import ResultsNotFoundError
from app.domain.models import (
    Claim,
    EditorReport,
    GraphData,
    Manifest,
    PressKitResult,
    ProcessingMode,
    StrategistOutput,
    WorkflowStatus,
)
from app.db.models import PressKitRow
from app.db.session import get_session_factory


def _row_to_result(row: PressKitRow) -> PressKitResult:
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return PressKitResult(
        id=str(row.id),
        youtube_url=row.youtube_url,
        mode=ProcessingMode(row.mode),
        title=row.title,
        blog_post=row.blog_post,
        tweets=list(row.tweets or []),
        graph=GraphData.model_validate(row.graph or {"nodes": [], "edges": []}),
        watcher_summary=row.watcher_summary or "",
        claims=[Claim.model_validate(c) for c in (row.claims or [])],
        workflow_status=WorkflowStatus(row.workflow_status),
        created_at=created,
    )


def _row_to_manifest(row: PressKitRow) -> Manifest:
    return Manifest(
        id=str(row.id),
        youtube_url=row.youtube_url,
        mode=row.mode,
        title=row.title,
        created_at=row.created_at.isoformat(),
        status="done",
        workflow_status=row.workflow_status,
        pipeline_mock=row.pipeline_mock,
        llm_mock=row.llm_mock,
        ingest_duration_sec=row.ingest_duration_sec,
        gemini_model=row.gemini_model,
        graph_source=row.graph_source,  # type: ignore[arg-type]
        vertical=row.vertical,
    )


class DbResultsRepository:
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
    ) -> None:
        now = datetime.now(timezone.utc)
        kit_id = uuid.UUID(result.id)
        async with get_session_factory()() as session:
            existing = await session.get(PressKitRow, kit_id)
            if existing:
                existing.title = result.title
                existing.blog_post = result.blog_post
                existing.tweets = result.tweets
                existing.graph = result.graph.model_dump()
                existing.claims = [c.model_dump() for c in result.claims]
                existing.watcher_summary = result.watcher_summary
                existing.workflow_status = result.workflow_status.value
                existing.pipeline_mock = pipeline_mock
                existing.llm_mock = llm_mock
                existing.ingest_duration_sec = ingest_duration_sec
                existing.gemini_model = gemini_model
                existing.graph_source = graph_source
                existing.vertical = vertical
                existing.unified_context = unified_context
                existing.strategist_brief = (
                    strategist_brief.model_dump() if strategist_brief else None
                )
                existing.editor_report = (
                    editor_report.model_dump() if editor_report else None
                )
                existing.updated_at = now
            else:
                row = PressKitRow(
                    id=kit_id,
                    guest_session_id=guest_session_id,
                    youtube_url=result.youtube_url,
                    mode=result.mode.value,
                    title=result.title,
                    workflow_status=result.workflow_status.value,
                    blog_post=result.blog_post,
                    tweets=result.tweets,
                    graph=result.graph.model_dump(),
                    claims=[c.model_dump() for c in result.claims],
                    watcher_summary=result.watcher_summary,
                    pipeline_mock=pipeline_mock,
                    llm_mock=llm_mock,
                    ingest_duration_sec=ingest_duration_sec,
                    gemini_model=gemini_model,
                    graph_source=graph_source,
                    vertical=vertical,
                    unified_context=unified_context,
                    strategist_brief=(
                        strategist_brief.model_dump() if strategist_brief else None
                    ),
                    editor_report=(
                        editor_report.model_dump() if editor_report else None
                    ),
                    created_at=result.created_at if result.created_at.tzinfo else now,
                    updated_at=now,
                )
                session.add(row)
            await session.commit()

    async def _get_row(self, job_id: str, guest_session_id: uuid.UUID | None = None) -> PressKitRow:
        async with get_session_factory()() as session:
            q = select(PressKitRow).where(PressKitRow.id == uuid.UUID(job_id))
            if guest_session_id is not None:
                q = q.where(PressKitRow.guest_session_id == guest_session_id)
            result = await session.execute(q)
            row = result.scalar_one_or_none()
        if not row:
            raise ResultsNotFoundError(f"Press kit {job_id} not found.")
        return row

    async def load(self, job_id: str) -> PressKitResult:
        row = await self._get_row(job_id)
        return _row_to_result(row)

    async def load_for_guest(self, job_id: str, guest_session_id: uuid.UUID) -> PressKitResult:
        row = await self._get_row(job_id, guest_session_id)
        return _row_to_result(row)

    async def load_manifest(self, job_id: str) -> Manifest:
        row = await self._get_row(job_id)
        return _row_to_manifest(row)

    async def load_manifest_for_guest(
        self, job_id: str, guest_session_id: uuid.UUID
    ) -> Manifest:
        row = await self._get_row(job_id, guest_session_id)
        return _row_to_manifest(row)

    async def update_workflow_status(self, job_id: str, status: WorkflowStatus) -> Manifest:
        async with get_session_factory()() as session:
            await session.execute(
                update(PressKitRow)
                .where(PressKitRow.id == uuid.UUID(job_id))
                .values(
                    workflow_status=status.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        return await self.load_manifest(job_id)

    async def save_blog(self, job_id: str, blog_post: str) -> None:
        async with get_session_factory()() as session:
            await session.execute(
                update(PressKitRow)
                .where(PressKitRow.id == uuid.UUID(job_id))
                .values(blog_post=blog_post, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()

    async def save_tweets(self, job_id: str, tweets: list[str]) -> None:
        async with get_session_factory()() as session:
            await session.execute(
                update(PressKitRow)
                .where(PressKitRow.id == uuid.UUID(job_id))
                .values(tweets=tweets, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()

    async def save_graph(
        self, job_id: str, graph: GraphData, graph_source: str | None = None
    ) -> None:
        values: dict = {
            "graph": graph.model_dump(),
            "updated_at": datetime.now(timezone.utc),
        }
        if graph_source is not None:
            values["graph_source"] = graph_source
        async with get_session_factory()() as session:
            await session.execute(
                update(PressKitRow).where(PressKitRow.id == uuid.UUID(job_id)).values(**values)
            )
            await session.commit()

    async def load_summary(self, job_id: str) -> str:
        row = await self._get_row(job_id)
        if not row.watcher_summary:
            raise ResultsNotFoundError(f"Summary for {job_id} not found.")
        return row.watcher_summary

    async def list_recent(
        self, guest_session_id: uuid.UUID, limit: int = 20
    ) -> list[Manifest]:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(PressKitRow)
                .where(PressKitRow.guest_session_id == guest_session_id)
                .order_by(PressKitRow.created_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
        return [_row_to_manifest(r) for r in rows]
