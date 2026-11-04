"""Price sequences through real checks (DB state, fake clock, injected fares).

Each sequence starts with the baseline check; ``.`` means no alert. Checks
are 25 h apart unless a test says otherwise, so the 24 h cooldown only
matters where a test makes it matter.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db import fare_watch_db, notifications_db
from app.db.database import get_connection
from app.db.users_db import create_user, create_users_table
from app.services import fare_watch
from app.services.fare_watch import FareCheck, check_watch

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
DAY = timedelta(hours=25)

SHORT = {
    "fare_drop": "drop",
    "fare_target": "target",
    "fare_low_level": "low",
    "fare_cheaper_date": "cheaper",
}


@pytest.fixture(autouse=True)
def _tables(monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    notifications_db.create_notifications_table()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 10_000)
    monkeypatch.setattr(fare_watch, "_estimate_calls", lambda w: 0)
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")


def _check(step):
    """A sequence step: price, (price, level), or (price, nearby, nearby_dep)."""
    if not isinstance(step, tuple):
        return FareCheck(price=step)
    if len(step) == 2 and isinstance(step[1], str):
        return FareCheck(price=step[0], price_level=step[1])
    price, nearby, dep = step
    return FareCheck(
        price=price,
        cheapest_price=nearby,
        cheapest_departure_date=dep,
        cheapest_return_date=None,
    )


async def run(steps, gap=DAY, **fields):
    user = create_user(f"seq-{uuid.uuid4().hex[:8]}", "pw-123456789")
    base = {
        "origin_code": "BER",
        "destination_code": "LIS",
        "origin_label": "Berlin",
        "destination_label": "Lisbon",
        "departure_date": "2027-02-01",
        "return_date": None,
        "num_travelers": 1,
        "alert_mode": "any_drop",
    }
    base.update(fields)
    w = fare_watch_db.create_watch(user["id"], base, now=START)
    out = []
    gaps = gap if isinstance(gap, list) else [gap] * len(steps)
    t = START
    for i, s in enumerate(steps):
        check = _check(s)

        async def fetch(watch, key, check=check):
            return check

        res = await check_watch(w["id"], now=t, api_key="k", fetch=fetch)
        out.append(SHORT[res.notification["kind"]] if res.notification else ".")
        t += gaps[i]
    return out


# ── The reviewer's scenarios ──────────────────────────────────────────────────


async def test_rebound_rearms_any_drop():
    # alert at 400, a week at 600, back to 450: a $150 drop is news again
    got = await run([500, 400, 600, 600, 450, 450, 420])
    assert got == [".", "drop", ".", ".", "drop", ".", "drop"]


async def test_target_rearms_after_climbing_back_above_it():
    got = await run(
        [600, 440, 700, 700, 445, 430], alert_mode="below_target", target_price=450
    )
    assert got == [".", "target", ".", ".", "target", "."]


async def test_own_dates_drop_after_a_nearby_alert_is_still_reported():
    dep = "2027-02-03"
    got = await run(
        [
            (500, 450, dep),
            (500, 450, dep),
            (500, 450, dep),
            (460, 450, dep),
            (440, 450, dep),
            (430, 450, dep),
        ],
        flexible_days=3,
    )
    assert got == [".", "cheaper", ".", "drop", ".", "drop"]


# ── Slow declines and tiny moves ──────────────────────────────────────────────


async def test_slow_decline_alerts_at_each_meaningful_step_only():
    prices = list(range(500, 420, -5))  # 500, 495 … 425, one a day
    got = await run(prices)
    alerted = [p for p, k in zip(prices, got) if k != "."]
    # 475 (−25 from 500), then ≤ 475 − 23.75 = 451.25 → 450, then ≤ 427.5 → 425
    assert alerted == [475, 450, 425]


async def test_one_dollar_a_day_under_the_target_does_not_alert_daily():
    prices = [460] + list(range(440, 415, -1))
    got = await run(prices, alert_mode="below_target", target_price=450)
    alerted = [p for p, k in zip(prices, got) if k != "."]
    assert alerted == [440, 418]  # step(440) = 22


async def test_one_dollar_a_day_google_low_does_not_alert_daily():
    prices = [(500, "typical")] + [(p, "low") for p in range(499, 470, -1)]
    got = await run(prices)
    alerted = [s[0] for s, k in zip(prices, got) if k != "."]
    assert alerted == [499, 474]  # "low" at 499, then a real drop ≤ 474.05
    assert got[1] == "low"
    assert got[prices.index((474, "low"))] == "drop"


# ── Oscillation ───────────────────────────────────────────────────────────────


async def test_oscillation_inside_the_step_never_repeats():
    got = await run([500, 470, 485, 470, 485, 470, 485, 470])
    assert got == [".", "drop", ".", ".", ".", ".", ".", "."]


async def test_oscillation_beyond_the_step_alerts_each_real_fall():
    # 470 → 495 rebounds ≥ 23.5 (re-arms); 495 → 470 is a ≥ 24.75 drop again
    got = await run([500, 470, 495, 470, 495, 470])
    assert got == [".", "drop", ".", "drop", ".", "drop"]


async def test_target_hovering_near_the_target_does_not_rearm():
    # 460 and 470 are above the 450 target but under 450 + 22.5 = 472.5
    got = await run(
        [600, 440, 460, 445, 470, 449], alert_mode="below_target", target_price=450
    )
    assert got == [".", "target", ".", ".", ".", "."]


async def test_target_can_alert_again_and_again_after_full_rebounds():
    got = await run(
        [600, 440, 480, 440, 480, 440], alert_mode="below_target", target_price=450
    )
    assert got == [".", "target", ".", "target", ".", "target"]


# ── Cooldown cap ──────────────────────────────────────────────────────────────


async def test_cooldown_caps_a_rearmed_drop_then_lets_it_through():
    # 6 h between checks: the re-armed drop to 490 is inside 24 h of the
    # 450 alert, and isn't ≤ 450 × 0.95 — it waits until the cooldown ends
    got = await run(
        [500, 450, 520, 490, 490],
        gap=[DAY, timedelta(hours=6), timedelta(hours=6), timedelta(hours=14), DAY],
    )
    assert got == [".", "drop", ".", ".", "drop"]


async def test_steep_fall_breaks_through_the_cooldown():
    got = await run(
        [500, 470, 440, 400],
        gap=timedelta(hours=2),
    )
    # 440 ≤ 470 × 0.95 = 446.5 and ≤ 470 − 23.5: allowed inside 24 h
    assert got == [".", "drop", "drop", "drop"]


# ── Nearby dates ──────────────────────────────────────────────────────────────


async def test_nearby_signal_repeats_only_on_a_further_step_or_rebound():
    dep = "2027-02-03"
    steps = [
        (500, 500, dep),  # baseline
        (500, 450, dep),  # cheaper (−50)
        (500, 440, dep),  # . (needs ≤ 427.5)
        (500, 427, dep),  # cheaper
        (500, 460, dep),  # . rebound 427 → 460 ≥ 427 + 21.35: re-armed
        (500, 436, dep),  # cheaper (≤ 460 − 23)
    ]
    got = await run(steps, flexible_days=3)
    assert got == [".", "cheaper", ".", "cheaper", ".", "cheaper"]


async def test_own_drop_does_not_silence_the_nearby_signal():
    dep = "2027-02-03"
    steps = [(500, 500, dep), (470, 470, "2027-02-01"), (470, 420, dep)]
    got = await run(steps, flexible_days=3)
    assert got == [".", "drop", "cheaper"]


async def test_state_is_persisted_per_signal():
    dep = "2027-02-03"
    user_steps = [(500, 500, dep), (500, 450, dep), (470, 450, dep), (480, 470, dep)]
    await run(user_steps, flexible_days=3)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_notified_price, own_peak_price, cheaper_notified_price, "
            "cheaper_peak_price, own_lowest_price, lowest_price "
            "FROM fare_watches ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert tuple(row) == (470.0, 480.0, 450.0, 470.0, 470.0, 450.0)


# ── Baseline already good: the first alert needs a full step ──────────────────


async def test_baseline_already_under_target_needs_a_full_step():
    # 430 at the start with a 450 target: 425 is no news; ≤ 430 − 21.5 is
    got = await run(
        [430, 425, 420, 409, 408.5], alert_mode="below_target", target_price=450
    )
    assert got == [".", ".", ".", ".", "target"]


async def test_baseline_above_target_still_alerts_on_crossing():
    got = await run([460, 449], alert_mode="below_target", target_price=450)
    assert got == [".", "target"]


async def test_baseline_already_google_low_needs_a_full_step():
    got = await run([(500, "low"), (490, "low"), (480, "low"), (475, "low")])
    assert got == [".", ".", ".", "drop"]


async def test_baseline_not_low_still_gets_the_first_low_alert():
    got = await run([(500, "typical"), (490, "low")])
    assert got == [".", "low"]


async def test_baseline_level_is_stored():
    await run([(500, "low")])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT baseline_price_level FROM fare_watches ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[0] == "low"
