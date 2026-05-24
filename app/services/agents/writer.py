from app.adapters.gemini import GeminiAdapter, get_gemini_adapter
from app.domain.models import WriterOutput

WRITER_SYSTEM = """You are an expert digital marketer and storyteller.

Given a factual chronological summary of a video event, write:
1. A polished Markdown blog post with a compelling # title, body paragraphs, and optional blockquote.
2. Exactly three tweets forming a cohesive Twitter thread (each under 280 characters, numbered 1/3, 2/3, 3/3)."""


class WriterAgent:
    """Blog post + 3-part Twitter thread from watcher summary via Gemini."""

    def __init__(self, gemini: GeminiAdapter | None = None) -> None:
        self.gemini = gemini or get_gemini_adapter()

    async def run(self, watcher_summary: str) -> WriterOutput:
        prompt = (
            "Write a press kit from this event summary.\n\n"
            f"{watcher_summary}"
        )
        return await self.gemini.generate_structured(
            prompt=prompt,
            schema=WriterOutput,
            system=WRITER_SYSTEM,
        )
