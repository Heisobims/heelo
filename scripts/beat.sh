#!/usr/bin/env bash
set -euo pipefail

echo "[beat] Starting Celery Beat..."
exec celery -A app.tasks.celery_app beat \
    --loglevel=info \
    --max-interval 5
