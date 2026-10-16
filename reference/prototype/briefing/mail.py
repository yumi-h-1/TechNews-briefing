import hashlib
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import format_datetime

import httpx


class DeliveryUncertain(RuntimeError):
    """Provider may have accepted the message: do not automatically resend."""


def send_email(settings, payload, day, now):
    key = "briefing-" + hashlib.sha256(f"{settings.recipient}:{day}".encode()).hexdigest()[:32]
    if settings.transport == "resend":
        try:
            response = httpx.post(
                "https://api.resend.com/emails", timeout=30,
                headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"], "Idempotency-Key": key},
                json={"from": settings.sender, "to": [settings.recipient],
                      "subject": payload["subject"], "html": payload["html"], "text": payload["text"]},
            )
        except httpx.HTTPError as exc:
            raise DeliveryUncertain("Email API response unknown; inspect provider logs") from exc
        if response.status_code >= 500:
            raise DeliveryUncertain("Email API server response uncertain; inspect provider logs")
        if response.status_code >= 400:
            # Do not include the raw provider response or any secret in logs.
            raise RuntimeError(f"Email API rejected request (HTTP {response.status_code})")
        try:
            return response.json()["id"]
        except (ValueError, KeyError) as exc:
            raise DeliveryUncertain("Email API accepted request without a readable message ID") from exc

    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = settings.recipient
    message["Subject"] = payload["subject"]
    message["Date"] = format_datetime(now)
    message["Message-ID"] = f"<{key}@personal-it-briefing.local>"
    message.set_content(payload["text"])
    message.add_alternative(payload["html"], subtype="html")
    smtp = smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                            int(os.getenv("SMTP_PORT", "465")),
                            context=ssl.create_default_context(), timeout=30)
    try:
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"].replace(" ", ""))
        try:
            smtp.send_message(message)
        except Exception as exc:
            raise DeliveryUncertain("SMTP result unknown; check Sent mail before retrying") from exc
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()  # A lost QUIT response must never cause a resend.
    return str(message["Message-ID"])
