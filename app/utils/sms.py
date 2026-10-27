"""
SMS delivery utility supporting Termii and Twilio.
Falls through based on configuration in app.config.settings.
"""

from __future__ import annotations

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()


def send_sms_sync(to_phone: str, message: str) -> dict:
    """Send SMS synchronously via Termii or Twilio."""
    cleaned_phone = to_phone.strip()
    if not cleaned_phone.startswith("+") and not cleaned_phone.startswith("234"):
        # Default Nigerian numbers if local 080...
        if cleaned_phone.startswith("0") and len(cleaned_phone) == 11:
            cleaned_phone = "234" + cleaned_phone[1:]

    # 1. Try Termii if configured
    if settings.TERMII_API_KEY:
        try:
            url = "https://api.ng.termii.com/api/sms/send"
            payload = {
                "to": cleaned_phone.lstrip("+"),
                "from": settings.TERMII_SENDER_ID or "Tixdoo",
                "sms": message,
                "type": "plain",
                "channel": "generic",
                "api_key": settings.TERMII_API_KEY,
            }
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                logger.info("sms.sent.termii", to=cleaned_phone, response=data)
                return {"provider": "termii", "message_id": data.get("message_id")}
        except Exception as err:
            logger.error("sms.termii_failed", to=cleaned_phone, error=str(err))
            raise

    # 2. Try Twilio if configured
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER:
        try:
            account_sid = settings.TWILIO_ACCOUNT_SID
            auth_token = settings.TWILIO_AUTH_TOKEN
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
            formatted_to = cleaned_phone if cleaned_phone.startswith("+") else f"+{cleaned_phone}"
            data = {
                "From": settings.TWILIO_PHONE_NUMBER,
                "To": formatted_to,
                "Body": message,
            }
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, data=data, auth=(account_sid, auth_token))
                resp.raise_for_status()
                res_data = resp.json()
                logger.info("sms.sent.twilio", to=formatted_to, sid=res_data.get("sid"))
                return {"provider": "twilio", "message_id": res_data.get("sid")}
        except Exception as err:
            logger.error("sms.twilio_failed", to=cleaned_phone, error=str(err))
            raise

    raise RuntimeError(
        "SMS provider is not configured. Set TERMII_API_KEY or TWILIO credentials in .env."
    )


async def send_sms_async(to_phone: str, message: str) -> dict:
    """Send SMS asynchronously via Termii or Twilio."""
    cleaned_phone = to_phone.strip()
    if not cleaned_phone.startswith("+") and not cleaned_phone.startswith("234"):
        if cleaned_phone.startswith("0") and len(cleaned_phone) == 11:
            cleaned_phone = "234" + cleaned_phone[1:]

    if settings.TERMII_API_KEY:
        try:
            url = "https://api.ng.termii.com/api/sms/send"
            payload = {
                "to": cleaned_phone.lstrip("+"),
                "from": settings.TERMII_SENDER_ID or "Tixdoo",
                "sms": message,
                "type": "plain",
                "channel": "generic",
                "api_key": settings.TERMII_API_KEY,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                logger.info("sms.sent.termii", to=cleaned_phone, response=data)
                return {"provider": "termii", "message_id": data.get("message_id")}
        except Exception as err:
            logger.error("sms.termii_failed", to=cleaned_phone, error=str(err))
            raise

    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER:
        try:
            account_sid = settings.TWILIO_ACCOUNT_SID
            auth_token = settings.TWILIO_AUTH_TOKEN
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
            formatted_to = cleaned_phone if cleaned_phone.startswith("+") else f"+{cleaned_phone}"
            data = {
                "From": settings.TWILIO_PHONE_NUMBER,
                "To": formatted_to,
                "Body": message,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, data=data, auth=(account_sid, auth_token))
                resp.raise_for_status()
                res_data = resp.json()
                logger.info("sms.sent.twilio", to=formatted_to, sid=res_data.get("sid"))
                return {"provider": "twilio", "message_id": res_data.get("sid")}
        except Exception as err:
            logger.error("sms.twilio_failed", to=cleaned_phone, error=str(err))
            raise

    raise RuntimeError(
        "SMS provider is not configured. Set TERMII_API_KEY or TWILIO credentials in .env."
    )
