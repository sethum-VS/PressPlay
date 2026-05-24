#!/usr/bin/env bash
# Smoke test: health, guest session, mock job, newsroom (requires API on :8000).
set -euo pipefail

BASE="${1:-http://localhost:8000}"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

curl -sf "$BASE/health" | grep -q '"ok"'
curl -sf "$BASE/health/ready" | grep -q '"ok"'

curl -sf -c "$COOKIE_JAR" "$BASE/" >/dev/null
test -s "$COOKIE_JAR"

JOB_JSON=$(curl -sf -b "$COOKIE_JAR" -X POST "$BASE/api/v1/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"youtube_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","mode":"quick"}')
JOB_ID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$JOB_JSON")

for _ in $(seq 1 60); do
  STATUS=$(curl -sf -b "$COOKIE_JAR" "$BASE/api/v1/jobs/$JOB_ID" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
  if [[ "$STATUS" == "done" ]]; then
    break
  fi
  sleep 1
done

[[ "$STATUS" == "done" ]]
curl -sf -b "$COOKIE_JAR" "$BASE/newsroom/$JOB_ID" | grep -q "Press"
echo "smoke_mvp: OK (job $JOB_ID)"
