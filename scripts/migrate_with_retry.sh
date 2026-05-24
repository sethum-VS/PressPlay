#!/bin/sh
# Retry Alembic until Cloud SQL proxy/socket is ready (cold start).
set -e

MAX_ATTEMPTS="${MIGRATE_MAX_ATTEMPTS:-30}"
DELAY_SEC="${MIGRATE_RETRY_DELAY_SEC:-2}"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  if alembic upgrade head; then
    echo "Migrations applied (attempt ${attempt})"
    exit 0
  fi
  echo "Alembic failed (attempt ${attempt}/${MAX_ATTEMPTS}), retrying in ${DELAY_SEC}s..."
  attempt=$((attempt + 1))
  sleep "$DELAY_SEC"
done

echo "Alembic failed after ${MAX_ATTEMPTS} attempts"
exit 1
