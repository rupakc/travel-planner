import logging

import pytest

from app.core.config import settings
from app.services import account_email


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(account_email, "send_message", lambda m: sent.append(m))
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "account_token_ttl_minutes", 30)
    return sent


async def test_verify_email_contains_link_and_30_minutes(mail):
    ok = await account_email.send_account_email(
        "verify", "a@b.co", link="https://x/v?t=1", locale="en", username="ann"
    )
    assert ok and len(mail) == 1
    msg = mail[0]
    text = msg.get_body(("plain",)).get_content()
    html_ = msg.get_body(("html",)).get_content()
    for part in (text, html_):
        assert "https://x/v?t=1" in part
        assert "30 minutes" in part
        assert "ann" in part
    assert msg["To"] == "a@b.co"


async def test_html_has_no_remote_images(mail):
    for kind in ("verify", "reset", "already_registered"):
        await account_email.send_account_email(
            kind, "a@b.co", link=None, locale=None, username="ann"
        )
    for msg in mail:
        html_ = msg.get_body(("html",)).get_content().lower()
        assert "<img" not in html_ and "src=" not in html_ and "url(" not in html_


async def test_hindi_subject_used_for_hi(mail):
    await account_email.send_account_email(
        "reset", "a@b.co", link="https://x/r", locale="hi-IN", username="ann"
    )
    assert mail[0]["Subject"] == account_email._catalog("hi")["reset.subject"]
    assert mail[0]["Subject"] != account_email._catalog("en")["reset.subject"]


async def test_unknown_locale_falls_back_to_english(mail):
    await account_email.send_account_email(
        "reset", "a@b.co", link="https://x/r", locale="xx", username="ann"
    )
    assert mail[0]["Subject"] == account_email._catalog("en")["reset.subject"]


async def test_dev_link_logged_only_when_enabled(monkeypatch, caplog):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "public_base_url", "https://x.sslip.io")
    monkeypatch.setattr(settings, "email_log_links", False)
    caplog.set_level(logging.INFO)
    assert not account_email.email_delivery_available()
    ok = await account_email.send_account_email(
        "verify", "a@b.co", link="https://x/v?t=9", locale="en", username="ann"
    )
    assert ok is False
    assert "account_email.dev_link" not in caplog.text

    monkeypatch.setattr(settings, "email_log_links", True)
    assert account_email.email_delivery_available()
    ok = await account_email.send_account_email(
        "verify", "a@b.co", link="https://x/v?t=9", locale="en", username="ann"
    )
    assert ok is True
    assert "account_email.dev_link kind=verify url=https://x/v?t=9" in caplog.text
    assert "a@b.co" not in caplog.text


async def test_localhost_enables_dev_links(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "email_log_links", False)
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:5174")
    assert account_email.dev_links_enabled()


async def test_send_failure_returns_false_without_address(monkeypatch, caplog):
    def boom(_m):
        raise OSError("nope")

    monkeypatch.setattr(account_email, "send_message", boom)
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    ok = await account_email.send_account_email(
        "verify", "secret@b.co", link="https://x", locale="en", username="ann"
    )
    assert ok is False and "secret@b.co" not in caplog.text
