"""Smarter checking: priority order and adaptive intervals (flag-gated).
Fakes only; SerpAPI is never reached."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db import fare_watch_db, notifications_db
from app.db.database import get_connection
from app.db.users_db import create_user, create_users_table
from app.services import alert_schedule, fare_watch
from app.services.fare_watch import FareCheck

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def _dep(days):
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.mark.parametrize(
    "days,expected",
    [(3, 1), (14, 1), (15, 2), (45, 2), (46, 4), (120, 4), (121, 7), (400, 7)],
)
def test_interval_table(days, expected):
    w = {"departure_date": _dep(days)}
    assert alert_schedule.next_interval("flight", w, TODAY) == timedelta(days=expected)


def test_no_date_uses_sixty_days():
    assert alert_schedule.next_interval("hotel", {}, TODAY) == timedelta(days=4)
    assert alert_schedule.priority("hotel", {}, TODAY)[1] == 60


def test_subject_dates_are_read():
    w = {"subject": {"check_in": _dep(10)}}
    assert alert_schedule.priority("hotel", w, TODAY)[1] == 10


def test_near_target_halves():
    w = {"departure_date": _dep(100), "target_price": 100.0, "last_price": 105.0}
    assert alert_schedule.next_interval("flight", w, TODAY) == timedelta(days=2)
    w["departure_date"] = _dep(5)  # minimum one day
    assert alert_schedule.next_interval("flight", w, TODAY) == timedelta(days=1)
    w["last_price"] = 150.0  # not near
    w["departure_date"] = _dep(100)
    assert alert_schedule.next_interval("flight", w, TODAY) == timedelta(days=4)


def test_flat_history_adds_a_day():
    w = {"departure_date": _dep(100)}
    flat = [100.0, 100.5, 100.2, 99.9, 100.0]
    assert alert_schedule.next_interval("flight", w, TODAY, flat) == timedelta(days=5)
    moving = [100.0, 110.0, 100.2, 99.9, 100.0]
    assert alert_schedule.next_interval("flight", w, TODAY, moving) == timedelta(days=4)
    assert alert_schedule.next_interval("flight", w, TODAY, flat[:4]) == timedelta(
        days=4
    )


def test_pending_first():
    pending = {"pending_first_check": True, "departure_date": _dep(300)}
    soon = {"departure_date": _dep(2)}
    assert alert_schedule.priority("flight", pending, TODAY) < alert_schedule.priority(
        "flight", soon, TODAY
    )


def test_target_gap_breaks_ties():
    a = {"departure_date": _dep(10), "target_price": 100.0, "last_price": 101.0}
    b = {"departure_date": _dep(10), "target_price": 100.0, "last_price": 150.0}
    c = {"departure_date": _dep(10)}
    p = lambda w: alert_schedule.priority("flight", w, TODAY)  # noqa: E731
    assert p(a) < p(b) < p(c)


# ── Scheduler integration ─────────────────────────────────────────────────────


@pytest.fixture
def sched(monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    notifications_db.create_notifications_table()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10_000)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda w: 1)
    with get_connection() as conn:
        conn.execute("UPDATE fare_watches SET status = 'paused'")
        conn.execute("DELETE FROM fare_watch_quota")
    return create_user(f"as-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _watch(user, days):
    return fare_watch_db.create_watch(
        user["id"],
        {
            "origin_code": "BER",
            "destination_code": "LIS",
            "origin_label": "Berlin",
            "destination_label": "Lisbon",
            "departure_date": _dep(days),
            "return_date": None,
            "num_travelers": 1,
            "alert_mode": "any_drop",
        },
        now=NOW,
    )


async def _fetch(watch, key):
    return FareCheck(price=200.0, calls=1)


@pytest.mark.asyncio
async def test_budget_short_checks_nearest_departure_first(sched, monkeypatch):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 1)
    monkeypatch.setattr(settings, "fare_watch_user_daily_share", 1.0)
    far, near, mid = _watch(sched, 200), _watch(sched, 5), _watch(sched, 60)
    outs = await fare_watch.run_due("k", clock=lambda: NOW, fetch=_fetch)
    statuses = {o.watch["id"]: o.status for o in outs if o and o.watch}
    assert statuses[near["id"]] == "checked"
    assert statuses[near["id"]] == "checked"
    assert statuses.get(far["id"]) != "checked"
    assert statuses.get(mid["id"]) != "checked"


@pytest.mark.asyncio
async def test_flag_on_uses_adaptive_interval(sched, monkeypatch):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    w = _watch(sched, 5)
    await fare_watch.run_due("k", clock=lambda: NOW, fetch=_fetch, rand=lambda: 0.5)
    got = fare_watch_db.get_watch(w["id"])
    assert got["next_check_at"] == (NOW + timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_flag_off_next_check_unchanged(sched, monkeypatch):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", False)
    w = _watch(sched, 5)
    for r, hours in ((0.0, 10.8), (0.5, 12.0), (1.0, 13.2)):
        got = fare_watch.next_check(NOW, lambda r=r: r)
        assert got == NOW + timedelta(hours=hours)
        # keyword args are ignored with the flag off
        assert fare_watch.next_check(
            NOW, lambda r=r: r, watch_kind="flight", watch=w
        ) == NOW + timedelta(hours=hours)
    # candidates=None keeps the old limit and order
    ws = [_watch(sched, d) for d in (200, 5, 60)]
    for i, x in enumerate(ws):
        fare_watch_db.update_watch(
            x["id"], next_check_at=(NOW - timedelta(minutes=10 - i)).isoformat()
        )
    assert fare_watch_db.due_watch_ids(NOW, 2) == [ws[0]["id"], ws[1]["id"]]
    assert fare_watch_db.due_watch_ids(NOW, 2, candidates=None) == [
        ws[0]["id"],
        ws[1]["id"],
    ]


@pytest.mark.asyncio
async def test_overdue_far_watch_is_not_starved(sched, monkeypatch):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda w: 0)
    far = _watch(sched, 300)
    fare_watch_db.update_watch(
        far["id"], next_check_at=(NOW - timedelta(days=8)).isoformat()
    )
    for _ in range(51):
        _watch(sched, 3)
    outs = await fare_watch.run_due("k", clock=lambda: NOW, fetch=_fetch)
    assert len(outs) == 50
    assert far["id"] in {o.watch["id"] for o in outs if o and o.watch}


@pytest.mark.asyncio
async def test_budget_one_merely_due_old_watch_still_picks_nearest(sched, monkeypatch):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 1)
    monkeypatch.setattr(settings, "fare_watch_user_daily_share", 1.0)
    far = _watch(sched, 300)
    fare_watch_db.update_watch(
        far["id"], next_check_at=(NOW - timedelta(days=2)).isoformat()
    )
    near = _watch(sched, 5)
    outs = await fare_watch.run_due("k", clock=lambda: NOW, fetch=_fetch)
    done = {o.watch["id"] for o in outs if o and o.watch and o.status == "checked"}
    assert done == {near["id"]}
