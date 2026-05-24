#!/usr/bin/env bash
# PressPlay local dev launcher — dependency checks, GCP/ADC, optional LLM smoke, uvicorn.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VERIFY_LLM=0
SKIP_SERVER=0

info() { printf '%s\n' "$*"; }
ok() { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*" >&2; }
die() { printf '  [fail] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: ./run.sh [OPTIONS]

Verify local dependencies and GCP (Pattern C ADC), then start the API server.

Options:
  --verify-llm   Run scripts/verify_gcp.py (Vertex smoke via GeminiAdapter)
  --skip-server  Run checks only; do not start uvicorn
  -h, --help     Show this help

Examples:
  ./run.sh
  ./run.sh --verify-llm
  ./run.sh --skip-server --verify-llm
EOF
}

for arg in "$@"; do
  case "$arg" in
    --verify-llm) VERIFY_LLM=1 ;;
    --skip-server) SKIP_SERVER=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $arg (try --help)"
      ;;
  esac
done

info "PressPlay — checking local environment..."

# --- Python / venv ---
if ! command -v python3 >/dev/null 2>&1; then
  die "python3 not found on PATH"
fi
ok "python3: $(python3 --version 2>&1 | head -1)"

VENV_DIR="$ROOT/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  info "Creating virtualenv at .venv ..."
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
ok "venv: $VENV_DIR"

info "Installing / verifying pip dependencies..."
if ! python -m pip install -q -r "$ROOT/requirements.txt"; then
  die "pip install -r requirements.txt failed"
fi

python - <<'PY' || die "Python imports from requirements.txt failed"
import importlib
mods = (
    "fastapi",
    "uvicorn",
    "pydantic_settings",
    "yt_dlp",
    "google.genai",
    "graphify",
)
for name in mods:
    importlib.import_module(name)
print("imports ok")
PY
ok "pip packages from requirements.txt"

# --- External tools ---
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg: $(command -v ffmpeg)"
else
  die "ffmpeg not on PATH (brew install ffmpeg / apt install ffmpeg)"
fi

if command -v yt-dlp >/dev/null 2>&1; then
  ok "yt-dlp: $(command -v yt-dlp)"
elif python -c "import yt_dlp" 2>/dev/null; then
  ok "yt-dlp: python module yt_dlp"
else
  die "yt-dlp not found (pip install yt-dlp or install yt-dlp binary)"
fi

MEMVID_OK=0
if command -v memvid >/dev/null 2>&1; then
  ok "memvid: $(command -v memvid)"
  MEMVID_OK=1
fi
if [[ "$MEMVID_OK" -eq 0 ]]; then
  warn "memvid CLI not found — ingest uses YouTube captions fallback only:"
  warn "  npm install -g memvid-cli  OR  cargo install memvid-cli --features whisper"
  warn "  pip install memvid-sdk"
fi

GRAPHIFY_OK=0
for name in graphify graphifyy; do
  if command -v "$name" >/dev/null 2>&1; then
    ok "graphify: $(command -v "$name")"
    GRAPHIFY_OK=1
    break
  fi
done
if [[ "$GRAPHIFY_OK" -eq 0 && -x "$VENV_DIR/bin/graphify" ]]; then
  ok "graphify: $VENV_DIR/bin/graphify"
  GRAPHIFY_OK=1
fi
if [[ "$GRAPHIFY_OK" -eq 0 ]]; then
  warn "graphify CLI not on PATH — pipeline uses heuristic graph unless graphifyy is installed"
  warn "  pip install graphifyy  (or set GRAPHIFY_BIN in .env)"
fi

mkdir -p "$ROOT/data/jobs" "$ROOT/data/results"
ok "data dirs: data/jobs, data/results"

# --- .env (do not print values) ---
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  ok "loaded .env (values not shown)"
else
  warn "no .env file — copy .env.example to .env and set GCP_PROJECT_ID"
fi

# --- GCP ---
PROJECT="${GCP_PROJECT_ID:-${VERTEX_PROJECT:-}}"
LOCATION="${GCP_LOCATION:-${VERTEX_LOCATION:-}}"

if [[ -z "$PROJECT" ]]; then
  die "GCP_PROJECT_ID (or VERTEX_PROJECT) is not set — edit .env before live Vertex use"
fi
if [[ -z "$LOCATION" ]]; then
  LOCATION="us-central1"
  export GCP_LOCATION="$LOCATION"
  warn "GCP_LOCATION unset — defaulting to us-central1"
fi
ok "GCP project configured (location=${LOCATION})"

MOCK_LLM_RAW="${MOCK_LLM:-false}"
MOCK_LLM_LC="$(printf '%s' "$MOCK_LLM_RAW" | tr '[:upper:]' '[:lower:]')"
if [[ "$MOCK_LLM_LC" == "true" || "$MOCK_LLM_LC" == "1" || "$MOCK_LLM_LC" == "yes" ]]; then
  warn "MOCK_LLM is enabled — Watcher/Writer use canned output (ingest may still run)"
fi

if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  if [[ -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
    ok "credentials: service account file (GOOGLE_APPLICATION_CREDENTIALS set)"
  else
    die "GOOGLE_APPLICATION_CREDENTIALS points to missing file. Local ADC: unset it and run gcloud auth application-default login"
  fi
else
  if ! command -v gcloud >/dev/null 2>&1; then
    die "gcloud CLI not found — install Google Cloud SDK for ADC (Pattern C local dev)"
  fi
  if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    die "Application Default Credentials unavailable. Run: gcloud auth application-default login"
  fi
  ok "credentials: Application Default Credentials (ADC)"
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

if [[ "$VERIFY_LLM" -eq 1 ]]; then
  info "Running Vertex LLM smoke test..."
  if ! python "$ROOT/scripts/verify_gcp.py"; then
    die "LLM verification failed (see errors above)"
  fi
  ok "LLM verification passed"
fi

if [[ "$SKIP_SERVER" -eq 1 ]]; then
  info "Checks complete (--skip-server)."
  exit 0
fi

info "Starting uvicorn on http://0.0.0.0:8000 ..."
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
