"""Pytest fixtures — requires Postgres (see docker compose db service)."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://pressplay:pressplay@localhost:5432/pressplay",
)
os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-pytest-only")
os.environ.setdefault("PRESSPLAY_USE_MOCK", "1")
os.environ.setdefault("MOCK_LLM", "true")

from app.config import get_settings
from app.db.session import close_db, get_session_factory, reset_db_for_tests
from app.main import create_app
from app.repositories.factory import reset_repositories


@pytest_asyncio.fixture
async def app():
    get_settings.cache_clear()
    reset_repositories()
    reset_db_for_tests(get_settings())
    application = create_app()
    async with application.router.lifespan_context(application):
        async with get_session_factory()() as session:
            await session.execute(
                text(
                    "TRUNCATE rate_limit_events, press_kits, jobs, guest_sessions "
                    "RESTART IDENTITY CASCADE"
                )
            )
            await session.commit()
        yield application
    await close_db()
    reset_repositories()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def guest_client(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert client.cookies.get("pressplay_session")
    return client


@pytest_asyncio.fixture
async def second_guest_client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/")
        yield ac
