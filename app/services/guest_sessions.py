"""Guest session persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import GuestSessionRow
from app.db.session import get_session_factory


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_guest_session(settings: Settings | None = None) -> GuestSessionRow:
    s = settings or get_settings()
    now = _utcnow()
    expires = now + timedelta(days=s.guest_session_ttl_days)
    row = GuestSessionRow(id=uuid.uuid4(), created_at=now, expires_at=expires, last_seen_at=now)
    async with get_session_factory()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def get_guest_session(guest_id: uuid.UUID) -> GuestSessionRow | None:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(GuestSessionRow).where(GuestSessionRow.id == guest_id)
        )
        return result.scalar_one_or_none()


async def touch_guest_session(guest_id: uuid.UUID) -> GuestSessionRow | None:
    now = _utcnow()
    async with get_session_factory()() as session:
        await session.execute(
            update(GuestSessionRow)
            .where(GuestSessionRow.id == guest_id)
            .values(last_seen_at=now)
        )
        await session.commit()
        result = await session.execute(
            select(GuestSessionRow).where(GuestSessionRow.id == guest_id)
        )
        return result.scalar_one_or_none()


def is_session_expired(row: GuestSessionRow) -> bool:
    now = _utcnow()
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return now >= exp
