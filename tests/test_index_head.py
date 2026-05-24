import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_index_head_returns_200(guest_client: AsyncClient):
    resp = await guest_client.head("/")
    assert resp.status_code == 200
