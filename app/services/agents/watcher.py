from app.adapters.gemini import GeminiAdapter, get_gemini_adapter

WATCHER_SYSTEM = """You are a meticulous investigative journalist analyzing video event footage.

Given transcript and visual context from a video, produce a chronological, factual summary of what happened.
Stick to observable facts from the provided context. Do not speculate or invent details not supported by the input.
Use clear paragraphs ordered by time. No markdown headings required."""


class WatcherAgent:
    """Chronological factual summary from Memvid unified context via Gemini."""

    def __init__(self, gemini: GeminiAdapter | None = None) -> None:
        self.gemini = gemini or get_gemini_adapter()

    async def run(self, unified_context: str) -> str:
        prompt = (
            "Summarize the following video context chronologically and factually.\n\n"
            f"{unified_context}"
        )
        return await self.gemini.generate_text(prompt=prompt, system=WATCHER_SYSTEM)
