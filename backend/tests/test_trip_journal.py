"""Journal entries and place ratings/visits."""

import uuid

import pytest

from app.db import trip_journal_db as db
from app.game import trip_hooks


@pytest.fixture
def trip(client, admin_headers):
    r = client.post(
        "/api/plans",
        json={"name": "J", "search_data": {}, "selections": {}},
        headers=admin_headers,
    )
    return r.json()["id"]


def _post(client, h, trip, **kw):
    body = {"client_id": str(uuid.uuid4()), "body": "hello"} | kw
    return client.post(f"/api/trips/{trip}/journal", json=body, headers=h)


def test_same_client_id_twice_one_row(client, admin_headers, trip):
    cid = str(uuid.uuid4())
    a = _post(client, admin_headers, trip, client_id=cid)
    b = _post(client, admin_headers, trip, client_id=cid)
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    r = client.get(f"/api/trips/{trip}/journal", headers=admin_headers)
    assert len(r.json()["entries"]) == 1


def test_body_limits(client, admin_headers, trip):
    r = _post(client, admin_headers, trip, body="  \x01 ")
    assert r.status_code == 422 and r.json()["error_code"] == "journal_empty"
    r = _post(client, admin_headers, trip, body="x" * 4001)
    assert r.json()["error_code"] == "journal_too_long"
    assert _post(client, admin_headers, trip, body="x" * 4000).status_code == 201
    r = _post(client, admin_headers, trip, body="a\x07b\tc\nd")
    assert r.json()["body"] == "abc\nd"


def test_mood_enum(client, admin_headers, trip):
    r = _post(client, admin_headers, trip, mood="meh")
    assert r.status_code == 422 and r.json()["error_code"] == "mood_invalid"
    assert _post(client, admin_headers, trip, mood="great").json()["mood"] == "great"


def test_sorted_by_day_nulls_last(client, admin_headers, trip):
    _post(client, admin_headers, trip, body="n")
    _post(client, admin_headers, trip, body="b", day="2027-04-02")
    _post(client, admin_headers, trip, body="a", day="2027-04-01")
    got = client.get(f"/api/trips/{trip}/journal", headers=admin_headers).json()
    assert [e["body"] for e in got["entries"]] == ["a", "b", "n"]


def test_patch_and_delete(client, admin_headers, trip):
    e = _post(client, admin_headers, trip).json()
    r = client.patch(
        f"/api/trips/{trip}/journal/{e['id']}",
        json={"body": "new"},
        headers=admin_headers,
    )
    assert r.json()["body"] == "new"
    r = client.delete(f"/api/trips/{trip}/journal/{e['id']}", headers=admin_headers)
    assert r.status_code == 204
    r = client.delete(f"/api/trips/{trip}/journal/{e['id']}", headers=admin_headers)
    assert r.status_code == 404 and r.json()["error_code"] == "entry_not_found"


def _put(client, h, trip, key="activity:belem", **kw):
    body = {"name": "Belem", "kind": "activity"} | kw
    return client.put(f"/api/trips/{trip}/places/{key}", json=body, headers=h)


def test_place_key_format(client, admin_headers, trip):
    r = _put(client, admin_headers, trip, key="Activity:x")
    assert r.status_code == 422 and r.json()["error_code"] == "place_key_invalid"


def test_stars_bounds(client, admin_headers, trip):
    for bad in (0, 6):
        r = _put(client, admin_headers, trip, stars=bad)
        assert r.status_code == 422 and r.json()["error_code"] == "stars_invalid"
    assert _put(client, admin_headers, trip, stars=4).json()["place"]["stars"] == 4
    assert (
        _put(client, admin_headers, trip, stars=None).json()["place"]["stars"] is None
    )


def test_upsert_keeps_omitted_fields(client, admin_headers, trip):
    _put(client, admin_headers, trip, stars=5, note="nice", lat=38.7, lng=-9.1)
    r = client.put(
        f"/api/trips/{trip}/places/activity:belem",
        json={"visited": True},
        headers=admin_headers,
    )
    p = r.json()["place"]
    assert (p["name"], p["stars"], p["note"], p["lat"], p["visited"]) == (
        "Belem",
        5,
        "nice",
        38.7,
        True,
    )
    assert p["visited_at"]
    assert (
        _put(client, admin_headers, trip, note="x" * 501).json()["error_code"]
        == "note_too_long"
    )


def test_visited_awards_once_per_place(client, admin_headers, trip, monkeypatch):
    calls = []
    monkeypatch.setattr(
        trip_hooks, "on_place_visited", lambda u, p, k: calls.append(k) or {"points": 5}
    )
    first = _put(client, admin_headers, trip, visited=True).json()
    again = _put(client, admin_headers, trip, visited=True).json()
    assert first["game"] == {"points": 5} and again["game"] is None
    assert calls == ["activity:belem"]
    assert _put(client, admin_headers, trip, stars=3).json()["game"] is None
    r = client.get(f"/api/trips/{trip}/places", headers=admin_headers)
    assert len(r.json()["places"]) == 1
    assert (
        client.delete(
            f"/api/trips/{trip}/places/activity:belem", headers=admin_headers
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/trips/{trip}/places/activity:belem", headers=admin_headers
        ).json()["error_code"]
        == "place_not_found"
    )


def test_limits(client, admin_headers, trip, monkeypatch):
    monkeypatch.setattr(db, "JOURNAL_LIMIT", 2)
    monkeypatch.setattr(db, "PLACES_LIMIT", 2)
    cid = str(uuid.uuid4())
    assert _post(client, admin_headers, trip, client_id=cid).status_code == 201
    assert _post(client, admin_headers, trip).status_code == 201
    r = _post(client, admin_headers, trip)
    assert r.status_code == 409 and r.json()["error_code"] == "journal_limit"
    assert _post(client, admin_headers, trip, client_id=cid).status_code == 200
    _put(client, admin_headers, trip, key="place:a")
    _put(client, admin_headers, trip, key="place:b")
    r = _put(client, admin_headers, trip, key="place:c")
    assert r.status_code == 409 and r.json()["error_code"] == "places_limit"
    assert _put(client, admin_headers, trip, key="place:a", stars=2).status_code == 200


def test_other_users_trip_404(client, admin_headers):
    r = client.get("/api/trips/999999/journal", headers=admin_headers)
    assert r.status_code == 404
