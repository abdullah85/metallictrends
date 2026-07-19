"""
metallictrends.notify.email

Sends the admin one-time login code via Resend's HTTP API — not SMTP.
Render's outbound network blocks SMTP entirely (confirmed live: raw socket
connections to smtp.gmail.com:587 fail with "Network is unreachable"), so
this uses a plain HTTPS POST instead, the same way this project already
talks to the GitHub and metals.dev APIs.

Required environment variables:
  RESEND_API_KEY - API key from resend.com

Optional:
  RESEND_FROM - sender address, e.g. "MetallicTrends <you@yourdomain.com>"
                once you've verified a domain with Resend. Defaults to
                Resend's shared onboarding@resend.dev test sender, which
                works with no domain verification.
"""

import os

import requests

_RESEND_API_URL = "https://api.resend.com/emails"
_DEFAULT_FROM = "MetallicTrends <onboarding@resend.dev>"
_REQUEST_TIMEOUT_SECONDS = 15


class EmailNotConfiguredError(Exception):
    """Raised when RESEND_API_KEY isn't set."""


class EmailSendTimeoutError(Exception):
    """Raised when the request to Resend doesn't complete within
    _REQUEST_TIMEOUT_SECONDS — kept distinct from other failures so the
    caller can tell "slow/unreachable network" apart from e.g. a bad API key."""


def send_otp_email(to_email: str, code: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EmailNotConfiguredError("RESEND_API_KEY is not configured.")
    from_address = os.environ.get("RESEND_FROM", _DEFAULT_FROM)

    payload = {
        "from": from_address,
        "to": [to_email],
        "subject": "Your MetallicTrends admin login code",
        "text": (
            f"Your one-time login code is: {code}\n\n"
            "This code expires in 10 minutes and can only be used once.\n"
            "If you didn't request this, you can safely ignore this email."
        ),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            _RESEND_API_URL, json=payload, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS
        )
    except requests.exceptions.Timeout as exc:
        raise EmailSendTimeoutError(
            f"Resend API request timed out after {_REQUEST_TIMEOUT_SECONDS}s."
        ) from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Resend API error {response.status_code}: {response.text[:300]}")
