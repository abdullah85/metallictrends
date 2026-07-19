"""
metallictrends.notify.email

Sends the admin one-time login code via a dedicated service Gmail account
(never the operator's personal address) over SMTP with an App Password.

Required environment variables:
  GMAIL_ADDRESS      - the service Gmail account, e.g. metallictrends.noreply@gmail.com
  GMAIL_APP_PASSWORD - a Google App Password for that account (not its login password)
"""

import os
import smtplib
from email.message import EmailMessage

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587
_SMTP_TIMEOUT_SECONDS = 15


class EmailNotConfiguredError(Exception):
    """Raised when GMAIL_ADDRESS/GMAIL_APP_PASSWORD aren't set."""


class EmailSendTimeoutError(Exception):
    """Raised when the SMTP connection doesn't complete within
    _SMTP_TIMEOUT_SECONDS — smtplib.SMTP has no timeout by default, so
    without this a blocked or silently-dropped outbound connection (some
    PaaS platforms restrict outbound SMTP) would hang the request forever
    instead of failing with a clear error."""


def send_otp_email(to_email: str, code: str) -> None:
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not gmail_address or not gmail_app_password:
        raise EmailNotConfiguredError("GMAIL_ADDRESS/GMAIL_APP_PASSWORD are not configured.")

    msg = EmailMessage()
    msg["Subject"] = "Your MetallicTrends admin login code"
    msg["From"] = f"MetallicTrends <{gmail_address}>"
    msg["To"] = to_email
    msg.set_content(
        f"Your one-time login code is: {code}\n\n"
        "This code expires in 10 minutes and can only be used once.\n"
        "If you didn't request this, you can safely ignore this email."
    )

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.starttls()
            smtp.login(gmail_address, gmail_app_password)
            smtp.send_message(msg)
    except TimeoutError as exc:
        raise EmailSendTimeoutError(
            f"Connecting to {_SMTP_HOST}:{_SMTP_PORT} timed out after {_SMTP_TIMEOUT_SECONDS}s — "
            "the network this is running on may be blocking outbound SMTP."
        ) from exc
