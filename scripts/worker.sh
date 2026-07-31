#!/usr/bin/env bash
set -euo pipefail

CONCURRENCY="${CELERY_CONCURRENCY:-4}"
# Must cover every queue named in task_routes (app/tasks/celery_app.py) plus the
# default "celery" queue — otherwise routed tasks (email/whatsapp/webhooks/...)
# are published but never consumed.
QUEUES="${CELERY_QUEUES:-celery,email,whatsapp,webhooks,notifications}"

echo "[worker] Starting Celery worker (concurrency=${CONCURRENCY}, queues=${QUEUES})..."
exec celery -A app.tasks.celery_app worker \
    --loglevel=info \
    --concurrency="${CONCURRENCY}" \
    --queues="${QUEUES}" \
    --without-gossip \
    --without-mingle \
    --without-heartbeat
