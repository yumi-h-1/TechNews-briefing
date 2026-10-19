import hashlib
import os
import httpx
from briefing.config import RECIPIENT


class DeliveryUncertain(RuntimeError):
    """Provider acceptance is unknown; operator reconciliation is required."""


def send_email(settings, payload, day, now):
    if settings.recipient != RECIPIENT:
        raise ValueError("Only the project owner can receive email")
    if not settings.sender:
        raise ValueError("MAIL_FROM is required")
    key = "briefing-" + hashlib.sha256(f"{settings.recipient}:{day}".encode()).hexdigest()[:32]
    try:
        response = httpx.post("https://api.resend.com/emails", timeout=30,
                              headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"], "Idempotency-Key": key},
                              json={"from": settings.sender, "to": [RECIPIENT], "subject": payload["subject"],
                                    "html": payload["html"], "text": payload["text"]})
    except httpx.HTTPError as exc:
        raise DeliveryUncertain("Provider response unknown") from exc
    if response.status_code >= 500 or response.status_code == 409:
        raise DeliveryUncertain("Provider acceptance requires reconciliation")
    if response.status_code >= 400:
        raise RuntimeError(f"Email rejected (HTTP {response.status_code})")
    try:
        provider_id = response.json()["id"]
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("Missing provider ID")
        return provider_id
    except (ValueError, KeyError, TypeError) as exc:
        raise DeliveryUncertain("Provider returned no usable message ID") from exc
