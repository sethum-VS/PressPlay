"""Press kit export formats for API and integrations."""

from __future__ import annotations

import json
from typing import Any

from app.domain.models import PressKitResult


def export_markdown(result: PressKitResult) -> str:
    lines = [
        f"# {result.title}",
        "",
        f"Source: {result.youtube_url}",
        f"Mode: {result.mode.value}",
        "",
        result.blog_post.strip(),
        "",
        "## Twitter thread",
        "",
    ]
    for i, tweet in enumerate(result.tweets, 1):
        lines.append(f"{i}. {tweet}")
    if result.claims:
        lines.extend(["", "## Source claims", ""])
        for c in result.claims:
            ts = ""
            if c.start_sec is not None:
                ts = f" [{int(c.start_sec)}s]"
            lines.append(f"- {c.text}{ts} ({c.source})")
    return "\n".join(lines) + "\n"


def export_json_payload(result: PressKitResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "title": result.title,
        "youtube_url": result.youtube_url,
        "mode": result.mode.value,
        "workflow_status": result.workflow_status.value,
        "blog_post": result.blog_post,
        "tweets": result.tweets,
        "graph": result.graph.model_dump(),
        "watcher_summary": result.watcher_summary,
        "claims": [c.model_dump() for c in result.claims],
        "created_at": result.created_at.isoformat(),
    }


def export_slack_blocks(result: PressKitResult) -> str:
    """Slack Block Kit–style plain text (paste-friendly)."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": result.title[:150]},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Source:* <{result.youtube_url}|YouTube>",
            },
        },
    ]
    preview = result.blog_post.strip()[:500]
    if len(result.blog_post) > 500:
        preview += "…"
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": preview},
        }
    )
    for i, tweet in enumerate(result.tweets, 1):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Tweet {i}/3:*\n{tweet}"},
            }
        )
    if result.claims:
        claim_lines = []
        for c in result.claims[:8]:
            link = ""
            if c.youtube_url and c.start_sec is not None:
                sep = "&" if "?" in c.youtube_url else "?"
                link = f" <{c.youtube_url}{sep}t={int(c.start_sec)}s|jump>"
            claim_lines.append(f"• {c.text}{link}")
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Citations:*\n" + "\n".join(claim_lines),
                },
            }
        )
    return json.dumps({"blocks": blocks}, indent=2)
