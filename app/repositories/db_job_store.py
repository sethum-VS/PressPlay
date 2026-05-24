"""Postgres-backed job store."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from app.domain.errors import JobNotFoundError
from app.domain.models import (
    STAGE_PROGRESS,
    BrandVertical,
    JobRecord,
    JobStatus,
    ProcessingMode,
)
from app.db.models import JobRow
from app.db.session import get_session_factory


def _row_to_record(row: JobRow) -> JobRecord:
    return JobRecord(
        id=str(row.id),
        status=JobStatus(row.status),
        stage=JobStatus(row.stage),
        progress_pct=row.progress_pct,
        progress_message=row.progress_message,
        mode=ProcessingMode(row.mode),
        youtube_url=row.youtube_url,
        quick_minutes=row.quick_minutes,
        error=row.error,
        result_url=row.result_url,
        webhook_url=row.webhook_url,
        vertical=BrandVertical(row.vertical),
        guest_session_id=str(row.guest_session_id),
        created_at=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc),
    )


class DbJobStore:
    async def create(
        self,
        guest_session_id: uuid.UUID,
        youtube_url: str,
        mode: ProcessingMode,
        quick_minutes: int | None = None,
        webhook_url: str | None = None,
        vertical: BrandVertical = BrandVertical.EVENTS,
    ) -> JobRecord:
        job_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        row = JobRow(
            id=job_id,
            guest_session_id=guest_session_id,
            status=JobStatus.QUEUED.value,
            stage=JobStatus.QUEUED.value,
            progress_pct=STAGE_PROGRESS[JobStatus.QUEUED],
            mode=mode.value,
            youtube_url=youtube_url,
            quick_minutes=quick_minutes,
            webhook_url=webhook_url,
            vertical=vertical.value,
            created_at=now,
            updated_at=now,
        )
        async with get_session_factory()() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _row_to_record(row)

    async def get(self, job_id: str) -> JobRecord:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(JobRow).where(JobRow.id == uuid.UUID(job_id))
            )
            row = result.scalar_one_or_none()
        if not row:
            raise JobNotFoundError(f"Job {job_id} not found.")
        return _row_to_record(row)

    async def get_for_guest(self, job_id: str, guest_session_id: uuid.UUID) -> JobRecord:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(JobRow).where(
                    JobRow.id == uuid.UUID(job_id),
                    JobRow.guest_session_id == guest_session_id,
                )
            )
            row = result.scalar_one_or_none()
        if not row:
            raise JobNotFoundError(f"Job {job_id} not found.")
        return _row_to_record(row)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        result_url: str | None = None,
        message: str | None = None,
    ) -> JobRecord:
        values: dict = {
            "status": status.value,
            "stage": status.value,
            "progress_pct": STAGE_PROGRESS.get(status, 0),
            "updated_at": datetime.now(timezone.utc),
        }
        if error is not None:
            values["error"] = error
        if result_url is not None:
            values["result_url"] = result_url
        if message is not None:
            values["progress_message"] = message

        async with get_session_factory()() as session:
            await session.execute(
                update(JobRow).where(JobRow.id == uuid.UUID(job_id)).values(**values)
            )
            await session.commit()
            result = await session.execute(
                select(JobRow).where(JobRow.id == uuid.UUID(job_id))
            )
            row = result.scalar_one()
        return _row_to_record(row)

    async def update_message(self, job_id: str, message: str) -> JobRecord:
        async with get_session_factory()() as session:
            await session.execute(
                update(JobRow)
                .where(JobRow.id == uuid.UUID(job_id))
                .values(
                    progress_message=message,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            result = await session.execute(
                select(JobRow).where(JobRow.id == uuid.UUID(job_id))
            )
            row = result.scalar_one()
        return _row_to_record(row)

    def active_count(self) -> int:
        raise RuntimeError("Use active_count_async with DbJobStore")

    async def active_count_async(self) -> int:
        active = [
            JobStatus.QUEUED.value,
            JobStatus.DOWNLOADING.value,
            JobStatus.MEMVID.value,
            JobStatus.WATCHING.value,
            JobStatus.STRATEGIZING.value,
            JobStatus.WRITING.value,
            JobStatus.EDITING.value,
            JobStatus.MAPPING.value,
        ]
        async with get_session_factory()() as session:
            result = await session.execute(
                select(func.count()).select_from(JobRow).where(JobRow.status.in_(active))
            )
            return int(result.scalar_one())
