"""Task 10: the opt-in weekly price digest."""

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.db import alerts_db, notifications_db, price_watch_db, user_settings_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import alert_digest, alert_email, push

MON_9_UTC = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)  # a Monday, ISO week 46


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    alerts_db.create_alert_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM alert_digests")
        conn.execute("DELETE FROM alert_prefs")
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


@pytest.fixture
def user():
    return create_user(f"dg-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _watch_with_looks(user, prices=(500.0, 450.0), now=MON_9_UTC):
    w = price_watch_db.create_watch(
        user["id"],
        {
            "kind": "hotel",
            "title": "Hotel Aurora",
            "subject": {},
            "match_key": uuid.uuid4().hex,
            "currency": "USD",
            "expires_on": "2027-01-01",
        },
        now=now,
    )
    for i, p in enumerate(prices):
        price_watch_db.add_history(
            w["id"],
            {
                "checked_at": now.replace(
                    day=now.day - len(prices) + i + 1
                ).isoformat(),
                "price": p,
                "observed": {"observed": True},
            },
        )
    return w


def _opt_in(user, **extra):
    prefs = alerts_db.get_prefs(user["id"])
    prefs.update(digest_weekly=True, **extra)
    alerts_db.put_prefs(user["id"], prefs)


def _count(user):
    return [
        n
        for n in notifications_db.list_notifications(user["id"], limit=50)["items"]
        if n["kind"] == "price_digest"
    ]


def test_digest_off_by_default(user):
    _watch_with_looks(user)
    assert alerts_db.get_prefs(user["id"])["digest_weekly"] is False
    assert alert_digest.run_due(MON_9_UTC) == 0
    assert _count(user) == []


def test_digest_due_monday_9_local(user):
    _watch_with_looks(user)
    _opt_in(user)
    user_settings_db.patch_settings(user["id"], {"timezone": "Asia/Kolkata"})
    # 03:00 UTC = 08:30 IST: too early; 04:00 UTC = 09:30 IST: due
    early = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
    assert alert_digest.run_due(early) == 0
    assert alert_digest.run_due(datetime(2026, 11, 9, 4, 0, tzinfo=UTC)) == 1
    # a Tuesday is not the digest day
    other = create_user(f"dg-{uuid.uuid4().hex[:8]}", "pw-123456789")
    _watch_with_looks(other)
    _opt_in(other)
    assert alert_digest.run_due(datetime(2026, 11, 10, 12, 0, tzinfo=UTC)) == 0


def test_digest_once_per_week_across_restart(user):
    _watch_with_looks(user)
    _opt_in(user)
    assert alert_digest.run_due(MON_9_UTC) == 1
    assert alert_digest.run_due(MON_9_UTC.replace(hour=10)) == 0
    assert len(_count(user)) == 1


def test_digest_skipped_when_no_looks_this_week(user):
    _watch_with_looks(user)
    _opt_in(user)
    later = datetime(2026, 12, 7, 9, 0, tzinfo=UTC)  # looks are a month old
    assert alert_digest.run_due(later) == 0
    assert _count(user) == []
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM alert_digests WHERE user_id = ?", (user["id"],)
        ).fetchone()
    assert row["status"] == "skipped"


def test_digest_notification_has_legacy_fields(user):
    _watch_with_looks(user)
    _opt_in(user)
    alert_digest.run_due(MON_9_UTC)
    (n,) = _count(user)
    for k in ("kind", "title", "body", "data", "read_at"):
        assert k in n
    d = n["data"]["digest"]
    assert d["week"] == "2026-W46"
    w = d["watches"][0]
    assert w["latest"] == 450.0 and w["lowest"] == 450.0 and w["change_7d"] == -50.0
    assert "total_usd" in d["savings"]


def test_digest_email_has_unsubscribe_and_no_estimate_as_price(user, monkeypatch):
    w = _watch_with_looks(user, prices=(500.0,))
    price_watch_db.add_history(
        w["id"],
        {
            "checked_at": MON_9_UTC.isoformat(),
            "price": 99.0,
            "observed": {"observed": False},
        },
    )
    digest = alert_digest.build_digest(user["id"], MON_9_UTC)
    msg = alert_email.build_digest_message({**user, "email": "a@b.co"}, digest)
    assert "/api/alerts/digest/unsubscribe?token=" in msg["List-Unsubscribe"]
    body = msg.get_body(("plain",)).get_content()
    assert "Stop the weekly digest" in body and "USD 500" in body
    # the unsubscribe URL carries a random token that may contain "99"
    body = re.sub(r"https?://\S+", "", body)
    assert "99" not in body


def test_digest_email_sent_only_if_verified_and_push_opt_in(user, monkeypatch):
    _watch_with_looks(user)
    _opt_in(user, digest_push=True)
    mails, pushes = [], []
    monkeypatch.setattr(alert_email, "email_available", lambda: True)
    monkeypatch.setattr(alert_email, "send_message", lambda m: mails.append(m))

    async def fake_push(username, title, body, data):
        pushes.append(data)
        return 1

    monkeypatch.setattr(push, "send_to_user", fake_push)
    monkeypatch.setattr(
        alert_digest.users_db,
        "get_user_by_id",
        lambda uid: {**user, "email": "a@b.co", "email_verified": False},
    )
    alert_digest.run_due(MON_9_UTC)
    assert mails == [] and pushes[0]["kind"] == "price_digest"


def test_digest_no_push_by_default(user, monkeypatch):
    _watch_with_looks(user)
    _opt_in(user)
    pushes = []

    async def fake_push(*a):
        pushes.append(a)
        return 1

    monkeypatch.setattr(push, "send_to_user", fake_push)
    assert alert_digest.run_due(MON_9_UTC) == 1
    assert pushes == []


def test_digest_unsubscribe_turns_off(client, user):
    _opt_in(user)
    token = alert_email.digest_unsubscribe_token(user["id"])
    url = f"/api/alerts/digest/unsubscribe?token={token}"
    assert client.get(url).status_code == 200
    assert alerts_db.get_prefs(user["id"])["digest_weekly"] is True  # GET is inert
    assert client.post(url).status_code == 200
    assert alerts_db.get_prefs(user["id"])["digest_weekly"] is False
    assert client.post("/api/alerts/digest/unsubscribe?token=bad").status_code == 400
