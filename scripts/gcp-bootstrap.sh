#!/usr/bin/env bash
# One-time GCP bootstrap for PressPlay (legacy VM path).
# Production demo: use ./scripts/gcp-cloudrun-bootstrap.sh instead (HTTPS + scale-to-zero).
# Usage: ./scripts/gcp-bootstrap.sh [GCP_PROJECT_ID]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_ID="${1:-${GCP_PROJECT_ID:-}}"
if [[ -z "$PROJECT_ID" ]]; then
  if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a && source .env && set +a
    PROJECT_ID="${GCP_PROJECT_ID:-}"
  fi
fi
[[ -n "$PROJECT_ID" ]] || { echo "Usage: $0 <GCP_PROJECT_ID> or set GCP_PROJECT_ID in .env"; exit 1; }

REGION="${GCP_LOCATION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"
AR_REPO="pressplay"
IMAGE_NAME="newsroom"
VM_NAME="${PRESSPLAY_VM_NAME:-pressplay-vm}"
RUNTIME_SA="pressplay-runtime"
DEPLOYER_SA="github-actions-deployer"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
AR_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${IMAGE_NAME}"

info() { printf '%s\n' "$*"; }

info "Project: $PROJECT_ID ($PROJECT_NUMBER)"
info "Artifact Registry image base: $AR_IMAGE"

info "Enabling APIs..."
gcloud services enable \
  compute.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  iamcredentials.googleapis.com \
  --project="$PROJECT_ID"

info "Artifact Registry repository..."
if ! gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="PressPlay newsroom API" \
    --project="$PROJECT_ID"
fi

info "Runtime service account..."
if ! gcloud iam service-accounts describe "${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA" \
    --display-name="PressPlay VM runtime" \
    --project="$PROJECT_ID"
fi
RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
for role in roles/aiplatform.user roles/logging.logWriter roles/artifactregistry.reader roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_EMAIL}" \
    --role="$role" \
    --quiet >/dev/null
done

info "GitHub Actions WIF binding for sethum-VS/PressPlay..."
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/sethum-VS/PressPlay" \
  --quiet >/dev/null || true

info "Secret Manager (session + db password)..."
for secret in pressplay-session-secret pressplay-db-password; do
  if ! gcloud secrets describe "$secret" --project="$PROJECT_ID" >/dev/null 2>&1; then
    if [[ "$secret" == pressplay-db-password ]]; then
      openssl rand -hex 16 | gcloud secrets create "$secret" --data-file=- --replication-policy=automatic --project="$PROJECT_ID"
    else
      openssl rand -hex 32 | gcloud secrets create "$secret" --data-file=- --replication-policy=automatic --project="$PROJECT_ID"
    fi
  fi
  gcloud secrets add-iam-policy-binding "$secret" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null || true
done

info "Local secrets/gcp-sa.json for Docker (if missing)..."
mkdir -p secrets
if [[ ! -f secrets/gcp-sa.json ]]; then
  gcloud iam service-accounts keys create secrets/gcp-sa.json \
    --iam-account="${RUNTIME_EMAIL}" \
    --project="$PROJECT_ID"
  info "  Created secrets/gcp-sa.json (gitignored)"
else
  info "  secrets/gcp-sa.json already exists — skipped"
fi

info "Firewall (legacy VM only — skipped; use Cloud Run bootstrap for HTTPS)..."
if gcloud compute firewall-rules describe allow-pressplay-8000 --project="$PROJECT_ID" >/dev/null 2>&1; then
  info "  allow-pressplay-8000 exists — delete via gcp-cloudrun-bootstrap.sh for production"
else
  info "  no allow-pressplay-8000 rule (good for Cloud Run production)"
fi

info "Compute VM..."
if ! gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$ZONE" \
    --machine-type=e2-standard-4 \
    --boot-disk-size=100GB \
    --tags=pressplay-http \
    --service-account="${RUNTIME_EMAIL}" \
    --scopes=https://www.googleapis.com/auth/cloud-platform \
    --metadata-from-file=startup-script="$ROOT/scripts/gcp-vm-startup.sh"
else
  info "  VM $VM_NAME already exists"
fi

EXTERNAL_IP="$(gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"
info ""
info "Bootstrap complete."
info "  VM: $VM_NAME ($ZONE) → http://${EXTERNAL_IP}:8000 (after first deploy)"
info "  Image: $AR_IMAGE:latest"
info ""
info "GitHub repository variables (Settings → Secrets and variables → Actions → Variables):"
info "  GCP_PROJECT_ID=$PROJECT_ID"
info "  GCP_REGION=$REGION"
info "  GCP_ZONE=$ZONE"
info "  GCP_VM_NAME=$VM_NAME"
info "  GCP_AR_REPOSITORY=$AR_REPO"
info "  GCP_IMAGE_NAME=$IMAGE_NAME"
info ""
info "No GitHub secrets required if WIF pool github-pool / provider github-provider is already configured."
info "Push to main to run CI + deploy, or trigger Deploy workflow manually."
