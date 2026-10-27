"""Gunicorn configuration for production."""
import multiprocessing
import os

# ── Workers ───────────────────────────────────────────────────────────────────
# UvicornWorker runs the async app inside each gunicorn process.
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_connections = 1000
threads = 1

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = 120          # kill unresponsive workers after 2 min
graceful_timeout = 30  # seconds to finish in-flight requests on SIGTERM
keepalive = 5          # keep-alive connections after response

# ── Binding ───────────────────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
preload_app = True     # load app before forking (saves memory via copy-on-write)

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"        # stdout
errorlog = "-"         # stderr
loglevel = "warning"
access_log_format = (
    '{"time":"%(t)s","method":"%(m)s","path":"%(U)s","qs":"%(q)s",'
    '"status":%(s)s,"bytes":%(b)s,"duration_ms":%(D)s,"referer":"%(f)s"}'
)

# ── Process ───────────────────────────────────────────────────────────────────
proc_name = "tixdoo"

# ── Hooks ─────────────────────────────────────────────────────────────────────
def on_starting(server):  # noqa: N802
    server.log.info("Tixdoo gunicorn master starting.")


def worker_exit(server, worker):  # noqa: N802
    server.log.info("Worker %s exiting.", worker.pid)
