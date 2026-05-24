#!/usr/bin/env bash
# Bootstrap Cloud SQL + Cloud Run (HTTPS, scale-to-zero) for PressPlay production demo.
# Usage: ./scripts/gcp-cloudrun-bootstrap.sh [GCP_PROJECT_ID]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_ID="${1:-${GCP_PROJECT_ID:-}}"
[[ -n "$PROJECT_ID" ]] || { echo "Usage: $0 <GCP_PROJECT_ID>"; exit 1; }

REGION="${GCP_REGION:-us-central1}"
SERVICE="${PRESSPLAY_CLOUD_RUN_SERVICE:-pressplay}"
SQL_INSTANCE="${PRESSPLAY_SQL_INSTANCE:-pressplay-db}"
RUNTIME_SA="pressplay-runtime"
RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
AR_REPO="pressplay"
IMAGE_NAME="newsroom"
CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

info() { printf '%s\n' "$*"; }

info "Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  --project="$PROJECT_ID"

if ! gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID"
fi

if ! gcloud iam service-accounts describe "$RUNTIME_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA" \
    --display-name="PressPlay runtime" \
    --project="$PROJECT_ID"
fi

for role in roles/aiplatform.user roles/cloudsql.client roles/secretmanager.secretAccessor roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_EMAIL}" \
    --role="$role" \
    --quiet >/dev/null
done

info "Secret Manager..."
for secret in pressplay-session-secret pressplay-db-password; do
  if ! gcloud secrets describe "$secret" --project="$PROJECT_ID" >/dev/null 2>&1; then
    if [[ "$secret" == pressplay-db-password ]]; then
      openssl rand -hex 16 | gcloud secrets create "$secret" --data-file=- --replication-policy=automatic --project="$PROJECT_ID"
    else
      openssl rand -hex 32 | gcloud secrets create "$secret" --data-file=- --replication-policy=automatic --project="$PROJECT_ID"
    fi
    info "  created $secret"
  fi
  gcloud secrets add-iam-policy-binding "$secret" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null || true
done

info "Cloud SQL instance (always on — Cloud Run scales to zero, DB does not)..."
DB_PASS="$(gcloud secrets versions access latest --secret=pressplay-db-password --project="$PROJECT_ID")"
if ! gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud sql instances create "$SQL_INSTANCE" \
    --project="$PROJECT_ID" \
    --database-version=POSTGRES_16 \
    --edition=ENTERPRISE \
    --tier=db-f1-micro \
    --region="$REGION" \
    --root-password="$DB_PASS" \
    --storage-size=10GB \
    --storage-auto-increase
  info "  creating $SQL_INSTANCE (may take several minutes)..."
fi
info "  waiting for Cloud SQL to be RUNNABLE..."
for _ in $(seq 1 60); do
  STATE="$(gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID" --format='value(state)')"
  [[ "$STATE" == "RUNNABLE" ]] && break
  sleep 15
done
[[ "$(gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID" --format='value(state)')" == "RUNNABLE" ]] \
  || { echo "Cloud SQL $SQL_INSTANCE not RUNNABLE"; exit 1; }

if ! gcloud sql databases describe pressplay --instance="$SQL_INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud sql databases create pressplay --instance="$SQL_INSTANCE" --project="$PROJECT_ID"
fi
if ! gcloud sql users list --instance="$SQL_INSTANCE" --project="$PROJECT_ID" --format='value(name)' | grep -qx pressplay; then
  gcloud sql users create pressplay \
    --instance="$SQL_INSTANCE" \
    --project="$PROJECT_ID" \
    --password="$DB_PASS"
fi

DB_PASS="$(gcloud secrets versions access latest --secret=pressplay-db-password --project="$PROJECT_ID")"
DATABASE_URL="postgresql+asyncpg://pressplay:${DB_PASS}@/pressplay?host=/cloudsql/${CONNECTION_NAME}"
if ! gcloud secrets describe pressplay-database-url --project="$PROJECT_ID" >/dev/null 2>&1; then
  printf '%s' "$DATABASE_URL" | gcloud secrets create pressplay-database-url \
    --data-file=- --replication-policy=automatic --project="$PROJECT_ID"
else
  printf '%s' "$DATABASE_URL" | gcloud secrets versions add pressplay-database-url --data-file=- --project="$PROJECT_ID"
fi
gcloud secrets add-iam-policy-binding pressplay-database-url \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet >/dev/null || true

info "Remove public VM firewall (Cloud Run uses HTTPS :443)..."
if gcloud compute firewall-rules describe allow-pressplay-8000 --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud compute firewall-rules delete allow-pressplay-8000 --project="$PROJECT_ID" --quiet
  info "  deleted allow-pressplay-8000"
fi

info "Deploy Cloud Run service..."
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${IMAGE_NAME}:latest"
if ! gcloud artifacts docker images describe "$IMAGE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  info "  Image missing — build and push first:"
  info "  docker build --platform linux/amd64 -t $IMAGE ."
  info "  docker push $IMAGE"
  exit 1
fi

info "Running migrations via Cloud SQL Auth Proxy..."
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PROXY_URL="https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.3/cloud-sql-proxy.darwin.arm64" ;;
  Darwin-x86_64) PROXY_URL="https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.3/cloud-sql-proxy.darwin.amd64" ;;
  Linux-*) PROXY_URL="https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.3/cloud-sql-proxy.linux.amd64" ;;
  *) info "  skip local migrate on this OS — CI deploy.yml runs alembic"; PROXY_URL="" ;;
esac
if [[ -n "$PROXY_URL" ]]; then
  PROXY_BIN="/tmp/cloud-sql-proxy-$$"
  curl -fsSL -o "$PROXY_BIN" "$PROXY_URL"
  chmod +x "$PROXY_BIN"
  "$PROXY_BIN" "${CONNECTION_NAME}" --port 5432 &
  PROXY_PID=$!
  sleep 3
  export DATABASE_URL="postgresql+asyncpg://pressplay:${DB_PASS}@127.0.0.1:5432/pressplay"
  export SESSION_SECRET=bootstrap
  if [[ -f "$ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
  else
    python3 -m venv "$ROOT/.venv"
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
    pip install -q -r "$ROOT/requirements.txt"
  fi
  (cd "$ROOT" && alembic upgrade head)
  kill "$PROXY_PID" 2>/dev/null || true
  rm -f "$PROXY_BIN"
fi

gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="$RUNTIME_EMAIL" \
  --add-cloudsql-instances="$CONNECTION_NAME" \
  --min-instances=0 \
  --max-instances=3 \
  --cpu=2 \
  --memory=4Gi \
  --timeout=3600 \
  --port=8000 \
  --set-secrets="SESSION_SECRET=pressplay-session-secret:latest,DATABASE_URL=pressplay-database-url:latest" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION},DEBUG=false,RATE_LIMIT_PER_HOUR=5,RATE_LIMIT_PER_IP_PER_HOUR=12,RATE_LIMIT_MIN_INTERVAL_SECONDS=90,MAX_CONCURRENT_JOBS=2" \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"
info ""
info "PressPlay HTTPS URL: $URL"
info "Open access — abuse limits: 5 jobs/hr per session, 12/hr per IP, 90s cooldown, max 2 concurrent"
