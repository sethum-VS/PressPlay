"""Vertex AI Gemini via google-genai SDK (Pattern C auth).

Local: ADC when ``GOOGLE_APPLICATION_CREDENTIALS`` is unset
(``gcloud auth application-default login``). Docker/VM: SA JSON via that env var.
Falls back to canned responses when ``should_mock_llm()`` (``MOCK_LLM`` or unset GCP).
Does not affect ingest — yt-dlp/Memvid run unless ``PRESSPLAY_USE_MOCK=1``.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.domain.models import WatcherOutput

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MOCK_WATCHER_OUTPUT_JSON = {
    "summary": (
        "Chronological summary (mock): The broadcast opens with pre-launch pad views. "
        "Countdown proceeds to liftoff; Falcon 9 ascends with Starlink V2 Mini payloads. "
        "Deployment is confirmed in orbit; the first stage returns and lands on the droneship."
    ),
    "claims": [
        {
            "text": "Falcon 9 lifts off from the pad during twilight.",
            "start_sec": 42.0,
            "end_sec": 55.0,
            "source": "visual",
        },
        {
            "text": "Mission control confirms payload deployment in orbit.",
            "start_sec": 180.0,
            "end_sec": 200.0,
            "source": "transcript",
        },
        {
            "text": "First stage lands on the droneship A Shortfall of Gravitas.",
            "start_sec": 320.0,
            "end_sec": 360.0,
            "source": "visual",
        },
    ],
}

MOCK_WATCHER_SUMMARY = (
    "Chronological summary (mock): The broadcast opens with pre-launch pad views. "
    "Countdown proceeds to liftoff; Falcon 9 ascends with Starlink V2 Mini payloads. "
    "Deployment is confirmed in orbit; the first stage returns and lands on the droneship."
)

MOCK_STRATEGIST_OUTPUT_JSON = {
    "angle": "Reusable launch milestone — precision engineering and global connectivity",
    "target_audience": "Space enthusiasts, industry press, and Starlink stakeholders",
    "thread_hook": "Twilight liftoff, next-gen V2 Mini payloads, and a droneship landing to close the loop",
    "omit_topics": [
        "unrelated launch delays on other pads",
        "speculation about future Starship dates",
        "political commentary",
    ],
}

MOCK_WRITER_OUTPUT_JSON = {
    "blog_post": """# SpaceX Successfully Deploys Starlink V2 Mini Satellites

In a spectacular display of precision engineering, a Falcon 9 rocket roared to life, piercing the twilight sky over Cape Canaveral. The mission: deliver a fresh batch of Starlink V2 Mini satellites into low Earth orbit.

> "The V2 Minis represent a significant leap in capability—four times the capacity of earlier generations." — Mission Control

The booster, designated B1073, executed a flawless return, touching down on the droneship *A Shortfall of Gravitas*. This marks the 11th successful flight for this first stage.
""",
    "tweets": [
        "LIFTOFF! 🚀 Falcon 9 carries the next generation of Starlink V2 Mini satellites. Expanding connectivity globally. #SpaceX #Starlink 1/3",
        "V2 Minis pack phased array upgrades and E-band backhaul—4× more capacity per satellite than prior versions. 📡 2/3",
        "Booster B1073 lands on 'A Shortfall of Gravitas' 🎯—11 flights for this stage. Reusability in action. 3/3",
    ],
}


class GeminiAdapter:
    """google-genai on Vertex; stubs when ``should_mock_llm()`` is true."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None

    @property
    def use_mock(self) -> bool:
        return self.settings.should_mock_llm()

    def _get_client(self):
        if self._client is not None:
            return self._client

        from google import genai

        project = self.settings.effective_gcp_project
        location = self.settings.effective_gcp_location
        logger.info(
            "Initializing Vertex Gemini client (project=%s, location=%s, mode=%s)",
            project,
            location,
            self.settings.gcp_credentials_mode,
        )
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
        return self._client

    async def generate_text(self, prompt: str, system: str | None = None) -> str:
        if self.use_mock:
            logger.debug("GeminiAdapter mock: generate_text")
            return MOCK_WATCHER_SUMMARY

        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=8192,
        )
        if system:
            config.system_instruction = system

        client = self._get_client()
        response = await client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=config,
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned empty text response")
        return text

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system: str | None = None,
    ) -> T:
        if self.use_mock:
            logger.debug("GeminiAdapter mock: generate_structured(%s)", schema.__name__)
            if schema.__name__ == "WatcherOutput":
                return schema.model_validate(MOCK_WATCHER_OUTPUT_JSON)
            if schema.__name__ == "StrategistOutput":
                return schema.model_validate(MOCK_STRATEGIST_OUTPUT_JSON)
            return schema.model_validate(MOCK_WRITER_OUTPUT_JSON)

        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_schema=schema,
        )
        if system:
            config.system_instruction = system

        client = self._get_client()
        response = await client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=config,
        )
        return self._parse_structured_response(response, schema)

    def _parse_structured_response(self, response, schema: type[T]) -> T:
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            if isinstance(parsed, schema):
                result = parsed
            else:
                try:
                    result = schema.model_validate(parsed)
                except ValidationError:
                    result = None
            if result is not None:
                return result

        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned empty structured response")
        try:
            return schema.model_validate_json(text)
        except ValidationError:
            payload = json.loads(text)
            if schema.__name__ == "WatcherOutput" and isinstance(payload, dict):
                payload = self._normalize_watcher_payload(payload)
            result = schema.model_validate(payload)
        if schema.__name__ == "WatcherOutput" and hasattr(result, "claims"):
            claims = getattr(result, "claims", None) or []
            summary = getattr(result, "summary", "") or ""
            if not claims and summary.strip():
                logger.warning(
                    "Gemini WatcherOutput parsed with empty claims (summary len=%d)",
                    len(summary),
                )
        return result

    @staticmethod
    def _normalize_watcher_payload(payload: dict) -> dict:
        """Vertex occasionally omits claims or uses null — keep a list for validation."""
        claims = payload.get("claims")
        if claims is None:
            payload = {**payload, "claims": []}
        elif not isinstance(claims, list):
            payload = {**payload, "claims": []}
        return payload


@lru_cache
def get_gemini_adapter() -> GeminiAdapter:
    return GeminiAdapter()
