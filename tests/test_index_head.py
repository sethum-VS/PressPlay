import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_index_head_returns_200(guest_client: AsyncClient):
    resp = await guest_client.head("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_index_uses_htmx2_and_safe_response_handling(guest_client: AsyncClient):
    resp = await guest_client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "htmx.org@2." in html
    assert "Array.isArray(defaults)" in html
    assert "error: false" in html
