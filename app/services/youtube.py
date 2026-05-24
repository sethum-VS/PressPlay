import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.config import Settings, get_settings
from app.domain.errors import DownloadError, ValidationError
from app.domain.models import ProcessingMode

logger = logging.getLogger(__name__)

YOUTUBE_PATTERNS = [
    re.compile(r"^https?://(www\.)?youtube\.com/watch\?v=[\w-]+", re.I),
    re.compile(r"^https?://youtu\.be/[\w-]+", re.I),
    re.compile(r"^https?://(www\.)?youtube\.com/shorts/[\w-]+", re.I),
    # Live URLs (/live/VIDEO_ID) and youtu.be-style live links
    re.compile(r"^https?://(www\.)?youtube\.com/live/[\w-]+", re.I),
]


@dataclass(frozen=True)
class VideoDownloadResult:
    job_id: str
    video_path: Path
    title: str = ""
    source_url: str = ""


class YouTubeService:
    """Validates YouTube URLs and downloads/trims via yt-dlp + ffmpeg."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @staticmethod
    def _base_ydl_opts() -> dict:
        """Defaults for server/datacenter IPs (e.g. Cloud Run) and current YouTube player."""
        return {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
            # Prefer clients that work without browser cookies on cloud IPs.
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }

    def validate_url(self, url: str) -> str:
        url = url.strip()
        if not url:
            raise ValidationError("YouTube URL is required.")
        if "list=" in url:
            raise ValidationError("Playlists are not supported in v1.")
        if not any(p.match(url) for p in YOUTUBE_PATTERNS):
            raise ValidationError("Please provide a valid YouTube video URL.")
        return url

    def enforce_quick_window(self, quick_minutes: int, settings_min: int, settings_max: int) -> int:
        if quick_minutes < settings_min or quick_minutes > settings_max:
            raise ValidationError(
                f"Quick mode window must be between {settings_min} and {settings_max} minutes."
            )
        return quick_minutes

    def job_dir(self, job_id: str) -> Path:
        path = self.settings.jobs_path / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def fetch_caption_text(self, url: str, title: str = "") -> str:
        """Best-effort YouTube auto-captions via yt-dlp (fallback when Memvid has no Whisper)."""
        url = self.validate_url(url)
        with tempfile.TemporaryDirectory(prefix="pressplay-caps-") as tmp:
            out = Path(tmp) / "captions"
            ydl_opts = {
                **self._base_ydl_opts(),
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en", "en-US", "en-GB"],
                "subtitlesformat": "vtt",
                "outtmpl": str(out),
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            except Exception as exc:
                logger.warning("Caption download failed for %s: %s", url, exc)
                return ""

            vtt_files = sorted(Path(tmp).glob("*.vtt"), key=lambda p: p.stat().st_size, reverse=True)
            if not vtt_files:
                return ""

            text = self._vtt_to_plaintext(vtt_files[0])
            if title and text:
                return f"Title: {title}\n\n{text}"
            return text

    @staticmethod
    def _vtt_to_plaintext(path: Path, max_chars: int = 120_000) -> str:
        raw = path.read_text(encoding="utf-8", errors="replace")
        lines: list[str] = []
        for line in raw.splitlines():
            s = line.strip()
            if not s or s == "WEBVTT" or s.startswith("Kind:") or s.startswith("Language:"):
                continue
            if "-->" in s:
                continue
            if s.startswith("NOTE"):
                continue
            cleaned = re.sub(r"<[^>]+>", "", s).strip()
            if cleaned and cleaned != "[Music]" and cleaned not in lines[-3:]:
                lines.append(cleaned)
        text = "\n".join(lines)
        return text[:max_chars].strip()

    async def download(
        self,
        job_id: str,
        url: str,
        mode: ProcessingMode,
        quick_minutes: int | None,
    ) -> VideoDownloadResult:
        url = self.validate_url(url)
        return await asyncio.to_thread(
            self._download_sync, job_id, url, mode, quick_minutes
        )

    def _download_sync(
        self,
        job_id: str,
        url: str,
        mode: ProcessingMode,
        quick_minutes: int | None,
    ) -> VideoDownloadResult:
        job_dir = self.job_dir(job_id)
        raw_template = str(job_dir / "source.%(ext)s")
        max_seconds = self._target_seconds(mode, quick_minutes)
        section = self._section_spec(max_seconds)

        ydl_opts: dict = {
            **self._base_ydl_opts(),
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": raw_template,
            "download_sections": [section],
            "force_keyframes_at_cuts": True,
        }

        info: dict | None = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadError(self._map_download_error(exc)) from exc
        except Exception as exc:
            raise DownloadError(f"Could not download video: {exc}") from exc

        source = self._find_downloaded_file(job_dir)
        if source is None:
            raise DownloadError("Download finished but no video file was found.")

        output = job_dir / "video.mp4"
        self._trim_to_mp4(source, output, max_seconds)

        title = ""
        if info:
            title = str(info.get("title") or "").strip()

        if source != output and source.exists():
            try:
                source.unlink()
            except OSError:
                logger.warning("Could not remove intermediate download %s", source)

        return VideoDownloadResult(
            job_id=job_id,
            video_path=output,
            title=title,
            source_url=url,
        )

    def _target_seconds(self, mode: ProcessingMode, quick_minutes: int | None) -> int:
        if mode == ProcessingMode.QUICK:
            minutes = quick_minutes or self.settings.quick_minutes_default
            return minutes * 60
        return self.settings.full_max_video_seconds

    @staticmethod
    def _section_spec(max_seconds: int) -> str:
        hours, rem = divmod(max_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        end = f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"*0:00-{end}"

    @staticmethod
    def _find_downloaded_file(job_dir: Path) -> Path | None:
        candidates = sorted(
            (p for p in job_dir.iterdir() if p.is_file() and p.name.startswith("source")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _trim_to_mp4(self, source: Path, output: Path, max_seconds: int) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            if source.suffix.lower() == ".mp4" and source != output:
                shutil.move(str(source), str(output))
            elif source == output:
                return
            else:
                shutil.copy2(source, output)
            return

        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-t",
            str(max_seconds),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=max(600, max_seconds * 2),
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise DownloadError(
                f"Could not trim video to MP4. {stderr[:300] if stderr else exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise DownloadError("Video trim timed out.") from exc

    @staticmethod
    def _map_download_error(exc: Exception) -> str:
        text = str(exc).lower()
        if "private" in text:
            return "This video is private. Use a public YouTube link."
        if "unavailable" in text or "video unavailable" in text:
            return "This video is unavailable or has been removed."
        if "live event" in text or "premiere" in text:
            return "Live streams and premieres are not ready yet. Try again after the event ends."
        if "age" in text and "restrict" in text:
            return "Age-restricted videos cannot be downloaded without sign-in (not supported in v1)."
        if "copyright" in text or "blocked" in text:
            return "This video cannot be downloaded due to platform restrictions."
        if any(
            phrase in text
            for phrase in (
                "not a bot",
                "confirm you're",
                "confirm you’re",
                "unusual traffic",
                "captcha",
            )
        ):
            return (
                "YouTube blocked automated download from this server (common on cloud IPs). "
                "Try again later, pick another public video, or run PressPlay locally. "
                "Sign-in and cookies are not supported in v1."
            )
        if any(
            phrase in text
            for phrase in (
                "sign in to confirm",
                "sign in to continue",
                "please sign in",
                "login required",
                "requires login",
                "use --cookies",
            )
        ):
            return "This video requires sign-in and is not supported in v1."
        raw = str(exc).strip()
        return raw[:400] if raw else "YouTube download failed."
