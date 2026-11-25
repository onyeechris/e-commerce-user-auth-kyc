import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS = 10

_SUBJECTS = {
    "email_verification": "Verify your email",
    "password_reset": "Reset your password",
}


def _mail_configured() -> bool:
    return bool(settings.MAIL_API_KEY and settings.MAIL_SENDER_EMAIL)


def send_otp_email(to_email: str, code: str, purpose: str) -> None:
    """Blocking call; invoke through run_in_threadpool from async code."""
    if not _mail_configured():
        if settings.ENVIRONMENT == "development" and settings.LOG_OTP_CODES:
            # Local convenience only: without a Resend key, show the code in the server log.
            # Never enable where logs are shipped to Loki: anyone who can read them could take over accounts.
            logger.warning("DEV ONLY - mail not configured. %s code for %s: %s", purpose, to_email, code)
            return
        raise RuntimeError("Mail is not configured (MAIL_API_KEY / MAIL_SENDER_EMAIL)")

    response = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {settings.MAIL_API_KEY}"},
        json={
            "from": f"{settings.MAIL_SENDER_NAME} <{settings.MAIL_SENDER_EMAIL}>",
            "to": [to_email],
            "subject": _SUBJECTS.get(purpose, "Your verification code"),
            "text": f"Your code is {code}. It expires in {settings.OTP_TTL_MINUTES} minutes. "
            "If you did not request it, you can ignore this email.",
        },
        timeout=RESEND_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Mail send failed: {response.status_code} {response.text}")
