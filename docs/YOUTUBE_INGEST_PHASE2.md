# YouTube ingest — OSS options matrix

Production on Cloud Run often cannot download video (yt-dlp bot block without real cookies; paid RapidAPI quota). PressPlay supports **transcript-only ingest** so the pipeline can reach Watcher without Memvid or a local file.

## OSS matrix

| Approach | License | Needs operator secrets? | Cloud Run today | Env / code |
|----------|---------|-------------------------|-----------------|------------|
| **yt-dlp + cookies** | OSS | Yes — Netscape `cookies.txt` | Best when cookies mounted | `YOUTUBE_COOKIES_PATH`, `YOUTUBE_DOWNLOAD_PROVIDER=ytdlp` or `auto` |
| **yt-dlp subtitles only** | OSS | Same cookies help; sometimes works without video | Used as transcript fallback #2 | `fetch_caption_text` in `YouTubeService` |
| **youtube-transcript-api** | MIT | No | Primary transcript fallback | `pip install youtube-transcript-api` |
| **Transcript-only pipeline** | — | No | **Enabled** when download fails | `INGEST_TRANSCRIPT_FALLBACK=1` or `YOUTUBE_DOWNLOAD_PROVIDER=auto` |
| **Piped instance** | AGPL | Public instance URL (operator choice) | Optional download fallback | `PIPED_API_BASE`, `YOUTUBE_DOWNLOAD_PROVIDER=piped` or `auto` |
| **RapidAPI / Apify** | Paid | API keys | Quota-dependent | `RAPIDAPI_KEY`, `APIFY_API_TOKEN`, `auto` |

## Transcript-only flow

1. Try normal download chain (yt-dlp → Piped if configured → RapidAPI → Apify).
2. On `DownloadError`, if `ingest_transcript_fallback_enabled` (explicit `INGEST_TRANSCRIPT_FALLBACK=1` **or** `auto` provider):
   - Fetch transcript via `youtube-transcript-api`, then yt-dlp captions-only.
   - Build `unified_context` with header `## Transcript (YouTube — transcript-only ingest)`.
   - Skip Memvid; continue to Watcher → Strategist → Writer.

**Trade-off:** No visual/Whisper context from Memvid; Watcher runs on text only. Suitable for talk-heavy videos with captions.

## Cookies (operator)

```bash
# Export from browser (logged-in session), gitignored path:
# secrets/youtube-cookies.txt

gcloud secrets versions add pressplay-youtube-cookies \
  --project=PROJECT_ID --data-file=secrets/youtube-cookies.txt

scripts/verify_youtube_cookies.sh   # byte size + tab rows, no secret print
```

Placeholder secrets (~99 bytes, header only) are ignored by `Settings.youtube_cookies_file`.

## Piped (optional)

```bash
# Example public instance — pick one you trust (AGPL); may rate-limit
export PIPED_API_BASE=https://pipedapi.kavin.rocks
export YOUTUBE_DOWNLOAD_PROVIDER=auto   # tries Piped after yt-dlp when base set
```

## Deploy env (Cloud Run)

`.github/workflows/deploy.yml` sets:

- `YOUTUBE_DOWNLOAD_PROVIDER=auto`
- `INGEST_TRANSCRIPT_FALLBACK=1`
- `YOUTUBE_COOKIES_PATH=/secrets/youtube-cookies.txt`

## Verification

1. Browser E2E: production URL + public video with captions.
2. Job should pass **downloading** (or fail download then transcript) → **memvid** stage label (transcript path still sets MEMVID stage) → **watching**.
3. Logs: `transcript-only ingest` when fallback used; no RapidAPI POST required for success.

See also [DEPLOY_GCP.md](./DEPLOY_GCP.md).
