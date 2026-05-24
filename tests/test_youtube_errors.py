import yt_dlp

from app.services.youtube import YouTubeService


def test_map_bot_block_message():
    exc = yt_dlp.utils.DownloadError(
        "ERROR: [youtube] abc: Sign in to confirm you're not a bot"
    )
    msg = YouTubeService._map_download_error(exc)
    assert "cloud IPs" in msg


def test_map_private_video():
    exc = yt_dlp.utils.DownloadError("ERROR: Private video")
    msg = YouTubeService._map_download_error(exc)
    assert "private" in msg.lower()
