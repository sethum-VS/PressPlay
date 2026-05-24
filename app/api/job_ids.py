"""Parse job IDs from URL path segments."""

from __future__ import annotations

import uuid

from app.domain.errors import JobNotFoundError


def parse_job_id(job_id: str) -> uuid.UUID:
    """Return job UUID or raise JobNotFoundError (malformed IDs → 404)."""
    try:
        return uuid.UUID(job_id)
    except ValueError:
        raise JobNotFoundError(f"Job {job_id} not found.") from None
