"""Trips core API over saved plans, and the /plans compatibility it keeps."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.auth import create_access_token
from app.db import users_db
from app.db.database import get_connection
from app.db.trip_children import TRIP_CHILD_TABLES
from app.db.user_countries_db import add_countries
from app.db.users_db import create_user
from app.game import trip_hooks
from app.services import trips as trips_service

_PW = "correct-horse-battery"

# The keys GET/POST/PUT /plans answered with before Phase 2.
LEGACY_PLAN_KEYS = {
    "id", "username", "name", "search_data", "selections",
    "created_at", "updated_at", "share_token",
}  # fmt: skip

TRIP_KEYS = {
    "id", "title", "destination", "destinations", "origin", "start_date",
    "end_date", "nights", "phase", "phase_source", "days_to_start", "day_index",
    "num_travelers", "budget_usd", "countries", "prep", "has_itinerary",
    "recap_completed_at", "created_at", "updated_at",
}  # fmt: skip


@pytest.fixture(autouse=True)
def _fast_hash(monkeypatch):
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")
    monkeypatch.setattr(users_db, "_verify", lambda pw, hashed: hashed == f"plain:{pw}")


def _user():
    name = f"trip_{uuid.uuid4().hex[:12]}"
    u = create_user(name, _PW, email=f"{name}@example.com")
    return u, {"Authorization": f"Bearer {create_access_token({'sub': name})}"}


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _d(offset: int) -> str:
    return (_utc_today() + timedelta(days=offset)).isoformat()


def _save_plan(client, h, search_data, selections=None, name="Trip"):
    r = client.post(
        "/api/plans",
        json={"name": name, "search_data": search_data, "selections": selections or {}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_trip(client, h, **body):
    body.setdefault("title", "Kyoto someday")
    r = client.post("/api/trips", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _seed_children(plan_id: int) -> None:
    now = "2026-11-11T00:00:00Z"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trip_expenses (plan_id, client_id, amount_minor, currency,"
            " category, spent_on, created_at, updated_at)"
            " VALUES (?, ?, 1250, 'EUR', 'food', '2027-04-01', ?, ?)",
            (plan_id, uuid.uuid4().hex, now, now),
        )
        conn.execute(
            "INSERT INTO trip_journal (plan_id, client_id, body, created_at, updated_at)"
            " VALUES (?, ?, 'Pastel de nata', ?, ?)",
            (plan_id, uuid.uuid4().hex, now, now),
        )
        conn.execute(
            "INSERT INTO trip_ratings (plan_id, place_key, name, kind, updated_at)"
            " VALUES (?, 'place:belem', 'Belém', 'place', ?)",
            (plan_id, now),
        )
        conn.execute(
            "INSERT INTO trip_prep (plan_id, item_id, done_at, updated_at)"
            " VALUES (?, 'passport', ?, ?)",
            (plan_id, now, now),
        )
        conn.execute(
            "INSERT INTO trip_snapshots (plan_id, data, updated_at)"
            ' VALUES (?, \'{"forex": {"rate": 0.92}}\', ?)',
            (plan_id, now),
        )
        conn.execute(
            "INSERT INTO trip_checkins (plan_id, day, created_at)"
            " VALUES (?, '2027-04-01', ?)",
            (plan_id, now),
        )


def _child_counts(plan_id: int) -> dict[str, int]:
    with get_connection() as conn:
        return {
            t: conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE plan_id = ?",  # nosec B608
                (plan_id,),
            ).fetchone()[0]
            for t in TRIP_CHILD_TABLES
        }


# ── legacy plans and the old SPA ──────────────────────────────────────────────


def test_legacy_plan_becomes_trip(client):
    _, h = _user()
    plan = _save_plan(
        client,
        h,
        {
            "origin": "NYC",
            "destination": "Lisbon",
            "departure_date": _d(60),
            "return_date": _d(67),
            "num_travelers": 2,
            "budget_usd": 3000,
        },
        name="Lisbon in spring",
    )
    assert plan["start_date"] == _d(60) and plan["end_date"] == _d(67)

    r = client.get("/api/trips", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["today"] == _utc_today().isoformat()
    [trip] = body["trips"]
    assert set(trip) == TRIP_KEYS
    assert trip["id"] == plan["id"]
    assert trip["title"] == "Lisbon in spring"
    assert trip["phase"] == "planning" and trip["phase_source"] == "auto"
    assert (trip["start_date"], trip["end_date"]) == (_d(60), _d(67))
    assert trip["nights"] == 7 and trip["days_to_start"] == 60
    assert trip["day_index"] is None
    assert trip["destinations"] == ["Lisbon"] and trip["destination"] == "Lisbon"
    assert trip["origin"] == "NYC"
    assert trip["num_travelers"] == 2 and trip["budget_usd"] == 3000
    assert trip["countries"] == ["PT"]
    assert trip["has_itinerary"] is False
    assert trip["created_at"].endswith("Z") and trip["updated_at"].endswith("Z")
    assert body["pinned_id"] == plan["id"]


def test_legacy_plan_dates_only_in_search_data(client):
    """A plan written by the previous backend (no date columns) still has dates."""
    u, h = _user()
    plan = _save_plan(client, h, {"destination": "Rome"})
    with get_connection() as conn:
        conn.execute(
            "UPDATE plans SET search_data = ?, start_date = NULL, end_date = NULL"
            " WHERE id = ?",
            (
                f'{{"destination": "Rome", "departure_date": "{_d(30)}",'
                f' "return_date": "{_d(33)}"}}',
                plan["id"],
            ),
        )
    trip = client.get(f"/api/trips/{plan['id']}", headers=h).json()
    assert (trip["start_date"], trip["end_date"]) == (_d(30), _d(33))
    assert trip["phase"] == "planning"


def test_get_plans_keeps_legacy_keys(client):
    _, h = _user()
    created = _save_plan(
        client, h, {"destination": "Tokyo", "departure_date": _d(5)}, {"hotel": None}
    )
    assert LEGACY_PLAN_KEYS <= set(created)

    listed = client.get("/api/plans", headers=h).json()
    assert isinstance(listed, list) and len(listed) == 1
    assert LEGACY_PLAN_KEYS <= set(listed[0])
    assert listed[0]["search_data"] == {"destination": "Tokyo", "departure_date": _d(5)}
    assert listed[0]["selections"] == {"hotel": None}

    one = client.get(f"/api/plans/{created['id']}", headers=h).json()
    assert LEGACY_PLAN_KEYS <= set(one)

    upd = client.put(
        f"/api/plans/{created['id']}",
        json={"name": "Renamed", "selections": {"hotel": {"name": "H"}}},
        headers=h,
    )
    assert upd.status_code == 200
    assert LEGACY_PLAN_KEYS <= set(upd.json())
    assert upd.json()["name"] == "Renamed"
    assert upd.json()["selections"] == {"hotel": {"name": "H"}}
    trip = client.get(f"/api/trips/{created['id']}", headers=h).json()
    assert trip["title"] == "Renamed"

    deleted = client.delete(f"/api/plans/{created['id']}", headers=h)
    assert deleted.status_code == 200 and deleted.json() == {"success": True}


def test_dreaming_trip_loads_in_old_drawer_shape(client):
    _, h = _user()
    trip = _create_trip(client, h, title="Kyoto someday", destination="Kyoto")
    assert set(trip) == TRIP_KEYS
    assert trip["phase"] == "dreaming"
    assert trip["prep"] == {"done": 0, "total": 0, "percent": 0, "complete": False}
    assert trip["destinations"] == ["Kyoto"] and trip["start_date"] is None

    [plan] = client.get("/api/plans", headers=h).json()
    assert plan["id"] == trip["id"]
    assert plan["name"] == "Kyoto someday"
    assert plan["search_data"] == {"destination": "Kyoto"}
    assert plan["selections"] == {}
    assert LEGACY_PLAN_KEYS <= set(plan)
    # the old drawer can update it like any plan
    r = client.put(
        f"/api/plans/{trip['id']}", json={"selections": {"activities": []}}, headers=h
    )
    assert r.status_code == 200 and r.json()["selections"] == {"activities": []}

    bare = _create_trip(client, h, title="Somewhere")
    plan = client.get(f"/api/plans/{bare['id']}", headers=h).json()
    assert plan["search_data"] == {} and plan["selections"] == {}
    assert bare["destinations"] == [] and bare["destination"] is None


def test_delete_plan_cascades(client):
    _, h = _user()
    other, oh = _user()
    a = _save_plan(client, h, {"destination": "Lisbon"})
    b = _create_trip(client, h, title="B")
    keep = _save_plan(client, oh, {"destination": "Porto"})
    for pid in (a["id"], b["id"], keep["id"]):
        _seed_children(pid)

    # someone else's id: nothing is deleted
    assert client.delete(f"/api/plans/{keep['id']}", headers=h).status_code == 404
    assert client.delete(f"/api/trips/{keep['id']}", headers=h).status_code == 404

    assert client.delete(f"/api/plans/{a['id']}", headers=h).status_code == 200
    assert set(_child_counts(a["id"]).values()) == {0}
    r = client.delete(f"/api/trips/{b['id']}", headers=h)
    assert r.status_code == 204 and r.content == b""
    assert set(_child_counts(b["id"]).values()) == {0}
    assert client.get("/api/plans", headers=h).json() == []
    assert client.get(f"/api/trips/{b['id']}", headers=h).status_code == 404

    assert set(_child_counts(keep["id"]).values()) == {1}


# ── trips routes ──────────────────────────────────────────────────────────────


def test_create_trip_with_dates_and_title_rules(client):
    _, h = _user()
    t = _create_trip(
        client, h, title="  Lisbon  ", destination="Lisbon",
        start_date=_d(100), end_date=_d(104),
    )  # fmt: skip
    assert t["title"] == "Lisbon" and t["phase"] == "planning" and t["nights"] == 4
    plan = client.get(f"/api/plans/{t['id']}", headers=h).json()
    assert plan["search_data"] == {"destination": "Lisbon"}
    for bad in ("", "   ", "x" * 81):
        r = client.post("/api/trips", json={"title": bad}, headers=h)
        assert r.status_code == 422 and r.json()["error_code"] == "trip_title_invalid"
    r = client.patch(f"/api/trips/{t['id']}", json={"title": None}, headers=h)
    assert r.json()["error_code"] == "trip_title_invalid"
    r = client.patch(f"/api/trips/{t['id']}", json={"title": "Porto"}, headers=h)
    assert r.status_code == 200 and r.json()["title"] == "Porto"
    assert client.get(f"/api/plans/{t['id']}", headers=h).json()["name"] == "Porto"
    assert client.post("/api/trips", json={}, headers=h).status_code == 422
    assert client.get("/api/trips").status_code == 401


def test_patch_phase_override_and_clear(client):
    _, h = _user()
    t = _create_trip(client, h, start_date=_d(100), end_date=_d(104))
    assert t["phase"] == "planning"
    r = client.patch(f"/api/trips/{t['id']}", json={"phase": "ready"}, headers=h)
    assert r.status_code == 200
    assert r.json()["phase"] == "ready" and r.json()["phase_source"] == "manual"
    assert r.json()["days_to_start"] == 100
    again = client.get(f"/api/trips/{t['id']}", headers=h).json()
    assert again["phase"] == "ready" and again["phase_source"] == "manual"

    bad = client.patch(f"/api/trips/{t['id']}", json={"phase": "lost"}, headers=h)
    assert bad.status_code == 422 and bad.json()["error_code"] == "trip_phase_invalid"

    # a title-only patch leaves the override alone
    r = client.patch(f"/api/trips/{t['id']}", json={"title": "New"}, headers=h)
    assert r.json()["phase"] == "ready"

    r = client.patch(f"/api/trips/{t['id']}", json={"phase": None}, headers=h)
    assert r.json()["phase"] == "planning" and r.json()["phase_source"] == "auto"


def test_patch_dates_set_and_clear(client):
    _, h = _user()
    plan = _save_plan(
        client, h,
        {"destination": "Rome", "departure_date": _d(40), "return_date": _d(45)},
    )  # fmt: skip
    r = client.patch(
        f"/api/trips/{plan['id']}", json={"end_date": _d(47)}, headers=h
    ).json()
    assert (r["start_date"], r["end_date"], r["nights"]) == (_d(40), _d(47), 7)
    # the old drawer sees the same dates
    sd = client.get(f"/api/plans/{plan['id']}", headers=h).json()["search_data"]
    assert sd["return_date"] == _d(47)

    r = client.patch(
        f"/api/trips/{plan['id']}",
        json={"start_date": None, "end_date": None},
        headers=h,
    ).json()
    assert r["start_date"] is None and r["end_date"] is None
    assert r["phase"] == "dreaming"
    sd = client.get(f"/api/plans/{plan['id']}", headers=h).json()["search_data"]
    assert sd == {"destination": "Rome"}


def test_dates_invalid(client):
    _, h = _user()
    t = _create_trip(client, h, start_date=_d(10), end_date=_d(12))
    cases = [
        {"start_date": _d(10), "end_date": _d(9)},  # end < start
        {"start_date": "2027-01-01", "end_date": "2028-01-02"},  # a 366-day span
        {"start_date": "1999-12-30", "end_date": "1999-12-31"},  # year 1999
        {"start_date": "2101-01-01"},
        {"start_date": "2027-02-30"},
        {"start_date": "tomorrow"},
    ]
    for body in cases:
        for r in (
            client.post("/api/trips", json={"title": "T", **body}, headers=h),
            client.patch(f"/api/trips/{t['id']}", json=body, headers=h),
        ):
            assert r.status_code == 422, (body, r.text)
            assert r.json()["error_code"] == "trip_dates_invalid", body
    # a patch is checked against the stored other date
    r = client.patch(f"/api/trips/{t['id']}", json={"end_date": _d(5)}, headers=h)
    assert r.json()["error_code"] == "trip_dates_invalid"
    # a 365-day span is fine
    ok = client.patch(
        f"/api/trips/{t['id']}",
        json={"start_date": "2027-01-01", "end_date": "2028-01-01"},
        headers=h,
    )
    assert ok.status_code == 200 and ok.json()["nights"] == 365


def test_other_users_trip_404(client):
    _, h = _user()
    _, oh = _user()
    t = _create_trip(client, oh)
    for method, path, body in (
        ("GET", f"/api/trips/{t['id']}", None),
        ("PATCH", f"/api/trips/{t['id']}", {"title": "Mine"}),
        ("DELETE", f"/api/trips/{t['id']}", None),
        ("GET", "/api/trips/99999999", None),
    ):
        r = client.request(method, path, json=body, headers=h)
        assert r.status_code == 404, (method, path)
        assert r.json()["error_code"] == "trip_not_found"
    assert client.get(f"/api/trips/{t['id']}", headers=oh).status_code == 200
    assert client.get("/api/trips", headers=h).json()["trips"] == []


def test_owned_trip_never_matches_a_plan_without_username(monkeypatch):
    from app.core import trip_access
    from app.core.errors import ApiError

    monkeypatch.setattr(
        trip_access.plans_db, "get_plan", lambda pid: {"id": pid, "username": None}
    )
    for user in ({"username": None}, {}):
        with pytest.raises(ApiError):
            trip_access.owned_trip(1, user)


def test_list_sorted_by_phase(client):
    _, h = _user()
    ids = {
        "memories_old": _create_trip(client, h, start_date=_d(-60), end_date=_d(-55)),
        "memories_new": _create_trip(client, h, start_date=_d(-20), end_date=_d(-18)),
        "dreaming": _create_trip(client, h),
        "planning_late": _create_trip(client, h, start_date=_d(90), end_date=_d(95)),
        "planning_soon": _create_trip(client, h, start_date=_d(40), end_date=_d(45)),
        "ready": _create_trip(client, h, start_date=_d(3), end_date=_d(5)),
        "road": _create_trip(client, h, start_date=_d(-1), end_date=_d(2)),
    }
    order = [t["id"] for t in client.get("/api/trips", headers=h).json()["trips"]]
    assert order == [
        ids[k]["id"]
        for k in (
            "road", "ready", "planning_soon", "planning_late", "dreaming",
            "memories_new", "memories_old",
        )
    ]  # fmt: skip


def test_pinned_prefers_on_the_road(client):
    _, h = _user()
    _create_trip(client, h, start_date=_d(3), end_date=_d(5))
    late_road = _create_trip(client, h, start_date=_d(-1), end_date=_d(4))
    early_road = _create_trip(client, h, start_date=_d(-3), end_date=_d(1))
    body = client.get("/api/trips", headers=h).json()
    assert body["pinned_id"] == early_road["id"]
    client.delete(f"/api/trips/{early_road['id']}", headers=h)
    client.delete(f"/api/trips/{late_road['id']}", headers=h)
    soonest = _create_trip(client, h, start_date=_d(2), end_date=_d(3))
    assert client.get("/api/trips", headers=h).json()["pinned_id"] == soonest["id"]


def test_pick_pinned_rules():
    today = date(2026, 11, 12)

    def trip(i, phase, start=None, end=None, dts=None, recap=None):
        return {"id": i, "phase": phase, "start_date": start, "end_date": end,
                "days_to_start": dts, "recap_completed_at": recap}  # fmt: skip

    pick = trips_service.pick_pinned
    assert pick([], today=today) is None
    assert pick([trip(1, "dreaming")], today=today) is None
    road = [
        trip(1, "ready", "2026-11-20", "2026-11-25", 8),
        trip(2, "on_the_road", "2026-11-10", "2026-11-14"),
        trip(3, "on_the_road", "2026-11-08", "2026-11-14"),
    ]
    assert pick(road, today=today) == 3
    soon = [
        trip(1, "planning", "2027-01-20", None, 69),
        trip(2, "ready", "2026-11-20", None, 8),
    ]
    assert pick(soon, today=today) == 2
    recent = [
        trip(1, "memories", "2026-10-01", "2026-10-05"),  # too old
        trip(2, "memories", "2026-11-01", "2026-11-05", recap="2026-11-06T00:00:00Z"),
        trip(3, "memories", "2026-10-25", "2026-10-30"),  # 13 days ago
        trip(4, "memories", "2026-11-01", "2026-11-04"),  # 8 days ago
    ]
    assert pick(recent, today=today) == 4
    assert pick(recent[:3], today=today) == 3
    assert pick(recent[:2], today=today) is None


def test_today_param_shifts_phase(client):
    _, h = _user()
    t = _create_trip(client, h, start_date=_d(1), end_date=_d(3))
    base = client.get(f"/api/trips/{t['id']}", headers=h).json()
    assert base["phase"] == "ready" and base["days_to_start"] == 1
    ahead = client.get(f"/api/trips/{t['id']}?today={_d(1)}", headers=h).json()
    assert ahead["phase"] == "on_the_road" and ahead["day_index"] == 1
    assert ahead["days_to_start"] is None
    listed = client.get(f"/api/trips?today={_d(1)}", headers=h).json()
    assert listed["today"] == _d(1) and listed["trips"][0]["phase"] == "on_the_road"
    # a client date more than a day from UTC is ignored
    far = client.get(f"/api/trips?today={_d(5)}", headers=h).json()
    assert far["today"] == _utc_today().isoformat()
    assert far["trips"][0]["phase"] == "ready"
    junk = client.get("/api/trips?today=nope", headers=h)
    assert junk.status_code == 200 and junk.json()["today"] == _utc_today().isoformat()


def test_trip_view_odd_plans():
    today = date(2026, 11, 12)
    prep = {"done": 1, "total": 9, "percent": 11, "complete": False}
    plan = {
        "id": 5, "name": "Old", "title": None, "phase": None,
        "start_date": "2027-04-08", "end_date": "2027-04-01",
        "search_data": {"destinations": ["Lisbon", "Porto"], "destination": "Lisbon",
                        "num_travelers": "lots"},
        "selections": {"itinerary": {"days": [{"day": 1}]}},
        "recap_completed_at": None,
        "created_at": "2026-11-01 10:00:00", "updated_at": "2026-11-02 11:00:00",
    }  # fmt: skip
    v = trips_service.trip_view(plan, today=today, prep=prep)
    assert v["title"] == "Old"
    assert (v["start_date"], v["end_date"], v["nights"]) == (
        "2027-04-08",
        "2027-04-08",
        0,
    )
    assert v["destinations"] == ["Lisbon", "Porto"] and v["countries"] == ["PT"]
    assert v["has_itinerary"] is True and v["prep"] == prep
    assert v["num_travelers"] is None
    assert v["created_at"] == "2026-11-01T10:00:00Z"
    bare = trips_service.trip_view(
        {"id": 6, "name": "N", "search_data": None, "selections": None},
        today=today,
        prep=prep,
    )
    assert bare["phase"] == "dreaming"
    assert bare["prep"] == {"done": 0, "total": 0, "percent": 0, "complete": False}
    assert bare["destinations"] == [] and bare["has_itinerary"] is False


def test_stats_countries_and_goal(client, monkeypatch):
    u, h = _user()
    _create_trip(client, h)
    road = _create_trip(client, h, start_date=_d(-1), end_date=_d(2))
    _create_trip(client, h, start_date=_d(-30), end_date=_d(-25))
    add_countries(u["id"], ["PT"], road["id"], "checkin")
    add_countries(u["id"], ["JP"], road["id"], "recap")

    r = client.get("/api/trips/stats", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"countries", "continents", "bucket_goal", "trips_by_phase"}
    by_code = {c["code"]: c for c in body["countries"]}
    assert set(by_code) == {"PT", "JP"}
    assert by_code["PT"]["name"] == "Portugal" and by_code["JP"]["name"] == "Japan"
    assert by_code["PT"]["first_trip_id"] == road["id"]
    assert by_code["PT"]["source"] == "checkin" and by_code["JP"]["source"] == "recap"
    assert by_code["PT"]["visited_at"].endswith("Z")
    assert set(by_code["PT"]) == {
        "code",
        "name",
        "first_trip_id",
        "visited_at",
        "source",
    }
    assert sorted(body["continents"]) == ["AS", "EU"]
    assert body["bucket_goal"] is None
    assert body["trips_by_phase"] == {
        "dreaming": 1, "planning": 0, "ready": 0, "on_the_road": 1, "memories": 1,
    }  # fmt: skip

    from app.db import user_settings_db

    real = user_settings_db.get_settings
    monkeypatch.setattr(
        user_settings_db,
        "get_settings",
        lambda uid: {**real(uid), "bucket_list_goal": 30},
    )
    assert client.get("/api/trips/stats", headers=h).json()["bucket_goal"] == 30
    _, other = _user()
    empty = client.get("/api/trips/stats", headers=other).json()
    assert empty["countries"] == [] and empty["continents"] == []


def test_plan_saved_hook_called_once_per_plan(client, monkeypatch):
    u, h = _user()
    calls = []
    monkeypatch.setattr(
        trip_hooks,
        "on_plan_saved",
        lambda user_id, plan_id: calls.append((user_id, plan_id)) or {"xp": 10},
    )
    a = _save_plan(client, h, {"destination": "Oslo"})
    assert calls == [(u["id"], a["id"])]
    assert "game" not in a  # the response keys are unchanged
    client.put(f"/api/plans/{a['id']}", json={"name": "Oslo 2"}, headers=h)
    b = _save_plan(client, h, {"destination": "Bergen"})
    assert calls == [(u["id"], a["id"]), (u["id"], b["id"])]


def test_plan_saved_hook_failure_still_saves(client, monkeypatch):
    _, h = _user()

    def boom(user_id, plan_id):
        raise RuntimeError("game down")

    monkeypatch.setattr(trip_hooks, "on_plan_saved", boom)
    plan = _save_plan(client, h, {"destination": "Oslo"})
    assert client.get(f"/api/plans/{plan['id']}", headers=h).status_code == 200


def test_save_plan_ignores_bad_search_dates(client):
    _, h = _user()
    plan = _save_plan(
        client, h, {"departure_date": "2027-02-30", "return_date": 20270301}
    )
    assert plan["start_date"] is None and plan["end_date"] is None


def test_stats_route_not_shadowed_by_trip_id(client):
    _, h = _user()
    assert client.get("/api/trips/stats", headers=h).status_code == 200
    assert client.get("/api/trips/abc", headers=h).status_code == 422
