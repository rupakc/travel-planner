"""Price watches in the shared scheduler loop: leasing, concurrency, crash
isolation and lifespan wiring. Fake clock, fake source; the real loop is
never started."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db import fare_watch_db, notifications_db, price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user, create_users_table
from app.services import fare_watch, price_watch
from app.services.price_watch import CreatedWatch, PriceObservation, record_created

from .price_watch_fakes import FakeSource, ok

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    price_watch_db.create_price_watch_tables()
    notifications_db.create_notifications_table()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10_000)
    with get_connection() as conn:  # only this test's watches are due
        conn.execute("UPDATE price_watches SET status = 'paused'")
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")


@pytest.fixture
def src():
    s = FakeSource()
    s.cost = 0
    price_watch.register_source(s)
    yield s
    price_watch.unregister_source("test")


@pytest.fixture
def user():
    return create_user(f"pws-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _due(user, expires_on="2027-02-01"):
    created = CreatedWatch(
        subject={"name": "Thing"},
        baseline=PriceObservation(price=400.0, source="fake_live"),
        title="Thing",
        subtitle=None,
        expires_on=expires_on,
    )
    w = record_created(
        user["id"],
        "test",
        created,
        match_key=uuid.uuid4().hex,
        alert_mode="any_drop",
        target_price=None,
        email_enabled=False,
        now=NOW - timedelta(hours=13),
        rand=lambda: 0.5,
    )
    return w


async def test_run_due_checks_due_watches_and_reschedules(src, user):
    w = _due(user)
    later = _due(user)
    price_watch_db.update_watch(
        later["id"], next_check_at=(NOW + timedelta(hours=1)).isoformat()
    )
    src.queue.append(ok(390.0))
    outcomes = await price_watch.run_due("k", clock=lambda: NOW, rand=lambda: 0.5)
    assert [o.status for o in outcomes] == ["checked"]
    got = price_watch_db.get_watch(w["id"])
    assert got["lease_until"] is None
    assert got["next_check_at"] == (NOW + timedelta(hours=12)).isoformat()
    assert await price_watch.run_due("k", clock=lambda: NOW) == []


async def test_run_due_checks_at_most_three_at_once(src, user):
    ws = [_due(user) for _ in range(7)]
    live = peak = 0

    async def check(watch, key):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return ok(390.0)

    src.check = check
    outcomes = await price_watch.run_due("k", clock=lambda: NOW)
    assert len(outcomes) == len(ws) and peak == 3


async def test_concurrent_passes_never_check_the_same_watch(src, user):
    ws = [_due(user) for _ in range(6)]
    seen = []

    async def check(watch, key):
        seen.append(watch["id"])
        await asyncio.sleep(0)
        return ok(390.0)

    src.check = check
    await asyncio.gather(
        price_watch.run_due("k", clock=lambda: NOW),
        price_watch.run_due("k", clock=lambda: NOW),
    )
    assert sorted(seen) == sorted(w["id"] for w in ws)


async def test_a_watch_held_by_check_now_is_skipped(src, user):
    w = _due(user)
    price_watch_db.claim_watch(w["id"], NOW, NOW + timedelta(minutes=10))
    assert await price_watch.run_due("k", clock=lambda: NOW) == []
    assert src.checked == []


async def test_one_crashing_check_does_not_stop_the_others(src, user, monkeypatch):
    a, b = _due(user), _due(user)
    real = price_watch.check_watch

    async def flaky(watch_id, **kw):
        if watch_id == a["id"]:
            raise RuntimeError("db locked")
        return await real(watch_id, **kw)

    monkeypatch.setattr(price_watch, "check_watch", flaky)
    src.queue.append(ok(390.0))
    outcomes = await price_watch.run_due("k", clock=lambda: NOW)
    assert [o.status for o in outcomes if o] == ["checked"]
    assert price_watch_db.get_watch(a["id"])["lease_until"] is None
    assert price_watch_db.get_watch(b["id"])["check_count"] == 2


async def test_run_due_quietly_ends_paused_watches_past_their_day(src, user):
    w = _due(user, expires_on="2026-11-04")
    price_watch_db.update_watch(w["id"], status="paused")
    await price_watch.run_due("k", clock=lambda: NOW)
    assert price_watch_db.get_watch(w["id"])["status"] == "expired"
    assert notifications_db.list_notifications(user["id"])["items"] == []


# ── One loop for both kinds of watch ──────────────────────────────────────────


async def test_one_loop_runs_fare_and_price_passes_and_survives_errors(monkeypatch):
    calls = []

    async def fare_pass(api_key, **kw):
        calls.append(("fare", api_key))
        if len(calls) == 1:
            raise RuntimeError("fare tick broke")
        return []

    async def price_pass(api_key, **kw):
        calls.append(("price", api_key))
        if len(calls) == 4:
            raise RuntimeError("price tick broke")
        return []

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(fare_watch, "run_due", fare_pass)
    monkeypatch.setattr(price_watch, "run_due", price_pass)
    monkeypatch.setattr(settings, "fare_watch_tick_seconds", 7)
    with pytest.raises(asyncio.CancelledError):
        await fare_watch.run_scheduler("k", sleep=fake_sleep)
    assert calls == [("fare", "k"), ("price", "k")] * 3
    assert sleeps == [7, 7, 7]


def test_lifespan_creates_the_price_watch_tables(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    created = []
    real = price_watch_db.create_price_watch_tables
    monkeypatch.setattr(
        price_watch_db,
        "create_price_watch_tables",
        lambda: created.append(1) or real(),
    )
    with TestClient(app):
        pass
    assert created == [1]


# ── Built-in sources ──────────────────────────────────────────────────────────


def test_builtin_sources_are_registered_from_their_modules(monkeypatch):
    monkeypatch.setattr(price_watch, "SOURCE_MODULES", ("tests.price_watch_fakes",))
    try:
        assert price_watch.register_builtin_sources() == ["test"]
        assert isinstance(price_watch.get_source("test"), FakeSource)
    finally:
        price_watch.unregister_source("test")


def test_a_broken_source_module_is_logged_not_fatal(monkeypatch, caplog):
    monkeypatch.setattr(price_watch, "SOURCE_MODULES", ("tests.no_such_module",))
    assert price_watch.register_builtin_sources() == []
    assert "no_such_module" in caplog.text


def test_lifespan_registers_the_builtin_sources(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    calls = []
    monkeypatch.setattr(
        price_watch, "register_builtin_sources", lambda: calls.append(1) or []
    )
    with TestClient(app):
        pass
    assert calls == [1]
