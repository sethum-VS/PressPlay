import pytest
from httpx import AsyncClient

from app.api.job_ids import parse_job_id
from app.domain.errors import JobNotFoundError


def test_parse_job_id_invalid():
    with pytest.raises(JobNotFoundError):
        parse_job_id("not-a-uuid")


@pytest.mark.asyncio
async def test_poll_invalid_job_id_returns_404_not_500(guest_client: AsyncClient):
    resp = await guest_client.get("/api/v1/jobs/not-a-uuid")
    assert resp.status_code == 404
    assert "error" in resp.json()
