import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_guest_cookie_set_on_first_visit(guest_client: AsyncClient):
    resp = await guest_client.get("/")
    assert resp.status_code == 200
    cookie = guest_client.cookies.get("pressplay_session")
    assert cookie is not None


@pytest.mark.asyncio
async def test_guest_cookie_reused(guest_client: AsyncClient):
    first = guest_client.cookies.get("pressplay_session")
    await guest_client.get("/")
    second = guest_client.cookies.get("pressplay_session")
    assert first == second


@pytest.mark.asyncio
async def test_v1_job_returns_session_token(guest_client: AsyncClient):
    resp = await guest_client.post(
        "/api/v1/jobs",
        json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "mode": "quick",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data.get("session_token")
