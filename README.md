# PressPlay

**Press kit factory + governance for event video.** Turn a YouTube link into an auditable press kit—blog post, social thread, timestamped citations, and knowledge graph—that comms teams can review, edit, and publish on your cloud.

PressPlay is **not** a generic “paste YouTube into ChatGPT” summarizer. It is a fixed pipeline with separated fact extraction (Watcher) and copywriting (Writer), shareable `/newsroom/{id}` artifacts, editorial workflow, and optional API/webhook integrations for B2B comms teams.

> [!TIP]
> **New here?** Run `./run.sh --verify-llm` after setting `GCP_PROJECT_ID` in `.env`, then open [http://localhost:8000](http://localhost:8000) and submit a YouTube URL in **Quick** mode.

---

## Why PressPlay?

| Chat tab | PressPlay |
|----------|-----------|
| Ad-hoc prompts, ephemeral thread | Guaranteed blog + 3 tweets + graph every run |
| Hard to audit | Timestamped **claims** with jump-to-moment links |
| No approval flow | Workflow: draft → in_review → approved → published |
| Consumer SaaS governance | Vertex on **your** GCP project, rate limits, demo secret |

- **Trust** — Watcher emits atomic claims with `[seconds]` anchors from Memvid transcript/visual context.
- **Speed to ship** — Structured outputs (Pydantic), CMS-ready Markdown, Slack/JSON export.
- **Editorial control** — Edit blog/tweets on the newsroom page; partial regen (tweets/graph/blog) without re-ingest.
- **Integrations** — `POST /api/v1/jobs` with optional `webhook_url`; export markdown/json/slack.

---

## Go-to-market (wedge)

**Positioning:** Sell as *automated, auditable press kit factory* for **event-driven comms** (sports post-game, launches, IR keynotes)—not “AI watches YouTube.”

**First pilot:** See [docs/PILOT_SPORTS.md](./docs/PILOT_SPORTS.md) for a sports post-game checklist and metrics vs a ChatGPT baseline (time-to-publish, citation coverage, editor edits).

**Do say:** “Separated fact extraction and copywriting, with shareable results and your cloud.”  
**Do not say:** “AI summarizes YouTube” or “~60 seconds” unless Memvid + Vertex are proven on your hardware.

---

## How it works

```text
YouTube URL  →  yt-dlp + ffmpeg  →  Memvid (transcript + visuals)
       →  Watcher (facts + claims)  →  Writer (blog + thread)
       →  Graphify (entities)  →  /newsroom/{id}  (draft by default)
```

| Stage | Role |
|-------|------|
| **Ingest** | Download and trim video (Quick: 5–20 min window; Full: ≤1 h) |
| **Memvid** | Build `unified_context` from speech and frames |
| **Watcher** | Gemini — chronological summary + timestamped claims |
| **Writer** | Structured press kit (blog + 3 tweets; optional `claim_refs`) |
| **Graphify** | Semantic entity graph with heuristic fallback |
| **Newsroom** | Citations, edit forms, workflow status, export links |

See **[Project Specification.md](./Project%20Specification.md)** for architecture and locked decisions.

---

## One-command ingest setup

Real ingest is the **default** when `GCP_PROJECT_ID` is set and `PRESSPLAY_USE_MOCK` is **unset**.

```bash
# 1. System tools
brew install ffmpeg          # or: apt install ffmpeg
pip install -r requirements.txt
pip install memvid-sdk

# 2. Memvid CLI with Whisper (recommended — not optional for caption-less videos)
cargo install memvid-cli --features whisper

# 3. Whisper model (or use ./run.sh with PRESSPLAY_INSTALL_WHISPER=1)
memvid models install whisper-small

# 4. Verify
./run.sh --skip-server
```

If the Memvid CLI is missing, the pipeline **fails fast** with install instructions (YouTube auto-captions may still work as fallback). Docker installs `memvid-sdk` and attempts `memvid models install whisper-small`; mount or bake the `memvid` binary for full multimodal ingest in containers.

---

## Quickstart

### Prerequisites

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) on `PATH`
- [gcloud](https://cloud.google.com/sdk) CLI (for local Vertex ADC)
- GCP project with **Vertex AI API** enabled

### Install and run

```bash
git clone https://github.com/sethum-VS/PressPlay.git
cd PressPlay
cp .env.example .env
# Set GCP_PROJECT_ID and GCP_LOCATION in .env

gcloud auth application-default login
chmod +x run.sh
./run.sh --verify-llm
./run.sh
```

Submit a **YouTube URL** → open **`/newsroom/{id}`** when the job completes.

### Docker (Postgres + guest sessions)

```bash
cp .env.example .env
# Required for production-shaped deploy:
echo "SESSION_SECRET=$(openssl rand -hex 32)" >> .env
mkdir -p secrets
# Place service account JSON at secrets/gcp-sa.json

docker compose up --build
```

`docker compose` starts **Postgres 16** and the API, runs **Alembic migrations**, and issues a **guest session cookie** on first visit (30-day TTL by default). Jobs and press kits persist across restarts; each guest only sees their own work.

Smoke test (API running):

```bash
chmod +x scripts/smoke_mvp.sh
./scripts/smoke_mvp.sh http://localhost:8000
```

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `GCP_PROJECT_ID` | Vertex project (required for live LLM) |
| `GCP_LOCATION` | Vertex region (e.g. `us-central1`) |
| `MOCK_LLM=true` | Real ingest; stub Watcher/Writer |
| `PRESSPLAY_USE_MOCK=1` | **UI-only** fast mock — skips download/Memvid (not default) |
| `PRESSPLAY_DEMO_SECRET` | Optional shared-secret gate (private demos only; not used on Cloud Run) |
| `RATE_LIMIT_PER_IP_PER_HOUR` | Per-IP cap across guest sessions (default 10) |
| `RATE_LIMIT_MIN_INTERVAL_SECONDS` | Cooldown between jobs from same IP (default 60) |
| `PRESSPLAY_INSTALL_WHISPER=1` | `./run.sh` runs `memvid models install whisper-small` |
| `GRAPHIFY_BIN` | Override path to `graphify` CLI |
| `DATABASE_URL` | Postgres async URL (required for MVP deploy) |
| `SESSION_SECRET` | Cookie signing secret (required in Docker compose) |
| `GUEST_SESSION_TTL_DAYS` | Guest session lifetime (default `30`) |

**Brand voice (vertical packs):** Each job selects a vertical at create time (`sports`, `events`, `corp`; default `events`). PressPlay loads `config/brand-{vertical}.yaml` into the Writer prompt only. Customize tone, voice, banned phrases, and hashtag policy in those files. Legacy override: copy `config/brand.yaml.example` → `config/brand.yaml` (used only when a vertical pack file is missing).

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Homepage — submit jobs, list past runs |
| `POST` | `/api/jobs` | Create async job (HTMX) |
| `GET` | `/api/jobs/{id}` | Poll status (HTMX) |
| `POST` | `/api/v1/jobs` | Create job (JSON) — `{id, status, poll_url}` |
| `GET` | `/api/v1/jobs/{id}` | Job status JSON |
| `GET` | `/api/v1/newsroom/{id}/export?format=` | `markdown` \| `json` \| `slack` |
| `POST` | `/api/jobs/{id}/regenerate` | Partial regen: `part=tweets\|blog\|graph` |
| `POST` | `/newsroom/{id}/save` | Save blog + tweets edits |
| `POST` | `/newsroom/{id}/workflow` | Update workflow status |
| `GET` | `/newsroom/{id}` | Shareable press kit |
| `GET` | `/health` | Liveness |
| `GET` | `/health/ready` | Readiness (Postgres `SELECT 1`) |

**JSON job create example:**

```bash
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"youtube_url":"https://www.youtube.com/watch?v=VIDEO_ID","mode":"quick","vertical":"sports","webhook_url":"https://example.com/hook"}'
```

`vertical` (or HTMX form field `vertical`): `sports` | `events` | `corp`. Poll responses include `"vertical"` on `GET /api/v1/jobs/{id}`; saved press kits store it on `manifest.json`.

---

## Development modes

| Mode | When to use |
|------|-------------|
| **Live** | `GCP_PROJECT_ID` set, Memvid CLI + ffmpeg, `PRESSPLAY_USE_MOCK` unset |
| **`MOCK_LLM=true`** | Demo with real ingest, stub LLM |
| **`PRESSPLAY_USE_MOCK=1`** | Fast UI-only (~2s), no download |

---

## License

See repository license file when published.
