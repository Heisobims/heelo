#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head

echo "[entrypoint] Starting Gunicorn..."
exec gunicorn app.main:app -c gunicorn.conf.py
