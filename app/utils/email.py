from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.config import settings

logger = structlog.get_logger()


def send_smtp(to: str | list[str], subject: str, html: str) -> None:
    """
    Single SMTP sender used for every outbound email in the app (OTP, password
    reset, welcome, team invites, and - via email_service.py - registration
    confirmations, reminders, and waitlist notices).
    """
    recipients = [to] if isinstance(to, str) else list(to)
    if not settings.SMTP_HOST:
        logger.warning("email.skipped_no_smtp_host", to=recipients, subject=subject)
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html, "html"))

        context = ssl.create_default_context()

        # Explicit timeout - smtplib's socket has no timeout by default, so a
        # blocked/dropped connection (e.g. a network that filters SMTP ports)
        # would otherwise hang indefinitely instead of failing.
        if settings.SMTP_SSL:
            with smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=10
            ) as server:
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_FROM_EMAIL, recipients, msg.as_string())
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                if settings.SMTP_TLS:
                    server.starttls(context=context)
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_FROM_EMAIL, recipients, msg.as_string())

        logger.info("email.sent", to=recipients, subject=subject)
    except Exception as exc:
        logger.error("email.send_failed", to=recipients, subject=subject, exc=str(exc))
        raise


async def send_otp_email(email: str, name: str, otp: str) -> None:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; background: #fff; color: #0A0A0A; max-width: 520px; margin: 0 auto; padding: 40px 24px;">
      <p style="font-size: 24px; font-weight: 700; margin: 0 0 8px;">tixdoo</p>
      <h1 style="font-size: 28px; font-weight: 700; margin: 32px 0 8px;">Your verification code</h1>
      <p style="font-size: 15px; color: #6B6B6B; margin: 0 0 32px;">Hi {name}, use this code to verify your email address. It expires in {settings.OTP_EXPIRE_MINUTES} minutes.</p>
      <div style="background: #F7F7F5; border-radius: 12px; padding: 32px; text-align: center; margin-bottom: 32px;">
        <p style="font-size: 48px; font-weight: 700; letter-spacing: 12px; margin: 0; font-family: monospace;">{otp}</p>
      </div>
      <p style="font-size: 13px; color: #ADADAD;">If you didn&rsquo;t create a Tixdoo account, you can safely ignore this email.</p>
    </body>
    </html>
    """
    await asyncio.to_thread(send_smtp, email, "Your Tixdoo verification code", html)


async def send_password_reset_email(email: str, name: str, reset_url: str) -> None:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; background: #fff; color: #0A0A0A; max-width: 520px; margin: 0 auto; padding: 40px 24px;">
      <p style="font-size: 24px; font-weight: 700; margin: 0 0 8px;">tixdoo</p>
      <h1 style="font-size: 28px; font-weight: 700; margin: 32px 0 8px;">Reset your password</h1>
      <p style="font-size: 15px; color: #6B6B6B; margin: 0 0 32px;">Hi {name}, click the button below to set a new password. This link expires in 60 minutes.</p>
      <a href="{reset_url}" style="display: inline-block; background: #E85938; color: #FFFFFF; font-weight: 600; font-size: 15px; text-decoration: none; padding: 14px 28px; border-radius: 100px; margin-bottom: 32px;">Reset password</a>
      <p style="font-size: 13px; color: #ADADAD;">If you didn&rsquo;t request a password reset, you can safely ignore this email. Your password won&rsquo;t change.</p>
      <p style="font-size: 12px; color: #ADADAD; margin-top: 8px;">Or copy this link: {reset_url}</p>
    </body>
    </html>
    """
    await asyncio.to_thread(send_smtp, email, "Reset your Tixdoo password", html)


async def send_welcome_email(email: str, name: str) -> None:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; background: #fff; color: #0A0A0A; max-width: 520px; margin: 0 auto; padding: 40px 24px;">
      <p style="font-size: 24px; font-weight: 700; margin: 0 0 8px;">tixdoo</p>
      <h1 style="font-size: 28px; font-weight: 700; margin: 32px 0 8px;">Welcome, {name}.</h1>
      <p style="font-size: 15px; color: #6B6B6B; margin: 0 0 32px;">Your account is ready. Every great event starts here.</p>
      <a href="{settings.FRONTEND_URL}/dashboard" style="display: inline-block; background: #E85938; color: #FFFFFF; font-weight: 600; font-size: 15px; text-decoration: none; padding: 14px 28px; border-radius: 100px;">Go to your dashboard</a>
    </body>
    </html>
    """
    await asyncio.to_thread(send_smtp, email, "Welcome to Tixdoo", html)


async def send_team_invite_email(
    email: str,
    inviter_name: str,
    org_name: str,
    invite_url: str,
    brand_color: str | None = None,
) -> None:
    from app.utils.color import contrasting_text_color

    button_bg = brand_color or "#E85938"
    button_text = contrasting_text_color(brand_color, "#FFFFFF")
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; background: #fff; color: #0A0A0A; max-width: 520px; margin: 0 auto; padding: 40px 24px;">
      <p style="font-size: 24px; font-weight: 700; margin: 0 0 8px;">tixdoo</p>
      <h1 style="font-size: 28px; font-weight: 700; margin: 32px 0 8px;">You&rsquo;ve been invited</h1>
      <p style="font-size: 15px; color: #6B6B6B; margin: 0 0 32px;">{inviter_name} has invited you to join <strong>{org_name}</strong> on Tixdoo.</p>
      <a href="{invite_url}" style="display: inline-block; background: {button_bg}; color: {button_text}; font-weight: 600; font-size: 15px; text-decoration: none; padding: 14px 28px; border-radius: 100px; margin-bottom: 32px;">Accept invitation</a>
      <p style="font-size: 13px; color: #ADADAD;">This invitation expires in 24 hours.</p>
    </body>
    </html>
    """
    await asyncio.to_thread(send_smtp, email, f"You're invited to join {org_name} on Tixdoo", html)
