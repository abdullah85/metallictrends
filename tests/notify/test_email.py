from unittest.mock import Mock, patch

import pytest
import requests

from metallictrends.notify.email import (
    EmailNotConfiguredError,
    EmailSendTimeoutError,
    send_otp_email,
)


def _mock_response(status_code, text=""):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    return resp


def test_send_otp_email_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(EmailNotConfiguredError):
        send_otp_email("person@example.com", "123456")


def test_send_otp_email_posts_to_resend_api(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("RESEND_FROM", raising=False)
    with patch(
        "metallictrends.notify.email.requests.post", return_value=_mock_response(200)
    ) as mock_post:
        send_otp_email("person@example.com", "123456")

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"
    assert kwargs["json"]["to"] == ["person@example.com"]
    assert "123456" in kwargs["json"]["text"]
    assert kwargs["json"]["from"] == "MetallicTrends <onboarding@resend.dev>"
    assert kwargs["timeout"] == 15


def test_send_otp_email_uses_custom_from_address_when_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESEND_FROM", "MetallicTrends <ops@metallictrends.com>")
    with patch("metallictrends.notify.email.requests.post", return_value=_mock_response(200)) as mock_post:
        send_otp_email("person@example.com", "123456")
    assert mock_post.call_args.kwargs["json"]["from"] == "MetallicTrends <ops@metallictrends.com>"


def test_send_otp_email_raises_on_non_2xx_response(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    with patch(
        "metallictrends.notify.email.requests.post",
        return_value=_mock_response(422, text="invalid recipient"),
    ):
        with pytest.raises(RuntimeError, match="422"):
            send_otp_email("person@example.com", "123456")


def test_send_otp_email_wraps_timeout_error(monkeypatch):
    """A hung/blocked outbound connection raises a clear, specific exception
    the caller can distinguish from other failures — not a bare
    requests.exceptions.Timeout, and critically, not an indefinite hang (the
    15s timeout passed to requests.post is what turns a hang into this)."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    with patch(
        "metallictrends.notify.email.requests.post",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with pytest.raises(EmailSendTimeoutError):
            send_otp_email("person@example.com", "123456")
