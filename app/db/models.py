"""SQLAlchemy ORM models for PressPlay MVP."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class GuestSessionRow(Base):
    __tablename__ = "guest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    jobs: Mapped[list[JobRow]] = relationship(back_populates="guest_session")
    press_kits: Mapped[list[PressKitRow]] = relationship(back_populates="guest_session")


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_guest_created", "guest_session_id", "created_at"),
        Index("ix_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guest_sessions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    youtube_url: Mapped[str] = mapped_column(Text, nullable=False)
    quick_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    vertical: Mapped[str] = mapped_column(String(16), nullable=False, default="events")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    guest_session: Mapped[GuestSessionRow] = relationship(back_populates="jobs")


class PressKitRow(Base):
    __tablename__ = "press_kits"
    __table_args__ = (Index("ix_press_kits_guest_created", "guest_session_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    guest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guest_sessions.id", ondelete="CASCADE"), nullable=False
    )
    youtube_url: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    blog_post: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tweets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    claims: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    watcher_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pipeline_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    llm_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingest_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    gemini_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    graph_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vertical: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unified_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategist_brief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    editor_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    guest_session: Mapped[GuestSessionRow] = relationship(back_populates="press_kits")


class RateLimitEventRow(Base):
    __tablename__ = "rate_limit_events"
    __table_args__ = (Index("ix_rate_limit_guest_ip_created", "guest_session_id", "client_ip", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guest_sessions.id", ondelete="SET NULL"), nullable=True
    )
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
