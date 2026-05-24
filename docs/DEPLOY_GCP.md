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

Production is **open** (no shared password). Abuse protection is enforced in-app and via Cloud Run env (see below).

### Abuse limits (Cloud Run defaults)

| Control | Production value | Env var |
|---------|------------------|---------|
| Per guest session + IP | 3 jobs / hour | `RATE_LIMIT_PER_HOUR` |
| Per IP (all sessions) | 8 jobs / hour | `RATE_LIMIT_PER_IP_PER_HOUR` |
| Cooldown between jobs | 120 seconds | `RATE_LIMIT_MIN_INTERVAL_SECONDS` |
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

For a fresh demo, bootstrap creates an empty Cloud SQL database; Alembic runs on each Cloud Run deploy startup.
