"""Fare-watch trigger rules and anti-spam rules (pure ``evaluate``).

Alert model (review ruling, replaces the plan's wording):
- Two signals with their own references: the traveller's own dates
  (target / drop / Google-low) and the cheapest nearby date (flexible).
  A nearby-date alert never moves the own-dates reference.
- First alert of a signal: measured from the baseline.
- Every repeat alert of a signal needs a further drop of max($15, 5 %)
  below that signal's last alerted price — except after re-arming: a
  signal re-arms when its price rebounds ≥ max($15, 5 %) above its last
  alerted price (any_drop: the reference becomes the peak since the
  alert) or, in target mode, back above the target by max($15, 5 %).
- 24 h cooldown per watch as a cap: inside it, only a price ≥ 5 % below
  the most recent alert gets through.
Sequence behaviour through real checks: test_fare_watch_sequences.py.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.fare_watch import COOLDOWN, FareCheck, evaluate, step

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LONG_AGO = (NOW - timedelta(days=3)).isoformat()


def _watch(**over):
    w = {
        "id": 7,
        "origin_code": "BER",
        "destination_code": "LIS",
        "origin_label": "Berlin, Germany",
        "destination_label": "Lisbon, Portugal",
        "departure_date": "2026-12-01",
        "return_date": "2026-12-08",
        "num_travelers": 2,
        "flexible_days": 0,
        "alert_mode": "any_drop",
        "target_price": None,
        "baseline_price": 500.0,
        "last_price": 500.0,
        "lowest_price": 500.0,
        "own_lowest_price": 500.0,
        "lowest_price_date": "2026-12-01",
        "last_notified_price": None,
        "last_notified_at": None,
        "own_peak_price": None,
        "cheaper_notified_price": None,
        "cheaper_notified_at": None,
        "cheaper_peak_price": None,
        "check_count": 1,
    }
    w.update(over)
    return w


def _alerted(price, peak=None, when=LONG_AGO, **over):
    """A watch whose own dates were last alerted at ``price``."""
    return _watch(
        last_notified_price=price,
        last_notified_at=when,
        own_peak_price=peak if peak is not None else price,
        own_lowest_price=min(price, over.pop("own_lowest_price", price)),
        lowest_price=min(price, over.pop("lowest_price", price)),
        **over,
    )


def _check(price=500.0, **over):
    return FareCheck(price=price, **over)


def kinds(notes):
    return [n["kind"] for n in notes]


def test_step_is_fifteen_dollars_or_five_percent():
    assert step(100) == 15
    assert step(300) == 15
    assert step(500) == 25
    assert step(1000) == 50


# ── First check / missing data ────────────────────────────────────────────────


def test_first_check_never_notifies_even_on_a_huge_drop():
    w = _watch(baseline_price=None, last_price=None, lowest_price=None, check_count=0)
    assert evaluate(w, _check(100.0, price_level="low"), NOW) == []


def test_check_count_zero_with_baseline_still_counts_as_first_check():
    assert evaluate(_watch(check_count=0), _check(100.0), NOW) == []


def test_no_price_found_never_notifies():
    assert evaluate(_watch(), _check(None), NOW) == []


# ── any_drop: first alert from the baseline ───────────────────────────────────


def test_first_drop_fires_at_exactly_five_percent_of_baseline():
    notes = evaluate(_watch(), _check(475.0), NOW)
    assert kinds(notes) == ["fare_drop"]
    data = notes[0]["data"]
    assert (data["price"], data["previous_price"], data["delta"]) == (
        475.0,
        500.0,
        -25.0,
    )


def test_first_drop_just_under_threshold_is_silent():
    assert evaluate(_watch(), _check(475.01), NOW) == []


def test_first_drop_uses_fifteen_dollar_floor_on_cheap_fares():
    w = _watch(baseline_price=120.0, own_lowest_price=120.0, lowest_price=120.0)
    assert kinds(evaluate(w, _check(105.0), NOW)) == ["fare_drop"]
    assert evaluate(w, _check(105.5), NOW) == []


def test_drop_title_and_body_read_naturally():
    note = evaluate(_watch(), _check(454.0), NOW)[0]
    assert note["title"] == "Berlin → Lisbon dropped to $454 (−$46)"
    assert "1–8 Dec" in note["body"]
    assert "total for 2 travellers" in note["body"]
    assert "lowest we've seen" in note["body"]


def test_one_traveller_and_one_way_wording():
    w = _watch(num_travelers=1, return_date=None)
    body = evaluate(w, _check(400.0), NOW)[0]["body"]
    assert "total for 1 traveller." in body
    assert "For 1 Dec" in body


def test_drop_that_is_not_a_new_low_does_not_claim_lowest():
    w = _watch(baseline_price=600.0, own_lowest_price=400.0, lowest_price=400.0)
    note = evaluate(w, _check(560.0), NOW)[0]
    assert note["kind"] == "fare_drop"
    assert "lowest we've seen" not in note["body"]
    assert note["data"]["is_lowest"] is False


def test_lowest_claim_ignores_cheaper_nearby_dates():
    # A nearby date was 430 once; 454 is still the lowest for the own dates
    w = _watch(own_lowest_price=500.0, lowest_price=430.0)
    note = evaluate(w, _check(454.0), NOW)[0]
    assert note["data"]["is_lowest"] is True


def test_any_drop_ignored_in_target_mode():
    w = _watch(alert_mode="below_target", target_price=300.0)
    assert evaluate(w, _check(420.0), NOW) == []


# ── any_drop: repeats need a further step ─────────────────────────────────────


@pytest.mark.parametrize(
    "price,fires",
    [(440.0, False), (431.0, False), (427.5, True), (400.0, True)],
)
def test_repeat_drop_needs_a_further_step_below_the_last_alert(price, fires):
    # last alert 450 → step max(15, 22.5) = 22.5 → ≤ 427.5
    out = evaluate(_alerted(450.0), _check(price), NOW)
    assert kinds(out) == (["fare_drop"] if fires else [])


def test_repeat_drop_measures_delta_from_the_last_alert():
    note = evaluate(_alerted(450.0), _check(420.0), NOW)[0]
    assert note["data"]["previous_price"] == 450.0
    assert note["title"] == "Berlin → Lisbon dropped to $420 (−$30)"


def test_small_rebound_does_not_rearm():
    # Peak 470 after an alert at 450 is below 450 + 22.5: still measured from 450
    w = _alerted(450.0, peak=470.0)
    assert evaluate(w, _check(440.0), NOW) == []
    assert kinds(evaluate(w, _check(427.5), NOW)) == ["fare_drop"]


def test_rebound_rearms_with_the_peak_as_reference():
    # Alert at 400, peak 600 since (≥ 400 + 20): reference is 600 → ≤ 570
    w = _alerted(400.0, peak=600.0)
    assert evaluate(w, _check(575.0), NOW) == []
    note = evaluate(w, _check(570.0), NOW)[0]
    assert note["kind"] == "fare_drop"
    assert note["data"]["previous_price"] == 600.0
    assert note["title"] == "Berlin → Lisbon dropped to $570 (−$30)"
    assert kinds(evaluate(w, _check(450.0), NOW)) == ["fare_drop"]


def test_rearm_needs_exactly_the_step():
    # 400 + max(15, 20) = 420
    assert kinds(evaluate(_alerted(400.0, peak=420.0), _check(399.0), NOW)) == [
        "fare_drop"
    ]
    assert evaluate(_alerted(400.0, peak=419.0), _check(399.0), NOW) == []


# ── below_target ──────────────────────────────────────────────────────────────


def _target(target=450.0, **over):
    return dict(alert_mode="below_target", target_price=target, **over)


def test_target_fires_at_exactly_the_target():
    notes = evaluate(_watch(**_target()), _check(450.0), NOW)
    assert kinds(notes) == ["fare_target"]
    assert notes[0]["data"]["target_price"] == 450.0
    assert notes[0]["title"] == "Berlin → Lisbon is now $450 — under your $450 target"


def test_target_silent_above_target_even_on_big_drop():
    assert evaluate(_watch(**_target(300.0)), _check(350.0), NOW) == []


def test_target_mode_without_target_never_fires():
    w = _watch(alert_mode="below_target", target_price=None)
    assert evaluate(w, _check(100.0, price_level="low"), NOW) == []


def test_target_already_met_at_baseline_needs_a_lower_price():
    w = _watch(**_target(400.0), baseline_price=380.0, own_lowest_price=380.0)
    assert evaluate(w, _check(385.0), NOW) == []
    assert evaluate(w, _check(380.0), NOW) == []
    assert kinds(evaluate(w, _check(370.0), NOW)) == ["fare_target"]


@pytest.mark.parametrize(
    "price,fires",
    [(439.0, False), (430.0, False), (418.5, False), (418.0, True), (400.0, True)],
)
def test_target_repeat_needs_a_further_step(price, fires):
    # last alert 440 under a 450 target → step(440) = 22 → ≤ 418
    out = evaluate(_alerted(440.0, **_target()), _check(price), NOW)
    assert kinds(out) == (["fare_target"] if fires else [])


def test_target_rearms_once_back_above_target_by_the_step():
    # target 450 + max(15, 22.5) = 472.5
    under_again = _check(445.0)
    assert evaluate(_alerted(440.0, peak=472.0, **_target()), under_again, NOW) == []
    assert kinds(
        evaluate(_alerted(440.0, peak=472.5, **_target()), under_again, NOW)
    ) == ["fare_target"]
    # even a price higher than the last alert, once re-armed
    assert kinds(
        evaluate(_alerted(440.0, peak=700.0, **_target()), under_again, NOW)
    ) == ["fare_target"]


def test_rearmed_target_still_needs_to_be_under_target():
    w = _alerted(440.0, peak=700.0, **_target())
    assert evaluate(w, _check(455.0), NOW) == []


def test_target_mode_skips_low_level_rule():
    w = _watch(**_target(200.0))
    assert evaluate(w, _check(480.0, price_level="low"), NOW) == []


# ── Google "low" ──────────────────────────────────────────────────────────────


def test_low_level_fires_on_new_lowest_small_drop():
    notes = evaluate(_watch(), _check(490.0, price_level="low"), NOW)
    assert kinds(notes) == ["fare_low_level"]
    assert "Google" in notes[0]["body"]


@pytest.mark.parametrize("level", ["typical", "high", None])
def test_low_level_needs_google_low(level):
    assert evaluate(_watch(), _check(490.0, price_level=level), NOW) == []


def test_low_level_needs_a_new_own_dates_lowest():
    w = _watch(own_lowest_price=480.0, lowest_price=480.0)
    assert evaluate(w, _check(490.0, price_level="low"), NOW) == []
    assert evaluate(w, _check(480.0, price_level="low"), NOW) == []


def test_low_level_repeat_needs_a_further_step():
    # Alerted (low) at 499; 498, 490 … are new lows but small moves: silent
    w = _alerted(499.0)
    for p in (498.0, 490.0, 480.0, 474.1):
        assert evaluate(w, _check(p, price_level="low"), NOW) == []
    # step(499) = 24.95 → ≤ 474.05 is a drop too, and drops outrank "low"
    assert kinds(evaluate(w, _check(474.0, price_level="low"), NOW)) == ["fare_drop"]


def test_drop_wins_over_low_level_and_mentions_google():
    notes = evaluate(_watch(), _check(450.0, price_level="low"), NOW)
    assert kinds(notes) == ["fare_drop"]
    assert "Google says this is a low price" in notes[0]["body"]


# ── Cheaper nearby date (flexible) ────────────────────────────────────────────


def _flex(**over):
    return _watch(flexible_days=3, **over)


def _cheaper(c, price=500.0, dep="2026-12-03", ret="2026-12-10", **over):
    return _check(
        price,
        cheapest_price=c,
        cheapest_departure_date=dep,
        cheapest_return_date=ret,
        **over,
    )


def test_cheaper_date_fires_at_eight_percent():
    notes = evaluate(_flex(), _cheaper(460.0), NOW)
    assert kinds(notes) == ["fare_cheaper_date"]
    note = notes[0]
    assert note["title"] == "Fly Berlin → Lisbon on 3 Dec and save $40"
    assert note["data"]["price"] == 460.0
    assert note["data"]["cheapest_departure_date"] == "2026-12-03"
    assert "3–10 Dec" in note["body"]
    links = note["data"]["links"]
    assert "BER.LIS.2026-12-03*LIS.BER.2026-12-10" in links["book"]
    assert links["replan"] == "/alerts?watch=7&replan=1&cheapest=1"


def test_cheaper_date_just_under_threshold_is_silent():
    assert evaluate(_flex(), _cheaper(460.5), NOW) == []


def test_cheaper_date_uses_25_dollar_floor():
    w = _flex(baseline_price=200.0, own_lowest_price=200.0, lowest_price=200.0)
    assert kinds(evaluate(w, _cheaper(175.0, price=200.0), NOW)) == [
        "fare_cheaper_date"
    ]
    assert evaluate(w, _cheaper(176.0, price=200.0), NOW) == []


def test_cheaper_date_only_for_flexible_watches():
    assert evaluate(_watch(), _cheaper(400.0, price=500.0), NOW) == []


def test_cheaper_date_ignored_when_cheapest_is_the_selected_date():
    check = _cheaper(400.0, price=500.0, dep="2026-12-01", ret="2026-12-08")
    assert evaluate(_flex(), check, NOW) == []


def test_cheaper_date_needs_a_selected_price():
    assert evaluate(_flex(), _cheaper(300.0, price=None), NOW) == []


def test_cheaper_date_never_fires_above_the_baseline():
    assert evaluate(_flex(), _cheaper(540.0, price=600.0), NOW) == []


def test_cheaper_date_in_target_mode_needs_to_beat_target():
    w = _flex(**_target(420.0))
    assert evaluate(w, _cheaper(440.0), NOW) == []
    assert kinds(evaluate(w, _cheaper(410.0), NOW)) == ["fare_cheaper_date"]


def test_selected_date_drop_wins_over_cheaper_date():
    assert kinds(evaluate(_flex(), _cheaper(380.0, price=450.0), NOW)) == ["fare_drop"]


def _cheaper_alerted(c, peak=None, when=LONG_AGO, **over):
    return _flex(
        cheaper_notified_price=c,
        cheaper_notified_at=when,
        cheaper_peak_price=peak if peak is not None else c,
        lowest_price=c,
        **over,
    )


@pytest.mark.parametrize("c,fires", [(460.0, False), (445.0, False), (437.0, True)])
def test_cheaper_date_repeat_needs_a_further_step(c, fires):
    # last nearby alert 460 → step 23 → ≤ 437
    out = evaluate(_cheaper_alerted(460.0), _cheaper(c), NOW)
    assert kinds(out) == (["fare_cheaper_date"] if fires else [])


def test_cheaper_date_rearms_after_a_rebound():
    w = _cheaper_alerted(460.0, peak=490.0)  # ≥ 460 + 23
    assert kinds(evaluate(w, _cheaper(465.0, price=520.0), NOW)) == [
        "fare_cheaper_date"
    ]


def test_nearby_alert_does_not_move_the_own_dates_reference():
    # Nearby alerted at 450; own dates fall 500 → 475: first own-date drop
    w = _cheaper_alerted(450.0, own_lowest_price=500.0)
    assert kinds(evaluate(w, _cheaper(450.0, price=475.0), NOW)) == ["fare_drop"]


def test_own_alert_does_not_move_the_nearby_reference():
    # Own dates alerted at 470; a nearby 455 is still a first nearby alert
    w = _alerted(470.0, flexible_days=3)
    note = evaluate(w, _cheaper(455.0, price=500.0), NOW)
    assert kinds(note) == ["fare_cheaper_date"]


# ── 24 h cooldown (cap) ───────────────────────────────────────────────────────


def test_cooldown_blocks_a_rearmed_drop_within_24h():
    recent = (NOW - timedelta(hours=2)).isoformat()
    w = _alerted(400.0, peak=600.0, when=recent)
    assert evaluate(w, _check(570.0), NOW) == []
    assert kinds(evaluate(w, _check(380.0), NOW)) == ["fare_drop"]  # ≤ 400 × 0.95


def test_cooldown_spans_signals():
    # A nearby-date alert at 450 an hour ago; the own dates' first drop to
    # 470 waits for the cooldown (needs ≤ 427.5 meanwhile)
    recent = (NOW - timedelta(hours=1)).isoformat()
    w = _cheaper_alerted(450.0, when=recent, own_lowest_price=500.0)
    assert evaluate(w, _check(470.0), NOW) == []
    assert kinds(evaluate(w, _check(427.5), NOW)) == ["fare_drop"]
    later = dict(w, cheaper_notified_at=LONG_AGO)
    assert kinds(evaluate(later, _check(470.0), NOW)) == ["fare_drop"]


def test_cooldown_uses_the_most_recent_alert_of_either_signal():
    old_own = (NOW - timedelta(hours=20)).isoformat()
    newer_nearby = (NOW - timedelta(hours=2)).isoformat()
    w = _alerted(
        480.0,
        when=old_own,
        flexible_days=3,
        cheaper_notified_price=420.0,
        cheaper_notified_at=newer_nearby,
        cheaper_peak_price=420.0,
    )
    # 455 is a valid own repeat (≤ 480 − 24 = 456) but not ≤ 420 × 0.95
    assert evaluate(w, _check(455.0), NOW) == []
    assert kinds(evaluate(w, _check(399.0), NOW)) == ["fare_drop"]


def test_cooldown_ends_after_exactly_24h():
    at_24h = _alerted(440.0, peak=700.0, when=(NOW - COOLDOWN).isoformat(), **_target())
    just_inside = dict(
        at_24h, last_notified_at=(NOW - COOLDOWN + timedelta(seconds=1)).isoformat()
    )
    assert kinds(evaluate(at_24h, _check(445.0), NOW)) == ["fare_target"]
    assert evaluate(just_inside, _check(445.0), NOW) == []


def test_cooldown_accepts_naive_and_z_suffixed_timestamps():
    for stamp in ("2026-11-04T11:00:00", "2026-11-04T11:00:00Z"):
        w = _alerted(440.0, peak=700.0, when=stamp, **_target())
        assert evaluate(w, _check(445.0), NOW) == []


# ── Shape ─────────────────────────────────────────────────────────────────────


def test_never_notifies_for_increases_or_equal_prices():
    for over in ({}, _target(900.0)):
        w = _watch(**over)
        assert evaluate(w, _check(520.0, price_level="low"), NOW) == []
        assert evaluate(w, _check(500.0, price_level="low"), NOW) == []


def test_returns_at_most_one_notification():
    notes = evaluate(_flex(), _cheaper(300.0, price=400.0, price_level="low"), NOW)
    assert len(notes) == 1


@pytest.mark.parametrize("over", [{}, _target(460.0)])
def test_notification_carries_deep_links(over):
    note = evaluate(_watch(**over), _check(450.0), NOW)[0]
    links = note["data"]["links"]
    assert links["alerts"] == "/alerts?watch=7"
    assert links["replan"] == "/alerts?watch=7&replan=1"
    assert links["book"].startswith("https://www.google.com/flights#flt=BER.LIS.")
    assert note["data"]["watch_id"] == 7
    assert note["data"]["num_travelers"] == 2
