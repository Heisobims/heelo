#!/usr/bin/env bash
set -euo pipefail

# Ensure macOS fork safety for Celery
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

echo "=================================================="
echo " Starting Tixdoo Local Development Environment"
echo " (Uvicorn + Celery Worker + Celery Beat)"
echo "=================================================="

PIDS=()

cleanup() {
    echo ""
    echo "[dev] Shutting down background processes..."
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    echo "[dev] All processes stopped."
}

trap cleanup EXIT INT TERM

# 1. Start Celery Worker
echo "[dev] Starting Celery worker (queues: celery,email,whatsapp,webhooks,notifications)..."
celery -A app.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=celery,email,whatsapp,webhooks,notifications \
    --without-gossip \
    --without-mingle \
    --without-heartbeat &
PIDS+=($!)

# 2. Start Celery Beat
echo "[dev] Starting Celery Beat..."
celery -A app.tasks.celery_app beat \
    --loglevel=info \
    --max-interval=5 &
PIDS+=($!)

# 3. Start Uvicorn Dev Server (foreground)
echo "[dev] Starting Uvicorn on http://localhost:8000..."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

