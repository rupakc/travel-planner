"""Phase 2 wave-0 seams: router stubs, ownership, hook and service stubs."""

import importlib
from datetime import date

import pytest

from app.core.config import settings
from app.core.errors import ApiError

ROUTERS = [
    "trips",
    "trip_prep",
    "trip_money",
    "trip_journal",
    "trip_offline",
    "trip_today",
    "trip_recap",
]


@pytest.mark.parametrize("name", ROUTERS)
def test_stub_routers_importable(name):
    mod = importlib.import_module(f"app.api.routes.{name}")
    assert hasattr(mod, "router")


def test_trips_route_not_served_by_stubs(client):
    assert client.get("/api/trips").status_code in (404, 405)


def test_owned_trip_404_for_other_user(monkeypatch):
    from app.core import trip_access

    monkeypatch.setattr(
        trip_access.plans_db, "get_plan", lambda pid: {"id": pid, "username": "alice"}
    )
    assert trip_access.owned_trip(1, {"username": "alice"})["id"] == 1
    with pytest.raises(ApiError) as exc:
        trip_access.owned_trip(1, {"username": "bob"})
    assert exc.value.status == 404 and exc.value.code == "trip_not_found"
    monkeypatch.setattr(trip_access.plans_db, "get_plan", lambda pid: None)
    with pytest.raises(ApiError) as exc:
        trip_access.owned_trip(2, {"username": "alice"})
    assert exc.value.code == "trip_not_found"


def test_hooks_stubs_return_none():
    from app.game import trip_hooks as h

    d = date(2026, 1, 1)
    assert h.on_plan_saved("u", 1) is None
    assert h.on_trip_ready("u", 1) is None
    assert h.on_smart_planner("u", 1, 90) is None
    assert h.on_place_visited("u", 1, "k") is None
    assert h.on_trip_checkin("u", 1, d, ["JP"]) == (None, None)
    assert h.on_recap_complete("u", 1, []) is None
    assert h.on_traveller_type("u", "foodie") is None


def test_service_stubs():
    from app.services import phrases, trip_money, trip_prep

    assert trip_prep.prep_summary({"id": "p-none"}, date(2026, 1, 1)) == {
        "done": 0,
        "total": 0,
        "percent": 0,
        "complete": False,
    }
    assert trip_money.spend_summary({}) == {
        "spent_usd": None,
        "by_category_usd": {},
        "unconverted": [],
        "by_currency": {},
    }
    assert trip_money.usd_rate(None) is None
    jp = phrases.phrases_for_country("JP")
    assert isinstance(jp, dict) and jp["language"] == "ja"


def test_db_stubs():
    from app.db import trip_checkins_db, trip_journal_db

    assert trip_journal_db.list_entries(1) == []
    assert trip_journal_db.list_places(1) == []
    assert trip_checkins_db.add(1, "2026-01-01", None, None) is False
    assert trip_checkins_db.list_days(1) == []


def test_settings_defaults():
    assert settings.journey_ui_enabled is False
    assert settings.offline_pack_enabled is True
    assert settings.ready_window_days == 14
    assert settings.trip_max_expenses == 2000
    assert settings.trip_max_journal == 500
    assert settings.trip_max_places == 1000
    assert settings.trip_snapshot_max_bytes == 262144


def test_lifespan_creates_trip_tables_on_fresh_db(monkeypatch, tmp_path):
    """Startup alone (own empty DB, not the session fixture's) creates them."""
    import sqlite3

    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    with TestClient(app):
        pass
    conn = sqlite3.connect(str(tmp_path / "airports.db"))
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        cols = {r[1] for r in conn.execute("PRAGMA table_info(plans)")}
    finally:
        conn.close()
    assert {
        "trip_expenses",
        "trip_journal",
        "trip_checkins",
        "user_countries",
    } <= tables
    assert {"title", "phase", "start_date", "end_date", "recap_completed_at"} <= cols
