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
        if settings.rapidapi_key.strip():
            chain.append(DownloadProvider.RAPIDAPI)
        if settings.apify_api_token.strip():
            chain.append(DownloadProvider.APIFY)
        return chain

    return [mode]


def _rapidapi_headers(api_key: str) -> dict[str, str]:
    return {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": RAPIDAPI_HOST,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def request_rapidapi_links(url: str, api_key: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """POST YouTube URL to skdeveloper YouTube Video Downloader Fast on RapidAPI."""
    endpoint = f"https://{RAPIDAPI_HOST}{RAPIDAPI_DOWNLOAD_PATH}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.post(
            endpoint,
            headers=_rapidapi_headers(api_key),
            data={"url": url},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("RapidAPI response was not a JSON object.")
    return payload


def pick_mp4_url(payload: Any) -> str:
    """Select best MP4 direct URL from a flexible RapidAPI / Apify JSON shape."""
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
    return (
        "YouTube blocked automated download from this server (common on cloud IPs). "
        "Set RAPIDAPI_KEY (or APIFY_API_TOKEN) and YOUTUBE_DOWNLOAD_PROVIDER=auto on Cloud Run, "
        "or run PressPlay locally. Sign-in and cookies are not supported in v1."
    )
