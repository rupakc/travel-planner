"""Fare alert emails: content, delivery via a fake SMTP, failure isolation."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db import fare_watch_db, notifications_db
from app.db.users_db import create_user, create_users_table
from app.services import alert_email, fare_watch
from app.services.fare_watch import FareCheck

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
PASSWORD = "s3cret-smtp-pw"


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.login_args = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _smtp(monkeypatch):
    # tokens are minted directly — skip bcrypt's deliberate slowness
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    notifications_db.create_notifications_table()
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(alert_email.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_port", 2525)
    monkeypatch.setattr(settings, "smtp_username", "mailer")
    monkeypatch.setattr(settings, "smtp_password", PASSWORD)
    monkeypatch.setattr(settings, "smtp_from", "Fare Alerts <alerts@trip.test>")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(settings, "app_base_url", "https://trip.test/")
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10_000)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda w: 0)


def _user(email="traveller@example.com"):
    addr = email and f"{uuid.uuid4().hex[:6]}-{email}"
    return create_user(f"em-{uuid.uuid4().hex[:8]}", "pw-123456789", email=addr)


def _watch(user, **over):
    fields = {
        "origin_code": "BER",
        "destination_code": "LIS",
        "origin_label": "Berlin, Germany",
        "destination_label": "Lisbon, Portugal",
        "departure_date": "2026-12-01",
        "return_date": "2026-12-08",
        "num_travelers": 2,
        "alert_mode": "any_drop",
        "email_enabled": True,
    }
    fields.update(over)
    return fare_watch_db.create_watch(user["id"], fields, now=NOW)


async def _drop(w, *prices):
    """Baseline 500 then the given prices, one check every 13 h."""
    t = NOW
    out = None
    for p in (500.0, *prices):

        async def fetch(watch, key, p=p):
            return FareCheck(price=p, price_level="typical")

        out = await fare_watch.check_watch(
            w["id"], now=t, api_key="k", fetch=fetch, rand=lambda: 0.5
        )
        t += timedelta(hours=13)
    return out


# ── Pure helpers ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prices,expected",
    [
        ([500, 480, 520, 454], "▆▄█▁"),
        ([300, 300, 300], "▄▄▄"),
        ([], ""),
        ([None, 400, None, 380], "█▁"),
    ],
)
def test_sparkline(prices, expected):
    assert alert_email.sparkline(prices) == expected


def test_sparkline_keeps_the_last_twelve_points():
    assert len(alert_email.sparkline(list(range(100, 130)))) == 12


def test_unsubscribe_token_round_trip():
    token = alert_email.unsubscribe_token(42)
    assert alert_email.read_unsubscribe_token(token) == 42
    assert alert_email.read_unsubscribe_token(token + "x") is None
    assert alert_email.read_unsubscribe_token("") is None


# ── Message content ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drop_email_is_multipart_and_well_formed():
    u = _user()
    w = _watch(u)
    out = await _drop(w, 454.0)
    assert out.notification["kind"] == "fare_drop"
    [smtp] = FakeSMTP.instances
    assert (smtp.host, smtp.port) == ("smtp.test", 2525)
    assert smtp.started_tls is True
    assert smtp.login_args == ("mailer", PASSWORD)
    [msg] = smtp.sent
    assert msg["To"] == u["email"]
    assert msg["From"] == "Fare Alerts <alerts@trip.test>"
    assert msg["Subject"] == "Berlin → Lisbon dropped to $454 (−$46)"
    assert msg.is_multipart()
    assert msg.get_content_type() == "multipart/alternative"
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    for part in (text, html):
        assert "$500" in part and "$454" in part
        assert "−$46" in part
        assert "1–8 Dec" in part
        assert "total for 2 travellers" in part
        assert f"https://trip.test/alerts?watch={w['id']}" in part
        assert f"https://trip.test/alerts?watch={w['id']}&amp;replan=1" in part or (
            f"https://trip.test/alerts?watch={w['id']}&replan=1" in part
        )
        assert "https://trip.test/api/fare-watches/unsubscribe?token=" in part
    assert "Lowest seen" in text
    assert "█▁" in text  # 500 → 454
    assert "<img" not in html.lower()
    assert "src=" not in html.lower()
    assert "<style" not in html.lower()  # inline styles only
    assert msg["List-Unsubscribe"].startswith(
        "<https://trip.test/api/fare-watches/unsubscribe?token="
    )
    note = notifications_db.list_notifications(u["id"])["items"][0]
    assert note["emailed_at"] == (NOW + timedelta(hours=13)).isoformat()


@pytest.mark.asyncio
async def test_html_escapes_user_supplied_labels():
    u = _user()
    w = _watch(u, destination_label="<script>x</script>, Evil")
    await _drop(w, 454.0)
    html = FakeSMTP.instances[0].sent[0].get_body(("html",)).get_content()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.asyncio
async def test_no_starttls_or_login_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "smtp_from", "")
    await _drop(_watch(_user()), 454.0)
    smtp = FakeSMTP.instances[0]
    assert smtp.started_tls is False
    assert smtp.login_args is None
    assert smtp.sent[0]["From"] == "alerts@localhost"


# ── When email is (not) sent ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_email_when_the_watch_has_email_off():
    await _drop(_watch(_user(), email_enabled=False), 454.0)
    assert FakeSMTP.instances == []


@pytest.mark.asyncio
async def test_no_email_when_the_user_has_no_address():
    await _drop(_watch(_user(email=None)), 454.0)
    assert FakeSMTP.instances == []


@pytest.mark.asyncio
async def test_no_email_without_smtp_host(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    out = await _drop(_watch(_user()), 454.0)
    assert out.notification is not None  # still notified in-app
    assert FakeSMTP.instances == []


@pytest.mark.asyncio
async def test_no_email_for_baseline_or_silent_checks():
    await _drop(_watch(_user()), 498.0, 510.0)
    assert FakeSMTP.instances == []


@pytest.mark.asyncio
async def test_no_email_for_expiry_or_error_notices():
    u = _user()
    w = _watch(u, departure_date="2026-11-04", return_date=None)
    out = await fare_watch.check_watch(w["id"], now=NOW, api_key="k")
    assert out.status == "expired"
    assert FakeSMTP.instances == []


@pytest.mark.asyncio
async def test_smtp_failure_is_logged_and_never_breaks_the_check(caplog):
    FakeSMTP.fail_with = OSError("connection refused")
    u = _user()
    w = _watch(u)
    with caplog.at_level(logging.INFO):
        out = await _drop(w, 454.0)
    assert out.status == "checked"
    assert out.notification["kind"] == "fare_drop"
    got = fare_watch_db.get_watch(w["id"])
    assert got["last_notified_price"] == 454.0
    note = notifications_db.list_notifications(u["id"])["items"][0]
    assert note["emailed_at"] is None
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "email" in logged.lower()
    assert PASSWORD not in logged
    assert u["email"] not in logged


@pytest.mark.asyncio
async def test_cheaper_date_email_names_the_dates():
    u = _user()
    w = _watch(u, flexible_days=3)

    async def base(watch, key):
        return FareCheck(price=500.0)

    async def cheaper(watch, key):
        return FareCheck(
            price=500.0,
            cheapest_price=430.0,
            cheapest_departure_date="2026-12-03",
            cheapest_return_date="2026-12-10",
        )

    await fare_watch.check_watch(w["id"], now=NOW, api_key="k", fetch=base)
    await fare_watch.check_watch(
        w["id"], now=NOW + timedelta(hours=13), api_key="k", fetch=cheaper
    )
    msg = FakeSMTP.instances[0].sent[0]
    assert msg["Subject"] == "Fly Berlin → Lisbon on 3 Dec and save $70"
    text = msg.get_body(("plain",)).get_content()
    assert "3–10 Dec" in text
    assert "cheapest=1" in text


# ── RFC 8058 one-click + deliverability headers ───────────────────────────────


@pytest.mark.asyncio
async def test_list_unsubscribe_headers_are_raw_and_one_click():
    await _drop(_watch(_user()), 454.0)
    msg = FakeSMTP.instances[0].sent[0]
    raw = msg.as_bytes()
    lines = raw.split(b"\n")
    unsub = [ln for ln in lines if ln.startswith(b"List-Unsubscribe:")]
    assert len(unsub) == 1
    assert (
        unsub[0]
        .rstrip(b"\r")
        .startswith(
            b"List-Unsubscribe: <https://trip.test/api/fare-watches/unsubscribe?token="
        )
    )
    assert unsub[0].rstrip(b"\r").endswith(b">")
    assert b"=?utf-8?" not in unsub[0]
    assert b"List-Unsubscribe-Post: List-Unsubscribe=One-Click" in raw


@pytest.mark.asyncio
async def test_date_and_message_id_headers():
    from email.utils import parsedate_to_datetime

    await _drop(_watch(_user()), 454.0)
    msg = FakeSMTP.instances[0].sent[0]
    assert parsedate_to_datetime(msg["Date"]) is not None
    assert msg["Message-ID"].startswith("<") and msg["Message-ID"].endswith(
        "@trip.test>"
    )


def test_message_id_domain_falls_back_to_the_app_url(monkeypatch):
    monkeypatch.setattr(settings, "smtp_from", "")
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "app_base_url", "https://voyager.example.org/app")
    assert alert_email._mail_domain() == "voyager.example.org"
