import logging

from app.adapters.gemini import GeminiAdapter, get_gemini_adapter
from app.domain.models import Claim, ClaimSource, WatcherOutput

logger = logging.getLogger(__name__)

WATCHER_SYSTEM = """You are a meticulous investigative journalist analyzing video event footage.

Given transcript and visual context from a video, produce:
1. A chronological, factual summary (clear paragraphs ordered by time).
2. A list of atomic claims — each a single observable fact supported by the input.

For each claim include:
- text: the factual statement
- start_sec and end_sec: seconds into the video when supported (use timeline timestamps when present)
- source: "transcript" for speech/dialogue, "visual" for on-screen action or visuals

Stick to observable facts. Do not speculate. If timing is unknown, omit start_sec/end_sec.
No markdown headings in the summary.

You MUST return at least 3 atomic claims in the claims array when the input contains any factual events."""

WATCHER_RETRY_SUFFIX = (
    "\n\nIMPORTANT: Your previous response had an empty claims array. "
    "Return the same summary (or an improved one) AND at least 3 atomic claims "
    "with text, source (transcript or visual), and start_sec/end_sec when timestamps exist."
)


def _coerce_claim_source(value: object) -> ClaimSource:
    if isinstance(value, ClaimSource):
        return value
    raw = str(value or "").strip().lower()
    if raw in ("visual", "video", "on-screen", "on_screen"):
        return ClaimSource.VISUAL
    return ClaimSource.TRANSCRIPT


def _normalize_claims(raw_claims: list[Claim]) -> list[Claim]:
    """Drop empty claim rows; coerce source enum for Vertex JSON quirks."""
    normalized: list[Claim] = []
    for claim in raw_claims:
        text = (claim.text or "").strip()
        if not text:
            continue
        normalized.append(
            claim.model_copy(
                update={
                    "text": text,
                    "source": _coerce_claim_source(claim.source),
                }
            )
        )
    return normalized


class WatcherAgent:
    """Chronological factual summary + timestamped claims from Memvid unified context."""

    def __init__(self, gemini: GeminiAdapter | None = None) -> None:
        self.gemini = gemini or get_gemini_adapter()

    async def run(
        self, unified_context: str, *, youtube_url: str | None = None
    ) -> WatcherOutput:
        prompt = (
            "Analyze the following video context. Return summary and claims.\n\n"
            f"{unified_context}"
        )
        out = await self.gemini.generate_structured(
            prompt=prompt,
            schema=WatcherOutput,
            system=WATCHER_SYSTEM,
        )
        out = WatcherOutput(
            summary=out.summary,
            claims=_normalize_claims(out.claims),
        )

        if not out.claims and out.summary.strip():
            logger.warning("Watcher returned no claims; retrying with stricter prompt")
            retry = await self.gemini.generate_structured(
                prompt=prompt + WATCHER_RETRY_SUFFIX,
                schema=WatcherOutput,
                system=WATCHER_SYSTEM,
            )
            retry_claims = _normalize_claims(retry.claims)
            if retry_claims:
                out = WatcherOutput(
                    summary=retry.summary or out.summary,
                    claims=retry_claims,
                )
            else:
                logger.warning(
                    "Watcher retry still produced no claims (summary len=%d)",
                    len(out.summary),
                )

        if youtube_url:
            for claim in out.claims:
                if claim.youtube_url is None:
                    claim.youtube_url = youtube_url
        return out
