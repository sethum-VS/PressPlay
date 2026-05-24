"""Unit tests for YouTube external download providers (mocked HTTP)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.domain.errors import DownloadError
from app.domain.models import ProcessingMode
from app.services.youtube import YouTubeService
from app.services.youtube_download.providers import (
    DownloadProvider,
    fetch_via_rapidapi,
    pick_mp4_url,
    request_rapidapi_links,
    resolve_provider_chain,
)


def test_resolve_provider_chain_auto_with_rapidapi() -> None:
    settings = Settings(
        youtube_download_provider="auto",
        rapidapi_key="test-key",
    )
    assert resolve_provider_chain(settings) == [
        DownloadProvider.YTDLP,
        DownloadProvider.RAPIDAPI,
    ]


def test_resolve_provider_chain_rapidapi_only() -> None:
    settings = Settings(youtube_download_provider="rapidapi")
    assert resolve_provider_chain(settings) == [DownloadProvider.RAPIDAPI]


def test_pick_mp4_url_prefers_720_over_360() -> None:
    payload = {
        "title": "Demo",
        "links": {
            "360": "https://cdn.example/360.mp4",
            "720": "https://cdn.example/720.mp4",
            "1080": "https://cdn.example/1080.mp4",
        },
    }
    assert pick_mp4_url(payload) == "https://cdn.example/1080.mp4"


def test_pick_mp4_url_from_list_of_formats() -> None:
    payload = [
        {"format": "360p mp4", "url": "https://cdn.example/low.mp4"},
        {"format": "720p mp4", "url": "https://cdn.example/hd.mp4"},
    ]
    assert pick_mp4_url(payload) == "https://cdn.example/hd.mp4"


def test_request_rapidapi_links_posts_form_body() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "title": "Launch",
        "720": "https://cdn.example/v.mp4",
    }

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response

    with patch("app.services.youtube_download.providers.httpx.Client", return_value=mock_client):
        data = request_rapidapi_links("https://www.youtube.com/watch?v=abc", "key")

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["data"] == {"url": "https://www.youtube.com/watch?v=abc"}
    assert call_kwargs["headers"]["X-RapidAPI-Host"] == (
        "youtube-video-downloader-fast.p.rapidapi.com"
    )
    assert data["title"] == "Launch"


def test_fetch_via_rapidapi_streams_file(tmp_path: Path) -> None:
    dest = tmp_path / "source.mp4"
    payload = {"title": "Clip", "720": "https://cdn.example/v.mp4"}

    links_response = MagicMock()
    links_response.raise_for_status = MagicMock()
    links_response.json.return_value = payload

    stream_response = MagicMock()
    stream_response.raise_for_status = MagicMock()
    stream_response.iter_bytes.return_value = [b"fake-mp4-bytes"]

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = links_response
    mock_client.stream.return_value.__enter__ = MagicMock(return_value=stream_response)
    mock_client.stream.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.services.youtube_download.providers.httpx.Client", return_value=mock_client):
        title = fetch_via_rapidapi(
            "https://www.youtube.com/watch?v=abc",
            dest,
            "key",
            max_bytes=10_000_000,
        )

    assert title == "Clip"
    assert dest.read_bytes() == b"fake-mp4-bytes"


def test_download_sync_falls_back_after_ytdlp_bot_block(tmp_path: Path) -> None:
    settings = Settings(
        youtube_download_provider="auto",
        rapidapi_key="test-key",
        data_dir=str(tmp_path),
    )
    service = YouTubeService(settings=settings)
    job_id = "job-fallback-test"

    with (
        patch.object(
            service,
            "_download_ytdlp",
            side_effect=DownloadError(
                "YouTube blocked automated download from this server (common on cloud IPs)."
            ),
        ),
        patch.object(service, "_download_external", return_value="Fallback Title") as ext,
        patch.object(service, "_trim_to_mp4"),
    ):
        result = service._download_sync(
            job_id,
            "https://www.youtube.com/watch?v=abc",
            ProcessingMode.QUICK,
            10,
        )

    ext.assert_called_once()
    assert result.title == "Fallback Title"
    assert result.video_path.name == "video.mp4"


def test_map_bot_block_message_still_mentions_cloud_ips() -> None:
    exc = __import__("yt_dlp.utils", fromlist=["DownloadError"]).DownloadError(
        "ERROR: [youtube] abc: Sign in to confirm you're not a bot"
    )
    msg = YouTubeService._map_download_error(exc)
    assert "cloud IPs" in msg
