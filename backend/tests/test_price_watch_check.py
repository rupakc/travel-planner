"""One price-watch check through the generic pipeline (fake ``test`` source,
fake clock, real SQLite): alerts, unavailable looks, failures, expiry, the
shared SerpAPI budget and email."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db import fare_watch_db, notifications_db, price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user, create_users_table
from app.services import alert_email, fare_watch, price_rules, price_watch
from app.services.fare_watch import FareCheck
from app.services.price_watch import (
    CreatedWatch,
    PriceObservation,
    check_watch,
    record_created,
)

from .price_watch_fakes import FakeSource, QuotaError, gone, ok

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
DAY = timedelta(hours=25)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    price_watch_db.create_price_watch_tables()
    notifications_db.create_notifications_table()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10_000)
    monkeypatch.setattr(settings, "smtp_host", "")
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")


@pytest.fixture
def src():
    s = FakeSource()
    price_watch.register_source(s)
    yield s
    price_watch.unregister_source("test")


@pytest.fixture
def user():
    return create_user(f"pwc-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _create(user, baseline=400.0, *, now=START, **over):
    created = CreatedWatch(
        subject={"name": "Thing"},
        baseline=PriceObservation(
            price=baseline, source="fake_live", link="https://example.test/b"
        ),
        title=over.pop("title", "Lumen Hotel"),
        subtitle="Lisbon",
        expires_on=over.pop("expires_on", "2027-02-01"),
    )
    opts = {
        "alert_mode": "any_drop",
        "target_price": None,
        "email_enabled": False,
        "match_key": uuid.uuid4().hex,
    }
    opts.update(over)
    return record_created(
        user["id"], "test", created, now=now, rand=lambda: 0.5, **opts
    )


async def _run(src, user, steps, gap=DAY, **over):
    w = _create(user, steps[0], **over)
    out = []
    t = START + gap
    for s in steps[1:]:
        src.queue.append(s if isinstance(s, PriceObservation) else ok(s))
        res = await check_watch(w["id"], now=t, api_key="k")
        out.append(res.notification["kind"] if res.notification else ".")
        t += gap
    return w, out


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_round_trip(src):
    assert price_watch.get_source("test") is src
    assert "test" in price_watch.registered_kinds()
    assert price_watch.get_source("nope") is None


def test_register_rejects_a_source_without_the_protocol():
    class Half:
        kind = "half"

    with pytest.raises(TypeError):
        price_watch.register_source(Half())


def test_step_defaults_to_the_fare_step(src):
    assert price_watch.step_for(src) is price_rules.FARE_STEP
    src.step = price_rules.TRIP_STEP
    assert price_watch.step_for(src) is price_rules.TRIP_STEP


# ── Baseline from creation ────────────────────────────────────────────────────


def test_record_created_stores_the_baseline_look(src, user):
    w = _create(user, 398.0, target_price=350.0, alert_mode="below_target")
    assert (w["baseline_price"], w["last_price"], w["lowest_price"]) == (398.0,) * 3
    assert w["check_count"] == 1
    assert w["last_checked_at"] == START.isoformat()
    assert w["next_check_at"] == (START + timedelta(hours=12)).isoformat()
    assert w["last_observation"]["link"] == "https://example.test/b"
    assert w["last_observation"]["status"] == "ok"
    h = price_watch_db.get_history(w["id"])
    assert [r["price"] for r in h] == [398.0]


# ── Alerts ────────────────────────────────────────────────────────────────────


async def test_drop_alert_with_generic_data(src, user):
    w, got = await _run(src, user, [400.0, 380.0])
    assert got == ["test_drop"]
    note = notifications_db.list_notifications(user["id"])["items"][0]
    d = note["data"]
    assert d["watch_kind"] == "test" and d["watch_id"] == w["id"]
    assert (d["price"], d["previous_price"], d["delta"]) == (380.0, 400.0, -20.0)
    assert d["baseline_price"] == 400.0 and d["is_lowest"] is True
    assert d["custom"] == "yes"  # the source's own data is kept
    assert d["links"]["alerts"] == f"/alerts?kind=test&watch={w['id']}"
    assert note["title"] == "Lumen Hotel dropped: $380"


async def test_target_alert(src, user):
    _, got = await _run(
        src, user, [400.0, 360.0, 340.0], alert_mode="below_target", target_price=350.0
    )
    assert got == [".", "test_target"]


async def test_same_sequences_alert_where_a_fare_watch_alerts(src, user):
    """Own-price decisions match the fare path for the same prices."""
    seqs = [
        ([500, 400, 600, 600, 450, 450, 420], {}),
        ([500, 470, 485, 470, 485, 470, 485, 470], {}),
        ([500, 470, 495, 470, 495, 470], {}),
        (list(range(500, 420, -5)), {}),
        ([600, 440, 700, 700, 445, 430], {"target_price": 450.0}),
        ([430, 425, 420, 409, 408.5], {"target_price": 450.0}),
    ]
    for prices, extra in seqs:
        mode = "below_target" if extra else "any_drop"
        _, got = await _run(src, user, prices, alert_mode=mode, **extra)
        fare = await _fare_decisions(user, prices, mode, extra.get("target_price"))
        assert [g.removeprefix("test_") for g in got] == fare, prices


async def _fare_decisions(user, prices, mode, target):
    w = fare_watch_db.create_watch(
        user["id"],
        {
            "origin_code": "BER",
            "destination_code": "LIS",
            "origin_label": "Berlin",
            "destination_label": "Lisbon",
            "departure_date": "2027-02-01",
            "num_travelers": 1,
            "alert_mode": mode,
            "target_price": target,
        },
        now=START,
    )
    out = []
    t = START
    for p in prices:

        async def fetch(watch, key, p=p):
            return FareCheck(price=float(p))

        res = await fare_watch.check_watch(w["id"], now=t, api_key="k", fetch=fetch)
        out.append(res.notification["kind"][5:] if res.notification else ".")
        t += DAY
    return out[1:]


async def test_trip_step_raises_the_threshold(src, user):
    src.step = price_rules.TRIP_STEP  # max($25, 4 %): 1000 → 40
    _, got = await _run(src, user, [1000.0, 965.0, 960.0])
    assert got == [".", "test_drop"]


async def test_cooldown_caps_alerts_within_a_day(src, user):
    _, got = await _run(src, user, [500.0, 470.0, 450.0, 440.0], gap=timedelta(hours=2))
    # 450 isn't ≤ 470 × 0.95 = 446.5 inside 24 h; 440 is
    assert got == ["test_drop", ".", "test_drop"]


async def test_rises_never_alert_and_state_follows_peaks(src, user):
    w, got = await _run(src, user, [400.0, 370.0, 420.0])
    assert got == ["test_drop", "."]
    row = price_watch_db.get_watch(w["id"])
    assert (row["last_notified_price"], row["own_peak_price"]) == (370.0, 420.0)
    assert (row["last_price"], row["lowest_price"], row["check_count"]) == (
        420.0,
        370.0,
        3,
    )


async def test_successful_check_records_history_and_observation(src, user):
    w = _create(user, 400.0)
    src.queue.append(
        ok(390.0, link="https://example.test/now", observed={"rating": 4.7})
    )
    res = await check_watch(w["id"], now=START + DAY, api_key="k")
    assert res.status == "checked"
    row = price_watch_db.get_watch(w["id"])
    assert row["last_observation"]["link"] == "https://example.test/now"
    assert row["last_observation"]["observed_at"] == (START + DAY).isoformat()
    assert row["lease_until"] is None and row["failure_count"] == 0
    h = price_watch_db.get_history(w["id"])
    assert h[-1]["price"] == 390.0 and h[-1]["observed"]["rating"] == 4.7


async def test_trip_breakdown_is_kept_in_history(src, user):
    w = _create(user, 1000.0)
    parts = [{"label": "Flights", "price": 600.0, "live": True}]
    src.queue.append(ok(990.0, breakdown=parts))
    await check_watch(w["id"], now=START + DAY, api_key="k")
    assert price_watch_db.get_history(w["id"])[-1]["breakdown"] == parts
    assert price_watch_db.get_watch(w["id"])["last_observation"]["breakdown"] == parts


# ── Unavailable looks ─────────────────────────────────────────────────────────


async def test_unavailable_is_not_an_alert_nor_a_failure(src, user):
    w, got = await _run(src, user, [400.0, gone(), gone(), 380.0])
    assert got == [".", ".", "test_drop"]
    row = price_watch_db.get_watch(w["id"])
    assert row["unavailable_count"] == 0 and row["failure_count"] == 0
    assert row["status"] == "active"
    prices = [h["price"] for h in price_watch_db.get_history(w["id"])]
    assert prices == [400.0, None, None, 380.0]


async def test_unavailable_reschedules_at_the_normal_cadence(src, user):
    w = _create(user)
    src.queue.append(gone())
    res = await check_watch(w["id"], now=START + DAY, api_key="k", rand=lambda: 0.5)
    assert res.status == "unavailable"
    assert res.watch["next_check_at"] == (START + DAY + timedelta(hours=12)).isoformat()
    assert res.watch["unavailable_count"] == 1
    assert res.watch["last_observation"]["status"] == "unavailable"
    assert res.watch["last_price"] == 400.0  # the last real price stays


async def test_three_unavailable_in_a_row_pause_the_watch_with_a_notice(src, user):
    w, got = await _run(src, user, [400.0, gone(), gone(), gone()])
    row = price_watch_db.get_watch(w["id"])
    assert row["status"] == "error"
    notes = notifications_db.list_notifications(user["id"])["items"]
    assert [n["kind"] for n in notes] == ["watch_error"]
    assert notes[0]["data"]["watch_kind"] == "test"
    assert notes[0]["data"]["reason"] == "unavailable"
    assert "Lumen Hotel" in notes[0]["title"]


# ── Failures ──────────────────────────────────────────────────────────────────


async def test_failure_retries_within_the_hour_then_errors(src, user):
    w = _create(user)
    t = START + DAY
    for i in range(3):
        src.queue.append(RuntimeError("HTTP 500 from serpapi"))
        res = await check_watch(w["id"], now=t, api_key="k")
        t += timedelta(hours=1)
    assert res.status == "errored"
    row = price_watch_db.get_watch(w["id"])
    assert row["status"] == "error" and row["failure_count"] == 3
    notes = notifications_db.list_notifications(user["id"])["items"]
    assert [n["kind"] for n in notes] == ["watch_error"]
    assert notes[0]["data"]["watch_kind"] == "test"
    assert notes[0]["data"]["links"]["alerts"] == f"/alerts?kind=test&watch={w['id']}"


async def test_one_failure_schedules_a_retry(src, user):
    w = _create(user)
    src.queue.append(RuntimeError("boom"))
    res = await check_watch(w["id"], now=START + DAY, api_key="k")
    assert res.status == "failed"
    assert res.watch["next_check_at"] == (START + DAY + timedelta(hours=1)).isoformat()
    assert res.watch["lease_until"] is None


async def test_an_ok_look_without_a_price_is_a_failure(src, user):
    w = _create(user)
    src.queue.append(PriceObservation(price=None, source="fake_live"))
    res = await check_watch(w["id"], now=START + DAY, api_key="k")
    assert res.status == "failed"


async def test_account_quota_postpones_without_a_strike(src, user):
    w = _create(user)
    src.queue.append(QuotaError("quota"))
    res = await check_watch(w["id"], now=START + DAY, api_key="k", rand=lambda: 0)
    assert res.status == "postponed"
    assert res.watch["failure_count"] == 0
    assert res.watch["next_check_at"].startswith("2026-11-06T00:00")


async def test_a_success_clears_failures(src, user):
    w = _create(user)
    src.queue += [RuntimeError("x"), gone(), ok(399.0)]
    for i in range(3):
        await check_watch(w["id"], now=START + DAY * (i + 1), api_key="k")
    row = price_watch_db.get_watch(w["id"])
    assert (row["failure_count"], row["unavailable_count"], row["last_error"]) == (
        0,
        0,
        None,
    )


# ── Lifecycle ─────────────────────────────────────────────────────────────────


async def test_expires_on_its_day_with_a_notice(src, user):
    w = _create(user, expires_on="2026-11-06")
    src.queue.append(ok(300.0))
    res = await check_watch(
        w["id"], now=datetime(2026, 11, 6, 1, tzinfo=UTC), api_key="k"
    )
    assert res.status == "expired"
    assert src.checked == []
    note = res.notification
    assert note["kind"] == "watch_expired"
    assert note["data"]["watch_kind"] == "test"
    assert "$400" in note["body"]


async def test_paused_watches_are_checked_only_manually(src, user):
    w = _create(user)
    price_watch_db.update_watch(w["id"], status="paused")
    src.queue.append(ok(390.0))
    assert (
        await check_watch(w["id"], now=START + DAY, api_key="k")
    ).status == "skipped"
    res = await check_watch(w["id"], now=START + DAY, api_key="k", manual=True)
    assert res.status == "checked"


async def test_deleted_while_fetching(src, user):
    w = _create(user)

    async def check(watch, key):
        price_watch_db.delete_watch(watch["id"], user["id"])
        return ok(300.0)

    src.check = check
    res = await check_watch(w["id"], now=START + DAY, api_key="k")
    assert res.status == "deleted"
    assert notifications_db.list_notifications(user["id"])["items"] == []


async def test_missing_source_skips_without_a_strike(src, user):
    w = _create(user)
    price_watch.unregister_source("test")
    res = await check_watch(w["id"], now=START, api_key="k", rand=lambda: 0.5)
    price_watch.register_source(src)
    assert res.status == "skipped"
    row = price_watch_db.get_watch(w["id"])
    assert row["failure_count"] == 0 and row["lease_until"] is None
    assert row["next_check_at"] == (START + timedelta(hours=12)).isoformat()


# ── Shared SerpAPI budget ─────────────────────────────────────────────────────


async def test_checks_spend_the_shared_fare_watch_budget(src, user):
    w = _create(user)
    src.cost = 4
    src.queue.append(ok(399.0))
    await check_watch(w["id"], now=START, api_key="k")
    assert fare_watch_db.calls_used("2026-11-04") == 4
    assert fare_watch_db.user_calls_used("2026-11-04", user["id"]) == 4


async def test_spent_budget_postpones_scheduled_and_refuses_manual(
    src, user, monkeypatch
):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 5)
    fare_watch_db.reserve_calls("2026-11-04", 5, 5)  # fare watches used it all
    w = _create(user)
    res = await check_watch(w["id"], now=START, api_key="k", rand=lambda: 0)
    assert res.status == "postponed"
    assert res.watch["next_check_at"].startswith("2026-11-05T00:00")
    res = await check_watch(w["id"], now=START, api_key="k", manual=True)
    assert (res.status, res.reason) == ("budget_exhausted", "global")
    assert src.checked == []


async def test_owner_share_spent(src, user, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10)
    monkeypatch.setattr(settings, "fare_watch_user_daily_share", 0.3)  # 3 calls
    w = _create(user)
    src.cost = 4
    res = await check_watch(w["id"], now=START, api_key="k", manual=True)
    assert (res.status, res.reason) == ("budget_exhausted", "user")


def test_active_limit_counts_fare_and_price_watches(src, user):
    _create(user)
    fare_watch_db.create_watch(
        user["id"],
        {
            "origin_code": "BER",
            "destination_code": "LIS",
            "origin_label": "Berlin",
            "destination_label": "Lisbon",
            "departure_date": "2027-02-01",
        },
        now=START,
    )
    assert price_watch.active_watch_count(user["id"]) == 2


# ── Email ─────────────────────────────────────────────────────────────────────


async def test_alerts_are_emailed_when_enabled(src, monkeypatch):
    u = create_user(
        f"pwe-{uuid.uuid4().hex[:8]}", "pw-123456789", email="t@example.com"
    )
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    sent = []
    monkeypatch.setattr(alert_email, "send_message", sent.append)
    w = _create(u, email_enabled=True)
    src.queue.append(ok(370.0, link="https://example.test/book"))
    res = await check_watch(w["id"], now=START + DAY, api_key="k")
    assert len(sent) == 1
    msg = sent[0]
    assert msg["Subject"] == "Lumen Hotel dropped: $370"
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "$400 → $370" in text
    assert "https://example.test/book" in text
    assert "/api/price-watches/unsubscribe?token=" in text
    note = notifications_db.list_notifications(u["id"])["items"][0]
    assert note["id"] == res.notification["id"] and note["emailed_at"]


async def test_no_email_when_disabled(src, user, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    sent = []
    monkeypatch.setattr(alert_email, "send_message", sent.append)
    w = _create(user)
    src.queue.append(ok(370.0))
    await check_watch(w["id"], now=START + DAY, api_key="k")
    assert sent == []
