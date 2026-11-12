"""Drop moment facts and the savings tally (Phase 3, Task 5)."""

import json
import uuid
from pathlib import Path

import pytest

from app.db import alerts_db, users_db
from app.services import alert_moments

CASES = json.loads(
    (Path(__file__).parent / "fixtures/alerts/savings_cases.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_savings_golden(case):
    got = alert_moments.compute_savings(
        case["input"]["rows"], case["input"]["watches_active"]
    )
    assert got == case["expected"]


def _fare_note(kind="fare_drop", price=412.0, prev=455.0):
    return {"kind": kind, "title": "t", "body": "b",
            "data": {"price": price, "previous_price": prev}}  # fmt: skip


def test_drop_facts_fare_drop():
    f = alert_moments.drop_facts("flight", {"id": 1}, _fare_note())
    assert f == {"from": 455.0, "to": 412.0, "amount": 43.0, "pct": 9.5,
                 "currency": "USD", "target_hit": False, "observed": True}  # fmt: skip


@pytest.mark.parametrize(
    "kind", ["fare_target", "hotel_target", "activity_target", "trip_target"]
)
def test_drop_facts_target_kinds(kind):
    f = alert_moments.drop_facts(
        "hotel", {"id": 1, "currency": "EUR"}, _fare_note(kind)
    )
    assert f["target_hit"] is True and f["currency"] == "EUR"


def test_eur_drop_not_in_usd_total():
    watch = {"id": 4, "currency": "EUR"}
    f = alert_moments.drop_facts("activity", watch, _fare_note("activity_drop", 28, 40))
    assert f["currency"] == "EUR" and f["amount"] == 12.0
    rows = [{"kind": "activity", "watch_id": 4, "title": "x", "currency": "EUR",
             "baseline": 40.0, "alerted_price": 28.0, "notification_id": 1,
             "at": "2026-11-01T00:00:00Z", "target_hit": False}]  # fmt: skip
    s = alert_moments.compute_savings(rows, 1)
    assert s["total_usd"] == 0 and s["by_currency"] == {"EUR": 12.0}


def test_expired_and_error_notes_have_no_drop():
    for kind in ("watch_expired", "watch_error", "price_digest"):
        note = {
            "kind": kind,
            "title": "t",
            "body": "",
            "data": {"price": 1, "previous_price": 2},
        }
        assert alert_moments.drop_facts("flight", {"id": 1}, note) is None
    no_price = {"kind": "fare_drop", "title": "t", "body": "", "data": {}}
    assert alert_moments.drop_facts("flight", {"id": 1}, no_price) is None


def test_estimate_never_counts_or_awards():
    # a trip whose parts are all estimates
    trip = {"id": 9, "currency": "USD",
            "subject": {"components": [{"id": "f", "live": False}]}}  # fmt: skip
    assert alert_moments.drop_facts("trip", trip, _fare_note("trip_drop")) is None
    # a trip drop whose moving part is an estimate
    note = _fare_note("trip_drop")
    note["data"]["components"] = [{"group": "hotels", "delta": -50, "live": False}]
    live_trip = {"id": 9, "subject": {"components": [{"id": "f", "live": True}]}}
    assert alert_moments.drop_facts("trip", live_trip, note) is None
    # a hotel that holds only an estimate
    hotel = {"id": 3, "currency": "USD", "last_observation": {"status": "estimate"}}
    assert alert_moments.drop_facts("hotel", hotel, _fare_note("hotel_drop")) is None
    est = _fare_note("hotel_drop")
    est["data"]["estimate"] = {"price": 100, "source": "ai_estimate"}
    assert alert_moments.drop_facts("hotel", {"id": 3}, est) is None
    # a live trip with no explained moves still counts
    assert alert_moments.drop_facts("trip", live_trip, _fare_note("trip_drop"))


def test_record_idempotent_per_notification(client):
    uid = users_db.create_user(f"m{uuid.uuid4().hex[:10]}", "pw-long-enough-1")["id"]
    alerts_db.create_alert_tables()
    watch = {"id": 7, "baseline_price": 455.0}
    drop = alert_moments.drop_facts("flight", watch, _fare_note())
    row = {"id": 501, "user_id": uid, "created_at": "2026-11-01T00:00:00Z",
           "data": {"drop": drop}}  # fmt: skip
    assert alert_moments.record("flight", watch, row) is True
    assert alert_moments.record("flight", watch, row) is False
    assert len(alerts_db.savings_rows(uid)) == 1
    assert (
        alert_moments.record("flight", watch, {**row, "id": 502, "data": {}}) is False
    )


def test_summary_progress_pct(client):
    uid = users_db.create_user(f"m{uuid.uuid4().hex[:10]}", "pw-long-enough-1")["id"]
    alerts_db.create_alert_tables()
    watch = {"id": 7, "baseline_price": 500.0}
    drop = alert_moments.drop_facts(
        "flight", watch, _fare_note(price=460.0, prev=500.0)
    )
    alert_moments.record("flight", watch, {"id": 601, "user_id": uid,
                         "created_at": "2026-11-01T00:00:00Z", "data": {"drop": drop}})  # fmt: skip
    s = alert_moments.summary(uid)
    assert s["total_usd"] == 40.0 and s["progress_pct"] == 80
    assert s["next_milestone"] == 50 and s["drops_caught"] == 1
    assert s["best"]["watch_id"] == 7 and s["best"]["caught"] == 40.0
