"""YouTube download error mapping and yt-dlp options."""

from pathlib import Path

from app.config import Settings
from app.services.youtube import YouTubeService


def test_map_download_error_sign_in_phrases() -> None:
    msg = YouTubeService._map_download_error(
        Exception("ERROR: Sign in to confirm you're not a bot")
    )
    assert "cloud IPs" in msg


def test_map_download_error_does_not_false_positive_on_login_substring() -> None:
    raw = "ERROR: unable to download video data: HTTP Error 403: Forbidden"
    msg = YouTubeService._map_download_error(Exception(raw))
    assert "sign-in" not in msg.lower()
    assert "403" in msg or "Forbidden" in msg or "download" in msg.lower()


def test_base_ydl_opts_includes_youtube_player_client() -> None:
    opts = YouTubeService()._base_ydl_opts()
    assert opts["extractor_args"]["youtube"]["player_client"] == [
        "mweb",
        "android",
        "web",
    ]


def test_youtube_cookies_file_ignores_header_only_placeholder(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    settings = Settings(youtube_cookies_path=str(cookies))
    assert settings.youtube_cookies_file is None


def test_base_ydl_opts_cookiefile_when_cookies_path_set(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tx\ty\n",
        encoding="utf-8",
    )
    settings = Settings(youtube_cookies_path=str(cookies))
    opts = YouTubeService(settings=settings)._base_ydl_opts()
    assert opts["cookiefile"] == str(cookies)


def test_base_ydl_opts_po_token_when_set() -> None:
    settings = Settings(youtube_po_token="mweb.gvs+TOKEN,android.gvs+TOKEN2")
    opts = YouTubeService(settings=settings)._base_ydl_opts()
    assert opts["extractor_args"]["youtube"]["po_token"] == [
        "mweb.gvs+TOKEN",
        "android.gvs+TOKEN2",
    ]
