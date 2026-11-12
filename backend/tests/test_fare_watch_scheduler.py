"""Fare-watch scheduler: leasing, concurrency, the loop and lifespan wiring.
Fake clock, injected fetch — the real loop is never started."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db import fare_watch_db, notifications_db
from app.db.database import get_connection
from app.db.users_db import create_user, create_users_table
from app.services import fare_watch
from app.services.fare_watch import FareCheck

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _tables(monkeypatch):
    # tokens are minted directly — skip bcrypt's deliberate slowness
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    notifications_db.create_notifications_table()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10_000)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda w: 0)
    with get_connection() as conn:  # only this test's watches are due
        conn.execute("UPDATE fare_watches SET status = 'paused'")
        conn.execute("DELETE FROM fare_watch_quota")


@pytest.fixture
def user():
    return create_user(f"fs-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _watch(user, **over):
    fields = {
        "origin_code": "BER",
        "destination_code": "LIS",
        "origin_label": "Berlin",
        "destination_label": "Lisbon",
        "departure_date": "2026-12-01",
        "return_date": None,
        "num_travelers": 1,
        "alert_mode": "any_drop",
    }
    fields.update(over)
    return fare_watch_db.create_watch(user["id"], fields, now=NOW)


# ── Leasing ───────────────────────────────────────────────────────────────────


def test_due_watch_ids_lists_only_due_active_unleased_watches(user):
    due = _watch(user)
    later = _watch(user)
    fare_watch_db.update_watch(
        later["id"], next_check_at=(NOW + timedelta(hours=1)).isoformat()
    )
    paused = _watch(user)
    fare_watch_db.update_watch(paused["id"], status="paused")
    leased = _watch(user)
    fare_watch_db.update_watch(
        leased["id"], lease_until=(NOW + timedelta(minutes=5)).isoformat()
    )
    assert fare_watch_db.due_watch_ids(NOW, 50) == [due["id"]]
    # listing takes no lease
    assert fare_watch_db.get_watch(due["id"])["lease_until"] is None


def test_due_watch_ids_respects_the_limit_oldest_first(user):
    ws = [_watch(user) for _ in range(3)]
    for i, w in enumerate(ws):
        fare_watch_db.update_watch(
            w["id"], next_check_at=(NOW - timedelta(minutes=10 - i)).isoformat()
        )
    assert fare_watch_db.due_watch_ids(NOW, 2) == [ws[0]["id"], ws[1]["id"]]


def test_a_claimed_watch_cannot_be_claimed_twice_until_the_lease_ends(user):
    w = _watch(user)
    lease = NOW + timedelta(minutes=10)
    assert fare_watch_db.claim_watch(w["id"], NOW, lease) is True
    assert (
        fare_watch_db.claim_watch(w["id"], NOW + timedelta(minutes=1), lease) is False
    )
    after = NOW + timedelta(minutes=11)  # a crashed worker's lease expires
    assert (
        fare_watch_db.claim_watch(w["id"], after, after + timedelta(minutes=10)) is True
    )


@pytest.mark.asyncio
async def test_watches_are_leased_one_by_one_as_they_are_processed(user):
    ws = [_watch(user) for _ in range(5)]
    leased_while_first_runs = []

    async def fetch(watch, key):
        if watch["id"] == ws[0]["id"]:
            leased_while_first_runs.extend(
                fare_watch_db.get_watch(w["id"])["lease_until"] is not None for w in ws
            )
        await asyncio.sleep(0)
        return FareCheck(price=100.0)

    await fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch)
    # 3 run at once; the 2 queued watches are not leased yet
    assert sum(leased_while_first_runs) <= 3
    assert leased_while_first_runs[3:] == [False, False]


@pytest.mark.asyncio
async def test_a_watch_taken_by_check_now_meanwhile_is_skipped(user):
    first, second = _watch(user), _watch(user)
    checked = []

    async def fetch(watch, key):
        checked.append(watch["id"])
        if watch["id"] == first["id"]:
            # "Check now" grabs the second watch while it waits in the queue
            fare_watch_db.claim_watch(second["id"], NOW, NOW + timedelta(minutes=10))
        return FareCheck(price=100.0)

    fare_watch.CONCURRENCY, old = 1, fare_watch.CONCURRENCY
    try:
        await fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch)
    finally:
        fare_watch.CONCURRENCY = old
    assert checked == [first["id"]]


@pytest.mark.asyncio
async def test_concurrent_schedulers_never_check_the_same_watch(user):
    ws = [_watch(user) for _ in range(6)]
    seen: list[int] = []

    async def fetch(watch, key):
        seen.append(watch["id"])
        await asyncio.sleep(0)
        return FareCheck(price=100.0)

    await asyncio.gather(
        fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch),
        fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch),
    )
    assert sorted(seen) == sorted(w["id"] for w in ws)


# ── run_due ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_due_checks_at_most_three_at_once(user):
    for _ in range(7):
        _watch(user)
    live = peak = 0

    async def fetch(watch, key):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return FareCheck(price=200.0)

    outcomes = await fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch)
    assert len(outcomes) == 7
    assert peak == 3
    assert all(o.status == "checked" for o in outcomes)


@pytest.mark.asyncio
async def test_run_due_releases_leases_and_reschedules(user):
    w = _watch(user)

    async def fetch(watch, key):
        return FareCheck(price=200.0)

    await fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch, rand=lambda: 0.5)
    got = fare_watch_db.get_watch(w["id"])
    assert got["lease_until"] is None
    assert got["next_check_at"] == (NOW + timedelta(hours=12)).isoformat()
    # not due again until then
    assert await fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch) == []


@pytest.mark.asyncio
async def test_one_crashing_check_does_not_stop_the_others(user, monkeypatch):
    a, b = _watch(user), _watch(user)
    real = fare_watch.check_watch

    async def flaky(watch_id, **kw):
        if watch_id == a["id"]:
            raise RuntimeError("db locked")
        return await real(watch_id, **kw)

    monkeypatch.setattr(fare_watch, "check_watch", flaky)

    async def fetch(watch, key):
        return FareCheck(price=200.0)

    outcomes = await fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch)
    assert [o.status for o in outcomes if o] == ["checked"]
    assert fare_watch_db.get_watch(a["id"])["lease_until"] is None
    assert fare_watch_db.get_watch(b["id"])["check_count"] == 1


# ── Loop ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_ticks_and_survives_errors(monkeypatch):
    calls = []

    async def fake_run_due(api_key, **kw):
        calls.append(api_key)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return []

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(fare_watch, "run_due", fake_run_due)
    monkeypatch.setattr(settings, "fare_watch_tick_seconds", 42)
    with pytest.raises(asyncio.CancelledError):
        await fare_watch.run_scheduler("k", sleep=fake_sleep)
    assert calls == ["k", "k", "k"]
    assert sleeps == [42, 42, 42]


@pytest.mark.parametrize(
    "key,enabled,starts",
    [("k", True, True), ("", True, False), ("k", False, False)],
)
@pytest.mark.asyncio
async def test_scheduler_starts_only_with_serpapi_and_enabled(
    monkeypatch, key, enabled, starts
):
    monkeypatch.setattr(settings, "serpapi_key", key)
    monkeypatch.setattr(settings, "fare_watch_enabled", enabled)
    started = asyncio.Event()

    async def fake_scheduler(api_key, **kw):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(fare_watch, "run_scheduler", fake_scheduler)
    task = fare_watch.start_scheduler()
    assert (task is not None) is starts
    if task:
        await asyncio.sleep(0)
        assert started.is_set()
        await fare_watch.stop_scheduler(task)
        assert task.cancelled()


def test_test_suite_never_runs_the_real_loop():
    assert settings.fare_watch_enabled is False


@pytest.mark.asyncio
async def test_run_due_quietly_ends_paused_and_errored_watches_past_departure(user):
    paused = _watch(user, departure_date="2026-11-04")
    fare_watch_db.update_watch(paused["id"], status="paused")
    errored = _watch(user, departure_date="2026-11-01")
    fare_watch_db.update_watch(errored["id"], status="error")
    future = _watch(user, departure_date="2026-11-05")
    fare_watch_db.update_watch(future["id"], status="paused")

    async def fetch(watch, key):
        return FareCheck(price=100.0)

    await fare_watch.run_due("k", clock=lambda: NOW, fetch=fetch)
    assert fare_watch_db.get_watch(paused["id"])["status"] == "expired"
    assert fare_watch_db.get_watch(errored["id"])["status"] == "expired"
    assert fare_watch_db.get_watch(future["id"])["status"] == "paused"
    assert notifications_db.list_notifications(user["id"])["items"] == []


# ── Notification retention ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_due_sweeps_notifications_older_than_180_days_once_a_day(
    user, monkeypatch
):
    monkeypatch.setattr(fare_watch, "_swept_day", None)
    old = notifications_db.add_notification(
        user["id"], "fare_drop", "old", "b", {}, now=NOW - timedelta(days=181)
    )
    kept = notifications_db.add_notification(
        user["id"], "fare_drop", "kept", "b", {}, now=NOW - timedelta(days=179)
    )
    await fare_watch.run_due("k", clock=lambda: NOW)
    ids = [n["id"] for n in notifications_db.list_notifications(user["id"])["items"]]
    assert old["id"] not in ids and kept["id"] in ids

    sweeps = []
    monkeypatch.setattr(
        notifications_db, "delete_older_than", lambda cutoff: sweeps.append(cutoff)
    )
    await fare_watch.run_due("k", clock=lambda: NOW + timedelta(hours=1))
    assert sweeps == []  # same UTC day
    await fare_watch.run_due("k", clock=lambda: NOW + timedelta(days=1))
    assert len(sweeps) == 1


@pytest.fixture(autouse=True)
def _legacy_alerts(monkeypatch):
    """These tests cover the legacy (flag off) alert pipeline."""
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", False)
