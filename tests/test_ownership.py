import asyncio

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_guest_cannot_access_other_newsroom(
    guest_client: AsyncClient, second_guest_client: AsyncClient
):
    create = await guest_client.post(
        "/api/v1/jobs",
        json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "mode": "quick",
        },
    )
    job_id = create.json()["id"]

    # Wait for mock pipeline to finish (PRESSPLAY_USE_MOCK=1)
    for _ in range(60):
        poll = await guest_client.get(f"/api/v1/jobs/{job_id}")
        if poll.json().get("status") == "done":
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail("job did not complete in time")

    ok = await guest_client.get(f"/newsroom/{job_id}")
    assert ok.status_code == 200

    denied = await second_guest_client.get(f"/newsroom/{job_id}")
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_list_recent_scoped_to_guest(
    guest_client: AsyncClient, second_guest_client: AsyncClient
):
    create = await guest_client.post(
        "/api/v1/jobs",
        json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "mode": "quick",
        },
    )
    job_id = create.json()["id"]

    for _ in range(60):
        poll = await guest_client.get(f"/api/v1/jobs/{job_id}")
        if poll.json().get("status") == "done":
            break
        await asyncio.sleep(0.2)

    home_a = await guest_client.get("/")
    assert f"/newsroom/{job_id}" in home_a.text

    home_b = await second_guest_client.get("/")
    assert f"/newsroom/{job_id}" not in home_b.text
