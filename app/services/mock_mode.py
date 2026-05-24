"""Central mock vs live detection for ingest and LLM.

Modes (see README / .env.example):

- **Default demo (no GCP):** ``should_mock_llm()`` true → real yt-dlp + Memvid, mock
  Watcher/Writer, heuristic Graphify.
- **``MOCK_LLM=true``:** same as default demo — real ingest, stub LLM agents.
- **``PRESSPLAY_USE_MOCK=1``:** full fast mock — skip ingest, stub Memvid, mock LLM,
  heuristic graph (quick UI demos only).
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.config import get_settings


def _pressplay_use_mock_raw() -> str:
    raw = os.environ.get("PRESSPLAY_USE_MOCK", "").strip().lower()
    if raw:
        return raw
    return (get_settings().pressplay_use_mock or "").strip().lower()


def _pressplay_mock_override() -> bool | None:
    raw = _pressplay_use_mock_raw()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


@lru_cache
def pipeline_skips_ingest() -> bool:
    """Skip yt-dlp/Memvid only when ``PRESSPLAY_USE_MOCK=1`` (full fast mock)."""
    override = _pressplay_mock_override()
    if override is not None:
        return override
    return False


def pipeline_uses_mock() -> bool:
    """Full pipeline mock (skips ingest). Alias for :func:`pipeline_skips_ingest`."""
    return pipeline_skips_ingest()


def should_mock_llm() -> bool:
    """Stub Watcher/Writer via GeminiAdapter when ``MOCK_LLM`` or GCP project unset."""
    return get_settings().should_mock_llm()


def graphify_llm_available() -> bool:
    keys = (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    )
    if any(os.environ.get(k, "").strip() for k in keys):
        return True
    settings = get_settings()
    return bool(settings.effective_gcp_project) and not settings.should_mock_llm()


def graphify_uses_heuristic() -> bool:
    """Use heuristic/stub graph instead of Graphify CLI (full mock, mock LLM, or no keys)."""
    if pipeline_skips_ingest() or should_mock_llm():
        return True
    return not graphify_llm_available()


def pipeline_label() -> str:
    if pipeline_skips_ingest():
        return "Demo pipeline (full mock)"
    if should_mock_llm():
        return "Demo pipeline (mock LLM, real ingest)"
    return "Live pipeline"


def manifest_pipeline_label(*, pipeline_mock: bool, llm_mock: bool) -> str:
    """Label for a saved press kit from manifest flags."""
    if pipeline_mock:
        return "Demo pipeline (full mock)"
    if llm_mock:
        return "Demo pipeline (mock LLM, real ingest)"
    return "Live pipeline"
