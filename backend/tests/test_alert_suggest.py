"""Watch suggestions for a plan: order, cap, flags, and that each spec is
accepted by quick-watch as emitted. No network."""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import alerts_db, notifications_db, plans_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import fare_watch, price_watch, serp_flights

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
GYG = "https://www.getyourguide.com/lisbon-l42/old-town-walk-t12345/"


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 10)
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    monkeypatch.setattr(serp_flights, "_today", lambda: NOW.date())
    alerts_db.create_alert_tables()
    notifications_db.create_notifications_table()
    plans_db.create_plans_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")


def _user():
    u = create_user(f"sg-{uuid.uuid4().hex[:8]}", "pw-123456789")
    h = {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}
    return u, h


def _plan(u, sd=None, sel=None):
    data = {
        "origin": "LIS",
        "destination": "JFK",
        "departure_date": "2026-12-01",
        "return_date": "2026-12-08",
        "num_travelers": 2,
    }
    data.update(sd or {})
    pid = plans_db.save_plan(u["username"], "Trip", data, sel or {})
    return pid if isinstance(pid, int) else pid["id"]


FULL = {
    "flight": {"price_usd": 400},
    "hotel": {"name": "Lumen Hotel", "total_price_usd": 900},
    "hotels": [{"name": "Second Inn"}, {"name": "Third Inn"}],
    "activities": [
        {"name": "Old Town Walk", "booking_url": GYG, "price_usd": 30},
        {"name": "Fado Night", "booking_url": GYG + "x-t999/"},
        {"name": "Boat", "booking_url": GYG + "y-t998/"},
        {"name": "No link"},
    ],
}


def _get(client, h, pid):
    return client.get(f"/api/alerts/suggestions?plan_id={pid}", headers=h)


def test_suggest_order_and_cap(client):
    u, h = _user()
    r = _get(client, h, _plan(u, sel=FULL))
    assert r.status_code == 200
    body = r.json()
    assert body["live_prices"] is True
    kinds = [s["kind"] for s in body["suggestions"]]
    assert kinds == ["flight", "hotel", "hotel", "activity", "activity"]
    assert len(kinds) <= 5


def test_trip_after_parts_when_room(client):
    u, h = _user()
    sel = {"flight": {"price_usd": 400}, "hotel": {"name": "Lumen", "total_price_usd": 9}}
    kinds = [s["kind"] for s in _get(client, h, _plan(u, sel=sel)).json()["suggestions"]]
    assert kinds == ["flight", "hotel", "trip"]


def test_multi_city_has_no_flight(client):
    u, h = _user()
    pid = _plan(u, sd={"destinations": ["Lisbon", "Porto"]}, sel=FULL)
    kinds = [s["kind"] for s in _get(client, h, pid).json()["suggestions"]]
    assert "flight" not in kinds


def test_empty_selections_returns_flight_only(client):
    u, h = _user()
    sugg = _get(client, h, _plan(u)).json()["suggestions"]
    assert [s["kind"] for s in sugg] == ["flight"]
    assert sugg[0]["reason"] == "departure_soon"  # 27 days out


def test_reason_selected_when_far(client):
    u, h = _user()
    pid = _plan(u, sd={"departure_date": "2027-03-01", "return_date": "2027-03-08"})
    assert _get(client, h, pid).json()["suggestions"][0]["reason"] == "selected_in_plan"


def test_already_watching_flagged(client):
    u, h = _user()
    pid = _plan(u, sel=FULL)
    s = _get(client, h, pid).json()["suggestions"]
    assert not any(x["already_watching"] for x in s)
    for x in s[:2]:
        r = client.post(
            "/api/alerts/quick-watch",
            headers=h,
            json={"kind": x["kind"], "title": x["title"], "spec": x["spec"],
                  "surface": "suggest"},
        )
        assert r.status_code == 201, r.text
    flags = [x["already_watching"] for x in _get(client, h, pid).json()["suggestions"]]
    assert flags == [True, True, False, False, False]


def test_suggest_specs_accepted_by_quick_watch(client):
    u, h = _user()
    pid = _plan(u, sel=FULL)
    for x in _get(client, h, pid).json()["suggestions"]:
        r = client.post(
            "/api/alerts/quick-watch",
            headers=h,
            json={"kind": x["kind"], "title": x["title"],
                  "subtitle": x["subtitle"], "spec": x["spec"],
                  "plan_id": pid, "surface": "suggest"},
        )
        assert r.status_code in (200, 201), (x["kind"], r.text)


def test_suggest_no_network(client, monkeypatch):
    import socket

    u, h = _user()
    pid = _plan(u, sel=FULL)

    def boom(*a, **k):
        raise AssertionError("network")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert _get(client, h, pid).status_code == 200


def test_suggest_404_other_user(client):
    u, _ = _user()
    _, h2 = _user()
    r = _get(client, h2, _plan(u))
    assert r.status_code == 404
    assert r.json()["error_code"] == "trip_not_found"


def test_live_prices_flag_off(client, monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "")
    u, h = _user()
    body = _get(client, h, _plan(u)).json()
    assert body["live_prices"] is False and body["suggestions"]
    assert price_watch  # imported for source registration
