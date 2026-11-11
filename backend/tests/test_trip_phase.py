import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.services.trip_phase import (
    day_index,
    days_to_start,
    effective_phase,
    resolve_today,
    trip_dates,
)

CASES = json.loads(
    (
        Path(__file__).parent / "fixtures" / "journey" / "trip_phase_cases.json"
    ).read_text()
)
REQUIRED = {
    "no_dates_dreaming",
    "end_before_start_single_day",
    "day_before_start_ready_window",
    "fifteen_days_out_planning",
    "prep_complete_far_out_ready",
    "first_day_on_the_road",
    "last_day_on_the_road",
    "day_after_end_memories",
    "override_wins",
    "tokyo_morning_day1",
    "no_end_date",
}


def _d(value):
    return date.fromisoformat(value) if value else None


def test_fixture_shape():
    assert len(CASES) >= 20
    assert REQUIRED <= {c["name"] for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_case(case):
    start, end, today = _d(case["start"]), _d(case["end"]), _d(case["today"])
    assert (
        effective_phase(start, end, case["override"], today, case["prep_complete"])
        == case["phase"]
    )
    assert day_index(start, end, today) == case["day_index"]
    assert days_to_start(start, today) == case["days_to_start"]


NOW = datetime(2026, 11, 12, 22, 0, tzinfo=UTC)


def test_resolve_today_accepts_client_day_ahead():
    assert resolve_today("2026-11-13", now=NOW) == date(2026, 11, 13)


def test_resolve_today_rejects_far_client_day():
    assert resolve_today("2026-11-20", now=NOW) == date(2026, 11, 12)


@pytest.mark.parametrize("junk", ["junk", "", None, "2026-13-45"])
def test_resolve_today_junk_is_utc(junk):
    assert resolve_today(junk, now=NOW) == date(2026, 11, 12)


def test_trip_dates_columns_then_search_data():
    plan = {
        "start_date": None,
        "search_data": {"departure_date": "2026-12-01", "return_date": "2026-12-08"},
    }
    assert trip_dates(plan) == (date(2026, 12, 1), date(2026, 12, 8))
    plan["start_date"], plan["end_date"] = "2027-01-01", "2027-01-05"
    assert trip_dates(plan) == (date(2027, 1, 1), date(2027, 1, 5))


def test_trip_dates_end_before_start_and_missing():
    plan = {
        "search_data": {"departure_date": "2026-12-05", "return_date": "2026-12-01"}
    }
    assert trip_dates(plan) == (date(2026, 12, 5), date(2026, 12, 5))
    assert trip_dates({}) == (None, None)
    assert trip_dates({"search_data": None}) == (None, None)
