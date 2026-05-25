"""Tests for OSS YouTube transcript fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.domain.errors import DownloadError
from app.services.youtube import YouTubeService
from app.services.youtube_transcript import (
    extract_youtube_video_id,
    fetch_via_youtube_transcript_api,
)


def test_extract_youtube_video_id_watch_url() -> None:
    assert (
        extract_youtube_video_id("https://www.youtube.com/watch?v=d6dp_dwgpYQ&t=12s")
        == "d6dp_dwgpYQ"
    )


def test_fetch_via_youtube_transcript_api_formats_text() -> None:
    fetched = MagicMock()
    fetched.snippets = [
        MagicMock(text="Hello"),
        MagicMock(text="world"),
    ]

    with patch("youtube_transcript_api.YouTubeTranscriptApi") as api_cls:
        api_cls.return_value.fetch.return_value = fetched
        text = fetch_via_youtube_transcript_api("abc12345678")

    assert "Hello" in text
    assert "world" in text


def test_fetch_transcript_unified_context_uses_api_then_captions() -> None:
    service = YouTubeService()
    with (
        patch(
            "app.services.youtube.fetch_via_youtube_transcript_api",
            return_value="",
        ),
        patch.object(service, "fetch_caption_text", return_value="Caption line"),
    ):
        unified = service.fetch_transcript_unified_context(
            "https://www.youtube.com/watch?v=abc12345678"
        )

    assert "transcript-only ingest" in unified.lower()
    assert "Caption line" in unified


def test_fetch_transcript_unified_context_raises_when_empty() -> None:
    service = YouTubeService()
    with (
        patch(
            "app.services.youtube.fetch_via_youtube_transcript_api",
            return_value="",
        ),
        patch.object(service, "fetch_caption_text", return_value=""),
    ):
        try:
            service.fetch_transcript_unified_context(
                "https://www.youtube.com/watch?v=abc12345678"
            )
        except DownloadError as exc:
            assert "youtube transcript" in str(exc).lower()
        else:
            raise AssertionError("expected DownloadError")


def test_ingest_transcript_fallback_enabled_for_auto() -> None:
    assert Settings(youtube_download_provider="auto").ingest_transcript_fallback_enabled


def test_ingest_transcript_fallback_explicit_flag() -> None:
    assert Settings(
        youtube_download_provider="ytdlp",
        ingest_transcript_fallback="1",
    ).ingest_transcript_fallback_enabled
