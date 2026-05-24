"""Initial schema: guest_sessions, jobs, press_kits, rate_limit_events.

Revision ID: 001
Revises:
Create Date: 2026-05-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guest_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress_pct", sa.Integer(), nullable=False),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("youtube_url", sa.Text(), nullable=False),
        sa.Column("quick_minutes", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_url", sa.Text(), nullable=True),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("vertical", sa.String(length=16), nullable=False, server_default="events"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guest_session_id"], ["guest_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_guest_created", "jobs", ["guest_session_id", "created_at"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "press_kits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("youtube_url", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("workflow_status", sa.String(length=32), nullable=False),
        sa.Column("blog_post", sa.Text(), nullable=False),
        sa.Column("tweets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("claims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("watcher_summary", sa.Text(), nullable=False),
        sa.Column("pipeline_mock", sa.Boolean(), nullable=False),
        sa.Column("llm_mock", sa.Boolean(), nullable=False),
        sa.Column("ingest_duration_sec", sa.Float(), nullable=True),
        sa.Column("gemini_model", sa.String(length=128), nullable=True),
        sa.Column("graph_source", sa.String(length=32), nullable=True),
        sa.Column("vertical", sa.String(length=16), nullable=True),
        sa.Column("unified_context", sa.Text(), nullable=True),
        sa.Column("strategist_brief", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("editor_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guest_session_id"], ["guest_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_press_kits_guest_created", "press_kits", ["guest_session_id", "created_at"]
    )
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guest_session_id"], ["guest_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rate_limit_guest_ip_created",
        "rate_limit_events",
        ["guest_session_id", "client_ip", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_guest_ip_created", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
    op.drop_index("ix_press_kits_guest_created", table_name="press_kits")
    op.drop_table("press_kits")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_guest_created", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("guest_sessions")
