from datetime import date

import pytest

from app.db import plans_db
from app.db.database import get_connection
from app.services.trip_recap import build_recap, haversine_km

TODAY = date(2027, 5, 1)


def _plan(**kw):
    p = {
        "id": 1,
        "name": "n",
        "search_data": {
            "destination": "Lisbon",
            "departure_date": "2027-04-01",
            "return_date": "2027-04-08",
        },
        "selections": {},
        "recap_completed_at": None,
    }
    p.update(kw)
    return p


def _recap(plan=None, places=(), codes=(), today=TODAY, spend=None):
    return build_recap(
        plan or _plan(),
        places=list(places),
        journal_count=2,
        checkin_days=3,
        spend=spend or {},
        user_country_codes=set(codes),
        today=today,
    )


def test_distance_two_points():
    d = haversine_km((38.7000, -9.1400), (38.7090, -9.1400))
    assert d == pytest.approx(1.0, abs=0.05)


def test_no_coordinates_distance_null():
    r = _recap(places=[{"visited": True, "name": "a"}, {"visited": True, "name": "b"}])
    assert r["route"] == [] and r["distance_km"] is None


def test_distance_and_order():
    places = [
        {"visited": True, "day": "2027-04-02", "lat": 38.709, "lng": -9.14},
        {"visited": True, "day": "2027-04-01", "lat": 38.7, "lng": -9.14},
        {"visited": False, "day": "2027-04-01", "lat": 10, "lng": 10},
    ]
    r = _recap(places=places)
    assert r["route"][0] == [38.7, -9.14]
    assert r["distance_km"] == pytest.approx(1.0, abs=0.1)
    assert r["visited_count"] == 2


def test_route_capped_500():
    places = [
        {"visited": True, "day": "2027-04-01", "lat": 1.0 + i * 1e-4, "lng": 2.0}
        for i in range(600)
    ]
    assert len(_recap(places=places)["route"]) == 500


def test_avg_stars_ignores_null():
    places = [{"stars": 5}, {"stars": 4}, {"stars": None}, {}]
    r = _recap(places=places)
    assert r["rated_count"] == 2 and r["avg_stars"] == 4.5
    assert _recap()["avg_stars"] is None


def test_spend_passthrough():
    spend = {
        "spent_usd": "10.00",
        "by_category_usd": {"food": "10.00"},
        "unconverted": ["GBP"],
    }
    plan = _plan()
    plan["search_data"]["budget_usd"] = 3000
    s = _recap(plan, spend=spend)["spend"]
    assert s == {
        "budget_usd": 3000,
        "plan_cost_usd": None,
        "spent_usd": "10.00",
        "by_category_usd": {"food": "10.00"},
        "unconverted": ["GBP"],
    }


def test_days_and_new_flag():
    r = _recap()
    assert (r["days"], r["nights"]) == (8, 7)
    assert r["countries"][0]["code"] == "PT" and r["countries"][0]["new"] is True
    assert r["continents"] == ["EU"] and r["can_complete"] is True
    assert _recap(codes={"PT"})["countries"][0]["new"] is False


# --- routes ---


@pytest.fixture
def mk(client, admin_headers):
    ids = []

    def make(dep="2027-04-01", ret="2027-04-08", dest="Lisbon"):
        sd = {"destination": dest}
        if dep:
            sd["departure_date"] = dep
        if ret:
            sd["return_date"] = ret
        plan = plans_db.save_plan("admin", "t", sd, {})
        with get_connection() as conn:
            conn.execute(
                "UPDATE plans SET start_date=?, end_date=? WHERE id=?",
                (dep, ret, plan["id"]),
            )
        ids.append(plan["id"])
        return plan["id"]

    yield make
    with get_connection() as conn:
        conn.execute("DELETE FROM user_countries")
        for i in ids:
            conn.execute("DELETE FROM plans WHERE id=?", (i,))


def test_not_ready_before_end(client, admin_headers, mk):
    pid = mk()
    r = client.post(
        f"/api/trips/{pid}/recap/complete?today=2027-04-08", headers=admin_headers
    )
    assert r.status_code == 409 and r.json()["error_code"] == "recap_not_ready"
    pid2 = mk(dep=None, ret=None)
    r = client.post(f"/api/trips/{pid2}/recap/complete", headers=admin_headers)
    assert r.status_code == 409


def test_complete_twice_same_completed_at(client, admin_headers, mk):
    pid = mk(dep="2020-04-01", ret="2020-04-08")
    a = client.post(f"/api/trips/{pid}/recap/complete", headers=admin_headers).json()
    b = client.post(f"/api/trips/{pid}/recap/complete", headers=admin_headers).json()
    assert a["new_countries"] == ["PT"]
    assert b["completed_at"] == a["completed_at"] and b["new_countries"] == []
    g = client.get(f"/api/trips/{pid}/recap", headers=admin_headers).json()
    assert g["completed_at"] == a["completed_at"] and g["can_complete"] is False
    assert g["countries"][0]["new"] is True  # added by this very trip


def test_new_countries_only_first_time(client, admin_headers, mk):
    p1 = mk(dep="2020-04-01", ret="2020-04-08")
    p2 = mk(dep="2021-04-01", ret="2021-04-08")
    assert client.post(f"/api/trips/{p1}/recap/complete", headers=admin_headers).json()[
        "new_countries"
    ] == ["PT"]
    r = client.post(f"/api/trips/{p2}/recap/complete", headers=admin_headers).json()
    assert r["new_countries"] == []
    g = client.get(f"/api/trips/{p2}/recap", headers=admin_headers).json()
    assert g["countries"][0]["new"] is False


def test_recap_404_for_other_user(client, admin_headers):
    assert (
        client.get("/api/trips/999999/recap", headers=admin_headers).status_code == 404
    )
