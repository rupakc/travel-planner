import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db import alerts_db, devices_db, notifications_db, notify_db, user_settings_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import alert_delivery as ad
from app.services import notify_center as nc
from app.services import push

QH = {"enabled": True, "start": "22:00", "end": "07:00"}
PREFS = {"categories": {}, "daily_cap": 3, "quiet_hours": QH}


def utc(*a):
    return datetime(*a, tzinfo=UTC)


# ── pure decide: golden edges ─────────────────────────────────────────────────


def test_quiet_kolkata_2330_local():
    now = utc(2026, 11, 12, 18, 0)  # 23:30 IST
    d = nc.decide("trip_reminders", PREFS, "Asia/Kolkata", 0, now)
    assert d.action == "hold" and d.due_at == utc(2026, 11, 13, 1, 30)  # 07:00 IST


def test_quiet_new_york_spring_forward_night():
    now = utc(2026, 3, 8, 5, 30)  # 00:30 EST, clocks jump at 02:00
    d = nc.decide("trip_reminders", PREFS, "America/New_York", 0, now)
    assert d.action == "hold" and d.due_at == utc(2026, 3, 8, 11, 0)  # 07:00 EDT


def test_no_tz_means_no_quiet_hours():
    d = nc.decide("trip_reminders", PREFS, None, 0, utc(2026, 11, 12, 18, 0))
    assert d.action == "send"


def test_cap_and_disabled():
    now = utc(2026, 11, 12, 12, 0)
    assert nc.decide("weather", PREFS, "UTC", 3, now).reason == "cap"
    assert nc.decide("weather", PREFS, "UTC", 2, now).action == "send"
    off = {**PREFS, "categories": {"weather": False}}
    assert nc.decide("weather", off, "UTC", 0, now).reason == "disabled"


# ── enqueue / flush ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    alerts_db.create_alert_tables()
    notify_db.create_notify_tables()
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


@pytest.fixture
def sent(monkeypatch):
    out = []

    async def fake(username, title, body, data):
        out.append((username, title, body, data))
        return 1

    monkeypatch.setattr(push, "send_to_user", fake)
    return out


@pytest.fixture
def user():
    u = create_user(f"nc-{uuid.uuid4().hex[:8]}", "pw-123456789")
    user_settings_db.patch_settings(u["id"], {"timezone": "UTC"})
    return u


def _enq(u, key, now, kind="trip_t7", cat="trip_reminders"):
    return nc.enqueue_category(
        u["id"],
        5,
        kind,
        cat,
        f"{u['id']}:{key}",
        "Voyager",
        "Hi",
        {"link": "/trips/5"},
        now,
    )


def test_enqueue_dedupe_and_inapp_row(user):
    now = utc(2026, 11, 12, 12, 0)
    r = _enq(user, "k1", now)
    assert r["status"] == "pending"
    assert _enq(user, "k1", now) is None
    rows = notifications_db.list_notifications(user["id"], limit=10)["items"]
    assert len(rows) == 1
    d = rows[0]["data"]
    assert d["category"] == "trip_reminders" and d["plan_id"] == 5
    assert d["link"] == "/trips/5"


def test_double_flush_sends_once(user, sent):
    now = utc(2026, 11, 12, 12, 0)
    _enq(user, "k1", now)
    nc.flush_due(now)
    nc.flush_due(now)
    mine = [x for x in sent if x[0] == user["username"]]
    assert len(mine) == 1
    assert mine[0][3]["category"] == "trip_reminders" and mine[0][3]["plan_id"] == "5"


def test_quiet_hold_then_release(user, sent):
    user_settings_db.patch_settings(user["id"], {"timezone": "Asia/Kolkata"})
    now = utc(2026, 11, 12, 18, 0)
    r = _enq(user, "k1", now)
    assert r["due_at"] == utc(2026, 11, 13, 1, 30)
    nc.flush_due(now + timedelta(hours=1))
    assert not [x for x in sent if x[0] == user["username"]]
    nc.flush_due(utc(2026, 11, 13, 1, 31))
    assert len([x for x in sent if x[0] == user["username"]]) == 1


def test_stale_hold_dropped(user, sent):
    user_settings_db.patch_settings(user["id"], {"timezone": "Asia/Kolkata"})
    _enq(user, "k1", utc(2026, 11, 12, 18, 0))
    nc.flush_due(utc(2026, 11, 14, 12, 0))
    with get_connection() as c:
        r = c.execute(
            "SELECT status, dropped_reason FROM notify_log WHERE user_id=?",
            (user["id"],),
        ).fetchone()
    assert (r[0], r[1]) == ("dropped", "stale") and not [
        x for x in sent if x[0] == user["username"]
    ]


def test_cap_rechecked_on_release(user, sent):
    notify_db.put_data(user["id"], {"daily_cap": 1})
    now = utc(2026, 11, 12, 12, 0)
    _enq(user, "a", now)
    _enq(user, "b", now)  # both pass at enqueue time (nothing sent yet)
    nc.flush_due(now)
    mine = [x for x in sent if x[0] == user["username"]]
    with get_connection() as c:
        reasons = [
            r[0]
            for r in c.execute(
                "SELECT dropped_reason FROM notify_log WHERE user_id=?", (user["id"],)
            )
        ]
    assert "cap" in reasons and len(mine) == 1


def test_disabled_category_still_writes_inapp_row(user, sent):
    notify_db.put_data(user["id"], {"categories": {"trip_reminders": False}})
    now = utc(2026, 11, 12, 12, 0)
    r = _enq(user, "k1", now)
    assert r["status"] == "dropped" and r["reason"] == "disabled"
    assert nc.flush_due(now) == 0 and not [x for x in sent if x[0] == user["username"]]
    assert len(notifications_db.list_notifications(user["id"], limit=5)["items"]) == 1


def test_locale_resolution(user):
    assert nc.user_locale(user["id"]) == "en"
    devices_db.upsert_device(
        user["username"], "tok1", "android", "fr_FR", now=utc(2026, 1, 1)
    )
    assert nc.user_locale(user["id"]) == "fr"
    user_settings_db.patch_settings(user["id"], {"language": "de"})
    assert nc.user_locale(user["id"]) == "de"


# ── price drops gate ──────────────────────────────────────────────────────────

NOW = utc(2026, 11, 12, 12, 0)
ROW = {"kind": "hotel_drop", "data": {}}


def test_plan_gate_off_blocks_only_non_legacy():
    d = ad.plan(ROW, "hotel", ad.DEFAULT_PREFS, None, {}, None, NOW, False)
    assert d.channels == [] and d.reason == "category_off"
    legacy = {"kind": "watch_expired", "data": {}}
    assert ad.plan(
        legacy, "hotel", ad.DEFAULT_PREFS, None, {}, None, NOW, False
    ).channels


def _dispatch(user):
    note = notifications_db.add_notification(
        user["id"], "hotel_drop", "Drop", "b", {"watch_id": 1}, now=NOW
    )
    ad.dispatch({"user_id": user["id"]}, "hotel", note, NOW)
    with get_connection() as c:
        return c.execute(
            "SELECT channel, dropped_reason FROM alert_outbox WHERE notification_id=?",
            (note["id"],),
        ).fetchall()


def test_dispatch_flag_off_ignores_toggle(user, monkeypatch):
    notify_db.put_data(user["id"], {"categories": {"price_drops": False}})
    monkeypatch.setattr(settings, "notifications_v2_enabled", False)
    assert all(r[1] is None for r in _dispatch(user))


def test_dispatch_flag_on_honours_toggle(user, monkeypatch):
    notify_db.put_data(user["id"], {"categories": {"price_drops": False}})
    monkeypatch.setattr(settings, "notifications_v2_enabled", True)
    rows = _dispatch(user)
    assert rows and all(r[1] == "category_off" for r in rows)


def test_stale_measured_from_creation_not_rehold(user, sent):
    user_settings_db.patch_settings(user["id"], {"timezone": "Asia/Kolkata"})
    _enq(user, "k1", utc(2026, 11, 12, 6, 0))
    with get_connection() as c:  # re-held recently, but created 13 h before
        c.execute(
            "UPDATE notify_log SET status='pending', due_at=? WHERE user_id=?",
            ("2026-11-12T18:50:00Z", user["id"]),
        )
    nc.flush_due(utc(2026, 11, 12, 19, 0))
    with get_connection() as c:
        r = c.execute(
            "SELECT dropped_reason FROM notify_log WHERE user_id=?", (user["id"],)
        ).fetchone()
    assert r[0] == "stale"


def test_interrupted_sending_reset(user, sent):
    _enq(user, "k1", utc(2026, 11, 12, 12, 0))
    with get_connection() as c:
        c.execute(
            "UPDATE notify_log SET status='sending', due_at='2026-11-12T12:00:00Z'"
            " WHERE user_id=?",
            (user["id"],),
        )
    nc.flush_due(utc(2026, 11, 12, 12, 11))
    with get_connection() as c:
        r = c.execute(
            "SELECT status, dropped_reason FROM notify_log WHERE user_id=?",
            (user["id"],),
        ).fetchone()
    assert (r[0], r[1]) == ("dropped", "interrupted")
