import asyncio
import uuid
from typing import Callable

from app.domain.errors import JobNotFoundError
from app.domain.models import (
    BrandVertical,
    JobRecord,
    JobStatus,
    ProcessingMode,
    STAGE_PROGRESS,
)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        youtube_url: str,
        mode: ProcessingMode,
        quick_minutes: int | None = None,
        webhook_url: str | None = None,
        vertical: BrandVertical = BrandVertical.EVENTS,
    ) -> JobRecord:
        job_id = str(uuid.uuid4())
        job = JobRecord(
            id=job_id,
            status=JobStatus.QUEUED,
            stage=JobStatus.QUEUED,
            progress_pct=STAGE_PROGRESS[JobStatus.QUEUED],
            mode=mode,
            youtube_url=youtube_url,
            quick_minutes=quick_minutes,
            webhook_url=webhook_url,
            vertical=vertical,
        )
        async with self._lock:
            self._jobs[job_id] = job
        return job

    async def get(self, job_id: str) -> JobRecord:
        async with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise JobNotFoundError(f"Job {job_id} not found.")
        return job

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        result_url: str | None = None,
        message: str | None = None,
    ) -> JobRecord:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job {job_id} not found.")
            job.status = status
            job.stage = status
            job.progress_pct = STAGE_PROGRESS.get(status, job.progress_pct)
            if error is not None:
                job.error = error
            if result_url is not None:
                job.result_url = result_url
            if message is not None:
                job.progress_message = message
            self._jobs[job_id] = job
            return job.model_copy(deep=True)

    async def update_message(self, job_id: str, message: str) -> JobRecord:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job {job_id} not found.")
            job.progress_message = message
            self._jobs[job_id] = job
            return job.model_copy(deep=True)

    def active_count(self) -> int:
        active = {
            JobStatus.QUEUED,
            JobStatus.DOWNLOADING,
            JobStatus.MEMVID,
            JobStatus.WATCHING,
            JobStatus.STRATEGIZING,
            JobStatus.WRITING,
            JobStatus.EDITING,
            JobStatus.MAPPING,
        }
        return sum(1 for j in self._jobs.values() if j.status in active)

    def list_all(self) -> list[JobRecord]:
        return list(self._jobs.values())


_job_store: JobStore | None = None


def get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store
