import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_liveness(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_ready(client: AsyncClient):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"] == "ok"
