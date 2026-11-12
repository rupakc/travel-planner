import json
import uuid
from datetime import date

import pytest

from app.core.config import settings
from app.db import user_countries_db, users_db
from app.db.database import get_connection
from app.game import engine, trip_hooks
from app.game.rules import BUILTIN_PATH, load_rules


@pytest.fixture
def uid(client):
    return users_db.create_user(f"t{uuid.uuid4().hex[:10]}", "pw-long-enough-1")["id"]


@pytest.fixture
def pid():
    return uuid.uuid4().int % 10**9  # idempotency keys are global; plan ids are unique


def _count(uid, rule):
    with get_connection() as c:
        return c.execute(
            "SELECT COUNT(*) FROM xp_ledger WHERE user_id=? AND rule=?", (uid, rule)
        ).fetchone()[0]


def test_rules_file_validates():
    r = load_rules(str(BUILTIN_PATH))
    assert r.rules["trip_checkin"].points == 10
    assert r.rules["traveller_type"].once is True
    assert r.streaks["trip_checkin"].freeze_per_week == 1
    assert r.rules["recap_complete"].points == 100
    json.loads(BUILTIN_PATH.read_text())


def test_catalog_lists_new_badges():
    c = engine.catalog()
    ids = {b["id"] for b in c["badges"]}
    assert {
        "traveller",
        "first_trip",
        "ready_regular",
        "road_warrior",
        "local_legend",
        "countries_30",
        "continents_6",
        "memory_keeper",
    } <= ids
    assert len(c["badges"]) >= 25  # 18 + 7 Deal-hunter badges, plus later phases
    assert {r["id"] for r in c["rules"]} >= {"plan_saved", "continent_visited"}


def test_plan_saved_cap_3_per_day(uid, pid):
    got = [trip_hooks.on_plan_saved(uid, pid + i)["awards"] for i in range(4)]
    assert [bool(a) for a in got] == [True, True, True, False]
    assert trip_hooks.on_plan_saved(uid, pid)["awards"] == []


def test_checkin_awards_country_and_continent_once(uid, pid):
    new = ["PT"]
    game, streak = trip_hooks.on_trip_checkin(uid, pid, date(2027, 4, 1), new)
    rules = [a["rule"] for a in game["awards"]]
    assert rules == ["trip_checkin", "country_visited", "continent_visited"]
    assert streak["current"] == 1
    again, _ = trip_hooks.on_trip_checkin(uid, pid, date(2027, 4, 1), new)
    assert again["awards"] == []
    # a second European country adds no continent
    g2, s2 = trip_hooks.on_trip_checkin(uid, pid, date(2027, 4, 2), ["ES"])
    # trip_checkin is capped at one a day, so only the country pays out now
    assert [a["rule"] for a in g2["awards"]] == ["country_visited"]
    assert _count(uid, "continent_visited") == 1
    assert _count(uid, "country_visited") == 2
    assert s2["current"] == 2


def test_continents_computed_before_insert_either_order(uid, pid):
    # route inserted the new country first: the hook must still see Europe as new
    user_countries_db.add_countries(uid, ["PT"], 1, "checkin")
    game, _ = trip_hooks.on_trip_checkin(uid, pid, date(2027, 4, 1), ["PT"])
    assert game["xp"] == 10 + 25 + 50
    # Spain joins Europe: no new continent even though PT is stored
    user_countries_db.add_countries(uid, ["ES"], 1, "checkin")
    g2, _ = trip_hooks.on_trip_checkin(uid, pid, date(2027, 4, 2), ["ES"])
    assert [a["rule"] for a in g2["awards"]] == ["country_visited"]


def test_streak_kind_trip_checkin(uid):
    engine.touch_streak(uid, "trip_checkin", date(2027, 4, 1))
    s = engine.touch_streak(uid, "trip_checkin", date(2027, 4, 2))
    assert s["current"] == 2 and s["freezes"] == 1
    assert engine.summary(uid, hidden=False)["streaks"]["trip_checkin"]["current"] == 2


def test_merge_deltas():
    a = {
        "xp": 10,
        "awards": [{"rule": "a", "points": 10}],
        "badges": [{"id": "x", "earned_at": "t"}],
        "level_up": {"from": 1, "to": 2},
    }
    b = {
        "xp": 60,
        "awards": [{"rule": "b", "points": 50}],
        "badges": [],
        "level_up": {"from": 2, "to": 3},
    }
    m = trip_hooks.merge_deltas(None, a, b)
    assert m["xp"] == 60 and len(m["awards"]) == 2 and len(m["badges"]) == 1
    assert m["level_up"] == {"from": 1, "to": 3}
    assert trip_hooks.merge_deltas(None, None) is None
    assert trip_hooks.merge_deltas(a) == a


def test_hook_failure_returns_empty_delta(uid, pid, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(engine, "award", boom)
    d = trip_hooks.on_trip_ready(uid, pid)
    assert d == {"xp": 0, "awards": [], "badges": [], "level_up": None}
    game, streak = trip_hooks.on_trip_checkin(uid, pid, date(2027, 4, 1), ["PT"])
    assert game["awards"] == [] and streak is None


def test_game_disabled_hooks_return_none(uid, monkeypatch):
    monkeypatch.setattr(settings, "game_enabled", False)
    assert trip_hooks.on_plan_saved(uid, 1) is None
    assert trip_hooks.on_trip_ready(uid, pid) is None
    assert trip_hooks.on_smart_planner(uid, pid, 80) is None
    assert trip_hooks.on_place_visited(uid, 1, "place:x") is None
    assert trip_hooks.on_trip_checkin(uid, pid, date(2027, 4, 1), []) == (None, None)
    assert trip_hooks.on_recap_complete(uid, 1, []) is None
    assert trip_hooks.on_traveller_type(uid, "foodie") is None
    assert _count(uid, "plan_saved") == 0


def test_recap_and_smart_planner_keys(uid, pid):
    assert trip_hooks.on_smart_planner(uid, pid, 70)["awards"]
    assert trip_hooks.on_smart_planner(uid, pid, 70)["awards"] == []
    assert trip_hooks.on_smart_planner(uid, pid, 80)["awards"]
    d = trip_hooks.on_recap_complete(uid, pid, ["JP"])
    assert [a["rule"] for a in d["awards"]] == [
        "recap_complete",
        "country_visited",
        "continent_visited",
    ]
    assert trip_hooks.on_recap_complete(uid, pid, [])["awards"] == []
