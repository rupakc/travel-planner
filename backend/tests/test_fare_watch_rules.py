"""Fare-watch trigger rules and anti-spam rules (pure ``evaluate``).

``evaluate(watch, check, now)`` never touches the DB or network: it decides
whether one check of a watched fare deserves a notification, and which.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.fare_watch import (
    COOLDOWN,
    FareCheck,
    evaluate,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


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
        "lowest_price_date": "2026-12-01",
        "last_notified_price": None,
        "last_notified_at": None,
        "check_count": 1,
    }
    w.update(over)
    return w


def _check(price=500.0, **over):
    return FareCheck(price=price, **over)


def kinds(notes):
    return [n["kind"] for n in notes]


# ── First check / missing data ────────────────────────────────────────────────


def test_first_check_never_notifies_even_on_a_huge_drop():
    w = _watch(baseline_price=None, last_price=None, lowest_price=None, check_count=0)
    assert evaluate(w, _check(100.0, price_level="low"), NOW) == []


def test_check_count_zero_with_baseline_still_counts_as_first_check():
    w = _watch(check_count=0)
    assert evaluate(w, _check(100.0), NOW) == []


def test_no_price_found_never_notifies():
    assert evaluate(_watch(), _check(None), NOW) == []


# ── Rule 2: any_drop ──────────────────────────────────────────────────────────


def test_any_drop_fires_at_exactly_five_percent_of_baseline():
    # baseline 500 → threshold max(15, 25) = 25 → 475 fires
    notes = evaluate(_watch(), _check(475.0), NOW)
    assert kinds(notes) == ["fare_drop"]
    data = notes[0]["data"]
    assert data["price"] == 475.0
    assert data["previous_price"] == 500.0
    assert data["delta"] == -25.0


def test_any_drop_just_under_threshold_is_silent():
    assert evaluate(_watch(), _check(475.01), NOW) == []


def test_any_drop_uses_fifteen_dollar_floor_on_cheap_fares():
    # baseline 120 → 5% = 6 → floor $15 → 105 fires, 105.5 does not
    w = _watch(baseline_price=120.0, last_price=120.0, lowest_price=120.0)
    assert kinds(evaluate(w, _check(105.0), NOW)) == ["fare_drop"]
    assert evaluate(w, _check(105.5), NOW) == []


def test_any_drop_measures_from_last_notified_price_not_baseline():
    w = _watch(
        last_notified_price=450.0,
        last_notified_at=(NOW - timedelta(days=3)).isoformat(),
        lowest_price=450.0,
    )
    # 440 is 60 below baseline but only 10 below the last alert → silent
    assert evaluate(w, _check(440.0), NOW) == []
    # threshold from 450 is max(15, 22.5) = 22.5 → 427.5 fires
    assert kinds(evaluate(w, _check(427.5), NOW)) == ["fare_drop"]


def test_any_drop_title_reads_naturally():
    note = evaluate(_watch(), _check(454.0), NOW)[0]
    assert note["title"] == "Berlin → Lisbon dropped to $454 (−$46)"
    assert "1–8 Dec" in note["body"]
    assert "total for 2 travellers" in note["body"]
    assert "lowest we've seen" in note["body"]


def test_drop_that_is_not_a_new_low_does_not_claim_lowest():
    w = _watch(
        baseline_price=600.0,
        last_price=600.0,
        lowest_price=400.0,
    )
    note = evaluate(w, _check(560.0), NOW)[0]
    assert note["kind"] == "fare_drop"
    assert "lowest we've seen" not in note["body"]
    assert note["data"]["is_lowest"] is False


def test_one_traveller_label_is_singular():
    w = _watch(num_travelers=1)
    assert "total for 1 traveller." in evaluate(w, _check(400.0), NOW)[0]["body"]


def test_one_way_dates_show_single_day():
    w = _watch(return_date=None)
    assert "1 Dec" in evaluate(w, _check(400.0), NOW)[0]["body"]


def test_any_drop_ignored_in_below_target_mode():
    w = _watch(alert_mode="below_target", target_price=300.0)
    assert evaluate(w, _check(420.0), NOW) == []


# ── Rule 1: below_target ──────────────────────────────────────────────────────


def test_target_fires_at_exactly_the_target():
    w = _watch(alert_mode="below_target", target_price=450.0)
    notes = evaluate(w, _check(450.0), NOW)
    assert kinds(notes) == ["fare_target"]
    assert notes[0]["data"]["target_price"] == 450.0
    assert "$450 target" in notes[0]["title"]


def test_target_silent_above_target_even_on_big_drop():
    w = _watch(alert_mode="below_target", target_price=300.0)
    assert evaluate(w, _check(350.0), NOW) == []


def test_target_does_not_repeat_at_same_or_higher_price():
    w = _watch(
        alert_mode="below_target",
        target_price=450.0,
        last_notified_price=430.0,
        last_notified_at=(NOW - timedelta(days=5)).isoformat(),
        lowest_price=430.0,
    )
    assert evaluate(w, _check(430.0), NOW) == []
    assert evaluate(w, _check(440.0), NOW) == []


def test_target_refires_below_previous_alert_after_cooldown():
    w = _watch(
        alert_mode="below_target",
        target_price=450.0,
        last_notified_price=430.0,
        last_notified_at=(NOW - timedelta(days=5)).isoformat(),
        lowest_price=430.0,
    )
    assert kinds(evaluate(w, _check(429.0), NOW)) == ["fare_target"]


def test_target_already_met_at_baseline_needs_a_lower_price():
    # Price was 380 when watching started with a 400 target: the UI said so.
    w = _watch(
        alert_mode="below_target",
        target_price=400.0,
        baseline_price=380.0,
        last_price=380.0,
        lowest_price=380.0,
    )
    assert evaluate(w, _check(385.0), NOW) == []
    assert evaluate(w, _check(380.0), NOW) == []
    assert kinds(evaluate(w, _check(370.0), NOW)) == ["fare_target"]


def test_target_mode_without_target_never_fires():
    w = _watch(alert_mode="below_target", target_price=None)
    assert evaluate(w, _check(100.0, price_level="low"), NOW) == []


def test_target_mode_skips_low_level_rule():
    w = _watch(alert_mode="below_target", target_price=200.0)
    assert evaluate(w, _check(480.0, price_level="low"), NOW) == []


# ── Rule 3: new lowest + Google "low" ─────────────────────────────────────────


def test_low_level_fires_on_new_lowest_small_drop():
    # 490 is only $10 below baseline (no drop alert) but is a new low that
    # Google calls "low"
    notes = evaluate(_watch(), _check(490.0, price_level="low"), NOW)
    assert kinds(notes) == ["fare_low_level"]
    assert "Google" in notes[0]["body"]


def test_low_level_needs_google_low():
    for level in ("typical", "high", None):
        assert evaluate(_watch(), _check(490.0, price_level=level), NOW) == []


def test_low_level_needs_a_new_lowest():
    # 490 is no drop rule hit (threshold 475) and 480 was already seen
    w = _watch(lowest_price=480.0)
    assert evaluate(w, _check(490.0, price_level="low"), NOW) == []
    assert evaluate(w, _check(480.0, price_level="low"), NOW) == []


def test_drop_wins_over_low_level_and_mentions_google():
    notes = evaluate(_watch(), _check(450.0, price_level="low"), NOW)
    assert kinds(notes) == ["fare_drop"]
    assert "Google says this is a low price" in notes[0]["body"]


# ── Rule 4: cheaper nearby date (flexible) ────────────────────────────────────


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
    # selected 500 → threshold max(25, 40) = 40 → 460 fires
    notes = evaluate(_flex(), _cheaper(460.0), NOW)
    assert kinds(notes) == ["fare_cheaper_date"]
    note = notes[0]
    assert note["title"] == "Fly Berlin → Lisbon on 3 Dec and save $40"
    assert note["data"]["price"] == 460.0
    assert note["data"]["cheapest_departure_date"] == "2026-12-03"
    assert "3–10 Dec" in note["body"]


def test_cheaper_date_just_under_threshold_is_silent():
    assert evaluate(_flex(), _cheaper(460.5), NOW) == []


def test_cheaper_date_uses_25_dollar_floor():
    w = _flex(baseline_price=200.0, last_price=200.0, lowest_price=200.0)
    # 8% of 200 = 16 → floor 25
    assert kinds(evaluate(w, _cheaper(175.0, price=200.0), NOW)) == [
        "fare_cheaper_date"
    ]
    assert evaluate(w, _cheaper(176.0, price=200.0), NOW) == []


def test_cheaper_date_only_for_flexible_watches():
    # Exact-date watch with no drop at its own dates: nothing at all
    assert evaluate(_watch(), _cheaper(400.0, price=500.0), NOW) == []


def test_cheaper_date_ignored_when_cheapest_is_the_selected_date():
    w = _flex()
    check = _cheaper(400.0, price=500.0, dep="2026-12-01", ret="2026-12-08")
    assert evaluate(w, check, NOW) == []


def test_cheaper_date_needs_a_selected_price():
    assert evaluate(_flex(), _cheaper(300.0, price=None), NOW) == []


def test_cheaper_date_never_fires_when_it_is_still_above_reference():
    # Selected went up to 600; a nearby 540 is cheaper than 600 but more than
    # the 500 we started at — an increase, so silent
    assert evaluate(_flex(), _cheaper(540.0, price=600.0), NOW) == []


def test_cheaper_date_in_target_mode_needs_to_beat_target():
    w = _flex(alert_mode="below_target", target_price=420.0)
    assert evaluate(w, _cheaper(440.0), NOW) == []
    assert kinds(evaluate(w, _cheaper(410.0), NOW)) == ["fare_cheaper_date"]


def test_selected_date_drop_wins_over_cheaper_date():
    notes = evaluate(_flex(), _cheaper(380.0, price=450.0), NOW)
    assert kinds(notes) == ["fare_drop"]


def test_cheaper_date_does_not_repeat_the_same_nearby_fare():
    w = _flex(
        last_notified_price=460.0,
        last_notified_at=(NOW - timedelta(days=3)).isoformat(),
        lowest_price=460.0,
    )
    assert evaluate(w, _cheaper(460.0), NOW) == []


# ── Anti-spam ─────────────────────────────────────────────────────────────────


def test_never_notifies_for_increases():
    for mode, target in (("any_drop", None), ("below_target", 900.0)):
        w = _watch(alert_mode=mode, target_price=target)
        assert evaluate(w, _check(520.0, price_level="low"), NOW) == []
        assert evaluate(w, _check(500.0, price_level="low"), NOW) == []


def test_any_drop_inside_cooldown_still_needs_its_own_threshold():
    # any_drop's threshold (>= 5 % of the last alert) already meets the
    # cooldown's "further 5 %" — both edges land on 446.5 here
    w = _watch(
        last_notified_price=470.0,
        last_notified_at=(NOW - timedelta(hours=23, minutes=59)).isoformat(),
        lowest_price=470.0,
    )
    assert evaluate(w, _check(446.6), NOW) == []
    assert kinds(evaluate(w, _check(446.5), NOW)) == ["fare_drop"]


def _recent_target_watch(hours_ago):
    return _watch(
        alert_mode="below_target",
        target_price=480.0,
        last_notified_price=470.0,
        last_notified_at=(NOW - timedelta(hours=hours_ago)).isoformat(),
        lowest_price=470.0,
    )


def test_cooldown_blocks_a_small_further_drop_within_24h():
    # 460 is under target and under the last alert, but only 2 % lower
    assert evaluate(_recent_target_watch(2), _check(460.0), NOW) == []


def test_cooldown_lets_a_further_five_percent_drop_through():
    # 5 % below 470 = 446.5
    assert evaluate(_recent_target_watch(2), _check(446.6), NOW) == []
    assert kinds(evaluate(_recent_target_watch(2), _check(446.5), NOW)) == [
        "fare_target"
    ]


def test_cooldown_ends_after_exactly_24h():
    w = _recent_target_watch(0)
    at_24h = dict(w, last_notified_at=(NOW - COOLDOWN).isoformat())
    just_inside = dict(
        w, last_notified_at=(NOW - COOLDOWN + timedelta(seconds=1)).isoformat()
    )
    assert kinds(evaluate(at_24h, _check(460.0), NOW)) == ["fare_target"]
    assert evaluate(just_inside, _check(460.0), NOW) == []


def test_cooldown_blocks_low_level_and_cheaper_date_too():
    recent = (NOW - timedelta(hours=1)).isoformat()
    w = _flex(last_notified_price=480.0, last_notified_at=recent, lowest_price=480.0)
    assert evaluate(w, _check(475.0, price_level="low"), NOW) == []
    assert evaluate(w, _cheaper(470.0, price=520.0), NOW) == []
    # …and outside the cooldown both would have fired
    old = dict(w, last_notified_at=(NOW - timedelta(days=2)).isoformat())
    assert kinds(evaluate(old, _check(475.0, price_level="low"), NOW)) == [
        "fare_low_level"
    ]
    assert kinds(evaluate(old, _cheaper(470.0, price=520.0), NOW)) == [
        "fare_cheaper_date"
    ]


def test_cooldown_accepts_naive_and_z_suffixed_timestamps():
    for stamp in ("2026-11-04T11:00:00", "2026-11-04T11:00:00Z"):
        w = dict(_recent_target_watch(0), last_notified_at=stamp)
        assert evaluate(w, _check(460.0), NOW) == []


def test_returns_at_most_one_notification():
    w = _flex(alert_mode="any_drop")
    notes = evaluate(w, _cheaper(300.0, price=400.0, price_level="low"), NOW)
    assert len(notes) == 1


@pytest.mark.parametrize(
    "kind_mode",
    [("any_drop", None), ("below_target", 460.0)],
)
def test_notification_carries_deep_links(kind_mode):
    mode, target = kind_mode
    w = _watch(alert_mode=mode, target_price=target)
    note = evaluate(w, _check(450.0), NOW)[0]
    links = note["data"]["links"]
    assert links["alerts"] == "/alerts?watch=7"
    assert links["replan"] == "/alerts?watch=7&replan=1"
    assert links["book"].startswith("https://www.google.com/flights#flt=BER.LIS.")
    assert note["data"]["watch_id"] == 7
    assert note["data"]["num_travelers"] == 2


def test_cheaper_date_book_link_uses_the_cheaper_dates():
    note = evaluate(_flex(), _cheaper(400.0, price=500.0), NOW)
    # selected-date price unchanged → the cheaper date alert is the one
    assert note[0]["kind"] == "fare_cheaper_date"
    assert "BER.LIS.2026-12-03*LIS.BER.2026-12-10" in note[0]["data"]["links"]["book"]
    assert note[0]["data"]["links"]["replan"] == "/alerts?watch=7&replan=1&cheapest=1"
