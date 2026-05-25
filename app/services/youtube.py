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
from app.services.youtube_download.providers import (
    DownloadProvider,
    fetch_via_apify,
    fetch_via_piped,
    fetch_via_rapidapi,
    is_bot_block_message,
    missing_fallback_config_message,
    resolve_provider_chain,
)
from app.services.youtube_transcript import (
    extract_youtube_video_id,
    fetch_via_youtube_transcript_api,
)

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

    def _base_ydl_opts(self) -> dict:
        """Defaults for server/datacenter IPs (e.g. Cloud Run) and current YouTube player."""
        youtube_args: dict[str, list[str]] = {
            "player_client": ["mweb", "android", "web"],
        }
        po_raw = self.settings.youtube_po_token.strip()
        if po_raw:
            tokens = [t.strip() for t in po_raw.split(",") if t.strip()]
            if tokens:
                youtube_args["po_token"] = tokens

        opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
            "extractor_args": {"youtube": youtube_args},
        }
        if shutil.which("deno"):
            # Production image installs Deno (Dockerfile); required for yt-dlp EJS on server IPs.
            opts["js_runtimes"] = {"deno": {}}
        cookies = self.settings.youtube_cookies_file
        if cookies is not None:
            opts["cookiefile"] = str(cookies)
        return opts

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

    def fetch_transcript_unified_context(self, url: str, title: str = "") -> str:
        """Build unified_context from OSS transcript sources (skips Memvid / local video)."""
        url = self.validate_url(url)
        text = self.fetch_caption_text(url, title)
        if not text.strip():
            video_id = extract_youtube_video_id(url)
            if video_id:
                text = fetch_via_youtube_transcript_api(video_id)
        if not text.strip():
            raise DownloadError(
                "Video download failed and no YouTube transcript or captions were available. "
                "Try a video with auto-generated captions, upload real cookies "
                "(YOUTUBE_COOKIES_PATH), or configure a download fallback."
            )
        header = "## Transcript (YouTube — transcript-only ingest)\n"
        body = header + text.strip()
        if title:
            return f"Title: {title}\n\n{body}"
        return body

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
        max_seconds = self._target_seconds(mode, quick_minutes)
        output = job_dir / "video.mp4"
        chain = resolve_provider_chain(self.settings)
        errors: list[str] = []
        title = ""

        for provider in chain:
            try:
                if provider == DownloadProvider.YTDLP:
                    source, title = self._download_ytdlp(
                        job_dir, url, mode, quick_minutes, max_seconds
                    )
                    self._trim_to_mp4(source, output, max_seconds)
                    if source != output and source.exists():
                        try:
                            source.unlink()
                        except OSError:
                            logger.warning(
                                "Could not remove intermediate download %s", source
                            )
                elif provider == DownloadProvider.RAPIDAPI:
                    title = self._download_external(
                        url,
                        job_dir / "source.mp4",
                        provider,
                        max_seconds,
                    )
                    self._trim_to_mp4(job_dir / "source.mp4", output, max_seconds)
                elif provider == DownloadProvider.APIFY:
                    title = self._download_external(
                        url,
                        job_dir / "source.mp4",
                        provider,
                        max_seconds,
                    )
                    self._trim_to_mp4(job_dir / "source.mp4", output, max_seconds)
                elif provider == DownloadProvider.PIPED:
                    base = self.settings.piped_api_base.strip()
                    if not base:
                        raise DownloadError(
                            "PIPED_API_BASE is not configured for YouTube download."
                        )
                    title = fetch_via_piped(
                        url,
                        job_dir / "source.mp4",
                        base,
                        max_bytes=max_seconds * 2_000_000,
                    )
                    self._trim_to_mp4(job_dir / "source.mp4", output, max_seconds)
                else:
                    continue
                return VideoDownloadResult(
                    job_id=job_id,
                    video_path=output,
                    title=title,
                    source_url=url,
                )
            except DownloadError as exc:
                errors.append(str(exc))
                if provider == DownloadProvider.YTDLP and not self._should_try_fallback(
                    str(exc)
                ):
                    raise
            except Exception as exc:
                errors.append(f"{provider.value}: {exc}")
                logger.warning(
                    "YouTube download via %s failed for %s: %s", provider.value, url, exc
                )

        if errors and is_bot_block_message(errors[0]):
            if not self.settings.rapidapi_key.strip() and not self.settings.apify_api_token.strip():
                raise DownloadError(missing_fallback_config_message(self.settings))
            raise DownloadError(
                "YouTube blocked direct download from this server. "
                "External download providers also failed. "
                f"{errors[-1][:200]}"
            )
        detail = errors[-1] if errors else "YouTube download failed."
        raise DownloadError(detail[:400])

    def _should_try_fallback(self, message: str) -> bool:
        chain = resolve_provider_chain(self.settings)
        if len(chain) <= 1:
            return False
        mode = (self.settings.youtube_download_provider or "ytdlp").strip().lower()
        if mode == DownloadProvider.AUTO.value:
            return True
        lowered = message.lower()
        return is_bot_block_message(lowered) or "cloud ips" in lowered

    def _download_external(
        self,
        url: str,
        dest: Path,
        provider: DownloadProvider,
        max_seconds: int,
    ) -> str:
        max_bytes = max_seconds * 2_000_000
        if provider == DownloadProvider.RAPIDAPI:
            key = self.settings.rapidapi_key.strip()
            if not key:
                raise DownloadError(
                    "RAPIDAPI_KEY is not configured for YouTube download fallback."
                )
            return fetch_via_rapidapi(url, dest, key, max_bytes=max_bytes)
        if provider == DownloadProvider.APIFY:
            token = self.settings.apify_api_token.strip()
            if not token:
                raise DownloadError(
                    "APIFY_API_TOKEN is not configured for YouTube download fallback."
                )
            return fetch_via_apify(url, dest, token, max_bytes=max_bytes)
        if provider == DownloadProvider.PIPED:
            base = self.settings.piped_api_base.strip()
            if not base:
                raise DownloadError(
                    "PIPED_API_BASE is not configured for YouTube download."
                )
            return fetch_via_piped(url, dest, base, max_bytes=max_bytes)
        raise DownloadError(f"Unknown download provider: {provider.value}")

    def _download_ytdlp(
        self,
        job_dir: Path,
        url: str,
        mode: ProcessingMode,
        quick_minutes: int | None,
        max_seconds: int,
    ) -> tuple[Path, str]:
        raw_template = str(job_dir / "source.%(ext)s")
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

        title = ""
        if info:
            title = str(info.get("title") or "").strip()
        return source, title

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
        if is_bot_block_message(text):
            return (
                "YouTube blocked automated download from this server (common on cloud IPs)."
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
