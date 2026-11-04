"""Fare-watch checks: baseline, history, quota guard, expiry and failures.

Fake clock (``now`` is always passed in), mocked SerpAPI (``_call`` or an
injected ``fetch``); the DB is the suite's temp SQLite.
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.cache import get_cache
from app.core.config import settings
from app.db import fare_watch_db, notifications_db
from app.db.database import get_connection
from app.db.users_db import create_user, create_users_table
from app.services import fare_watch, serp_flights
from app.services.fare_watch import FareCheck, check_watch
from app.services.serp_flights import SerpAPIError

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
KEY = "test-key"


@pytest.fixture(autouse=True)
def _tables(monkeypatch):
    # tokens are minted directly — skip bcrypt's deliberate slowness
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    notifications_db.create_notifications_table()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 200)
    monkeypatch.setattr(settings, "fare_watch_interval_hours", 12)
    monkeypatch.setattr(serp_flights, "_today", lambda: NOW.date())
    monkeypatch.setattr(fare_watch, "_budget_logged_day", None)
    with get_connection() as conn:  # a fresh daily budget per test
        conn.execute("DELETE FROM fare_watch_quota")
    get_cache().clear()
    yield
    get_cache().clear()


@pytest.fixture
def user():
    return create_user(f"fw-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _new_watch(user, **over):
    fields = {
        "origin_code": "BER",
        "destination_code": "LIS",
        "origin_label": "Berlin, Germany",
        "destination_label": "Lisbon, Portugal",
        "departure_date": "2026-12-01",
        "return_date": "2026-12-08",
        "num_travelers": 2,
        "flexible_days": 0,
        "alert_mode": "any_drop",
    }
    fields.update(over)
    return fare_watch_db.create_watch(user["id"], fields, now=NOW)


def _fetch(*checks):
    """An injected fetch returning each FareCheck in turn."""
    return AsyncMock(side_effect=list(checks))


async def _run(watch, fetch, now=NOW, **kw):
    kw.setdefault("rand", lambda: 0.5)  # no jitter
    return await check_watch(watch["id"], now=now, api_key=KEY, fetch=fetch, **kw)


def _notes(user):
    return notifications_db.list_notifications(user["id"])["items"]


# ── Baseline + regular checks ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_check_sets_baseline_without_notifying(user):
    w = _new_watch(user)
    out = await _run(w, _fetch(FareCheck(price=500.0, price_level="typical", calls=1)))
    assert out.status == "checked"
    assert out.notification is None
    got = fare_watch_db.get_watch(w["id"])
    assert got["baseline_price"] == 500.0
    assert got["last_price"] == 500.0
    assert got["lowest_price"] == 500.0
    assert got["lowest_price_date"] == "2026-12-01"
    assert got["check_count"] == 1
    assert got["google_price_level"] == "typical"
    assert got["last_checked_at"] == NOW.isoformat()
    assert got["next_check_at"] == (NOW + timedelta(hours=12)).isoformat()
    assert got["lease_until"] is None
    assert _notes(user) == []
    hist = fare_watch_db.get_history(w["id"])
    assert [h["price"] for h in hist] == [500.0]


@pytest.mark.asyncio
async def test_drop_creates_one_notification_and_records_it(user):
    w = _new_watch(user)
    await _run(w, _fetch(FareCheck(price=500.0, calls=1)))
    later = NOW + timedelta(hours=12)
    out = await _run(w, _fetch(FareCheck(price=454.0, calls=1)), now=later)
    assert out.notification["kind"] == "fare_drop"
    notes = _notes(user)
    assert len(notes) == 1
    assert notes[0]["title"] == "Berlin → Lisbon dropped to $454 (−$46)"
    assert notes[0]["data"]["watch_id"] == w["id"]
    assert notes[0]["read_at"] is None
    got = fare_watch_db.get_watch(w["id"])
    assert got["last_notified_price"] == 454.0
    assert got["last_notified_at"] == later.isoformat()
    assert got["lowest_price"] == 454.0
    assert got["baseline_price"] == 500.0


@pytest.mark.asyncio
async def test_increase_is_recorded_but_silent(user):
    w = _new_watch(user)
    await _run(w, _fetch(FareCheck(price=500.0, calls=1)))
    out = await _run(
        w, _fetch(FareCheck(price=560.0, calls=1)), now=NOW + timedelta(hours=12)
    )
    assert out.notification is None
    got = fare_watch_db.get_watch(w["id"])
    assert got["last_price"] == 560.0
    assert got["lowest_price"] == 500.0
    assert [h["price"] for h in fare_watch_db.get_history(w["id"])] == [500.0, 560.0]
    assert _notes(user) == []


@pytest.mark.asyncio
async def test_no_fare_found_keeps_baseline_unset(user):
    w = _new_watch(user)
    out = await _run(w, _fetch(FareCheck(price=None, calls=1)))
    assert out.status == "checked"
    got = fare_watch_db.get_watch(w["id"])
    assert got["baseline_price"] is None
    assert got["check_count"] == 0
    # …so the next real price is still treated as the baseline (no alert)
    out = await _run(
        w, _fetch(FareCheck(price=100.0, calls=1)), now=NOW + timedelta(hours=12)
    )
    assert out.notification is None
    assert fare_watch_db.get_watch(w["id"])["baseline_price"] == 100.0


@pytest.mark.parametrize("r,hours", [(0.0, 10.8), (1.0, 13.2), (0.5, 12.0)])
@pytest.mark.asyncio
async def test_next_check_has_ten_percent_jitter(user, r, hours):
    w = _new_watch(user)
    await _run(w, _fetch(FareCheck(price=500.0, calls=1)), rand=lambda: r)
    got = fare_watch_db.get_watch(w["id"])
    assert got["next_check_at"] == (NOW + timedelta(hours=hours)).isoformat()


@pytest.mark.asyncio
async def test_history_is_capped_at_120_rows(user):
    w = _new_watch(user)
    t = NOW
    for i in range(125):
        await _run(w, _fetch(FareCheck(price=500.0 + i, calls=0)), now=t)
        t += timedelta(minutes=1)
    hist = fare_watch_db.get_history(w["id"])
    assert len(hist) == 120
    assert hist[0]["price"] == 505.0  # oldest five dropped
    assert hist[-1]["price"] == 624.0


@pytest.mark.asyncio
async def test_flexible_check_tracks_cheapest_nearby_date(user):
    w = _new_watch(user, flexible_days=3)
    await _run(
        w,
        _fetch(
            FareCheck(
                price=500.0,
                cheapest_price=430.0,
                cheapest_departure_date="2026-12-03",
                cheapest_return_date="2026-12-10",
                calls=7,
            )
        ),
    )
    got = fare_watch_db.get_watch(w["id"])
    assert got["lowest_price"] == 430.0
    assert got["lowest_price_date"] == "2026-12-03"
    h = fare_watch_db.get_history(w["id"])[0]
    assert h["cheapest_price"] == 430.0
    assert h["cheapest_departure_date"] == "2026-12-03"
    assert h["cheapest_return_date"] == "2026-12-10"


# ── Expiry ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("dep", ["2026-11-04", "2026-11-01"])
@pytest.mark.asyncio
async def test_departure_today_or_past_expires_once(user, dep):
    w = _new_watch(user, departure_date=dep, return_date=None)
    fetch = _fetch()
    out = await _run(w, fetch)
    assert out.status == "expired"
    fetch.assert_not_called()
    got = fare_watch_db.get_watch(w["id"])
    assert got["status"] == "expired"
    notes = _notes(user)
    assert [n["kind"] for n in notes] == ["watch_expired"]
    # a second run (e.g. a stale claim) never repeats the notification
    out = await _run(w, fetch)
    assert out.status == "skipped"
    assert len(_notes(user)) == 1


@pytest.mark.asyncio
async def test_departure_tomorrow_is_still_checked(user):
    w = _new_watch(user, departure_date="2026-11-05", return_date=None)
    out = await _run(w, _fetch(FareCheck(price=300.0, calls=1)))
    assert out.status == "checked"


@pytest.mark.asyncio
async def test_expired_notification_mentions_lowest_seen(user):
    w = _new_watch(user, departure_date="2026-11-06", return_date=None)
    await _run(w, _fetch(FareCheck(price=300.0, calls=1)))
    out = await _run(w, _fetch(), now=NOW + timedelta(days=2))
    assert out.status == "expired"
    assert "$300" in out.notification["body"]


@pytest.mark.asyncio
async def test_paused_watch_is_skipped_by_the_scheduler(user):
    w = _new_watch(user)
    fare_watch_db.update_watch(w["id"], status="paused")
    fetch = _fetch()
    out = await _run(w, fetch)
    assert out.status == "skipped"
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_manual_check_works_on_paused_watch(user):
    w = _new_watch(user)
    fare_watch_db.update_watch(w["id"], status="paused")
    out = await _run(w, _fetch(FareCheck(price=500.0, calls=1)), manual=True)
    assert out.status == "checked"
    assert fare_watch_db.get_watch(w["id"])["status"] == "paused"


# ── Daily SerpAPI budget ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_is_charged_per_call(user, monkeypatch):
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda watch: 7)
    w = _new_watch(user, flexible_days=3)
    await _run(w, _fetch(FareCheck(price=500.0, calls=7)))
    assert fare_watch_db.calls_used("2026-11-04") == 7


@pytest.mark.asyncio
async def test_exhausted_budget_postpones_to_next_utc_day_and_logs_once(
    user, monkeypatch, caplog
):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 3)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda watch: 1)
    fare_watch_db.reserve_calls("2026-11-04", 3, 3)
    a, b = _new_watch(user), _new_watch(user, destination_code="OPO")
    fetch = _fetch()
    with caplog.at_level(logging.WARNING, logger="app.services.fare_watch"):
        out_a = await _run(a, fetch)
        out_b = await _run(b, fetch)
    assert out_a.status == out_b.status == "postponed"
    fetch.assert_not_called()
    for w in (a, b):
        nxt = datetime.fromisoformat(fare_watch_db.get_watch(w["id"])["next_check_at"])
        assert nxt.date() == date(2026, 11, 5)
        assert nxt < datetime(2026, 11, 5, 1, 0, tzinfo=UTC)  # spread in the 1st hour
    budget_logs = [r for r in caplog.records if "budget" in r.getMessage()]
    assert len(budget_logs) == 1


@pytest.mark.asyncio
async def test_check_that_would_overrun_budget_is_postponed(user, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda watch: 7)
    fare_watch_db.reserve_calls("2026-11-04", 5, 10)
    w = _new_watch(user, flexible_days=3)
    out = await _run(w, _fetch())
    assert out.status == "postponed"
    assert fare_watch_db.calls_used("2026-11-04") == 5


@pytest.mark.asyncio
async def test_manual_check_with_exhausted_budget_leaves_schedule_alone(
    user, monkeypatch
):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 1)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda watch: 1)
    fare_watch_db.reserve_calls("2026-11-04", 1, 1)
    w = _new_watch(user)
    before = fare_watch_db.get_watch(w["id"])["next_check_at"]
    out = await _run(w, _fetch(), manual=True)
    assert out.status == "budget_exhausted"
    assert fare_watch_db.get_watch(w["id"])["next_check_at"] == before


@pytest.mark.asyncio
async def test_cached_fares_cost_nothing(user, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 0)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda watch: 0)
    w = _new_watch(user)
    out = await _run(w, _fetch(FareCheck(price=500.0, calls=0)))
    assert out.status == "checked"
    assert fare_watch_db.calls_used("2026-11-04") == 0


@pytest.mark.asyncio
async def test_budget_counter_is_per_utc_day(user, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 1)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda watch: 1)
    fare_watch_db.reserve_calls("2026-11-04", 1, 1)
    w = _new_watch(user)
    tomorrow = datetime(2026, 11, 5, 0, 5, tzinfo=UTC)
    out = await _run(w, _fetch(FareCheck(price=500.0, calls=1)), now=tomorrow)
    assert out.status == "checked"
    assert fare_watch_db.calls_used("2026-11-05") == 1


def test_reserve_calls_is_all_or_nothing():
    day = "2030-01-01"
    assert fare_watch_db.reserve_calls(day, 4, 5) is True
    assert fare_watch_db.reserve_calls(day, 2, 5) is False
    assert fare_watch_db.calls_used(day) == 4
    assert fare_watch_db.reserve_calls(day, 1, 5) is True
    assert fare_watch_db.calls_used(day) == 5


# ── Failures ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transient_failure_retries_in_an_hour(user):
    w = _new_watch(user)
    out = await _run(w, AsyncMock(side_effect=SerpAPIError("SerpAPI timeout")))
    assert out.status == "failed"
    got = fare_watch_db.get_watch(w["id"])
    assert got["status"] == "active"
    assert got["failure_count"] == 1
    assert got["next_check_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert "timeout" in got["last_error"]
    assert _notes(user) == []


@pytest.mark.asyncio
async def test_three_failures_in_a_row_mark_error_and_notify_once(user):
    w = _new_watch(user)
    boom = AsyncMock(side_effect=SerpAPIError("SerpAPI HTTP 500"))
    t = NOW
    for _ in range(2):
        await _run(w, boom, now=t)
        t += timedelta(hours=1)
    out = await _run(w, boom, now=t)
    assert out.status == "errored"
    got = fare_watch_db.get_watch(w["id"])
    assert got["status"] == "error"
    notes = _notes(user)
    assert [n["kind"] for n in notes] == ["watch_error"]
    assert notes[0]["data"]["action"] == "retry"
    # the scheduler skips error watches — no repeat
    out = await _run(w, boom, now=t + timedelta(hours=1))
    assert out.status == "skipped"
    assert len(_notes(user)) == 1


@pytest.mark.asyncio
async def test_success_resets_failure_streak(user):
    w = _new_watch(user)
    boom = AsyncMock(side_effect=SerpAPIError("SerpAPI HTTP 500"))
    await _run(w, boom)
    await _run(w, boom, now=NOW + timedelta(hours=1))
    await _run(w, _fetch(FareCheck(price=500.0, calls=1)), now=NOW + timedelta(hours=2))
    got = fare_watch_db.get_watch(w["id"])
    assert got["failure_count"] == 0
    assert got["last_error"] is None
    await _run(w, boom, now=NOW + timedelta(hours=3))
    assert fare_watch_db.get_watch(w["id"])["status"] == "active"


@pytest.mark.asyncio
async def test_serpapi_account_quota_postpones_without_a_strike(user):
    w = _new_watch(user)
    out = await _run(
        w, AsyncMock(side_effect=SerpAPIError("quota", quota_exceeded=True))
    )
    assert out.status == "postponed"
    got = fare_watch_db.get_watch(w["id"])
    assert got["failure_count"] == 0
    assert datetime.fromisoformat(got["next_check_at"]).date() == date(2026, 11, 5)


@pytest.mark.asyncio
async def test_unexpected_exception_counts_as_a_failure(user):
    w = _new_watch(user)
    out = await _run(w, AsyncMock(side_effect=ValueError("bad json")))
    assert out.status == "failed"
    assert fare_watch_db.get_watch(w["id"])["failure_count"] == 1


# ── Live fare fetch (serp_flights.watch_fares, `_call` mocked) ────────────────


def _serp(prices, insights=None):
    data = {
        "best_flights": [{"price": p, "flights": [], "layovers": []} for p in prices],
        "other_flights": [],
    }
    if insights:
        data["price_insights"] = insights
    return data


INSIGHTS = {
    "lowest_price": 480,
    "price_level": "low",
    "typical_price_range": [520, 700],
}


@pytest.mark.asyncio
async def test_fetch_fares_exact_dates_costs_one_call_then_zero(user, monkeypatch):
    call = AsyncMock(return_value=_serp([530, 480], INSIGHTS))
    monkeypatch.setattr(serp_flights, "_call", call)
    w = fare_watch_db.get_watch(_new_watch(user)["id"])
    assert fare_watch._estimate_calls(w) == 1
    check = await fare_watch.fetch_fares(w, KEY)
    assert check.price == 480.0
    assert check.price_level == "low"
    assert (check.typical_low, check.typical_high) == (520, 700)
    assert check.calls == 1
    params = call.call_args.args[0]
    assert params["departure_id"] == "BER"
    assert params["arrival_id"] == "LIS"
    assert params["adults"] == "2"
    assert params["return_date"] == "2026-12-08"
    # cached for the cache TTL: free
    assert fare_watch._estimate_calls(w) == 0
    again = await fare_watch.fetch_fares(w, KEY)
    assert again.price == 480.0 and again.calls == 0
    assert call.call_count == 1


@pytest.mark.asyncio
async def test_fetch_fares_reuses_a_cached_main_search(user, monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr(serp_flights, "_call", call)
    w = fare_watch_db.get_watch(_new_watch(user)["id"])
    get_cache()[
        serp_flights._main_key("BER", "LIS", date(2026, 12, 1), date(2026, 12, 8), 2)
    ] = {
        "results": [{"price_usd": 455.0}, {"price_usd": 470.0}],
        "price_insights": INSIGHTS,
    }
    assert fare_watch._estimate_calls(w) == 0
    check = await fare_watch.fetch_fares(w, KEY)
    assert check.price == 455.0
    assert check.price_level == "low"
    call.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_fares_flexible_uses_the_calendar(user, monkeypatch):
    prices = {
        "2026-11-28": 610,
        "2026-11-29": 590,
        "2026-11-30": 560,
        "2026-12-01": 500,
        "2026-12-02": 520,
        "2026-12-03": 430,
        "2026-12-04": 470,
    }

    async def fake_call(params):
        return _serp([prices[params["outbound_date"]]], INSIGHTS)

    monkeypatch.setattr(serp_flights, "_call", AsyncMock(side_effect=fake_call))
    w = fare_watch_db.get_watch(_new_watch(user, flexible_days=3)["id"])
    assert fare_watch._estimate_calls(w) == 7
    check = await fare_watch.fetch_fares(w, KEY)
    assert check.price == 500.0
    assert check.cheapest_price == 430.0
    assert check.cheapest_departure_date == "2026-12-03"
    assert check.cheapest_return_date == "2026-12-10"
    assert check.calls == 7
    assert serp_flights._call.call_count == 7
    assert fare_watch._estimate_calls(w) == 0


@pytest.mark.asyncio
async def test_fetch_fares_flexible_skips_dates_before_tomorrow(user, monkeypatch):
    monkeypatch.setattr(
        serp_flights, "_call", AsyncMock(return_value=_serp([400], INSIGHTS))
    )
    w = fare_watch_db.get_watch(
        _new_watch(user, departure_date="2026-11-06", flexible_days=3)["id"]
    )
    # 11-03 .. 11-09 → 11-05 onward are allowed (tomorrow = 11-05)
    assert fare_watch._estimate_calls(w) == 5


@pytest.mark.asyncio
async def test_fetch_fares_comma_code_lists_are_passed_through(user, monkeypatch):
    call = AsyncMock(return_value=_serp([300]))
    monkeypatch.setattr(serp_flights, "_call", call)
    w = fare_watch_db.get_watch(
        _new_watch(user, origin_code="LHR,LGW,STN", return_date=None)["id"]
    )
    await fare_watch.fetch_fares(w, KEY)
    params = call.call_args.args[0]
    assert params["departure_id"] == "LHR,LGW,STN"
    assert params["type"] == "2"


@pytest.mark.asyncio
async def test_fetch_fares_propagates_serpapi_errors(user, monkeypatch):
    monkeypatch.setattr(
        serp_flights, "_call", AsyncMock(side_effect=SerpAPIError("HTTP 500"))
    )
    w = fare_watch_db.get_watch(_new_watch(user)["id"])
    with pytest.raises(SerpAPIError):
        await fare_watch.fetch_fares(w, KEY)


@pytest.mark.asyncio
async def test_check_watch_end_to_end_with_mocked_serpapi(user, monkeypatch):
    monkeypatch.setattr(
        serp_flights, "_call", AsyncMock(return_value=_serp([500], INSIGHTS))
    )
    w = _new_watch(user)
    out = await check_watch(w["id"], now=NOW, api_key=KEY, rand=lambda: 0.5)
    assert out.status == "checked"
    got = fare_watch_db.get_watch(w["id"])
    assert got["baseline_price"] == 500.0
    assert (got["google_typical_low"], got["google_typical_high"]) == (520, 700)
    assert fare_watch_db.calls_used("2026-11-04") == 1


# ── DB helpers ────────────────────────────────────────────────────────────────


def test_watches_are_scoped_to_their_owner(user):
    other = create_user(f"fw-{uuid.uuid4().hex[:8]}", "pw-123456789")
    w = _new_watch(user)
    assert fare_watch_db.get_watch_for_user(w["id"], user["id"])["id"] == w["id"]
    assert fare_watch_db.get_watch_for_user(w["id"], other["id"]) is None
    assert fare_watch_db.delete_watch(w["id"], other["id"]) is False
    assert fare_watch_db.delete_watch(w["id"], user["id"]) is True
    assert fare_watch_db.get_watch(w["id"]) is None


def test_new_watch_defaults(user):
    w = _new_watch(user)
    assert w["status"] == "active"
    assert w["cabin"] == "economy"
    assert w["email_enabled"] is False
    assert w["check_count"] == 0
    assert w["failure_count"] == 0
    assert w["next_check_at"] == NOW.isoformat()
    assert w["created_at"] == NOW.isoformat()


def test_count_active(user):
    a = _new_watch(user)
    _new_watch(user)
    fare_watch_db.update_watch(a["id"], status="paused")
    assert fare_watch_db.count_active(user["id"]) == 1


def test_notifications_read_state(user):
    a = notifications_db.add_notification(
        user["id"], "fare_drop", "t1", "b1", {"watch_id": 1}, now=NOW
    )
    b = notifications_db.add_notification(
        user["id"], "fare_target", "t2", "b2", {"watch_id": 1}, now=NOW
    )
    assert notifications_db.count_unread(user["id"]) == 2
    notifications_db.mark_read(user["id"], [a["id"]], now=NOW)
    assert notifications_db.count_unread(user["id"]) == 1
    page = notifications_db.list_notifications(user["id"], unread_only=True)
    assert [n["id"] for n in page["items"]] == [b["id"]]
    notifications_db.mark_read(user["id"], None, now=NOW)
    assert notifications_db.count_unread(user["id"]) == 0


def test_notifications_newest_first_and_paginated(user):
    for i in range(5):
        notifications_db.add_notification(
            user["id"], "fare_drop", f"t{i}", "b", {}, now=NOW + timedelta(minutes=i)
        )
    page = notifications_db.list_notifications(user["id"], limit=2, offset=1)
    assert [n["title"] for n in page["items"]] == ["t3", "t2"]
    assert page["total"] == 5


def test_mark_read_ignores_other_users_ids(user):
    other = create_user(f"fw-{uuid.uuid4().hex[:8]}", "pw-123456789")
    n = notifications_db.add_notification(
        other["id"], "fare_drop", "t", "b", {}, now=NOW
    )
    notifications_db.mark_read(user["id"], [n["id"]], now=NOW)
    assert notifications_db.count_unread(other["id"]) == 1
