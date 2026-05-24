from app.adapters.gemini import GeminiAdapter, get_gemini_adapter
from app.domain.models import BrandVertical, Claim, StrategistOutput, WriterOutput
from app.services.brand import brand_prompt_suffix

WRITER_SYSTEM = """You are an expert digital marketer and storyteller.

Given a factual chronological summary and optional numbered claims from a video event, write:
1. A polished Markdown blog post with a compelling # title, body paragraphs, and optional blockquote.
2. Exactly three tweets forming a cohesive Twitter thread (each under 280 characters, numbered 1/3, 2/3, 3/3).

Only state facts that appear in the summary or claims list. Do not invent details.
Optionally set claim_refs to a list of 0-based claim indices that support key blog statements."""


class WriterAgent:
    """Blog post + 3-part Twitter thread from watcher output via Gemini."""

    def __init__(self, gemini: GeminiAdapter | None = None) -> None:
        self.gemini = gemini or get_gemini_adapter()

    async def run(
        self,
        watcher_summary: str,
        claims: list[Claim] | None = None,
        *,
        strategy: StrategistOutput | None = None,
        vertical: BrandVertical | None = None,
    ) -> WriterOutput:
        claims_block = ""
        if claims:
            lines = [f"[{i}] {c.text}" for i, c in enumerate(claims)]
            claims_block = "\n\nNumbered claims (cite via claim_refs only):\n" + "\n".join(lines)

        strategy_block = ""
        if strategy:
            omit = ", ".join(strategy.omit_topics) if strategy.omit_topics else "none"
            strategy_block = (
                "\n\nEditorial brief:\n"
                f"- Angle: {strategy.angle}\n"
                f"- Audience: {strategy.target_audience}\n"
                f"- Thread hook: {strategy.thread_hook}\n"
                f"- Omit: {omit}"
            )

        prompt = (
            "Write a press kit from this event summary."
            f"{strategy_block}{claims_block}\n\nSummary:\n{watcher_summary}"
        )
        system = WRITER_SYSTEM + brand_prompt_suffix(vertical)
        return await self.gemini.generate_structured(
            prompt=prompt,
            schema=WriterOutput,
            system=system,
        )
