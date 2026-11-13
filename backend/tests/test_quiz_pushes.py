"""Daily-quiz reminder push (quiz_pushes) and like/comment pushes."""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import (
    alerts_db,
    devices_db,
    notify_db,
    plans_db,
    quiz_db,
    social_db,
    user_settings_db,
    users_db,
)
from app.db.database import get_connection
from app.services import notify_text, quiz_pushes, social_notify

LANGS = ("en", "es", "de", "fr", "hi", "zh", "bn")
NOON = datetime(2026, 11, 13, 13, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    alerts_db.create_alert_tables()
    notify_db.create_notify_tables()
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")
    monkeypatch.setattr(settings, "play_enabled", True)
    monkeypatch.setattr(settings, "game_enabled", True)
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(quiz_pushes, "_cursor", "")


def _user(tz="UTC", device=True, played=True):
    name = f"qp_{uuid.uuid4().hex[:10]}"
    u = users_db.create_user(
        name, "pw-long-enough-1", email=f"{name}@example.com", is_first_login=False
    )
    if tz:
        user_settings_db.patch_settings(u["id"], {"timezone": tz})
    if device:
        devices_db.upsert_device(name, "tok-" + name, "android", "en", now=NOON)
    if played:
        _session(u, "pack", finished=True, now=NOON)
    u["h"] = {"Authorization": f"Bearer {create_access_token({'sub': name})}"}
    return u


def _session(u, mode, finished, now, day=None):
    ms = int(now.timestamp() * 1000)
    with get_connection() as c:
        quiz_db.create_session(
            c,
            uuid.uuid4().hex,
            u["id"],
            mode,
            None,
            day or now.date().isoformat(),
            "s",
            [],
            ms,
        )
        if finished:
            c.execute(
                "UPDATE quiz_sessions SET finished_ms = ? WHERE user_id = ?"
                " AND mode = ?",
                (ms, u["id"], mode),
            )


def _log(u, kind):
    with get_connection() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM notify_log WHERE user_id = ? AND kind = ?",
                (u["id"], kind),
            )
        ]


def test_text_all_locales():
    for k in ("social_idea_liked", "social_idea_comment", "quiz_daily"):
        for lang in LANGS:
            assert notify_text.render(k, lang)
        assert notify_text.render(k, "de") != notify_text.render(k, "en")


def test_daily_once_per_local_day():
    u = _user()
    quiz_pushes.run_due(NOON)
    quiz_pushes.run_due(NOON.replace(hour=15))
    rows = _log(u, "quiz_daily")
    assert len(rows) == 1 and rows[0]["category"] == "quiz"
    quiz_pushes.run_due(NOON.replace(day=14))
    assert len(_log(u, "quiz_daily")) == 2


def test_daily_skips(monkeypatch):
    done = _user()
    _session(done, "daily", True, NOON)
    nodev = _user(device=False)
    notz = _user(tz=None)
    never = _user(played=False)
    hidden = _user()
    user_settings_db.patch_settings(hidden["id"], {"hide_game": True})
    quiz_pushes.run_due(NOON)
    for u in (done, nodev, notz, never, hidden):
        assert _log(u, "quiz_daily") == []
    # outside the local window
    early = _user()
    quiz_pushes.run_due(NOON.replace(hour=6))
    assert _log(early, "quiz_daily") == []
    # kill switches
    monkeypatch.setattr(settings, "play_enabled", False)
    assert quiz_pushes.run_due(NOON) == 0
    assert _log(early, "quiz_daily") == []


def test_daily_respects_category_off_and_tz():
    off = _user()
    notify_db.put_data(off["id"], {"categories": {"quiz": False}})
    tokyo = _user(tz="Asia/Tokyo")  # 13:00 UTC = 22:00 local, past window
    quiz_pushes.run_due(NOON)
    r = _log(off, "quiz_daily")[0]
    assert r["status"] == "dropped" and r["dropped_reason"] == "disabled"
    assert _log(tokyo, "quiz_daily") == []


def test_daily_quiet_hours_hold():
    u = _user()
    alerts_db.put_prefs(
        u["id"],
        {"quiet_hours": {"enabled": True, "start": "12:00", "end": "14:00"}},
    )
    quiz_pushes.run_due(NOON)
    r = _log(u, "quiz_daily")[0]
    assert r["status"] == "pending" and r["due_at"] > "2026-11-13T13:00:00Z"


# ── like / comment ───────────────────────────────────────────────────────────


def _profile(u):
    u["handle"] = "h" + uuid.uuid4().hex[:10]
    social_db.save_profile(u["id"], {"handle": u["handle"], "visibility": "public"})


def _idea(client, a):
    plan = plans_db.save_plan(
        a["username"], "t", {"destination": "Lisbon"}, {"activities": [{"name": "x"}]}
    )
    r = client.post(
        "/api/social/ideas",
        json={"plan_id": plan["id"], "kind": "plan", "title": "Lisbon", "caption": "c"},
        headers=a["h"],
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _pair(client):
    a, b = _user(played=False), _user(played=False)
    _profile(a)
    _profile(b)
    return a, b, _idea(client, a)


def test_like_pushes_once_per_idea_per_day_not_self(client):
    a, b, i = _pair(client)
    c = _user(played=False)
    _profile(c)
    client.put(f"/api/social/ideas/{i}/like", headers=b["h"])
    client.put(f"/api/social/ideas/{i}/like", headers=c["h"])
    client.put(f"/api/social/ideas/{i}/like", headers=a["h"])
    rows = _log(a, "social_idea_liked")
    assert len(rows) == 1 and rows[0]["category"] == "social"


def test_like_blocked_no_push(client):
    a, b, i = _pair(client)
    social_db.block(a["id"], b["id"])
    social_notify.idea_liked(a["id"], b["id"], i)
    assert _log(a, "social_idea_liked") == []


def test_comment_push_and_held_not_announced(client):
    a, b, i = _pair(client)
    r = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "Lovely"}, headers=b["h"]
    )
    assert r.status_code == 200, r.text
    assert len(_log(a, "social_idea_comment")) == 1
    note = _log(a, "social_idea_comment")[0]
    assert note["category"] == "social"
    client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "again"}, headers=a["h"]
    )  # own comment
    assert len(_log(a, "social_idea_comment")) == 1


def test_comment_category_off_dropped(client):
    a, b, i = _pair(client)
    notify_db.put_data(a["id"], {"categories": {"social": False}})
    client.post(f"/api/social/ideas/{i}/comments", json={"text": "Hi"}, headers=b["h"])
    r = _log(a, "social_idea_comment")[0]
    assert r["status"] == "dropped" and r["dropped_reason"] == "disabled"


def test_candidates_rotate_past_the_page_size(monkeypatch):
    monkeypatch.setattr(quiz_pushes, "MAX_USERS", 10)
    ids = {_user()["id"] for _ in range(25)}
    seen: list[str] = []
    for _ in range(20):  # other tests' players share the table
        seen += [c["user_id"] for c in quiz_pushes._candidates(NOON)]
    assert ids <= set(seen)
    assert len(quiz_pushes._candidates(NOON)) > 0  # wraps, never stuck
