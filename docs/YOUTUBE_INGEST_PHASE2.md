# YouTube ingest — Phase 2 roadmap

Phase 1 (cookies-only on Cloud Run) is the default path: operator-exported Netscape `cookies.txt` in Secret Manager `pressplay-youtube-cookies`, mounted at `/secrets/youtube-cookies.txt`. No code deploy is required to rotate the secret (`:latest` mount).

**Escalate to Phase 2 only if**, after uploading a real cookies secret (thousands of bytes, logged-in session rows such as `SID`, `LOGIN_INFO`, `__Secure-3PSID`) and optional `YOUTUBE_PO_TOKEN`, production jobs still fail at **downloading** with yt-dlp bot/sign-in errors.

## Decision tree

| Symptom after real cookies | Next track |
|----------------------------|------------|
| Video download still blocked | B. Piped/Invidious provider, or C. residential worker |
| Captions work, video blocked | A. Transcript-first ingest |
| Need highest reliability | C. Off–Cloud Run yt-dlp worker |
| Cannot change Memvid pipeline | Not D — Memvid requires local file today |

## A. Transcript-first ingest (lowest code change)

- **youtube-transcript-api** or yt-dlp `skip_download` + subtitles only
- Pipeline branch: `downloading` → `watching` with caption-only `unified_context`
- **Tradeoff:** no visual/Whisper richness; UI “transcript-only mode”

## B. Piped / Invidious stream provider

- Self-hosted [Piped](https://github.com/TeamPiped/Piped) or [Invidious](https://github.com/iv-org/invidious)
- New `DownloadProvider.PIPED` → stream URL → existing `stream_url_to_file` → ffmpeg → Memvid
- **Tradeoff:** extra service; datacenter Piped may still be blocked

## C. Residential / off–Cloud Run download worker

- yt-dlp + small FastAPI worker on homelab/VPS (residential IP)
- PressPlay calls worker; worker returns GCS signed URL or streams MP4
- Tailscale / Cloudflare Tunnel for exposure
- **Tradeoff:** best yt-dlp reliability; highest ops burden

## D. True streaming without local file

Not viable without replacing Memvid: `memvid put` requires a local path. Alternatives (Vertex video API) are paid and out of OSS scope.

## E. Proxy + yt-dlp on Cloud Run

- `YTDLP_PROXY` in yt-dlp opts; residential proxies are usually commercial
- **Tradeoff:** recurring cost; may violate provider ToS

## What Phase 2 does not include by default

- RapidAPI quota tuning (429 is plan/quota)
- Removing Memvid
- In-app Google login for end users

See also [`docs/DEPLOY_GCP.md`](DEPLOY_GCP.md) § YouTube cookies and [`Project Specification.md`](../Project%20Specification.md) checklist §883.
