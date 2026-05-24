# PressPlay

**The multimodal newsroom for event video.** Turn a YouTube link into a publish-ready press kit—blog post, social thread, and knowledge graph—in minutes, not hours.

PressPlay is an AI-native content pipeline built for communications teams, creators, and newsrooms who need to move from raw footage to multi-format storytelling without a room full of editors. Point it at a launch, keynote, or highlight reel; get structured copy and an explorable entity graph you can share, refine, and ship.

> [!TIP]
> **New here?** Run `./run.sh --verify-llm` after setting `GCP_PROJECT_ID` in `.env` to confirm Vertex is wired, then open [http://localhost:8000](http://localhost:8000) and submit a YouTube URL in **Quick** mode.

---

## Why PressPlay?

Modern events are captured on video first—but distribution still demands blogs, threads, and context-rich visuals. PressPlay closes that gap with a single, repeatable workflow:

- **Speed to publish** — Quick mode targets a full press kit in ~60 seconds after ingest for typical 5–20 minute clips; Full mode handles longer source material (up to one hour).
- **Multimodal fidelity** — Local [Memvid](https://github.com/memvid/memvid) ingest fuses transcript and visual context before any LLM writes a word, so summaries reflect what was said *and* shown.
- **Editorial outputs, not raw JSON** — A polished Markdown article, a three-part Twitter thread, and a D3 knowledge graph—ready for `/newsroom/{id}` sharing.
- **Production-minded defaults** — Async jobs with HTMX polling, rate limits, optional demo secret, GCP Vertex via `google-genai`, and Docker-ready deployment.
- **Demo-safe fallbacks** — Mock only the LLM when you need a reliable stage demo; or skip ingest entirely for fast UI walkthroughs.

---

## How it works

```text
YouTube URL  →  yt-dlp + ffmpeg  →  Memvid (transcript + visuals)
       →  Watcher (journalist analysis)  →  Writer (blog + thread)
       →  Graphify (entities)  →  /newsroom/{id}
```

| Stage | Role |
|-------|------|
| **Ingest** | Download and trim video (Quick: 5–20 min window; Full: ≤1 h) |
| **Memvid** | Build `unified_context` from speech and frames |
| **Watcher** | Gemini 2.5 Flash on Vertex — narrative and fact extraction |
| **Writer** | Structured press kit (Pydantic-validated blog + 3 tweets) |
| **Graphify** | Semantic entity graph (`graphify extract`) with heuristic fallback |
| **Newsroom** | Shareable page: article, thread, interactive D3 graph |

Orchestration is a thin Python pipeline (CrewAI-*style* two-agent design, no CrewAI runtime dependency). See **[Project Specification.md](./Project%20Specification.md)** for architecture, API contracts, and locked design decisions.

---

## Features

- **YouTube-first workflow** — URL validation, Quick/Full modes, server-enforced trim windows
- **HTMX + Jinja UI** — No frontend build step; Tailwind CDN; polling job progress with stage labels
- **Vertex / Agent Platform** — `google-genai` with `vertexai=True`; Application Default Credentials locally, service account in Docker
- **Persisted press kits** — `data/results/{id}/` with manifest, markdown, tweets, and graph JSON
- **Operational guardrails** — ~5 jobs/hour/IP, max 2 concurrent jobs, optional `PRESSPLAY_DEMO_SECRET`
- **Local dev ergonomics** — `run.sh` dependency checks, `scripts/verify_gcp.py` LLM smoke test, `docker compose` for prod-like runs

---

## Quickstart

### Prerequisites

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) on `PATH`
- [gcloud](https://cloud.google.com/sdk) CLI (for local Vertex ADC)
- GCP project with **Vertex AI API** enabled

### Install and run (recommended)

```bash
git clone https://github.com/sethum-VS/PressPlay.git
cd PressPlay
cp .env.example .env
# Set GCP_PROJECT_ID and GCP_LOCATION in .env

gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

chmod +x run.sh
./run.sh --verify-llm   # optional: confirm Vertex responds
./run.sh                # start API at http://localhost:8000
```

Submit a **YouTube URL** on the homepage → wait for job completion → open **`/newsroom/{id}`**.

### Docker (prod-like)

```bash
cp .env.example .env
mkdir -p secrets
# Place service account JSON at secrets/gcp-sa.json (gitignored)

docker compose up --build
```

Compose mounts the SA at `/secrets/gcp.json` and sets `GOOGLE_APPLICATION_CREDENTIALS`—mirroring the GCP VM path in the spec.

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `GCP_PROJECT_ID` | Vertex project (required for live LLM) |
| `GCP_LOCATION` | Vertex region (e.g. `us-central1`) |
| `MOCK_LLM=true` | Real ingest; stub Watcher/Writer and heuristic graph |
| `PRESSPLAY_USE_MOCK=1` | Full fast mock — skips download/Memvid |
| `PRESSPLAY_DEMO_SECRET` | Optional gate for public demos |
| `GRAPHIFY_BIN` | Override path to `graphify` CLI |

**Auth (Pattern C):** Local dev uses ADC only—leave `GOOGLE_APPLICATION_CREDENTIALS` unset. Docker uses a mounted service account JSON.

Full matrix: [Project Specification.md §10](./Project%20Specification.md).

---

## PressPlay stack

| Layer | Technology |
|-------|------------|
| API & UI | FastAPI, Jinja2, HTMX, Tailwind CDN |
| Video | yt-dlp, ffmpeg |
| Multimodal context | Memvid CLI / SDK (Whisper + visual search) |
| LLM | Gemini 2.5 Flash via `google-genai` → Vertex |
| Knowledge graph | Graphify (`graphifyy` package, `graphify` CLI) + D3.js |
| Hosting | GCP Compute + Docker (see spec §12) |

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Homepage — submit jobs, list past runs |
| `POST` | `/api/jobs` | Create async job (HTMX) |
| `GET` | `/api/jobs/{id}` | Poll status (~2s) |
| `GET` | `/newsroom/{id}` | Shareable press kit |
| `GET` | `/health` | Liveness |

---

## Repository layout

```text
app/
  adapters/gemini.py      # Vertex client
  services/pipeline.py    # Orchestration
  services/agents/        # Watcher, Writer
  templates/              # Jinja + HTMX
  static/js/graph.js      # D3 visualization
run.sh                    # Local checks + server
scripts/
  verify_gcp.py           # Vertex smoke test
  cleanup_ttl.py          # Artifact TTL cleanup
data/results/{id}/        # Persisted press kits
Project Specification.md  # Architecture & decisions
```

---

## Documentation

- **[Project Specification.md](./Project%20Specification.md)** — Vision, locked decisions, API surface, GCP deployment, mock modes, and implementation status
- **[`.env.example`](./.env.example)** — Environment template

---

## Development modes

| Mode | When to use |
|------|-------------|
| **Live** | `GCP_PROJECT_ID` set, ADC or SA, Memvid + ffmpeg installed |
| **`MOCK_LLM=true`** | Judge demos: real video ingest, stub LLM/graph |
| **`PRESSPLAY_USE_MOCK=1`** | Fast UI-only (~2s), no download |

Install Memvid for full ingest:

```bash
pip install -r requirements.txt
pip install memvid-sdk
memvid models install whisper-small
```

Optional: `pip install graphifyy` and set `GEMINI_API_KEY` for semantic Graphify extraction (Vertex SA alone may not satisfy the Graphify CLI).

---

## Roadmap

- [ ] GCP VM deploy with HTTPS and TTL cron
- [ ] Graphify auth parity with Vertex service accounts
- [ ] Homepage analytics and source management (nav placeholders today)

---

## License

See repository license file when published. Hackathon / demo use—confirm terms before production deployment.
