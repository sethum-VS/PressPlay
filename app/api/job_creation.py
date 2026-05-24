"""Shared job creation logic for HTMX and JSON API."""

from __future__ import annotations

import uuid

from app.api.deps import check_concurrent_cap, check_rate_limit
from app.config import Settings
from app.domain.errors import ValidationError
from app.domain.models import BrandVertical, JobRecord, ProcessingMode
from app.repositories.factory import get_job_store
from app.services.pipeline import schedule_pipeline
from app.services.youtube import YouTubeService


def parse_brand_vertical(vertical: str | BrandVertical | None) -> BrandVertical:
    if vertical is None:
        return BrandVertical.EVENTS
    if isinstance(vertical, BrandVertical):
        return vertical
    key = vertical.lower().strip()
    try:
        return BrandVertical(key)
    except ValueError:
        raise ValidationError(
            "vertical must be 'sports', 'events', 'corp', or 'technical'."
        )


async def create_pressplay_job(
    *,
    youtube_url: str,
    mode: ProcessingMode,
    quick_minutes: int | None,
    settings: Settings,
    guest_session_id: uuid.UUID,
    webhook_url: str | None = None,
    vertical: BrandVertical = BrandVertical.EVENTS,
) -> JobRecord:
    yt = YouTubeService(settings)
    url = yt.validate_url(youtube_url)
    qm: int | None = None
    if mode == ProcessingMode.QUICK:
        qm = quick_minutes or settings.quick_minutes_default
        qm = yt.enforce_quick_window(
            qm, settings.quick_minutes_min, settings.quick_minutes_max
        )

    store = get_job_store()
    job = await store.create(
        guest_session_id,
        url,
        mode,
        qm,
        webhook_url=webhook_url,
        vertical=vertical,
    )
    schedule_pipeline(job.id)
    return job


def parse_processing_mode(mode: str) -> ProcessingMode:
    proc_mode = ProcessingMode(mode.lower())
    if proc_mode not in (ProcessingMode.QUICK, ProcessingMode.FULL):
        raise ValidationError("Mode must be 'quick' or 'full'.")
    return proc_mode
