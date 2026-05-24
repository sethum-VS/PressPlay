"""Database startup tasks."""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import get_session_factory

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (
    "queued",
    "downloading",
    "memvid",
    "watching",
    "strategizing",
    "writing",
    "editing",
    "mapping",
)


async def sweep_stale_jobs() -> int:
    """Mark in-flight jobs as failed after server restart."""
    sql = text(
        """
        UPDATE jobs
        SET status = 'failed',
            stage = 'failed',
            progress_pct = 0,
            error = 'Interrupted by server restart',
            updated_at = NOW()
        WHERE status = ANY(:statuses)
        """
    )
    async with get_session_factory()() as session:
        result = await session.execute(sql, {"statuses": list(ACTIVE_STATUSES)})
        await session.commit()
        count = result.rowcount or 0
    if count:
        logger.info("Marked %s stale job(s) as failed after restart", count)
    return count
