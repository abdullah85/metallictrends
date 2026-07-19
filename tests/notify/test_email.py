from unittest.mock import MagicMock, patch

import pytest

from metallictrends.notify.email import (
    EmailNotConfiguredError,
    EmailSendTimeoutError,
    send_otp_email,
)


def test_send_otp_email_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(EmailNotConfiguredError):
        send_otp_email("person@example.com", "123456")


def test_send_otp_email_sends_via_smtp(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "metallictrends.noreply@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app password with spaces")
    mock_smtp = MagicMock()
    mock_smtp.__enter__.return_value = mock_smtp
    with patch("metallictrends.notify.email.smtplib.SMTP", return_value=mock_smtp) as mock_ctor:
        send_otp_email("person@example.com", "123456")

    mock_ctor.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
    mock_smtp.starttls.assert_called_once()
    # Spaces in the app password (as Google displays it) are stripped before use.
    mock_smtp.login.assert_called_once_with("metallictrends.noreply@gmail.com", "apppasswordwithspaces")
    mock_smtp.send_message.assert_called_once()


def test_send_otp_email_wraps_timeout_error(monkeypatch):
    """A hung/blocked outbound SMTP connection raises a clear, specific
    exception the caller can distinguish from other failures — not a bare
    socket timeout, and critically, not an indefinite hang (the 15s timeout
    passed to smtplib.SMTP is what turns a hang into this)."""
    monkeypatch.setenv("GMAIL_ADDRESS", "metallictrends.noreply@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    with patch("metallictrends.notify.email.smtplib.SMTP", side_effect=TimeoutError("timed out")):
        with pytest.raises(EmailSendTimeoutError):
            send_otp_email("person@example.com", "123456")
