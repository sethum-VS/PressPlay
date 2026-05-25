"""YouTube download via external APIs when yt-dlp is blocked on datacenter IPs."""

from __future__ import annotations

import logging
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.youtube_transcript import extract_youtube_video_id

logger = logging.getLogger(__name__)

RAPIDAPI_HOST = "youtube-video-downloader-fast.p.rapidapi.com"
RAPIDAPI_DOWNLOAD_PATH = "/download.php"
APIFY_ACTOR_ID = "tazy~youtube-converter"

_BOT_PHRASES = (
    "not a bot",
    "confirm you're",
    "confirm you're",
    "unusual traffic",
    "captcha",
    "sign in to confirm",
    "sign in to continue",
    "please sign in",
    "login required",
    "requires login",
    "use --cookies",
)

_MP4_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_QUALITY_ORDER = ("1080", "720", "480", "360", "240")


class DownloadProvider(str, Enum):
    YTDLP = "ytdlp"
    PIPED = "piped"
    RAPIDAPI = "rapidapi"
    APIFY = "apify"
    AUTO = "auto"


def is_bot_block_message(message: str) -> bool:
    text = message.lower()
    return any(phrase in text for phrase in _BOT_PHRASES)


def resolve_provider_chain(settings: Settings) -> list[DownloadProvider]:
    raw = (settings.youtube_download_provider or "ytdlp").strip().lower()
    try:
        mode = DownloadProvider(raw)
    except ValueError:
        mode = DownloadProvider.YTDLP

    if mode == DownloadProvider.AUTO:
        chain = [DownloadProvider.YTDLP]
        if settings.piped_api_base.strip():
            chain.append(DownloadProvider.PIPED)
        if settings.rapidapi_key.strip():
            chain.append(DownloadProvider.RAPIDAPI)
        if settings.apify_api_token.strip():
            chain.append(DownloadProvider.APIFY)
        return chain

    return [mode]


def _rapidapi_headers(api_key: str) -> dict[str, str]:
    return {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": RAPIDAPI_HOST,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _rapidapi_failure_message(payload: dict[str, Any]) -> str | None:
    """Map skdeveloper error/quota payloads to a user-facing message."""
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()[:400]

    error = payload.get("error")
    if not error:
        return None

    err_text = str(error).strip()
    nested = payload.get("response")
    if isinstance(nested, dict):
        status = nested.get("statusCode") or nested.get("status")
        detail = nested.get("error") or nested.get("message") or ""
        medias = nested.get("medias")
        if medias == [] or (isinstance(medias, list) and not medias):
            parts = [err_text]
            if status:
                parts.append(f"upstream status {status}")
            if detail:
                parts.append(str(detail).strip()[:120])
            return (
                "RapidAPI YouTube downloader returned no media links "
                f"({'; '.join(parts)})."
            )[:400]
    return f"RapidAPI error: {err_text}"[:400]


_RAPIDAPI_429_DELAYS_SEC = (3.0, 8.0, 20.0)


def request_rapidapi_links(url: str, api_key: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """POST YouTube URL to skdeveloper YouTube Video Downloader Fast on RapidAPI."""
    endpoint = f"https://{RAPIDAPI_HOST}{RAPIDAPI_DOWNLOAD_PATH}"
    last_429: str | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for attempt, delay in enumerate((*_RAPIDAPI_429_DELAYS_SEC, None)):
            response = client.post(
                endpoint,
                headers=_rapidapi_headers(api_key),
                data={"url": url},
            )
            if response.status_code == 403:
                raise ValueError(
                    "RapidAPI rejected the request (403). Check subscription and "
                    "x-rapidapi-key for YouTube Video Downloader Fast."
                )
            if response.status_code == 429:
                last_429 = (
                    "RapidAPI rate limit exceeded (429). Retry later or upgrade plan."
                )
                if delay is not None:
                    logger.warning(
                        "RapidAPI 429 for %s (attempt %s), retrying in %ss",
                        url,
                        attempt + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise ValueError(last_429)
            response.raise_for_status()
            payload = response.json()
            break
    if not isinstance(payload, dict):
        raise ValueError("RapidAPI response was not a JSON object.")
    failure = _rapidapi_failure_message(payload)
    if failure:
        raise ValueError(failure)
    return payload


def pick_mp4_url(payload: Any) -> str:
    """Select best MP4 direct URL from a flexible RapidAPI / Apify JSON shape."""
    if isinstance(payload, dict):
        medias = payload.get("medias")
        if medias is None and isinstance(payload.get("response"), dict):
            medias = payload["response"].get("medias")
        if isinstance(medias, list) and medias:
            media_candidates = _collect_mp4_candidates(medias, "medias")
            if media_candidates:
                payload = media_candidates

    if isinstance(payload, list) and payload and isinstance(payload[0], tuple):
        candidates = payload
    else:
        candidates = _collect_mp4_candidates(payload)
    if not candidates:
        raise ValueError("No MP4 download link found in provider response.")

    def score(item: tuple[str, int | None, str]) -> tuple[int, int]:
        url, height, label = item
        label_lower = label.lower()
        quality_rank = 0
        for idx, q in enumerate(_QUALITY_ORDER):
            if q in label_lower:
                quality_rank = len(_QUALITY_ORDER) - idx
                break
        h = height or 0
        return (quality_rank, h)

    best = max(candidates, key=score)
    return best[0]


def _collect_mp4_candidates(node: Any, label: str = "") -> list[tuple[str, int | None, str]]:
    out: list[tuple[str, int | None, str]] = []

    if isinstance(node, str):
        if _looks_like_mp4_url(node):
            height = _height_from_label(label)
            out.append((node, height, label))
        return out

    if isinstance(node, list):
        for item in node:
            item_label = label
            if isinstance(item, dict):
                item_label = str(
                    item.get("format")
                    or item.get("quality")
                    or item.get("label")
                    or label
                )
            out.extend(_collect_mp4_candidates(item, item_label))
        return out

    if not isinstance(node, dict):
        return out

    title_hint = str(node.get("title") or node.get("quality") or node.get("label") or label)
    for key, value in node.items():
        key_str = str(key)
        merged_label = f"{title_hint} {key_str}".strip()
        if isinstance(value, str) and _looks_like_mp4_url(value):
            out.append((value, _height_from_label(key_str), merged_label))
        else:
            out.extend(_collect_mp4_candidates(value, merged_label))

    return out


def _looks_like_mp4_url(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    lower = url.lower()
    if "googlevideo.com" in lower or "mime=video" in lower:
        return True
    if ".mp4" in lower:
        return True
    parsed = urlparse(lower)
    path = parsed.path
    return path.endswith(".mp4") or "/mp4" in path


def _height_from_label(label: str) -> int | None:
    match = re.search(r"(\d{3,4})\s*p", label, re.I)
    if match:
        return int(match.group(1))
    for token in _QUALITY_ORDER:
        if token in label:
            return int(token)
    return None


def stream_url_to_file(
    url: str,
    dest: Path,
    *,
    timeout: float = 600.0,
    max_bytes: int | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            total = 0
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
                        total += len(chunk)
                        if max_bytes is not None and total > max_bytes:
                            raise ValueError(
                                f"Download exceeded size limit ({max_bytes} bytes)."
                            )


def extract_title(payload: dict[str, Any]) -> str:
    for key in ("title", "video_title", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def fetch_via_rapidapi(
    url: str,
    dest: Path,
    api_key: str,
    *,
    max_bytes: int | None = None,
) -> str:
    payload = request_rapidapi_links(url, api_key)
    mp4_url = pick_mp4_url(payload)
    logger.info("RapidAPI selected MP4 link for %s", url)
    stream_url_to_file(mp4_url, dest, max_bytes=max_bytes)
    return extract_title(payload) if isinstance(payload, dict) else ""


def _apify_start_run(url: str, token: str, *, timeout: float = 30.0) -> str:
    endpoint = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs"
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            endpoint,
            params={"token": token},
            json={"url": url},
        )
        response.raise_for_status()
        data = response.json()
    run_id = (data.get("data") or {}).get("id")
    if not run_id:
        raise ValueError("Apify run did not return a run id.")
    return str(run_id)


def _apify_wait_for_run(run_id: str, token: str, *, timeout_sec: float = 300.0) -> None:
    status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
    deadline = time.monotonic() + timeout_sec
    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            response = client.get(status_url, params={"token": token})
            response.raise_for_status()
            status = (response.json().get("data") or {}).get("status", "")
            if status == "SUCCEEDED":
                return
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise ValueError(f"Apify run {run_id} ended with status {status}.")
            time.sleep(2.0)
    raise TimeoutError(f"Apify run {run_id} did not finish within {timeout_sec}s.")


def _apify_dataset_items(run_id: str, token: str) -> list[dict[str, Any]]:
    endpoint = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
    with httpx.Client(timeout=60.0) as client:
        response = client.get(endpoint, params={"token": token})
        response.raise_for_status()
        items = response.json()
    if not isinstance(items, list):
        raise ValueError("Apify dataset response was not a list.")
    return [item for item in items if isinstance(item, dict)]


def _pick_piped_stream_url(payload: dict[str, Any]) -> str:
    streams = payload.get("videoStreams") or []
    if not isinstance(streams, list) or not streams:
        raise ValueError("Piped response had no videoStreams.")

    candidates: list[tuple[str, int, bool]] = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        url = stream.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        mime = str(stream.get("mimeType") or "").lower()
        if mime and "video" not in mime and "mp4" not in mime:
            continue
        quality = str(stream.get("quality") or "")
        height = _height_from_label(quality) or 0
        video_only = bool(stream.get("videoOnly"))
        candidates.append((url, height, video_only))

    if not candidates:
        raise ValueError("No playable stream URL in Piped response.")

    with_audio = [c for c in candidates if not c[2]]
    pool = with_audio or candidates
    best = max(pool, key=lambda item: item[1])
    return best[0]


def fetch_via_piped(
    url: str,
    dest: Path,
    api_base: str,
    *,
    max_bytes: int | None = None,
) -> str:
    """Download via a Piped-compatible instance (AGPL; operator-hosted)."""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        raise ValueError("Could not parse YouTube video id for Piped.")
    base = api_base.rstrip("/")
    endpoint = f"{base}/streams/{video_id}"
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(endpoint)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Piped response was not a JSON object.")
    stream_url = _pick_piped_stream_url(payload)
    title = str(payload.get("title") or "").strip()
    logger.info("Piped selected stream for %s via %s", url, base)
    stream_url_to_file(stream_url, dest, max_bytes=max_bytes)
    return title


def fetch_via_apify(
    url: str,
    dest: Path,
    token: str,
    *,
    max_bytes: int | None = None,
) -> str:
    run_id = _apify_start_run(url, token)
    _apify_wait_for_run(run_id, token)
    items = _apify_dataset_items(run_id, token)
    if not items:
        raise ValueError("Apify actor returned no dataset items.")
    mp4_url = pick_mp4_url(items)
    logger.info("Apify selected MP4 link for %s (run %s)", url, run_id)
    stream_url_to_file(mp4_url, dest, max_bytes=max_bytes)
    for item in items:
        title = extract_title(item)
        if title:
            return title
    return ""


def missing_fallback_config_message(settings: Settings) -> str:
    if settings.youtube_cookies_file is None:
        return (
            "YouTube blocked automated download from this server (common on cloud IPs). "
            "Mount operator-exported Netscape cookies via YOUTUBE_COOKIES_PATH "
            "(Secret Manager pressplay-youtube-cookies on Cloud Run). "
            "Optional paid fallbacks: RAPIDAPI_KEY or APIFY_API_TOKEN with "
            "YOUTUBE_DOWNLOAD_PROVIDER=auto. Or run PressPlay locally."
        )
    return (
        "YouTube blocked download even with configured cookies. "
        "Rotate cookies.txt (dedicated service account), or set RAPIDAPI_KEY / "
        "APIFY_API_TOKEN with YOUTUBE_DOWNLOAD_PROVIDER=auto."
    )
