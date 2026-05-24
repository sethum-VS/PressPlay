"""Partial regeneration without re-ingesting video."""

from __future__ import annotations

from app.domain.models import BrandVertical, PressKitResult, RegeneratePart
from app.repositories.factory import get_results_repo
from app.services.agents.writer import WriterAgent
from app.services.graphify import GraphifyService


class RegenService:
    def __init__(self) -> None:
        self.repo = get_results_repo()
        self.writer = WriterAgent()
        self.graphify = GraphifyService()

    async def regenerate(self, job_id: str, part: RegeneratePart) -> PressKitResult:
        result = await self.repo.load(job_id)
        summary = result.watcher_summary or await self.repo.load_summary(job_id)
        manifest = await self.repo.load_manifest(job_id)
        vertical: BrandVertical | None = None
        if manifest.vertical:
            try:
                vertical = BrandVertical(manifest.vertical)
            except ValueError:
                vertical = None

        if part == RegeneratePart.TWEETS:
            writer_out = await self.writer.run(
                summary,
                claims=result.claims,
                vertical=vertical,
            )
            await self.repo.save_tweets(job_id, writer_out.tweets)
        elif part == RegeneratePart.BLOG:
            writer_out = await self.writer.run(
                summary,
                claims=result.claims,
                vertical=vertical,
            )
            await self.repo.save_blog(job_id, writer_out.blog_post)

        if part == RegeneratePart.GRAPH:
            graph, graph_source = await self.graphify.build_graph_with_source(
                result.blog_post
            )
            await self.repo.save_graph(job_id, graph, graph_source=graph_source)

        return await self.repo.load(job_id)


_regen: RegenService | None = None


def get_regen_service() -> RegenService:
    global _regen
    if _regen is None:
        _regen = RegenService()
    return _regen
