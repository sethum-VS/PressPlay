"""Best-effort async webhook delivery on job completion."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


async def notify_job_complete(
    webhook_url: str,
    *,
    job_id: str,
    status: str,
    result_url: str | None,
    youtube_url: str,
) -> None:
    payload = {
        "id": job_id,
        "status": status,
        "result_url": result_url,
        "youtube_url": youtube_url,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Webhook %s returned %s for job %s",
                    webhook_url,
                    resp.status_code,
                    job_id,
                )
    except Exception as exc:
        logger.warning("Webhook delivery failed for job %s: %s", job_id, exc)


def schedule_webhook(
    webhook_url: str | None,
    *,
    job_id: str,
    status: str,
    result_url: str | None,
    youtube_url: str,
) -> None:
    if not webhook_url:
        return
    asyncio.create_task(
        notify_job_complete(
            webhook_url,
            job_id=job_id,
            status=status,
            result_url=result_url,
            youtube_url=youtube_url,
        )
    )
