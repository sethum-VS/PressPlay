#!/usr/bin/env python3
"""Optional one-shot: import filesystem press kits into Postgres (legacy guest)."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.db.models import GuestSessionRow, PressKitRow
from app.db.session import get_session_factory, init_db
from app.domain.models import Claim, GraphData, Manifest, ProcessingMode, WorkflowStatus


async def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate data/results/* to Postgres")
    parser.add_argument("--results-dir", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.use_database:
        raise SystemExit("DATABASE_URL must be set")

    await init_db()
    base = args.results_dir or settings.results_path

    async with get_session_factory()() as session:
        legacy = GuestSessionRow(
            id=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        session.add(legacy)
        await session.flush()

        count = 0
        for job_dir in sorted(base.iterdir()):
            if not job_dir.is_dir():
                continue
            manifest_path = job_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = Manifest.model_validate_json(manifest_path.read_text())
            blog = (job_dir / "blog.md").read_text(encoding="utf-8")
            tweets = json.loads((job_dir / "tweets.json").read_text())
            graph = GraphData.model_validate_json((job_dir / "graph.json").read_text())
            claims_path = job_dir / "claims.json"
            claims = []
            if claims_path.exists():
                claims = [Claim.model_validate(c) for c in json.loads(claims_path.read_text())]
            summary = ""
            if (job_dir / "summary.txt").exists():
                summary = (job_dir / "summary.txt").read_text(encoding="utf-8")

            row = PressKitRow(
                id=uuid.UUID(manifest.id),
                guest_session_id=legacy.id,
                youtube_url=manifest.youtube_url,
                mode=manifest.mode,
                title=manifest.title,
                workflow_status=manifest.workflow_status,
                blog_post=blog,
                tweets=tweets,
                graph=graph.model_dump(),
                claims=[c.model_dump() for c in claims],
                watcher_summary=summary,
                pipeline_mock=manifest.pipeline_mock,
                llm_mock=manifest.llm_mock,
                ingest_duration_sec=manifest.ingest_duration_sec,
                gemini_model=manifest.gemini_model,
                graph_source=manifest.graph_source,
                vertical=manifest.vertical,
                created_at=datetime.fromisoformat(manifest.created_at),
                updated_at=datetime.now(timezone.utc),
            )
            session.merge(row)
            count += 1

        await session.commit()
    print(f"Migrated {count} press kit(s) to guest {legacy.id}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
