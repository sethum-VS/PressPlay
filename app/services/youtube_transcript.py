"""OSS YouTube transcript fetch (no local video) for ingest fallback."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_VIDEO_ID_PATTERNS = (
    re.compile(r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/|/live/)([\w-]{11})", re.I),
    re.compile(r"^[\w-]{11}$"),
)

_PREFERRED_LANGS = ("en", "en-US", "en-GB", "en-CA", "en-AU")


def extract_youtube_video_id(url: str) -> str | None:
    url = url.strip()
    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def fetch_via_youtube_transcript_api(video_id: str, *, max_chars: int = 120_000) -> str:
    """Fetch captions via youtube-transcript-api (no yt-dlp / no video file)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError(
            "youtube-transcript-api is not installed (pip install youtube-transcript-api)."
        ) from exc

    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=_PREFERRED_LANGS)
    except Exception as exc:
        logger.warning("youtube-transcript-api fetch failed for %s: %s", video_id, exc)
        return ""

    lines: list[str] = []
    snippets = getattr(fetched, "snippets", None) or []
    for snippet in snippets:
        text = getattr(snippet, "text", None)
        if text is None and isinstance(snippet, dict):
            text = snippet.get("text")
        if text:
            lines.append(str(text).strip())
    if not lines and hasattr(fetched, "to_raw_data"):
        for segment in fetched.to_raw_data():
            if isinstance(segment, dict) and segment.get("text"):
                lines.append(str(segment["text"]).strip())

    body = "\n".join(lines).strip()
    return body[:max_chars] if body else ""
