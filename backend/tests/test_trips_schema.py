"""Phase 2 trip schema, one-time backfill and shared row helpers."""

import json

import pytest

from app.db import plans_db, trip_snapshot_db, user_countries_db
from app.db.database import get_connection
from app.db.trip_children import TRIP_CHILD_TABLES, delete_trip_children
from app.db.trips_schema import BACKFILL_KEY, create_trip_tables


@pytest.fixture(autouse=True)
def _fresh():
    plans_db.create_plans_table()
    create_trip_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM plans")
        conn.execute("DELETE FROM meta WHERE key = ?", (BACKFILL_KEY,))
        for t in TRIP_CHILD_TABLES + ("user_countries",):
            conn.execute(f"DELETE FROM {t}")
    yield


def _plan(search_data, name="t") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO plans (username, name, search_data, selections) "
            "VALUES ('u', ?, ?, '{}')",
            (
                name,
                search_data
                if isinstance(search_data, str)
                else json.dumps(search_data),
            ),
        )
        return cur.lastrowid


def _dates(pid):
    with get_connection() as conn:
        r = conn.execute(
            "SELECT start_date, end_date FROM plans WHERE id=?", (pid,)
        ).fetchone()
    return r["start_date"], r["end_date"]


def test_create_twice_is_idempotent():
    create_trip_tables()
    create_trip_tables()
    with get_connection() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(plans)")]
    assert len(cols) == len(set(cols))


def test_backfill_sets_dates_from_search_data():
    pid = _plan({"departure_date": "2026-04-01", "return_date": "2026-04-08"})
    create_trip_tables()
    assert _dates(pid) == ("2026-04-01", "2026-04-08")


def test_backfill_keeps_existing_dates():
    pid = _plan({"departure_date": "2026-04-01", "return_date": "2026-04-08"})
    with get_connection() as conn:
        conn.execute("UPDATE plans SET start_date='2027-01-01' WHERE id=?", (pid,))
    create_trip_tables()
    assert _dates(pid) == ("2027-01-01", "2026-04-08")


def test_backfill_runs_once():
    pid = _plan({"departure_date": "2026-04-01", "return_date": "2026-04-08"})
    create_trip_tables()
    with get_connection() as conn:
        conn.execute(
            "UPDATE plans SET start_date=NULL, end_date=NULL WHERE id=?", (pid,)
        )
    create_trip_tables()
    assert _dates(pid) == (None, None)


def test_bad_search_data_is_skipped():
    a = _plan("not json")
    b = _plan({"destination": "Rome"})
    c = _plan({"departure_date": "2026-13-99x", "return_date": "2026-04-0"})
    create_trip_tables()
    assert _dates(a) == (None, None)
    assert _dates(b) == (None, None)
    assert _dates(c) == (None, None)


def test_get_plan_has_new_keys():
    pid = _plan({})
    p = plans_db.get_plan(pid)
    for k in ("title", "phase", "start_date", "end_date", "recap_completed_at"):
        assert k in p


def test_delete_children_removes_all_six():
    now = "2026-01-01T00:00:00Z"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trip_expenses (plan_id,client_id,amount_minor,currency,category,spent_on,created_at,updated_at) VALUES (1,'a',100,'USD','food','2026-01-01',?,?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO trip_journal (plan_id,client_id,body,created_at,updated_at) VALUES (1,'a','x',?,?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO trip_ratings (plan_id,place_key,name,kind,updated_at) VALUES (1,'k','n','place',?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO trip_prep (plan_id,item_id,updated_at) VALUES (1,'i',?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO trip_snapshots (plan_id,data,updated_at) VALUES (1,'{}',?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO trip_checkins (plan_id,day,created_at) VALUES (1,'2026-01-01',?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO trip_prep (plan_id,item_id,updated_at) VALUES (2,'i',?)",
            (now,),
        )
        delete_trip_children(conn, 1)
        for t in TRIP_CHILD_TABLES:
            assert (
                conn.execute(f"SELECT COUNT(*) FROM {t} WHERE plan_id=1").fetchone()[0]
                == 0
            )
        assert (
            conn.execute("SELECT COUNT(*) FROM trip_prep WHERE plan_id=2").fetchone()[0]
            == 1
        )
    assert len(TRIP_CHILD_TABLES) == 6


def test_add_countries_returns_only_new():
    assert user_countries_db.add_countries("u1", ["pt", "ES"], 5, "checkin") == [
        "PT",
        "ES",
    ]
    assert user_countries_db.add_countries("u1", ["PT", "FR"], 6, "recap") == ["FR"]
    rows = {r["country_code"]: r for r in user_countries_db.list_countries("u1")}
    assert set(rows) == {"PT", "ES", "FR"}
    assert rows["PT"]["first_plan_id"] == 5 and rows["FR"]["source"] == "recap"
    assert user_countries_db.list_countries("other") == []


def test_snapshot_merge_and_clear():
    assert trip_snapshot_db.get_snapshot(9) is None
    as_of = trip_snapshot_db.put_snapshot(9, {"forex": {"a": 1}, "visa": {"b": 2}})
    snap = trip_snapshot_db.get_snapshot(9)
    assert snap["forex"] == {"a": 1} and snap["as_of"] == as_of
    trip_snapshot_db.put_snapshot(9, {"visa": None, "weather": {"c": 3}})
    snap = trip_snapshot_db.get_snapshot(9)
    assert (
        "visa" not in snap and snap["forex"] == {"a": 1} and snap["weather"] == {"c": 3}
    )
