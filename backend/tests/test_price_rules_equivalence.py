"""Old vs new: the fare rules after the ``price_rules`` extraction decide
exactly what the frozen pre-extraction rules (``legacy_fare_rules``) decided.

Identical price sequences (the scripted ones from
test_fare_watch_sequences.py plus seeded random walks across both alert
modes, Google price levels, nearby dates and uneven gaps) are evaluated
step by step through both paths on the same evolving watch state.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.services import fare_watch
from app.services.fare_watch import FareCheck

from . import legacy_fare_rules as legacy

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
DEP = "2027-02-01"
NEAR = "2027-02-03"


def _watch(**over):
    w = {
        "id": 1,
        "origin_code": "BER",
        "destination_code": "LIS",
        "origin_label": "Berlin",
        "destination_label": "Lisbon",
        "departure_date": DEP,
        "return_date": None,
        "num_travelers": 1,
        "flexible_days": 0,
        "alert_mode": "any_drop",
        "target_price": None,
        "baseline_price": None,
        "check_count": 0,
    }
    w.update(over)
    return w


def _advance(w: dict, check: FareCheck, kind: str | None, stamp: str) -> None:
    """The state a check leaves behind (pre-extraction ``_record_success``)."""
    p, c = check.price, check.cheapest_price
    if p is not None:
        w["last_price"] = p
        w["check_count"] = (w.get("check_count") or 0) + 1
        if w.get("baseline_price") is None:
            w["baseline_price"] = p
            w["baseline_price_level"] = check.price_level
        if w.get("own_lowest_price") is None or p < w["own_lowest_price"]:
            w["own_lowest_price"] = p
        if kind in ("fare_target", "fare_drop", "fare_low_level"):
            w.update(last_notified_price=p, last_notified_at=stamp, own_peak_price=p)
        elif w.get("last_notified_price") is not None:
            w["own_peak_price"] = max(w.get("own_peak_price") or p, p)
    if c is not None:
        if kind == "fare_cheaper_date":
            w.update(
                cheaper_notified_price=c,
                cheaper_notified_at=stamp,
                cheaper_peak_price=c,
            )
        elif w.get("cheaper_notified_price") is not None:
            w["cheaper_peak_price"] = max(w.get("cheaper_peak_price") or c, c)
    for price in (p, c):
        if price is not None and (
            w.get("lowest_price") is None or price < w["lowest_price"]
        ):
            w["lowest_price"] = price


def _new(w, check, now):
    return [
        (n["kind"], n["data"]["price"], n["data"]["previous_price"])
        for n in fare_watch.evaluate(w, check, now)
    ]


def _drive(checks, gaps, **fields):
    """Run both paths; return the per-step decisions (asserting they agree)."""
    w = _watch(**fields)
    now = START
    decisions = []
    for check, gap in zip(checks, gaps):
        old = legacy.evaluate(w, check, now)
        new = _new(w, check, now)
        assert new == old, (check, w)
        kind = old[0][0] if old else None
        decisions.append(kind)
        _advance(w, check, kind, now.isoformat())
        now += gap
    return decisions


DAY = timedelta(hours=25)

SCRIPTED = [
    ([500, 400, 600, 600, 450, 450, 420], {}),
    (
        [600, 440, 700, 700, 445, 430],
        {"alert_mode": "below_target", "target_price": 450},
    ),
    (list(range(500, 420, -5)), {}),
    ([460, *range(440, 415, -1)], {"alert_mode": "below_target", "target_price": 450}),
    ([500, 470, 485, 470, 485, 470, 485, 470], {}),
    ([500, 470, 495, 470, 495, 470], {}),
    (
        [600, 440, 460, 445, 470, 449],
        {"alert_mode": "below_target", "target_price": 450},
    ),
    (
        [600, 440, 480, 440, 480, 440],
        {"alert_mode": "below_target", "target_price": 450},
    ),
    ([430, 425, 420, 409, 408.5], {"alert_mode": "below_target", "target_price": 450}),
    ([460, 449], {"alert_mode": "below_target", "target_price": 450}),
]


@pytest.mark.parametrize("prices,fields", SCRIPTED)
def test_scripted_sequences_decide_the_same(prices, fields):
    checks = [FareCheck(price=float(p)) for p in prices]
    decisions = _drive(checks, [DAY] * len(checks), **fields)
    assert any(decisions)  # every scripted sequence alerts at least once


def test_google_low_and_nearby_sequences_decide_the_same():
    low = [FareCheck(price=500.0, price_level="typical")] + [
        FareCheck(price=float(p), price_level="low") for p in range(499, 470, -1)
    ]
    assert "fare_low_level" in _drive(low, [DAY] * len(low))
    nearby = [
        FareCheck(
            price=500.0,
            cheapest_price=float(c),
            cheapest_departure_date=NEAR,
        )
        for c in (500, 450, 440, 427, 460, 436)
    ]
    assert "fare_cheaper_date" in _drive(nearby, [DAY] * 6, flexible_days=3)


def test_cooldown_sequences_decide_the_same():
    checks = [FareCheck(price=float(p)) for p in (500, 450, 520, 490, 490)]
    gaps = [DAY, timedelta(hours=6), timedelta(hours=6), timedelta(hours=14), DAY]
    assert _drive(checks, gaps) == [None, "fare_drop", None, None, "fare_drop"]


def _random_check(rng: random.Random, price: float) -> FareCheck:
    level = rng.choice([None, None, "low", "typical", "high"])
    if rng.random() < 0.05:
        return FareCheck(price=None)
    if rng.random() < 0.4:
        nearby = round(price * rng.uniform(0.75, 1.05), 2)
        dep = rng.choice([NEAR, DEP])
        return FareCheck(
            price=price,
            price_level=level,
            cheapest_price=nearby,
            cheapest_departure_date=dep,
        )
    return FareCheck(price=price, price_level=level)


@pytest.mark.parametrize("seed", range(40))
def test_random_walks_decide_the_same(seed):
    rng = random.Random(seed)
    total_alerts = 0
    for _ in range(25):
        price = rng.uniform(80, 1500)
        checks = []
        for _ in range(rng.randint(5, 30)):
            price = max(20.0, round(price * rng.uniform(0.85, 1.12), 2))
            checks.append(_random_check(rng, price))
        gaps = [timedelta(hours=rng.choice([1, 6, 12, 23, 24, 25, 48])) for _ in checks]
        mode = rng.choice(["any_drop", "below_target"])
        fields = {
            "alert_mode": mode,
            "flexible_days": rng.choice([0, 3]),
            "target_price": (
                round(checks[0].price * rng.uniform(0.7, 1.1), 2)
                if mode == "below_target" and checks[0].price
                else None
            ),
        }
        total_alerts += sum(1 for d in _drive(checks, gaps, **fields) if d)
    assert total_alerts > 0
