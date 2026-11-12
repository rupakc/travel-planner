"""Tests for the trip snapshot and offline pack."""

import json
from datetime import date

import pytest

from app.services.offline_pack import build_pack

TODAY = date(2027, 4, 2)


def _plan(**over):
    plan = {
        "id": 5,
        "name": "Japan",
        "search_data": {
            "destination": "Tokyo",
            "departure_date": "2027-04-01",
            "return_date": "2027-04-08",
            "nationality": "American",
            "existing_visas": ["x"],
            "residence_permits": ["y"],
            "accessibility_needs": ["z"],
        },
        "selections": {"hotel": {"name": "Hotel Sakura", "location": "Shinjuku"}},
    }
    plan.update(over)
    return plan


def _card(n="112"):
    return {
        "emergency_card": {
            "cities": [
                {"city": "Tokyo", "emergency_numbers": {"police": n}, "embassy": None}
            ]
        }
    }


def test_pack_static_without_snapshot():
    pack = build_pack(_plan(), None, [], TODAY)
    assert pack["version"] == 1 and pack["trip_id"] == 5
    assert pack["emergency"]["source"] == "static"
    assert pack["emergency"]["as_of"] is None
    assert pack["emergency"]["cities"][0]["city"] == "Tokyo"
    assert pack["address_card"]["hotel_name"] == "Hotel Sakura"
    assert pack["address_card"]["area"] == "Shinjuku"
    assert pack["address_card"]["take_me_to"]["text"]
    assert pack["destinations"][0]["country_code"] == "JP"


def test_pack_prefers_ai_snapshot_with_as_of():
    snap = {**_card("110"), "as_of": "2027-03-01T10:00:00Z"}
    em = build_pack(_plan(), snap, [], TODAY)["emergency"]
    assert em["source"] == "ai" and em["as_of"] == "2027-03-01T10:00:00Z"
    assert em["cities"][0]["emergency_numbers"] == {"police": "110"}


def test_multi_city_has_one_entry_per_city():
    sd = {"destinations": ["Tokyo", "Paris"], "departure_date": "2027-04-01"}
    pack = build_pack(_plan(search_data=sd), None, [], TODAY)
    assert [d["city"] for d in pack["destinations"]] == ["Tokyo", "Paris"]
    assert [c["city"] for c in pack["emergency"]["cities"]] == ["Tokyo", "Paris"]


def test_currency_rate_null_without_snapshot(monkeypatch):
    assert build_pack(_plan(), None, [], TODAY)["currency"] is None
    monkeypatch.setattr(
        "app.services.trip_money.usd_rate",
        lambda s: {
            "local": "JPY",
            "usd_to_local": 150.0,
            "as_of": "2027-03-01T00:00:00Z",
        },
    )
    cur = build_pack(_plan(), {"forex": {}}, [], TODAY)["currency"]
    assert cur["rate"] == 150.0 and cur["source"] == "snapshot" and cur["home"] == "USD"


def test_take_me_to_from_phrases(monkeypatch):
    monkeypatch.setattr(
        "app.services.phrases.phrases_for_country",
        lambda c: {
            "language": "ja",
            "items": [{"id": "take_me_to", "text": "X", "romanized": "x"}],
        },
    )
    pack = build_pack(_plan(), None, [], TODAY)
    assert pack["address_card"]["take_me_to"] == {"text": "X", "romanized": "x"}
    assert pack["phrases"]["language"] == "ja"


def test_pack_has_no_personal_search_fields():
    text = json.dumps(build_pack(_plan(), None, ["2027-04-01"], TODAY))
    for key in (
        "nationality",
        "existing_visas",
        "residence_permits",
        "accessibility_needs",
    ):
        assert key not in text


@pytest.fixture()
def trip(client, admin_headers):
    r = client.post(
        "/api/plans",
        json={
            "name": "Offline",
            "search_data": {"destination": "Tokyo", "departure_date": "2027-04-01"},
            "selections": {},
        },
        headers=admin_headers,
    )
    return r.json()["id"]


def test_no_store_header(client, admin_headers, trip):
    r = client.get(f"/api/trips/{trip}/offline-pack", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.json()["trip_id"] == trip


def test_snapshot_roundtrip_into_pack(client, admin_headers, trip):
    r = client.put(
        f"/api/trips/{trip}/snapshot", json=_card("110"), headers=admin_headers
    )
    assert r.status_code == 204
    em = client.get(f"/api/trips/{trip}/offline-pack", headers=admin_headers).json()[
        "emergency"
    ]
    assert em["source"] == "ai" and em["as_of"]


def test_snapshot_too_large_413(client, admin_headers, trip):
    big = {"weather": {"blob": "x" * 270000}}
    r = client.put(f"/api/trips/{trip}/snapshot", json=big, headers=admin_headers)
    assert r.status_code == 413
    assert r.json()["error_code"] == "snapshot_too_large"


def test_snapshot_non_object_422(client, admin_headers, trip):
    r = client.put(f"/api/trips/{trip}/snapshot", json=[1], headers=admin_headers)
    assert r.status_code == 422 and r.json()["error_code"] == "snapshot_invalid"
    r = client.put(
        f"/api/trips/{trip}/snapshot", json={"forex": "x"}, headers=admin_headers
    )
    assert r.status_code == 422


def test_snapshot_strips_unknown_keys(client, admin_headers, trip):
    from app.db import trip_snapshot_db

    r = client.put(
        f"/api/trips/{trip}/snapshot",
        json={"weather": {"a": 1}, "evil": {"b": 2}},
        headers=admin_headers,
    )
    assert r.status_code == 204
    snap = trip_snapshot_db.get_snapshot(trip)
    assert "evil" not in snap and snap["weather"] == {"a": 1}


def test_other_users_pack_404(client, admin_headers, trip):
    client.post(
        "/api/admin/users",
        json={"username": "packother", "password": "temp5678-kv", "is_admin": False},
        headers=admin_headers,
    )
    tok = client.post(
        "/api/auth/login", json={"username": "packother", "password": "temp5678-kv"}
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"/api/trips/{trip}/offline-pack", headers=h).status_code == 404
    assert (
        client.put(f"/api/trips/{trip}/snapshot", json={}, headers=h).status_code == 404
    )
