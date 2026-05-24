# Sports post-game pilot — PressPlay wedge

Use this doc to run a **single-league or single-broadcaster** pilot: post-game press kits with citations and approval, measured against an intern pasting the same URL into ChatGPT/Gemini.

## Job-to-be-done

After a game ends, comms needs within ~30 minutes:

- Blog recap (CMS-ready Markdown)
- Exactly 3 tweets (thread)
- Entity graph (players, teams, plays, venues)
- Timestamped facts legal/PR can verify (“jump to moment”)

## Sample URLs (replace with your rights-cleared feeds)

| Type | Example pattern |
|------|-----------------|
| Full highlight | `https://www.youtube.com/watch?v=<id>` |
| Press conference | League or team official channel |
| Quick mode window | 10–15 min of second-half highlights |

Keep a spreadsheet of 10 canonical games for offline eval.

## Metrics vs ChatGPT baseline

Track per game, same video URL:

| Metric | How to measure | PressPlay target |
|--------|----------------|------------------|
| Time to first draft | Stopwatch from URL submit → newsroom readable | ≤ baseline or 20% faster after ingest warm |
| Time to publish-ready | Including human edits + approval | 30% faster vs chat (fewer re-prompts) |
| Citation coverage | % of blog sentences with a supporting claim link | ≥ 60% on pilot set |
| Editor edit distance | Character diff blog/tweets vs draft | Lower than chat paste cleanup |
| Factual disputes | Count corrections from fact-checker | ≤ chat baseline |
| Workflow adoption | % kits moved past `draft` | > 50% in pilot month |

## Pilot checklist

- [ ] Copy `config/brand.yaml.example` → `config/brand.yaml` (league tone, banned phrases)
- [ ] `./run.sh` passes memvid + ffmpeg checks; `PRESSPLAY_USE_MOCK` **unset**
- [ ] Vertex live: `./run.sh --verify-llm`
- [ ] Run 3 games Quick mode; confirm **Source citations** on newsroom
- [ ] Editor uses workflow: `draft` → `in_review` → `approved`
- [ ] Export JSON to CMS or Slack blocks to social desk
- [ ] Optional: `webhook_url` to Slack when job completes
- [ ] Compare one game side-by-side with ChatGPT video prompt (same brand brief)

## API smoke test

```bash
JOB=$(curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"youtube_url":"https://www.youtube.com/watch?v=VIDEO_ID","mode":"quick"}' | jq -r .id)

# Poll until done
curl -s "http://localhost:8000/api/v1/jobs/$JOB"

# Export
curl -s "http://localhost:8000/api/v1/newsroom/$JOB/export?format=markdown"
```

## Success criteria (4-week pilot)

1. Median time-to-approved kit beats chat baseline on ≥ 7/10 games.
2. ≥ 1 stakeholder (social lead or PR) prefers newsroom link over chat transcript for handoff.
3. Zero publish-blocking hallucinations traced to Writer (unsupported claims flagged via citations).

## Out of scope for this pilot

- SSO / multi-tenant org isolation
- Auto-publish to Twitter/X
- Playlist or channel ingest
