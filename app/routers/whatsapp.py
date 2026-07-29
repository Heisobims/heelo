"""
WhatsApp Business Cloud API webhook endpoints.

GET  /api/v1/webhooks/whatsapp  — Meta verification handshake
POST /api/v1/webhooks/whatsapp  — Incoming messages & status updates
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.config import settings

router_whatsapp = APIRouter(prefix="/api/v1/webhooks", tags=["whatsapp"])


# ── Webhook verification ──────────────────────────────────────────────────────

@router_whatsapp.get("/whatsapp", response_class=PlainTextResponse)
async def whatsapp_verify(request: Request) -> str:
    """
    Meta sends a GET request with:
      hub.mode        = "subscribe"
      hub.verify_token = <our WHATSAPP_VERIFY_TOKEN>
      hub.challenge   = <random string>

    We must respond with the challenge value to confirm ownership.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return challenge

    raise HTTPException(403, "Webhook verification failed.")


# ── Incoming messages ─────────────────────────────────────────────────────────

@router_whatsapp.post("/whatsapp", status_code=200)
async def whatsapp_incoming(request: Request) -> dict:
    """
    Handle incoming WhatsApp messages and status updates.
    Respond with 200 immediately; dispatch bot replies via Celery.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ok"}  # Meta requires 200 even on bad payloads

    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ok"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])

            for msg in messages:
                if msg.get("type") != "text":
                    continue  # only handle text messages for now
                from_phone = msg.get("from", "")
                text = msg.get("text", {}).get("body", "")
                if from_phone and text:
                    # Dispatch to Celery — never block the 200 response
                    try:
                        from app.tasks.whatsapp import handle_incoming_message
                        handle_incoming_message.delay(from_phone, text)
                    except Exception:
                        pass  # Celery not available? Respond 200 anyway

    return {"status": "ok"}
