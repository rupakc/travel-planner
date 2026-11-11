import json
import uuid
from datetime import UTC, date, datetime

import pytest

from app.core.config import settings
from app.db import users_db
from app.db.database import get_connection
from app.game import engine, hooks
from app.game.rules import load_rules


@pytest.fixture
def uid(client):
    u = users_db.create_user(f"g{uuid.uuid4().hex[:10]}", "pw-long-enough-1")
    return u["id"]


def _ledger(uid):
    with get_connection() as c:
        return c.execute("SELECT * FROM xp_ledger WHERE user_id=?", (uid,)).fetchall()


def test_award_once_is_idempotent(uid):
    d1 = engine.award(uid, "email_verified", "a")
    d2 = engine.award(uid, "email_verified", "b")
    assert d1["xp"] == 50 and d1["awards"] == [{"rule": "email_verified", "points": 50}]
    assert d2 == {"xp": 50, "awards": [], "badges": [], "level_up": None}
    assert len(_ledger(uid)) == 1


def test_unknown_rule(uid):
    with pytest.raises(KeyError):
        engine.award(uid, "nope", "x")


def test_daily_cap(uid, monkeypatch):
    rules = load_rules()
    rules.rules["email_verified"].once = False
    monkeypatch.setattr(engine, "get_rules", lambda: rules)
    assert engine.award(uid, "email_verified", "k1")["awards"]
    assert engine.award(uid, "email_verified", "k2")["awards"] == []
    nxt = datetime(2099, 1, 1, tzinfo=UTC)
    assert engine.award(uid, "email_verified", "k3", now=nxt)["awards"]


def test_level_up_reported(uid):
    engine.award(uid, "email_verified", "x")
    d = engine.award(uid, "onboarding_complete", "y")
    assert d["xp"] == 150 and d["level_up"] == {"from": 1, "to": 2}


def test_badge_earned_with_progress(uid):
    d = engine.award(uid, "email_verified", "x")
    assert [b["id"] for b in d["badges"]] == ["verified"]
    s = engine.summary(uid, hidden=False)
    assert s["badges"][0]["progress"] == 1 and s["badges"][0]["earned_at"]
    assert s["level"] == 1 and s["next_level_xp"] == 100


def test_streak_next_day(uid):
    engine.touch_streak(uid, "daily", date(2026, 11, 2))
    s = engine.touch_streak(uid, "daily", date(2026, 11, 3))
    assert s["current"] == 2 and s["longest"] == 2
    assert engine.touch_streak(uid, "daily", date(2026, 11, 3))["current"] == 2
    assert engine.touch_streak(uid, "daily", date(2026, 11, 1))["current"] == 2


def test_streak_freeze_covers_one_missed_day(uid):
    engine.touch_streak(uid, "daily", date(2026, 11, 2))
    s = engine.touch_streak(uid, "daily", date(2026, 11, 4))
    assert s["current"] == 2 and s["freezes"] == 0


def test_streak_resets_after_two_missed_days(uid):
    engine.touch_streak(uid, "daily", date(2026, 11, 2))
    engine.touch_streak(uid, "daily", date(2026, 11, 3))
    s = engine.touch_streak(uid, "daily", date(2026, 11, 6))
    assert s["current"] == 1 and s["longest"] == 2


def test_freeze_refills_each_iso_week(uid):
    engine.touch_streak(uid, "daily", date(2026, 11, 2))  # Monday
    engine.touch_streak(uid, "daily", date(2026, 11, 4))  # uses the freeze
    s = engine.touch_streak(uid, "daily", date(2026, 11, 9))  # next week, 4 days missed
    assert s["current"] == 1
    s = engine.touch_streak(uid, "daily", date(2026, 11, 11))
    assert s["current"] == 2 and s["freezes"] == 0
    s = engine.touch_streak(uid, "daily", date(2026, 11, 12))
    assert s["current"] == 3


def test_invalid_override_falls_back(tmp_path):
    bad = tmp_path / "r.json"
    bad.write_text(json.dumps({"rules": 5}))
    assert "email_verified" in load_rules(str(bad)).rules
    assert "email_verified" in load_rules(str(tmp_path / "missing.json")).rules


def test_hooks_award_and_swallow_errors(uid, monkeypatch):
    assert hooks.on_email_verified(uid)["xp"] == 50
    monkeypatch.setattr(engine, "award", lambda *a, **k: 1 / 0)
    # a failed award is the empty delta (None means "game disabled")
    assert hooks.on_onboarding_complete(uid) == {
        "xp": 50, "awards": [], "badges": [], "level_up": None
    }  # fmt: skip
    monkeypatch.setattr(settings, "game_enabled", False)
    assert hooks.on_email_verified(uid) is None


def test_builtin_rules_values():
    r = load_rules()
    base = {k: r.rules[k] for k in ("email_verified", "onboarding_complete")}
    assert {k: (v.points, v.daily_cap, v.once) for k, v in base.items()} == {
        "email_verified": (50, 1, True),
        "onboarding_complete": (100, 1, True),
    }
    assert r.badges["verified"].icon == "mail-check"
    assert r.badges["first_steps"].icon == "footprints"
    assert r.levels.min_xp == [0, 100, 250, 500, 1000, 2000, 3500, 5500, 8000, 12000]
    assert r.streaks["daily"].freeze_per_week == 1
    assert r.streaks["trip_checkin"].freeze_per_week == 1


def test_valid_override_is_used_and_once_key_is_forced(uid, tmp_path):
    data = json.loads(open(load_rules.__globals__["BUILTIN_PATH"]).read())
    data["rules"]["email_verified"]["points"] = 7
    p = tmp_path / "ok.json"
    p.write_text(json.dumps(data))
    assert load_rules(str(p)).rules["email_verified"].points == 7
    engine.award(uid, "email_verified", "k1")
    assert [r["idem_key"] for r in _ledger(uid)] == [f"email_verified:{uid}"]


def test_engine_honours_rules_path_setting(uid, tmp_path, monkeypatch):
    data = json.loads(open(load_rules.__globals__["BUILTIN_PATH"]).read())
    data["rules"]["email_verified"]["points"] = 7
    p = tmp_path / "ok.json"
    p.write_text(json.dumps(data))
    monkeypatch.setattr(settings, "game_rules_path", str(p))
    assert engine.get_rules().rules["email_verified"].points == 7
    assert engine.award(uid, "email_verified", "k")["xp"] == 7
    monkeypatch.setattr(settings, "game_rules_path", str(tmp_path / "missing.json"))
    assert engine.get_rules().rules["email_verified"].points == 50
