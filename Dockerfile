# ── Build stage ───────────────────────────────────────────────────────────────
# Installs Python packages in an isolated layer; only compile deps needed here.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
# Only runtime shared libs - no gcc, no build-essential.
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client lib (asyncpg / psycopg2 runtime)
    libpq5 \
    # WeasyPrint PDF rendering
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    shared-mime-info \
    # Health check
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN addgroup --system tixdoo && adduser --system --ingroup tixdoo --no-create-home tixdoo

WORKDIR /app

# Python packages from builder (no re-download in runtime layer)
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Application source
COPY --chown=tixdoo:tixdoo . .

# Make entrypoint scripts executable
RUN chmod +x scripts/entrypoint.sh scripts/worker.sh scripts/beat.sh

USER tixdoo

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
