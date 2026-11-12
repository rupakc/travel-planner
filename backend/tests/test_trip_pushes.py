import uuid
from datetime import UTC, datetime

import pytest

from app.db import (
    alerts_db,
    notify_db,
    trip_prep_db,
    trip_snapshot_db,
    user_settings_db,
)
from app.db.database import get_connection
from app.db.plans_db import save_plan
from app.db.users_db import create_user
from app.services import notify_center as nc
from app.services import trip_pushes as tp

LANGS = ("en", "es", "de", "fr", "hi", "zh", "bn")


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    alerts_db.create_alert_tables()
    notify_db.create_notify_tables()
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


@pytest.fixture
def user():
    u = create_user(f"tp-{uuid.uuid4().hex[:8]}", "pw-123456789")
    user_settings_db.patch_settings(u["id"], {"timezone": "UTC"})
    return u


def run(now, u):
    before = len(rows(u))
    tp.run_due(now)
    return len(rows(u)) - before


def plan(u, start, end, nat="Indian", selections=None):
    return save_plan(
        u["username"],
        "Trip",
        {
            "destination": "Japan",
            "nationality": nat,
            "departure_date": start,
            "return_date": end,
        },
        selections or {},
    )


def rows(u):
    with get_connection() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM notify_log WHERE user_id = ? ORDER BY id", (u["id"],)
            )
        ]


def notes(u):
    from app.db import notifications_db

    return notifications_db.list_notifications(u["id"], limit=50)["items"]


def test_t30_once_and_window(user):
    p = plan(user, "2026-12-12", "2026-12-20")
    assert run(utc(2026, 11, 12, 8, 0), user) == 0  # before 09:00 UTC
    assert run(utc(2026, 11, 12, 9, 0), user) == 1
    assert run(utc(2026, 11, 12, 10, 0), user) == 0  # double run
    r = rows(user)
    assert r[0]["kind"] == "trip_t30" and r[0]["plan_id"] == p["id"]
    assert notes(user)[0]["data"]["link"] == f"/trips/{p['id']}"


def test_t30_stale_and_visa_free_and_done(user):
    plan(user, "2026-12-12", "2026-12-20")
    assert run(utc(2026, 11, 18, 12, 0), user) == 0  # 24 days: past the window
    assert run(utc(2026, 11, 17, 12, 0), user) == 1  # 25 days: window edge
    u2 = create_user(f"tp-{uuid.uuid4().hex[:8]}", "pw-123456789")
    plan(u2, "2026-12-12", "2026-12-20", nat="American")  # visa-free -> na
    p3 = plan(user, "2026-12-13", "2026-12-20")
    trip_prep_db.set_done(p3["id"], "visa", True)
    n0 = len(rows(user))
    tp.run_due(utc(2026, 11, 13, 12, 0))
    kinds = [x["plan_id"] for x in rows(user)[n0:]]
    assert p3["id"] not in kinds and not rows(u2)


def test_t7_packing_and_done_suppress(user):
    p = plan(user, "2026-11-19", "2026-11-25", nat="American")
    assert run(utc(2026, 11, 12, 12, 0), user) == 1
    assert rows(user)[0]["kind"] == "trip_t7"
    q = plan(user, "2026-11-19", "2026-11-25", nat="American")
    trip_prep_db.set_done(q["id"], "packing", True)
    tp.run_due(utc(2026, 11, 13, 12, 0))
    assert all(r["plan_id"] != q["id"] for r in rows(user))
    assert p["id"]


def test_t1_with_weather_and_toggle(user):
    p = plan(user, "2026-11-13", "2026-11-20", nat="American")
    trip_snapshot_db.put_snapshot(
        p["id"],
        {
            "weather": {
                "days": [
                    {
                        "date": "2026-11-13",
                        "description": "Clear",
                        "temp_high_c": 18.2,
                        "temp_low_c": 9.4,
                    }
                ]
            }
        },
    )
    assert run(utc(2026, 11, 12, 12, 0), user) >= 1
    t1 = [n for n in notes(user) if n["kind"] == "trip_t1"][0]
    assert "Clear 9-18°C" in t1["body"]
    assert "streak" not in t1["body"].lower()


def test_t1_weather_toggle_off_drops_only_weather(user):
    from app.db import notify_db as ndb

    ndb.put_data(user["id"], {"categories": {"weather": False}})
    p = plan(user, "2026-11-13", "2026-11-20", nat="American")
    trip_snapshot_db.put_snapshot(
        p["id"], {"weather": {"days": [{"date": "2026-11-13", "description": "Rain"}]}}
    )
    run(utc(2026, 11, 12, 12, 0), user)
    body = [n for n in notes(user) if n["kind"] == "trip_t1"][0]["body"]
    assert "Rain" not in body


def test_trip_reminders_off_suppresses(user):
    notify_db.put_data(user["id"], {"categories": {"trip_reminders": False}})
    plan(user, "2026-12-12", "2026-12-20")
    assert run(utc(2026, 11, 12, 12, 0), user) == 0
    assert not rows(user) and not notes(user)


def test_no_tz_uses_utc_nine(user):
    user_settings_db.patch_settings(user["id"], {"timezone": None})
    plan(user, "2026-12-12", "2026-12-20")
    assert run(utc(2026, 11, 12, 8, 59), user) == 0
    assert run(utc(2026, 11, 12, 9, 0), user) == 1


def test_morning_brief(user):
    user_settings_db.patch_settings(user["id"], {"timezone": "Asia/Tokyo"})
    sel = {
        "itinerary_slots": [
            {"day_number": 2, "time_of_day": "afternoon", "activity": "Teamlab"},
            {"day_number": 2, "time_of_day": "morning", "activity": "Senso-ji"},
        ]
    }
    p = plan(user, "2026-11-11", "2026-11-14", nat="American", selections=sel)
    trip_snapshot_db.put_snapshot(
        p["id"],
        {"weather": {"days": [{"date": "2026-11-12", "description": "Sunny"}]}},
    )
    # 22:59 UTC = 07:59 JST on the 13th: too early (day 3); day 2 is 11/12 JST
    assert run(utc(2026, 11, 11, 22, 59), user) == 0
    assert run(utc(2026, 11, 11, 23, 0), user) == 1  # 08:00 JST on 11/12
    assert run(utc(2026, 11, 12, 1, 0), user) == 0  # same day again
    n = [x for x in notes(user) if x["kind"] == "trip_morning"][0]
    assert "Senso-ji" in n["body"] and "Sunny" in n["body"] and "Tip:" in n["body"]
    assert n["data"]["link"] == f"/trips/{p['id']}/today"
    # next local day is a new brief; after the trip nothing
    assert run(utc(2026, 11, 12, 23, 30), user) == 1
    assert run(utc(2026, 11, 14, 23, 30), user) == 0  # 15th JST: ended


def test_morning_needs_tz_and_toggle(user):
    user_settings_db.patch_settings(user["id"], {"timezone": None})
    plan(user, "2026-11-11", "2026-11-14", nat="American")
    assert run(utc(2026, 11, 12, 12, 0), user) == 0
    user_settings_db.patch_settings(user["id"], {"timezone": "UTC"})
    notify_db.put_data(user["id"], {"categories": {"morning_brief": False}})
    assert run(utc(2026, 11, 12, 12, 0), user) == 0


def test_far_trips_not_scanned_and_prune(user):
    plan(user, "2027-06-01", "2027-06-10")
    assert run(utc(2026, 11, 12, 12, 0), user) == 0
    nc.enqueue_category(
        user["id"], 1, "trip_t7", "trip_reminders", "old", "t", "b", {}, utc(2026, 8, 1)
    )
    with get_connection() as conn:  # created_at uses the wall clock: age it explicitly
        conn.execute(
            "UPDATE notify_log SET created_at = '2000-01-01T00:00:00Z'"
            " WHERE dedupe_key = 'old'"
        )
    assert tp.prune_log(datetime.now(UTC)) == 1


@pytest.mark.parametrize("lang", LANGS)
def test_languages_render(user, lang):
    user_settings_db.patch_settings(user["id"], {"language": lang})
    plan(user, "2026-12-12", "2026-12-20")
    assert run(utc(2026, 11, 12, 12, 0), user) == 1
    body = notes(user)[0]["body"]
    assert "Japan" in body and "{" not in body


def test_t1_not_on_departure_day_and_t1_only_day_before(user):
    plan(user, "2026-11-12", "2026-11-14", nat="American")
    run(utc(2026, 11, 12, 12, 0), user)  # start day: brief only, no "Tomorrow"
    assert [r["kind"] for r in rows(user)] == ["trip_morning"] or not rows(user)
    assert all(r["kind"] != "trip_t1" for r in rows(user))
    assert all("omorrow" not in n["body"] for n in notes(user))


def test_t1_fires_day_before(user):
    plan(user, "2026-11-13", "2026-11-14", nat="American")
    run(utc(2026, 11, 12, 12, 0), user)
    assert [r["kind"] for r in rows(user)] == ["trip_t1"]


def test_invalid_timezone_counts_as_none(user):
    with get_connection() as c:  # bypasses validation: stale/legacy stored value
        c.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, data, updated_at)"
            " VALUES (?, ?, ?)",
            (user["id"], '{"timezone": "Not/AZone"}', "2026-11-12T00:00:00Z"),
        )
    plan(user, "2026-11-11", "2026-11-14", nat="American")
    assert run(utc(2026, 11, 12, 9, 0), user) == 0  # no brief without a tz


def test_send_windows(user):
    plan(user, "2026-12-12", "2026-12-20")  # T-30 window: 25-30 days
    assert run(utc(2026, 11, 12, 21, 0), user) == 0  # too late in the day
    assert run(utc(2026, 11, 13, 10, 0), user) == 1  # next day still in window
    q = plan(user, "2026-11-11", "2026-11-14", nat="American")
    assert run(utc(2026, 11, 12, 11, 0), user) == 0  # brief window closed
    assert q["id"]


def test_t30_t7_show_days_remaining(user):
    plan(user, "2026-12-08", "2026-12-20")  # 26 days
    run(utc(2026, 11, 12, 12, 0), user)
    assert "26 days" in notes(user)[0]["body"]
    plan(user, "2026-11-18", "2026-11-25", nat="American")  # 6 days
    run(utc(2026, 11, 12, 12, 0), user)
    assert any("6 days" in n["body"] for n in notes(user))
