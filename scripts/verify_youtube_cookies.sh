#!/usr/bin/env bash
# Verify pressplay-youtube-cookies in Secret Manager (size + tab rows; never prints values).
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-project-3bb9c91c-69ed-4507-998}"
SECRET_NAME="${YOUTUBE_COOKIES_SECRET:-pressplay-youtube-cookies}"
MIN_BYTES="${YOUTUBE_COOKIES_MIN_BYTES:-2000}"
MIN_ROWS="${YOUTUBE_COOKIES_MIN_ROWS:-10}"

if [[ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  if [[ -f "${REPO_ROOT}/secrets/gcp-sa.json" ]]; then
    export GOOGLE_APPLICATION_CREDENTIALS="${REPO_ROOT}/secrets/gcp-sa.json"
  fi
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

gcloud secrets versions access latest \
  --secret="${SECRET_NAME}" \
  --project="${PROJECT_ID}" >"$TMP"

BYTES=$(wc -c <"$TMP" | tr -d ' ')
ROWS=$(grep -c $'\t' "$TMP" || true)

echo "secret=${SECRET_NAME} project=${PROJECT_ID}"
echo "bytes=${BYTES} tab_rows=${ROWS}"
echo "thresholds: min_bytes=${MIN_BYTES} min_rows=${MIN_ROWS}"

OK=0
if [[ "$BYTES" -lt "$MIN_BYTES" ]]; then
  echo "FAIL: secret too small (likely placeholder header only; expect thousands of bytes)"
  OK=1
fi
if [[ "$ROWS" -lt "$MIN_ROWS" ]]; then
  echo "FAIL: too few tab-separated cookie rows (need logged-in YouTube session cookies)"
  OK=1
fi

if [[ "$OK" -eq 0 ]]; then
  echo "OK: secret looks like a real Netscape cookies.txt"
  exit 0
fi
echo "See docs/DEPLOY_GCP.md § YouTube cookies for export and upload steps."
exit 1
