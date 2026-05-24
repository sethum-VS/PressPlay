from app.adapters.gemini import GeminiAdapter, get_gemini_adapter
from app.domain.models import Claim, StrategistOutput

STRATEGIST_SYSTEM = """You are an editorial strategist for a press kit pipeline.

Given a factual video summary and optional timestamped claims, define how the copy team should frame the story:
- angle: the single narrative lens (one sentence)
- target_audience: who this kit is for (one sentence)
- thread_hook: opening line or theme for the 3-part Twitter thread
- omit_topics: topics or angles to avoid (speculation, off-topic tangents, sensitive areas)

Stay grounded in the summary and claims. Do not invent facts."""


class StrategistAgent:
    """Editorial brief between Watcher facts and Writer copy."""

    def __init__(self, gemini: GeminiAdapter | None = None) -> None:
        self.gemini = gemini or get_gemini_adapter()

    async def run(
        self,
        watcher_summary: str,
        claims: list[Claim] | None = None,
        *,
        vertical: str | None = None,
    ) -> StrategistOutput:
        claims_block = ""
        if claims:
            lines = [f"- {c.text}" for c in claims[:30]]
            claims_block = "\n\nClaims:\n" + "\n".join(lines)

        vertical_block = ""
        if vertical:
            vertical_block = f"\n\nVertical / beat: {vertical}"

        prompt = (
            "Create an editorial strategy brief for this event."
            f"{vertical_block}{claims_block}\n\nSummary:\n{watcher_summary}"
        )
        return await self.gemini.generate_structured(
            prompt=prompt,
            schema=StrategistOutput,
            system=STRATEGIST_SYSTEM,
        )
