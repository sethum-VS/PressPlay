"""Load brand voice packs for Writer prompt injection."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from app.domain.models import BrandVertical

logger = logging.getLogger(__name__)

VERTICAL_PACK_NAMES = frozenset(v.value for v in BrandVertical)


def _brand_paths(vertical: str | None = None) -> list[Path]:
    root = get_settings().project_root
    if vertical:
        return [root / "config" / f"brand-{vertical}.yaml"]
    return [root / "brand.yaml", root / "config" / "brand.yaml"]


@lru_cache
def load_brand_config(vertical: str | None = None) -> dict | None:
    for path in _brand_paths(vertical):
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not parse %s: %s", path, exc)
            return None
        if isinstance(data, dict):
            return data
    return None


def _vertical_key(vertical: BrandVertical | str | None) -> str | None:
    if vertical is None:
        return None
    if isinstance(vertical, BrandVertical):
        return vertical.value
    return vertical


def brand_prompt_suffix(vertical: BrandVertical | str | None = None) -> str:
    """Tone guide and banned phrases for Writer system prompt."""
    cfg = load_brand_config(_vertical_key(vertical))
    if not cfg:
        return ""

    parts: list[str] = []
    if tone := cfg.get("tone"):
        parts.append(f"Brand tone: {tone}")
    if voice := cfg.get("voice"):
        parts.append(f"Voice: {voice}")
    banned = cfg.get("banned_phrases") or cfg.get("banned")
    if isinstance(banned, list) and banned:
        phrases = ", ".join(f'"{p}"' for p in banned[:20])
        parts.append(f"Never use these phrases: {phrases}")
    if hashtags := cfg.get("hashtag_policy"):
        parts.append(f"Hashtag policy: {hashtags}")
    if max_tweet := cfg.get("max_tweet_chars"):
        parts.append(f"Keep each tweet under {max_tweet} characters.")

    if not parts:
        return ""
    return "\n\nBrand guidelines:\n" + "\n".join(f"- {p}" for p in parts)


def brand_banned_phrases(vertical: BrandVertical | str | None = None) -> list[str]:
    cfg = load_brand_config(_vertical_key(vertical))
    if not cfg:
        return []
    banned = cfg.get("banned_phrases") or cfg.get("banned")
    if isinstance(banned, list):
        return [str(p).strip() for p in banned if str(p).strip()]
    return []


def brand_max_tweet_chars(vertical: BrandVertical | str | None = None) -> int:
    cfg = load_brand_config(_vertical_key(vertical))
    if not cfg:
        return 280
    val = cfg.get("max_tweet_chars")
    if isinstance(val, int) and val > 0:
        return val
    return 280
