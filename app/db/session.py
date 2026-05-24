"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured.")
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def init_db() -> None:
    """Initialize engine (tables via Alembic)."""
    get_engine()


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def check_db_connection() -> bool:
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def wait_for_db_connection(
    *,
    max_attempts: int = 30,
    delay_sec: float = 2.0,
) -> bool:
    """Retry until Postgres is reachable (Cloud SQL cold start)."""
    for attempt in range(1, max_attempts + 1):
        if await check_db_connection():
            if attempt > 1:
                logger.info("Postgres connected on attempt %s", attempt)
            return True
        if attempt < max_attempts:
            logger.warning(
                "Postgres not ready (attempt %s/%s), retrying in %ss",
                attempt,
                max_attempts,
                delay_sec,
            )
            await asyncio.sleep(delay_sec)
    return False


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


def reset_db_for_tests(settings: Settings | None = None) -> None:
    """Clear cached engine (tests only)."""
    global _engine, _session_factory
    from app.config import get_settings

    get_settings.cache_clear()
    _engine = None
    _session_factory = None
    if settings and settings.database_url:
        _engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
