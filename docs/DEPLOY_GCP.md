# GCP deployment & GitHub CI/CD

PressPlay production uses **Cloud Run** (HTTPS, scale-to-zero) + **Cloud SQL Postgres** + **Secret Manager**. Vertex AI uses the attached runtime service account (Pattern C — metadata ADC on Cloud Run, no JSON mount).

The legacy GCE VM path (`docker-compose.prod.yml`, port `:8000`) is retained for reference only; CI deploys to Cloud Run.

## Architecture

| Component | Resource |
|-----------|----------|
| Public URL | `https://pressplay-….run.app` (port 443, no `:8000`) |
| Compute | Cloud Run `pressplay` — `min-instances=0`, `max-instances=3`, 2 vCPU / 4 GiB |
| Database | Cloud SQL `pressplay-db` (Postgres 16, `db-f1-micro`) — always on |
| Container image | `us-central1-docker.pkg.dev/…/pressplay/newsroom` |
| Runtime SA | `pressplay-runtime@…` (Vertex, Cloud SQL client, Secret Accessor) |
| Deploy SA (WIF) | `github-actions-deployer@…` |
| WIF pool / provider | `github-pool` / `github-provider` |

### Secrets (Secret Manager)

| Secret | Env var on Cloud Run |
|--------|----------------------|
| `pressplay-session-secret` | `SESSION_SECRET` |
| `pressplay-database-url` | `DATABASE_URL` (Cloud SQL unix socket) |
| `pressplay-db-password` | *(used to build `pressplay-database-url`)* |
| `pressplay-youtube-cookies` *(recommended)* | File mount → `YOUTUBE_COOKIES_PATH=/secrets/youtube-cookies.txt` — Netscape `cookies.txt` for yt-dlp (open-source production ingest) |
| `pressplay-rapidapi-key` *(optional)* | `RAPIDAPI_KEY` — paid YouTube download fallback when yt-dlp still fails |

Production is **open** (no shared password). Abuse protection is enforced in-app and via Cloud Run env (see below).

### Abuse limits (Cloud Run defaults)

| Control | Production value | Env var |
|---------|------------------|---------|
| Per guest session + IP | 5 jobs / hour | `RATE_LIMIT_PER_HOUR` |
| Per IP (all sessions) | 12 jobs / hour | `RATE_LIMIT_PER_IP_PER_HOUR` |
| Cooldown between jobs | 90 seconds | `RATE_LIMIT_MIN_INTERVAL_SECONDS` |
| Global concurrent pipelines | 2 | `MAX_CONCURRENT_JOBS` |
| Bot honeypot | Hidden `website` field on form | *(always on for HTMX)* |

Tune limits in `.github/workflows/deploy.yml` (`--set-env-vars`) and redeploy. Optional `PRESSPLAY_DEMO_SECRET` remains available for private demos if you mount it manually.

One-time bootstrap (Cloud SQL + IAM + firewall cleanup + optional first deploy):

```bash
./scripts/gcp-cloudrun-bootstrap.sh project-3bb9c91c-69ed-4507-998
```

Legacy VM bootstrap (not used by deploy workflow):

```bash
./scripts/gcp-bootstrap.sh project-3bb9c91c-69ed-4507-998
```

## GitHub configuration

### Repository variables

**Settings → Secrets and variables → Actions → Variables**

| Variable | Example |
|----------|---------|
| `GCP_PROJECT_ID` | `project-3bb9c91c-69ed-4507-998` |
| `GCP_REGION` | `us-central1` |
| `GCP_AR_REPOSITORY` | `pressplay` |
| `GCP_IMAGE_NAME` | `newsroom` |
| `GCP_CLOUD_RUN_SERVICE` | `pressplay` |
| `GCP_SQL_INSTANCE` | `pressplay-db` |

Variables no longer required for deploy: `GCP_ZONE`, `GCP_VM_NAME`.

### Secrets

**None required** if Workload Identity Federation is configured (`github-pool` / `github-provider`) and `github-actions-deployer` can impersonate `sethum-VS/PressPlay`.

### Workflows

| Workflow | Trigger |
|----------|---------|
| `ci.yml` | Push/PR to `main` — pytest + migrations |
| `deploy.yml` | After successful `CI` on `main`, or **Run workflow** manually |

After deploy, the workflow prints the public **HTTPS** URL (no port).

## Local `.env`

See `.env.example`. Docker Compose overrides `DATABASE_URL` for the local `db` service hostname.

Generate a real session secret:

```bash
openssl rand -hex 32
```

## First deploy without waiting for GitHub

```bash
export GCP_PROJECT_ID=project-3bb9c91c-69ed-4507-998
export GCP_REGION=us-central1
gcloud auth configure-docker "${GCP_REGION}-docker.pkg.dev"
docker build --platform linux/amd64 \
  -t "${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/pressplay/newsroom:latest" .
docker push "${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/pressplay/newsroom:latest"
./scripts/gcp-cloudrun-bootstrap.sh "$GCP_PROJECT_ID"
```

## Post-deploy checks

```bash
URL=$(gcloud run services describe pressplay --region=us-central1 \
  --project=project-3bb9c91c-69ed-4507-998 --format='value(status.url)')
curl -s "${URL}/health/ready"
./scripts/smoke_mvp.sh "${URL}"
```

## Security notes

- Public ingress is **HTTPS only** via Cloud Run (`*.run.app`).
- Firewall rule `allow-pressplay-8000` (world-open `:8000` on the VM) is **removed** during Cloud Run bootstrap.
- The VM `pressplay-vm` may still exist for migration/debug; it is **not** updated by `deploy.yml`.
- Rotate secrets in Secret Manager and redeploy to pick up new values.
- Cloud Run ephemeral disk holds in-flight job artifacts only; durable state lives in Postgres.

## VM → Cloud Run migration (optional)

If the VM had Postgres data to preserve:

1. Export from VM: `docker compose -f docker-compose.prod.yml exec db pg_dump -U pressplay pressplay > backup.sql`
2. Import to Cloud SQL via Cloud SQL Auth Proxy or `gcloud sql import`.
3. Or run `./scripts/migrate_fs_to_db.py` if results were filesystem-only.

For a fresh demo, bootstrap creates an empty Cloud SQL database; Alembic runs on each Cloud Run deploy startup (`scripts/migrate_with_retry.sh` retries until Cloud SQL is reachable).

## YouTube downloads on Cloud Run

PressPlay uses **yt-dlp** (open source) with **ffmpeg** trim. YouTube often blocks **datacenter IPs** (including Cloud Run) with “confirm you're not a bot” / sign-in challenges.

**Recommended production (open source):** export browser **Netscape** `cookies.txt` from a dedicated Google account used only for ingestion (not end-user login in the app). Store in Secret Manager and mount on Cloud Run so `YOUTUBE_COOKIES_PATH` points at the file. PressPlay passes it to yt-dlp as `cookiefile`. Rotate cookies periodically.

**Optional paid fallback:** [YouTube Video Downloader Fast on RapidAPI](https://rapidapi.com/skdeveloper/api/youtube-video-downloader-fast) when `YOUTUBE_DOWNLOAD_PROVIDER=auto` and `RAPIDAPI_KEY` is set — use only if cookies are unavailable or exhausted.

### YouTube cookies (open-source production)

1. Sign into YouTube in Chrome or Firefox with a **service / burner account** (org policy and YouTube ToS are your responsibility).
2. Export cookies in **Netscape** format to `cookies.txt` (browser extension such as “Get cookies.txt LOCALLY”, or `yt-dlp --cookies-from-browser chrome` once locally then copy the file).
3. **Never commit** `cookies.txt` — it lives under `secrets/` (gitignored).

**Quality checks before upload** (automation: `./scripts/verify_youtube_cookies.sh`):

| Check | Good | Bad (placeholder) |
|-------|------|-------------------|
| Byte size | Thousands (e.g. ≥ 2000) | ~99 (header only) |
| Tab rows | Many (e.g. ≥ 10) | 0–2 |
| Cookie names | Includes session IDs (`SID`, `LOGIN_INFO`, `__Secure-3PSID`, …) | Only `PREF`, `VISITOR_*`, `YSC`, … |

**macOS note:** `yt-dlp --cookies-from-browser chrome` often fails with `cannot decrypt v10 cookies: no key found` unless Chrome can access the login keychain. Prefer the **“Get cookies.txt LOCALLY”** extension while logged into YouTube, save to `secrets/youtube-cookies.txt`, then upload.

```bash
export GOOGLE_APPLICATION_CREDENTIALS=secrets/gcp-sa.json
gcloud secrets versions add pressplay-youtube-cookies \
  --project=project-3bb9c91c-69ed-4507-998 \
  --data-file=secrets/youtube-cookies.txt
./scripts/verify_youtube_cookies.sh
```

If cookies are insufficient after rotation, see [`docs/YOUTUBE_INGEST_PHASE2.md`](YOUTUBE_INGEST_PHASE2.md).

```bash
# One-time: create secret from exported file
gcloud secrets create pressplay-youtube-cookies \
  --project=PROJECT_ID --data-file=./cookies.txt

# Rotate after re-export
gcloud secrets versions add pressplay-youtube-cookies \
  --project=PROJECT_ID --data-file=./cookies.txt

gcloud secrets add-iam-policy-binding pressplay-youtube-cookies \
  --project=PROJECT_ID \
  --member="serviceAccount:pressplay-runtime@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud run services update pressplay \
  --project=PROJECT_ID --region=us-central1 \
  --update-secrets=/secrets/youtube-cookies.txt=pressplay-youtube-cookies:latest \
  --set-env-vars=YOUTUBE_COOKIES_PATH=/secrets/youtube-cookies.txt
```

`.github/workflows/deploy.yml` mounts the same secret path and sets `YOUTUBE_COOKIES_PATH` on each deploy (secret must exist in the project before deploy succeeds).

**Local dev:** `YOUTUBE_COOKIES_PATH=secrets/youtube-cookies.txt` in `.env` with `YOUTUBE_DOWNLOAD_PROVIDER=ytdlp`.

**Optional:** `YOUTUBE_PO_TOKEN` — comma-separated PO tokens per [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) if cookies alone are insufficient.

## RapidAPI fallback (optional)

### RapidAPI request contract (skdeveloper)

PressPlay calls this API from `app/services/youtube_download/providers.py`:

| Item | Value |
|------|--------|
| Host | `youtube-video-downloader-fast.p.rapidapi.com` |
| Method | `POST` `/download.php` |
| Headers | `x-rapidapi-key`, `x-rapidapi-host`, `Content-Type: application/x-www-form-urlencoded` |
| Body | form field `url` = full YouTube watch URL |

Successful JSON includes downloadable links (often a `medias` array). Errors may be HTTP **403** (bad key/subscription), **429** (rate limit), or HTTP 200 with `message` (quota) / `error` + empty `medias` (upstream fetch failed).

```bash
# One-time: create secret (replace with your RapidAPI key; never commit the key)
echo -n 'YOUR_RAPIDAPI_KEY' | gcloud secrets create pressplay-rapidapi-key \
  --project=PROJECT_ID --data-file=-

# Rotate key after subscribing on RapidAPI
printf '%s' "$RAPIDAPI_KEY" | gcloud secrets versions add pressplay-rapidapi-key \
  --project=PROJECT_ID --data-file=-

# Grant runtime SA access
gcloud secrets add-iam-policy-binding pressplay-rapidapi-key \
  --project=PROJECT_ID \
  --member="serviceAccount:pressplay-runtime@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Point Cloud Run at latest secret version (no full image rebuild required)
gcloud run services update pressplay \
  --project=PROJECT_ID --region=us-central1 \
  --update-secrets=RAPIDAPI_KEY=pressplay-rapidapi-key:latest
```

`.github/workflows/deploy.yml` already sets:

- `--set-secrets=...,RAPIDAPI_KEY=pressplay-rapidapi-key:latest`
- `YOUTUBE_DOWNLOAD_PROVIDER=auto`

| Env var | Cloud Run value | Purpose |
|---------|-----------------|--------|
| `YOUTUBE_DOWNLOAD_PROVIDER` | `auto` | Try yt-dlp first; on bot/sign-in blocks use RapidAPI (and Apify if configured) |
| `RAPIDAPI_KEY` | Secret Manager | [skdeveloper YouTube Video Downloader Fast](https://rapidapi.com/skdeveloper/api/youtube-video-downloader-fast) |
| `APIFY_API_TOKEN` | *(optional secret)* | Second fallback via Apify actor `tazy/youtube-converter` |

**Local dev:** leave `YOUTUBE_DOWNLOAD_PROVIDER=ytdlp` (default) so residential IPs keep using yt-dlp only. Put `RAPIDAPI_KEY` in `.env` (gitignored) to test `auto` locally.

**Without `RAPIDAPI_KEY`:** bot blocks still surface a clear job error suggesting configuration or running locally (`./run.sh`).

**Revision note (2026-05-25):** After rotating `pressplay-rapidapi-key`, confirm active revision with `gcloud run services describe pressplay --format='value(status.latestReadyRevisionName)'`. Quota/plan limits on RapidAPI BASIC can surface as job errors even when the key is valid.

## Transcript-only ingest (OSS fallback)

When video download fails (bot block, RapidAPI 429, etc.), PressPlay can continue with **captions only** — no Memvid, no local file.

| Env var | Deploy value | Purpose |
|---------|--------------|---------|
| `INGEST_TRANSCRIPT_FALLBACK` | `1` | Enable transcript path after download failure (also automatic when `YOUTUBE_DOWNLOAD_PROVIDER=auto`) |
| `PIPED_API_BASE` | *(optional)* | AGPL Piped-compatible API base URL; tried in `auto` chain after yt-dlp |

Full OSS matrix: [`docs/YOUTUBE_INGEST_PHASE2.md`](./YOUTUBE_INGEST_PHASE2.md).

**Local dev:** `INGEST_TRANSCRIPT_FALLBACK=1` in `.env` to test without fixing RapidAPI quota.
