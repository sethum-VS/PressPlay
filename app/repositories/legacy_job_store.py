"""Adapter: in-memory JobStore with guest_id ignored (filesystem fallback)."""

from __future__ import annotations

import uuid

from app.domain.models import BrandVertical, JobRecord, JobStatus, ProcessingMode
from app.services.job_store import JobStore, get_job_store as _get_mem_store


class LegacyJobStoreAdapter:
    def __init__(self) -> None:
        self._store = _get_mem_store()

    async def create(
        self,
        guest_session_id: uuid.UUID,
        youtube_url: str,
        mode: ProcessingMode,
        quick_minutes: int | None = None,
        webhook_url: str | None = None,
        vertical: BrandVertical = BrandVertical.EVENTS,
    ) -> JobRecord:
        del guest_session_id
        return await self._store.create(
            youtube_url, mode, quick_minutes, webhook_url=webhook_url, vertical=vertical
        )

    async def get(self, job_id: str) -> JobRecord:
        return await self._store.get(job_id)

    async def get_for_guest(self, job_id: str, guest_session_id: uuid.UUID) -> JobRecord:
        del guest_session_id
        return await self._store.get(job_id)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        result_url: str | None = None,
        message: str | None = None,
    ) -> JobRecord:
        return await self._store.update_status(
            job_id, status, error=error, result_url=result_url, message=message
        )

    async def update_message(self, job_id: str, message: str) -> JobRecord:
        return await self._store.update_message(job_id, message)

    def active_count(self) -> int:
        return self._store.active_count()

    async def active_count_async(self) -> int:
        return self._store.active_count()
