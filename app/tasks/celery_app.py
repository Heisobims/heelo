from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "heelo",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.email",
        "app.tasks.whatsapp",
        "app.tasks.campaign",
        "app.tasks.ai_tasks",
        "app.tasks.webhooks",
        "app.tasks.admin_broadcast",
        "app.tasks.ticketing",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.tasks.email.*": {"queue": "email"},
        "app.tasks.whatsapp.*": {"queue": "whatsapp"},
        "app.tasks.webhooks.*": {"queue": "webhooks"},
        "app.tasks.notifications.*": {"queue": "notifications"},
        "app.tasks.admin_broadcast.*": {"queue": "email"},
    },
    beat_schedule={
        "email-reminders-hourly": {
            "task": "app.tasks.email.send_event_reminders",
            "schedule": 3600.0,
        },
        "email-interest-nudges-hourly": {
            "task": "app.tasks.email.send_interest_nudges",
            "schedule": 3600.0,
        },
        "email-feedback-requests-hourly": {
            "task": "app.tasks.email.send_feedback_requests",
            "schedule": 3600.0,
        },
        "whatsapp-reminders-hourly": {
            "task": "app.tasks.whatsapp.send_event_reminders",
            "schedule": 3600.0,
        },
        "scheduled-campaigns-hourly": {
            "task": "app.tasks.campaign.send_scheduled_campaigns",
            "schedule": 3600.0,
        },
        "webhook-retries-every-minute": {
            "task": "app.tasks.webhooks.retry_failed_webhooks",
            "schedule": 60.0,
        },
        "release-stale-reservations-every-5-min": {
            "task": "app.tasks.ticketing.release_stale_reservations",
            "schedule": 300.0,
        },
        "expire-waitlist-offers-every-10-min": {
            "task": "app.tasks.ticketing.expire_waitlist_offers",
            "schedule": 600.0,
        },
    },
)
