#!/usr/bin/env bash
set -euo pipefail

CONCURRENCY="${CELERY_CONCURRENCY:-4}"
QUEUES="${CELERY_QUEUES:-celery}"

echo "[worker] Starting Celery worker (concurrency=${CONCURRENCY}, queues=${QUEUES})..."
exec celery -A app.tasks.celery_app worker \
    --loglevel=info \
    --concurrency="${CONCURRENCY}" \
    --queues="${QUEUES}" \
    --without-gossip \
    --without-mingle \
    --without-heartbeat
