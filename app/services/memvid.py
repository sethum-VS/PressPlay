import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import Settings, get_settings
from app.domain.errors import MemvidError
from app.services.youtube import VideoDownloadResult, YouTubeService

logger = logging.getLogger(__name__)

VISUAL_SEARCH_QUERIES = (
    "main subject or speaker on screen",
    "slides charts or on-screen text",
    "action movement or demonstration",
    "crowd audience or environment",
)


class MemvidService:
    """Ingest local video via Memvid CLI; build unified_context for the Watcher."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.whisper_model = os.getenv("MEMVID_WHISPER_MODEL", "small")

    async def extract_context_stub(
        self, youtube_url: str, quick_minutes: int | None
    ) -> str:
        """Synthetic unified context when ``PRESSPLAY_USE_MOCK=1`` (full fast mock)."""
        window = quick_minutes or self.settings.quick_minutes_default
        return (
            f"Visuals from a {window}-minute window of {youtube_url}: Falcon 9 on the pad "
            "at twilight with venting LOX. Audio: 'T-minus 10, 9, 8…' followed by liftoff. "
            "Mission control confirms payload deployment. Booster returns to droneship."
        )

    async def extract_context(self, video: VideoDownloadResult) -> str:
        self.verify_cli_available()
        return await asyncio.to_thread(self._extract_sync, video)

    def _extract_sync(self, video: VideoDownloadResult) -> str:
        if not video.video_path.is_file():
            raise MemvidError(f"Video file not found: {video.video_path}")

        job_dir = video.video_path.parent
        mv2_path = job_dir / "memory.mv2"
        if mv2_path.exists():
            mv2_path.unlink()

        self._run_ingest(mv2_path, video.video_path)

        try:
            unified = self._build_unified_context(mv2_path)
        finally:
            self._delete_video(video.video_path)

        if self._needs_caption_fallback(unified) and video.source_url:
            captions = YouTubeService(self.settings).fetch_caption_text(
                video.source_url, video.title
            )
            if captions:
                prefix = "## Transcript (YouTube captions)\n" + captions
                unified = f"{prefix}\n\n{unified}".strip() if unified.strip() else prefix

        if not unified.strip():
            raise MemvidError(
                "No transcript or visual context from Memvid or YouTube captions. "
                "Install memvid-cli with Whisper (`cargo install memvid-cli --features whisper`) "
                "or use a video with auto-generated captions."
            )
        return unified.strip()

    def _memvid_cmd(self) -> list[str]:
        for candidate in (
            shutil.which("memvid"),
            "/opt/homebrew/bin/memvid",
            Path.home() / ".cargo/bin/memvid",
        ):
            if not candidate:
                continue
            path = Path(candidate) if isinstance(candidate, Path) else Path(str(candidate))
            if path.is_file():
                return [str(path)]
        raise MemvidError(self._install_hint())

    def verify_cli_available(self) -> None:
        """Fail fast before download when Memvid CLI is required."""
        self._memvid_cmd()
        try:
            import memvid_sdk  # noqa: F401
        except ImportError as exc:
            raise MemvidError(self._install_hint()) from exc

    def _ensure_memory_file(self, mv2_path: Path) -> None:
        if mv2_path.is_file():
            return
        create = [
            *self._memvid_cmd(),
            "create",
            str(mv2_path),
        ]
        result = subprocess.run(create, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise MemvidError(
                f"Could not create Memvid memory file: {stderr[:300] if stderr else 'unknown error'}"
            )

    def _run_ingest(self, mv2_path: Path, video_path: Path) -> None:
        self._ensure_memory_file(mv2_path)
        cmd = [
            *self._memvid_cmd(),
            "put",
            str(mv2_path),
            "--input",
            str(video_path),
            "--transcribe",
            "--clip",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("MEMVID_INGEST_TIMEOUT_SEC", "7200")),
            )
        except FileNotFoundError as exc:
            raise MemvidError(self._install_hint()) from exc
        except subprocess.TimeoutExpired as exc:
            raise MemvidError("Memvid ingest timed out.") from exc

        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            if "not found" in stderr.lower() or "no such file" in stderr.lower():
                raise MemvidError(self._install_hint())
            raise MemvidError(
                f"Memvid ingest failed: {stderr[:500] if stderr else 'unknown error'}"
            )

        if not mv2_path.is_file():
            raise MemvidError("Memvid ingest did not create a memory file.")

    def _build_unified_context(self, mv2_path: Path) -> str:
        try:
            import memvid_sdk as memvid
        except ImportError as exc:
            raise MemvidError(self._install_hint()) from exc

        sections: list[str] = []
        mem = memvid.use("basic", str(mv2_path))

        try:
            timeline = mem.timeline(limit=300)
            transcript_lines = self._format_timeline(timeline)
            if transcript_lines:
                sections.append("## Transcript (chronological)\n" + "\n".join(transcript_lines))
        except Exception as exc:
            logger.warning("Memvid timeline failed: %s", exc)

        visual_lines: list[str] = []
        for query in VISUAL_SEARCH_QUERIES:
            try:
                hits = mem.find(query, k=4, mode="clip")
            except Exception:
                try:
                    hits = mem.find(query, k=4, mode="auto")
                except Exception:
                    continue
            for hit in hits or []:
                line = self._hit_preview(hit, query)
                if line and line not in visual_lines:
                    visual_lines.append(line)

        if visual_lines:
            sections.append(
                "## Visual highlights\n"
                + "\n".join(f"- Visuals show {line}" for line in visual_lines[:24])
            )

        if sections:
            return "\n\n".join(sections)

        try:
            answer = mem.ask(
                "Describe chronologically what is seen and heard in this video.",
                context_only=True,
            )
            if isinstance(answer, dict):
                ctx = answer.get("context") or answer.get("answer") or ""
                if ctx:
                    return str(ctx)
        except Exception as exc:
            logger.warning("Memvid ask fallback failed: %s", exc)

        return self._cli_context_fallback(mv2_path)

    @staticmethod
    def _needs_caption_fallback(unified: str) -> bool:
        if not unified.strip():
            return True
        if "## Transcript" in unified and len(unified) > 400:
            return False
        return len(unified) < 400

    @staticmethod
    def _timestamp_to_seconds(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("s") and s[:-1].replace(".", "", 1).isdigit():
            return float(s[:-1])
        if ":" in s:
            parts = s.split(":")
            try:
                nums = [float(p) for p in parts]
            except ValueError:
                return None
            if len(nums) == 2:
                return nums[0] * 60 + nums[1]
            if len(nums) == 3:
                return nums[0] * 3600 + nums[1] * 60 + nums[2]
        try:
            return float(s)
        except ValueError:
            return None

    @classmethod
    def _format_timeline(cls, timeline: object) -> list[str]:
        lines: list[str] = []
        entries = timeline if isinstance(timeline, list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            text = (
                entry.get("preview")
                or entry.get("text")
                or entry.get("content")
                or ""
            )
            if not text:
                continue
            meta = entry.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            ts_raw = (
                entry.get("timestamp")
                or entry.get("start_sec")
                or entry.get("start")
                or meta.get("timestamp")
                or meta.get("segment_start")
                or meta.get("start_sec")
                or meta.get("start")
            )
            sec = cls._timestamp_to_seconds(ts_raw)
            if sec is None and entry.get("end_sec") is not None:
                sec = cls._timestamp_to_seconds(entry.get("end_sec"))
            if sec is not None:
                prefix = f"[{int(sec)}s] "
            elif ts_raw:
                prefix = f"[{ts_raw}] "
            else:
                prefix = ""
            lines.append(f"{prefix}{str(text).strip()}")
        return lines

    @staticmethod
    def _hit_preview(hit: object, fallback_query: str) -> str:
        if isinstance(hit, str):
            return hit.strip() or fallback_query
        if not isinstance(hit, dict):
            return fallback_query
        preview = hit.get("preview") or hit.get("text") or hit.get("label")
        if preview:
            return str(preview).strip()
        meta = hit.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("timestamp"):
            return f"{fallback_query} (at {meta['timestamp']})"
        return fallback_query

    def _cli_context_fallback(self, mv2_path: Path) -> str:
        cmd = [
            *self._memvid_cmd(),
            "ask",
            str(mv2_path),
            "--question",
            "Summarize chronologically what is seen and what is said.",
            "--sources",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""

        if result.returncode != 0:
            return (result.stderr or result.stdout or "").strip()[:4000]

        stdout = result.stdout.strip()
        if stdout.startswith("{"):
            try:
                data = json.loads(stdout)
                return str(data.get("context") or data.get("answer") or stdout)
            except json.JSONDecodeError:
                pass
        return stdout[:8000]

    @staticmethod
    def _delete_video(video_path: Path) -> None:
        try:
            if video_path.is_file():
                video_path.unlink()
        except OSError as exc:
            logger.warning("Could not delete temp video %s: %s", video_path, exc)

    @staticmethod
    def _install_hint() -> str:
        return (
            "Memvid video CLI is not on PATH (pip install memvid-sdk alone is not enough). "
            "Install the CLI, Whisper models, and ensure ffmpeg is available:\n"
            "  cargo install memvid-cli --features whisper   # npm build lacks transcription\n"
            "  # or: npm install -g memvid-cli (no Whisper — ingest will be caption-only)\n"
            "  pip install memvid-sdk\n"
            f"Python: {sys.executable}\n"
            "See README.md and https://docs.memvid.com/sdks/cli"
        )
