"""Check-in API (Task 14), including day boundaries across time zones."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.database import get_connection
from app.game import trip_hooks


def utc_today():
    return datetime.now(UTC).date()


@pytest.fixture(autouse=True)
def _clean_countries():
    with get_connection() as conn:
        conn.execute("DELETE FROM user_countries")
    yield


def make_trip(client, headers, start, end, **sd):
    sd = {"destination": "Lisbon", **sd}
    if start:
        sd["departure_date"] = start.isoformat()
    if end:
        sd["return_date"] = end.isoformat()
    r = client.post(
        "/api/plans",
        json={"name": "T", "search_data": sd, "selections": {}},
        headers=headers,
    )
    return r.json()["id"]


def checkin(client, headers, pid, day):
    return client.post(
        f"/api/trips/{pid}/checkin", json={"day": day.isoformat()}, headers=headers
    )


def test_checkin_out_of_trip_409(client, admin_headers):
    t = utc_today()
    pid = make_trip(client, admin_headers, t + timedelta(days=1), t + timedelta(days=3))
    r = checkin(client, admin_headers, pid, t)
    assert r.status_code == 409
    assert r.json()["error_code"] == "checkin_out_of_trip"


def test_checkin_no_dates_409(client, admin_headers):
    pid = make_trip(client, admin_headers, None, None)
    assert checkin(client, admin_headers, pid, utc_today()).status_code == 409


def test_checkin_day_too_far_422(client, admin_headers):
    t = utc_today()
    pid = make_trip(client, admin_headers, t - timedelta(days=5), t + timedelta(days=5))
    for d in (t + timedelta(days=2), t - timedelta(days=2)):
        r = checkin(client, admin_headers, pid, d)
        assert r.status_code == 422
        assert r.json()["error_code"] == "checkin_day_invalid"


def test_checkin_accepts_client_day_ahead_of_utc(client, admin_headers):
    # Tokyo 07:00 on day 1 while UTC is still the day before.
    t = utc_today()
    pid = make_trip(
        client,
        admin_headers,
        t + timedelta(days=1),
        t + timedelta(days=4),
        destination="Tokyo",
    )
    r = checkin(client, admin_headers, pid, t + timedelta(days=1))
    assert r.status_code == 200
    body = r.json()
    assert body["day_index"] == 1
    assert body["city"] == "Tokyo"
    assert body["country_code"] == "JP"


def test_checkin_idempotent(client, admin_headers, monkeypatch):
    t = utc_today()
    pid = make_trip(client, admin_headers, t, t + timedelta(days=2))
    calls = []

    def hook(*a):
        calls.append(a)
        return {"points": 10}, {"current": 1}

    monkeypatch.setattr(trip_hooks, "on_trip_checkin", hook)
    first = checkin(client, admin_headers, pid, t).json()
    second = checkin(client, admin_headers, pid, t).json()
    assert first["new_country"] is True and first["game"] == {"points": 10}
    assert second["city"] == first["city"]
    assert second["country_code"] == first["country_code"] == "PT"
    assert second["new_country"] is False and second["game"] is None
    assert len(calls) == 1
    r = client.get(f"/api/trips/{pid}/checkins", headers=admin_headers)
    assert r.json()["days"] == [t.isoformat()]


def test_multi_city_day_city(client, admin_headers):
    t = utc_today()
    pid = make_trip(
        client,
        admin_headers,
        t - timedelta(days=3),
        t + timedelta(days=2),
        destinations=["Lisbon", "Porto"],
        destination_nights=[3, 2],
    )
    # day 4 of the trip is today: Porto
    assert checkin(client, admin_headers, pid, t).json()["city"] == "Porto"
    r = checkin(client, admin_headers, pid, t - timedelta(days=1))
    assert r.json()["city"] == "Lisbon"


def test_new_country_once_per_user(client, admin_headers):
    t = utc_today()
    a = make_trip(client, admin_headers, t, t + timedelta(days=1))
    b = make_trip(client, admin_headers, t, t + timedelta(days=1))
    assert checkin(client, admin_headers, a, t).json()["new_country"] is True
    assert checkin(client, admin_headers, b, t).json()["new_country"] is False


def test_hook_receives_new_countries(client, admin_headers, monkeypatch):
    t = utc_today()
    seen = []

    def hook(user_id, plan_id, day, new_countries):
        seen.append((plan_id, day, new_countries))
        return None, None

    monkeypatch.setattr(trip_hooks, "on_trip_checkin", hook)
    a = make_trip(client, admin_headers, t, t + timedelta(days=1))
    b = make_trip(client, admin_headers, t, t + timedelta(days=1))
    checkin(client, admin_headers, a, t)
    checkin(client, admin_headers, b, t)
    assert seen == [(a, t, ["PT"]), (b, t, [])]


def test_checkin_other_users_trip_404(client, admin_headers):
    r = client.post(
        "/api/trips/999999/checkin", json={"day": "2026-01-01"}, headers=admin_headers
    )
    assert r.status_code == 404
