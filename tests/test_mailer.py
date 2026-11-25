import logging

import pytest

from app.core.config import settings
from app.services import mailer


class _Resp:
    def __init__(self, status_code=200, text="{}"):
        self.status_code = status_code
        self.text = text


def test_development_without_key_logs_code(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "MAIL_API_KEY", "")
    monkeypatch.setattr(settings, "LOG_OTP_CODES", True)
    monkeypatch.setattr(mailer.requests, "post", lambda *a, **k: pytest.fail("must not call Resend"))
    with caplog.at_level(logging.WARNING):
        mailer.send_otp_email("a@example.com", "123456", "email_verification")
    assert "123456" in caplog.text


def test_development_without_opt_in_does_not_log_code(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "MAIL_API_KEY", "")
    monkeypatch.setattr(settings, "LOG_OTP_CODES", False)
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError):
        mailer.send_otp_email("a@example.com", "123456", "email_verification")
    assert "123456" not in caplog.text


def test_non_development_without_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "MAIL_API_KEY", "")
    with pytest.raises(RuntimeError):
        mailer.send_otp_email("a@example.com", "123456", "email_verification")


def test_sends_to_resend(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "MAIL_API_KEY", "re_test")
    monkeypatch.setattr(settings, "MAIL_SENDER_EMAIL", "noreply@example.com")
    calls = {}

    def fake_post(url, headers, json, timeout):
        calls.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Resp(200)

    monkeypatch.setattr(mailer.requests, "post", fake_post)
    mailer.send_otp_email("ada@example.com", "654321", "password_reset")
    assert calls["url"] == "https://api.resend.com/emails"
    assert calls["headers"]["Authorization"] == "Bearer re_test"
    assert calls["json"]["to"] == ["ada@example.com"]
    assert calls["json"]["from"] == "Marketly <noreply@example.com>"
    assert calls["json"]["subject"] == "Reset your password"
    assert "654321" in calls["json"]["text"]


def test_resend_error_raises(monkeypatch):
    monkeypatch.setattr(settings, "MAIL_API_KEY", "re_test")
    monkeypatch.setattr(settings, "MAIL_SENDER_EMAIL", "noreply@example.com")
    monkeypatch.setattr(mailer.requests, "post", lambda *a, **k: _Resp(403, "domain not verified"))
    with pytest.raises(RuntimeError, match="403"):
        mailer.send_otp_email("a@example.com", "123456", "email_verification")
