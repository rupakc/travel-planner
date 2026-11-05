"""The kind-agnostic own-price rules shared by fare and price watches.

Sequence-level equivalence with the pre-extraction fare rules lives in
test_price_rules_equivalence.py.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services import price_rules
from app.services.price_rules import (
    COOLDOWN,
    FARE_STEP,
    TRIP_STEP,
    Step,
    advance_own,
    cooldown_blocks,
    own_signal,
    rearmed,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def sig(price, **over):
    kw = {
        "mode": "any_drop",
        "target": None,
        "baseline": 500.0,
        "last": None,
        "peak": None,
    }
    kw.update(over)
    return own_signal(price, **kw)


# ── Steps ─────────────────────────────────────────────────────────────────────


def test_fare_step_is_fifteen_dollars_or_five_percent():
    assert [FARE_STEP(p) for p in (100, 300, 500, 1000)] == [15, 15, 25, 50]


def test_trip_step_is_twenty_five_dollars_or_four_percent():
    assert [TRIP_STEP(p) for p in (100, 625, 1000, 2500)] == [25, 25, 40, 100]


def test_a_step_is_a_value_object():
    assert Step(15.0, 0.05) == FARE_STEP
    assert price_rules.DEFAULT_STEP is FARE_STEP


def test_rearmed_needs_a_full_step_rebound():
    assert rearmed(400.0, None) is False
    assert rearmed(400.0, 419.99) is False
    assert rearmed(400.0, 420.0) is True
    assert rearmed(1000.0, 1039.0, TRIP_STEP) is False
    assert rearmed(1000.0, 1040.0, TRIP_STEP) is True


# ── own_signal: any_drop ──────────────────────────────────────────────────────


def test_first_drop_is_measured_from_the_baseline():
    s = sig(475.0)
    assert (s.drop, s.target, s.reference) == (True, False, 500.0)
    assert sig(475.01).drop is False


def test_rises_and_equal_prices_never_fire():
    for p in (500.0, 520.0):
        s = sig(p)
        assert not s.drop and not s.target and not s.repeat_ok


def test_repeat_needs_a_further_step_below_the_last_alert():
    assert sig(452.0, last=470.0, peak=470.0).drop is False
    s = sig(446.5, last=470.0, peak=470.0)
    assert (s.drop, s.reference) == (True, 470.0)


def test_rebound_rearms_with_the_peak_as_reference():
    s = sig(470.0, last=400.0, peak=600.0)
    assert (s.drop, s.reference, s.repeat_ok) == (True, 600.0, True)


def test_custom_step_scales_every_threshold():
    # trip: max($25, 4 %) of 1000 = 40
    assert sig(965.0, baseline=1000.0, step=TRIP_STEP).drop is False
    assert sig(960.0, baseline=1000.0, step=TRIP_STEP).drop is True


def test_any_drop_never_reports_a_target():
    assert sig(100.0, target=450.0).target is False


# ── own_signal: below_target ──────────────────────────────────────────────────


def test_target_fires_when_crossing_from_above():
    s = sig(450.0, mode="below_target", target=450.0, baseline=600.0)
    assert (s.target, s.drop, s.reference) == (True, False, 600.0)
    assert sig(451.0, mode="below_target", target=450.0).target is False


def test_target_without_a_target_price_never_fires():
    assert sig(10.0, mode="below_target", target=None).target is False


def test_target_already_met_at_baseline_needs_a_full_step():
    kw = {"mode": "below_target", "target": 450.0, "baseline": 430.0}
    assert sig(409.0, **kw).target is False
    assert sig(408.5, **kw).target is True


def test_target_repeat_and_rearm():
    kw = {"mode": "below_target", "target": 450.0, "baseline": 600.0}
    assert sig(430.0, last=440.0, peak=440.0, **kw).target is False
    assert sig(418.0, last=440.0, peak=440.0, **kw).target is True
    # back above the target by step(450) = 22.5 re-arms
    assert sig(445.0, last=440.0, peak=472.5, **kw).target is True
    assert sig(445.0, last=440.0, peak=472.0, **kw).target is False


def test_baseline_already_low_needs_a_full_step_to_repeat_ok():
    assert sig(490.0, baseline_already_low=True).repeat_ok is False
    assert sig(475.0, baseline_already_low=True).repeat_ok is True
    assert sig(499.0).repeat_ok is True


# ── Cooldown ──────────────────────────────────────────────────────────────────


def test_cooldown_blocks_unless_five_percent_below_the_last_alert():
    latest = (NOW - timedelta(hours=2), 400.0)
    assert cooldown_blocks(390.0, latest, NOW) is True
    assert cooldown_blocks(380.0, latest, NOW) is False
    assert cooldown_blocks(390.0, (NOW - COOLDOWN, 400.0), NOW) is False
    assert cooldown_blocks(390.0, None, NOW) is False


# ── State after a check ───────────────────────────────────────────────────────


def test_an_alert_resets_reference_and_peak():
    got = advance_own(420.0, alerted=True, last=500.0, peak=530.0, stamp="t")
    assert got == {
        "last_notified_price": 420.0,
        "last_notified_at": "t",
        "own_peak_price": 420.0,
    }


def test_peak_follows_rebounds_after_an_alert_only():
    assert advance_own(450.0, alerted=False, last=400.0, peak=420.0, stamp="t") == {
        "own_peak_price": 450.0
    }
    assert advance_own(410.0, alerted=False, last=400.0, peak=420.0, stamp="t") == {
        "own_peak_price": 420.0
    }
    assert advance_own(410.0, alerted=False, last=400.0, peak=None, stamp="t") == {
        "own_peak_price": 410.0
    }
    assert advance_own(410.0, alerted=False, last=None, peak=None, stamp="t") == {}


@pytest.mark.parametrize("bad", ["drop", "", "target"])
def test_own_signal_rejects_unknown_modes(bad):
    with pytest.raises(ValueError):
        sig(400.0, mode=bad)
