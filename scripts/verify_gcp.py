#!/usr/bin/env python3
"""Minimal Vertex Gemini smoke test via GeminiAdapter (Pattern C / SA JSON)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.adapters.gemini import GeminiAdapter
from app.config import get_settings

SMOKE_PROMPT = (
    "You are a connectivity check. Reply with one short sentence that includes "
    "the exact phrase PressPlay OK and nothing else important."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Vertex Gemini via PressPlay adapter.")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print errors; success is silent except exit code.",
    )
    return parser.parse_args()


async def _run() -> int:
    settings = get_settings()

    if settings.should_mock_llm():
        print(
            "ERROR: LLM verification needs a real Vertex client.\n"
            "  - Set GCP_PROJECT_ID (or VERTEX_PROJECT) in .env\n"
            "  - Set MOCK_LLM=false (or unset)\n"
            "  - Do not use PRESSPLAY_USE_MOCK=1 for this check",
            file=sys.stderr,
        )
        return 1

    project = settings.effective_gcp_project
    location = settings.effective_gcp_location
    mode = settings.gcp_credentials_mode

    for warning in settings.gcp_credential_warnings():
        print(f"WARNING: {warning}", file=sys.stderr)

    adapter = GeminiAdapter(settings)
    try:
        text = await adapter.generate_text(SMOKE_PROMPT)
    except Exception as exc:
        print(f"ERROR: Vertex generate_content failed: {exc}", file=sys.stderr)
        return 1

    if not text.strip():
        print("ERROR: Gemini returned an empty response.", file=sys.stderr)
        return 1

    preview = text.strip().replace("\n", " ")
    if len(preview) > 160:
        preview = preview[:157] + "..."

    print(
        f"Vertex LLM OK (project={project}, location={location}, mode={mode}, "
        f"model={settings.gemini_model})"
    )
    print(f"Response preview: {preview}")
    return 0


def main() -> int:
    args = _parse_args()
    code = asyncio.run(_run())
    if args.quiet and code == 0:
        return 0
    return code


if __name__ == "__main__":
    sys.exit(main())
