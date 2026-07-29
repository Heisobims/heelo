.PHONY: test test-fast lint format migrate dev \
        docker-build docker-up docker-down docker-logs docker-shell \
        certbot-init db-shell

# ── Test ─────────────────────────────────────────────────────────────────────
test:
	TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/heelo_test \
	TEST_DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@localhost:5432/heelo_test \
	pytest

test-fast:
	TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/heelo_test \
	TEST_DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@localhost:5432/heelo_test \
	pytest -x --no-cov -q

test-ci:
	pytest --cov=app --cov-report=xml -q

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check app tests
	ruff format --check app tests

format:
	ruff format app tests
	isort app tests

# ── DB ────────────────────────────────────────────────────────────────────────
migrate:
	alembic upgrade head

# ── Dev server (no Docker) ────────────────────────────────────────────────────
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ── Docker ───────────────────────────────────────────────────────────────────
docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f --tail=100

docker-shell:
	docker compose exec app bash

# ── Production (no override file) ────────────────────────────────────────────
prod-up:
	docker compose -f docker-compose.yml up -d

prod-down:
	docker compose -f docker-compose.yml down

# ── SSL — run once to issue a Let's Encrypt cert ─────────────────────────────
# Usage: make certbot-init DOMAIN=heelo.io EMAIL=you@example.com
certbot-init:
	docker compose -f docker-compose.yml run --rm certbot \
	    certonly --webroot -w /var/www/certbot \
	    -d $(DOMAIN) -d www.$(DOMAIN) \
	    --email $(EMAIL) --agree-tos --no-eff-email

# ── Database shell ────────────────────────────────────────────────────────────
db-shell:
	docker compose exec db psql -U heelo -d heelo
