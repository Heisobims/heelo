# Tixdoo

**Every great event starts with tixdoo.**

All-in-one event management platform built for Africa and the world.

---

## Quick start (Docker)

```bash
cp .env.example .env
# Fill in the required secrets in .env

docker compose up --build
```

App: http://localhost:8000  
API docs: http://localhost:8000/api/docs  
Flower (Celery): http://localhost:5555

---

## Local development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pre-commit install

cp .env.example .env               # fill in DATABASE_URL, SECRET_KEY, etc.

alembic upgrade head               # run all migrations

uvicorn app.main:app --reload      # http://localhost:8000
```

In a separate terminal:

```bash
celery -A app.tasks.celery_app worker --loglevel=info
```

---

## Database migrations

```bash
# After changing a model:
alembic revision --autogenerate -m "describe the change"
alembic upgrade head

# Roll back one step:
alembic downgrade -1
```

---

## Running tests

```bash
pytest
```

---

## Tech stack

| Layer | Choice |
|---|---|
| Framework | FastAPI (Python 3.12) |
| Database | PostgreSQL 16 + SQLAlchemy 2 (async) |
| Migrations | Alembic |
| Frontend | Jinja2 + HTMX + Alpine.js |
| Jobs | Celery + Redis |
| Payments | Paystack / Flutterwave / Stripe |
| WhatsApp | Meta Cloud API |
| Email | Resend |
| SMS | Termii / Twilio |
| Storage | Cloudflare R2 |
| AI | Anthropic Claude (SSE streaming) |
| Deployment | Docker + Nginx |
