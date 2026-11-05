"""SQLite persistence for price watches (hotel / activity / trip)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db import fare_watch_db, price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user, create_users_table

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _tables(monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    create_users_table()
    fare_watch_db.create_fare_watch_tables()
    price_watch_db.create_price_watch_tables()
    with get_connection() as conn:  # only this test's watches are due
        conn.execute("UPDATE price_watches SET status = 'paused'")


@pytest.fixture
def user():
    return create_user(f"pw-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _fields(**over):
    f = {
        "kind": "hotel",
        "title": "Lumen Hotel",
        "subtitle": "Lisbon · 10–14 Dec",
        "subject": {"name": "Lumen Hotel", "property_token": "tok", "adults": 2},
        "match_key": "lumen|lisbon|2026-12-10",
        "alert_mode": "any_drop",
        "expires_on": "2026-12-10",
        "baseline_price": 398.0,
        "last_price": 398.0,
        "lowest_price": 398.0,
        "check_count": 1,
        "next_check_at": (NOW + timedelta(hours=12)).isoformat(),
        "last_observation": {"status": "ok", "link": "https://x"},
    }
    f.update(over)
    return f


def test_tables_are_created_idempotently():
    price_watch_db.create_price_watch_tables()
    with get_connection() as conn:
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"price_watches", "price_watch_history"} <= names


def test_create_round_trips_json_and_defaults(user):
    w = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    assert w["kind"] == "hotel"
    assert w["subject"] == {"name": "Lumen Hotel", "property_token": "tok", "adults": 2}
    assert w["last_observation"] == {"status": "ok", "link": "https://x"}
    assert w["status"] == "active"
    assert w["currency"] == "USD"
    assert w["email_enabled"] is False
    assert w["failure_count"] == 0 and w["unavailable_count"] == 0
    assert w["created_at"] == NOW.isoformat()
    assert w["next_check_at"] == (NOW + timedelta(hours=12)).isoformat()


def test_create_ignores_scheduler_state_it_does_not_own(user):
    w = price_watch_db.create_watch(
        user["id"], _fields(status="error", failure_count=9, user_id="x"), now=NOW
    )
    assert (w["status"], w["failure_count"], w["user_id"]) == (
        "active",
        0,
        user["id"],
    )


def test_update_encodes_json_and_bools(user):
    w = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    got = price_watch_db.update_watch(
        w["id"], email_enabled=True, last_observation={"status": "unavailable"}
    )
    assert got["email_enabled"] is True
    assert got["last_observation"] == {"status": "unavailable"}


def test_ownership_lookups(user):
    other = create_user(f"pw-{uuid.uuid4().hex[:8]}", "pw-123456789")
    w = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    assert price_watch_db.get_watch_for_user(w["id"], user["id"])["id"] == w["id"]
    assert price_watch_db.get_watch_for_user(w["id"], other["id"]) is None
    assert price_watch_db.delete_watch(w["id"], other["id"]) is False
    assert price_watch_db.get_watch(w["id"]) is not None


def test_list_filters_by_kind_and_orders_by_expiry(user):
    late = price_watch_db.create_watch(
        user["id"], _fields(expires_on="2027-01-01"), now=NOW
    )
    early = price_watch_db.create_watch(
        user["id"], _fields(expires_on="2026-12-01"), now=NOW
    )
    act = price_watch_db.create_watch(user["id"], _fields(kind="activity"), now=NOW)
    ids = [w["id"] for w in price_watch_db.list_watches(user["id"])]
    assert ids.index(early["id"]) < ids.index(late["id"])
    assert [
        w["id"] for w in price_watch_db.list_watches(user["id"], kind="activity")
    ] == [act["id"]]


def test_find_watch_by_kind_and_match_key_newest_first(user):
    a = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    b = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    assert (
        price_watch_db.find_watch(user["id"], "hotel", a["match_key"])["id"] == b["id"]
    )
    assert price_watch_db.find_watch(user["id"], "activity", a["match_key"]) is None


def test_count_active_counts_only_active(user):
    a = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    price_watch_db.update_watch(a["id"], status="paused")
    assert price_watch_db.count_active(user["id"]) == 1


def test_due_and_claim(user):
    due = price_watch_db.create_watch(
        user["id"], _fields(next_check_at=NOW.isoformat()), now=NOW
    )
    price_watch_db.create_watch(user["id"], _fields(), now=NOW)  # later
    assert price_watch_db.due_watch_ids(NOW, 50) == [due["id"]]
    lease = NOW + timedelta(minutes=10)
    assert price_watch_db.claim_watch(due["id"], NOW, lease, due_only=True)
    assert not price_watch_db.claim_watch(due["id"], NOW, lease)
    assert price_watch_db.due_watch_ids(NOW, 50) == []
    after = NOW + timedelta(minutes=11)
    assert price_watch_db.claim_watch(due["id"], after, after + timedelta(minutes=10))


def test_claim_due_only_skips_paused(user):
    w = price_watch_db.create_watch(
        user["id"], _fields(next_check_at=NOW.isoformat()), now=NOW
    )
    price_watch_db.update_watch(w["id"], status="paused")
    assert not price_watch_db.claim_watch(
        w["id"], NOW, NOW + timedelta(minutes=10), due_only=True
    )


def test_history_keeps_the_newest_rows_and_round_trips_json(user, monkeypatch):
    monkeypatch.setattr(price_watch_db, "HISTORY_KEEP", 3)
    w = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    for i in range(5):
        price_watch_db.add_history(
            w["id"],
            {
                "checked_at": f"t{i}",
                "price": 100.0 + i,
                "breakdown": [{"label": "hotel", "price": 1}] if i == 4 else None,
                "observed": {"status": "ok", "i": i},
            },
        )
    h = price_watch_db.get_history(w["id"])
    assert [r["price"] for r in h] == [102.0, 103.0, 104.0]
    assert h[-1]["breakdown"] == [{"label": "hotel", "price": 1}]
    assert h[0]["breakdown"] is None
    assert h[-1]["observed"] == {"status": "ok", "i": 4}


def test_delete_removes_history(user):
    w = price_watch_db.create_watch(user["id"], _fields(), now=NOW)
    price_watch_db.add_history(w["id"], {"checked_at": "t", "price": 1.0})
    assert price_watch_db.delete_watch(w["id"], user["id"]) is True
    assert price_watch_db.get_history(w["id"]) == []


def test_expire_inactive_past_ends_paused_and_errored_only(user):
    paused = price_watch_db.create_watch(
        user["id"], _fields(expires_on="2026-11-04"), now=NOW
    )
    price_watch_db.update_watch(paused["id"], status="paused")
    err = price_watch_db.create_watch(
        user["id"], _fields(expires_on="2026-11-01"), now=NOW
    )
    price_watch_db.update_watch(err["id"], status="error")
    active = price_watch_db.create_watch(
        user["id"], _fields(expires_on="2026-11-01"), now=NOW
    )
    future = price_watch_db.create_watch(
        user["id"], _fields(expires_on="2026-11-05"), now=NOW
    )
    price_watch_db.update_watch(future["id"], status="paused")
    price_watch_db.expire_inactive_past("2026-11-04", now=NOW)
    status = {w["id"]: w["status"] for w in price_watch_db.list_watches(user["id"])}
    assert status[paused["id"]] == "expired"
    assert status[err["id"]] == "expired"
    assert status[active["id"]] == "active"  # expires through its own check
    assert status[future["id"]] == "paused"


def test_disable_email_for_user(user):
    w = price_watch_db.create_watch(user["id"], _fields(email_enabled=True), now=NOW)
    price_watch_db.disable_email_for_user(user["id"])
    assert price_watch_db.get_watch(w["id"])["email_enabled"] is False
