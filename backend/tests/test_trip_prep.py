"""Prep checklist: pure builder, DB state and routes."""

from datetime import date

import pytest

from app.db import trip_prep_db, trip_snapshot_db
from app.services.trip_prep import build_items, prep_summary, visa_lead_days

TODAY = date(2027, 3, 1)


def _plan(**over):
    plan = {
        "id": 1,
        "username": "admin",
        "search_data": {
            "destination": "Japan",
            "nationality": "American",
            "departure_date": "2027-04-01",
            "return_date": "2027-04-08",
        },
        "selections": {},
    }
    plan.update(over)
    return plan


def _by_id(items):
    return {i["id"]: i for i in items}


def test_visa_free_is_na():
    items = _by_id(build_items(_plan(), None, {}, TODAY))
    assert items["visa"]["status"] == "na"
    assert items["visa"]["facts"]["source"] == "static"


def test_visa_lead_days():
    assert visa_lead_days("5-10 business days", "e-visa") == 21
    assert visa_lead_days("2 weeks", "e-visa") == 21
    assert visa_lead_days("3-4 weeks", "e-visa") == 35
    assert visa_lead_days("N/A (visa-free)", "visa-free") is None
    assert visa_lead_days("varies", "e-visa") == 21
    assert visa_lead_days(None, "visa-required") == 21


def test_due_dates_relative_to_start():
    items = _by_id(build_items(_plan(), None, {}, TODAY))
    assert items["passport"]["due"] == "2027-03-02"
    assert items["insurance"]["due"] == "2027-03-18"
    assert items["documents"]["due"] == "2027-03-25"
    assert items["sim"]["due"] == "2027-03-29"
    assert items["packing"]["due"] == "2027-03-31"
    assert items["visa"]["due"] == "2027-03-11"  # visa-free falls back to 21 days
    assert [i for i in items][-1] == "offline_pack"


def test_overdue_flag():
    items = _by_id(build_items(_plan(), None, {}, date(2027, 3, 20)))
    assert items["passport"]["overdue"] is True
    assert items["packing"]["overdue"] is False
    done = {"passport": {"done": True}}
    items = _by_id(build_items(_plan(), None, done, date(2027, 3, 20)))
    assert items["passport"]["status"] == "done"
    assert items["passport"]["overdue"] is False


def test_checkin_na_without_flight():
    items = _by_id(build_items(_plan(), None, {}, TODAY))
    assert items["checkin"]["status"] == "na"
    sel = {"flight": {"airline": "X"}, "hotel": {"name": "H"}}
    items = _by_id(build_items(_plan(selections=sel), None, {}, TODAY))
    assert items["checkin"]["status"] == "todo"
    assert items["bookings"]["facts"] == {"flight": True, "hotel": True}


def test_stress_test_na_without_itinerary():
    items = _by_id(build_items(_plan(), None, {}, TODAY))
    assert items["stress_test"]["status"] == "na"
    sel = {"itinerary_slots": [{"day": 1}]}
    state = {"stress_test": {"done": False, "meta": {"score": 82}}}
    items = _by_id(build_items(_plan(selections=sel), None, state, TODAY))
    assert items["stress_test"]["status"] == "todo"
    assert items["stress_test"]["facts"] == {"score": 82}


def test_dreaming_trip_has_no_due():
    plan = _plan(search_data={"destination": "Japan"})
    items = build_items(plan, None, {}, TODAY)
    assert all(i["due"] is None and i["overdue"] is False for i in items)
    assert prep_summary(plan, TODAY) == {
        "done": 0,
        "total": 0,
        "percent": 0,
        "complete": False,
    }


def test_snapshot_visa_preferred_over_static():
    snap = {
        "visa": {
            "visa_type": "e-visa",
            "max_stay_days": 30,
            "processing_time": "3-4 weeks",
            "official_url": "https://x.test",
        },
        "forex": {"local_currency": {"code": "JPY"}},
        "packing_list": {"categories": [{"items": [{}, {}]}, {"items": [{}]}]},
    }
    items = _by_id(build_items(_plan(), snap, {}, TODAY))
    assert items["visa"]["status"] == "todo"
    assert items["visa"]["facts"]["source"] == "ai"
    assert items["visa"]["facts"]["max_stay_days"] == 30
    assert items["visa"]["due"] == "2027-02-25"  # 35 days before
    assert items["money"]["facts"] == {"currency": "JPY"}
    assert items["packing"]["facts"] == {"items": 3}


def test_money_currency_from_static_tables():
    items = _by_id(build_items(_plan(), None, {}, TODAY))
    assert items["money"]["facts"]["currency"] == "JPY"


# ---- routes ----


@pytest.fixture
def trip(client, admin_headers):
    r = client.post(
        "/api/plans",
        json={
            "name": "Prep",
            "search_data": {
                "destination": "Japan",
                "nationality": "American",
                "departure_date": "2999-04-01",
                "return_date": "2999-04-08",
            },
            "selections": {},
        },
        headers=admin_headers,
    )
    return r.json()["id"]


def test_get_prep_and_404(client, admin_headers, trip):
    r = client.get(f"/api/trips/{trip}/prep", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 9 and body["done"] == 0 and body["complete"] is False
    assert (
        client.get("/api/trips/999999/prep", headers=admin_headers).status_code == 404
    )


def test_put_errors(client, admin_headers, trip):
    base = f"/api/trips/{trip}/prep"
    r = client.put(f"{base}/nope", json={"done": True}, headers=admin_headers)
    assert (r.status_code, r.json()["error_code"]) == (404, "prep_item_unknown")
    r = client.put(f"{base}/visa", json={"done": True}, headers=admin_headers)
    assert (r.status_code, r.json()["error_code"]) == (409, "prep_item_na")


def test_offline_pack_put_is_409(client, admin_headers, trip):
    r = client.put(
        f"/api/trips/{trip}/prep/offline_pack",
        json={"done": True},
        headers=admin_headers,
    )
    assert (r.status_code, r.json()["error_code"]) == (409, "prep_item_auto")


def test_complete_awards_once(client, admin_headers, trip, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.game.trip_hooks.on_trip_ready",
        lambda uid, pid: calls.append(pid) or {"points": 10},
    )
    base = f"/api/trips/{trip}/prep"
    ids = ["passport", "bookings", "insurance", "documents", "sim", "money"]
    ids += ["packing", "emergency_card"]
    for i in ids:
        r = client.put(f"{base}/{i}", json={"done": True}, headers=admin_headers)
        assert r.status_code == 200 and r.json()["game"] is None
    trip_prep_db.set_done(trip, "offline_pack", True)
    r = client.put(f"{base}/passport", json={"done": False}, headers=admin_headers)
    assert r.json()["game"] is None and calls == []
    r = client.put(f"{base}/passport", json={"done": True}, headers=admin_headers)
    body = r.json()
    assert body["complete"] is True and body["percent"] == 100
    assert body["game"] == {"points": 10} and calls == [trip]
    assert body["item"]["id"] == "passport" and body["item"]["status"] == "done"
    client.put(f"{base}/passport", json={"done": False}, headers=admin_headers)
    r = client.put(f"{base}/passport", json={"done": True}, headers=admin_headers)
    assert r.json()["game"] is None and calls == [trip]


def test_db_meta_and_snapshot_roundtrip(trip):
    trip_prep_db.set_done(trip, "sim", True)
    trip_prep_db.set_meta(trip, "sim", {"x": 1})
    st = trip_prep_db.get_state(trip)["sim"]
    assert st["done"] is True and st["meta"] == {"x": 1}
    assert trip_prep_db.get_meta(trip, "nope") is None
    trip_snapshot_db.put_snapshot(trip, {"visa": {"visa_type": "e-visa"}})
    items = _by_id(
        build_items(_plan(id=trip), trip_snapshot_db.get_snapshot(trip), {}, TODAY)
    )
    assert items["visa"]["facts"]["source"] == "ai"
