"""Phase 5 T5: social and quiz notification senders."""

import logging
import string
import uuid

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import (
    notifications_db,
    notify_db,
    plans_db,
    social_db,
    user_settings_db,
    users_db,
)
from app.db.database import get_connection
from app.game.quiz import engine as qe
from app.services import notify_center, notify_text, social_notify

KINDS = (
    "social_idea_saved",
    "social_new_follower",
    "quiz_h2h_invite",
    "quiz_h2h_result",
)
LANGS = ("en", "es", "de", "fr", "hi", "zh", "bn")


@pytest.fixture(autouse=True)
def _on(client, monkeypatch):
    notify_db.create_notify_tables()
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(settings, "play_enabled", True)
    monkeypatch.setattr(settings, "game_enabled", True)
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")


def _mk(client, visibility="public"):
    name = f"sn_{uuid.uuid4().hex[:10]}"
    u = users_db.create_user(
        name, "pw-long-enough-1", email=f"{name}@example.com", is_first_login=False
    )
    u["h"] = {"Authorization": f"Bearer {create_access_token({'sub': name})}"}
    u["handle"] = "h" + uuid.uuid4().hex[:10]
    social_db.save_profile(u["id"], {"handle": u["handle"], "visibility": visibility})
    return u


def _log(u, kind=None):
    with get_connection() as c:
        q = "SELECT * FROM notify_log WHERE user_id = ?"
        args = [u["id"]]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        return [dict(r) for r in c.execute(q + " ORDER BY id", args)]


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


def test_text_every_locale_and_placeholders():
    for lang in LANGS:
        for k in KINDS:
            t = notify_text.render(k, lang)
            assert t and not [f for _, f, _, _ in string.Formatter().parse(t) if f]
    assert notify_text.render(KINDS[1], "de") != notify_text.render(KINDS[1], "en")


def test_follow_sends_once_and_no_handle(client):
    a, b = _mk(client), _mk(client)
    assert (
        client.put(f"/api/social/follow/{b['handle']}", headers=a["h"]).status_code
        == 200
    )
    rows = _log(b, "social_new_follower")
    assert len(rows) == 1 and rows[0]["category"] == "social"
    note = notifications_db.list_notifications(b["id"], limit=5)["items"][0]
    assert a["handle"] not in note["body"] and a["id"] not in str(note["data"])
    client.delete(f"/api/social/follow/{b['handle']}", headers=a["h"])
    client.put(f"/api/social/follow/{b['handle']}", headers=a["h"])
    assert len(_log(b, "social_new_follower")) == 1  # deduped


def test_private_follow_request_not_a_follower_push(client):
    a, b = _mk(client), _mk(client, visibility="followers")
    r = client.put(f"/api/social/follow/{b['handle']}", headers=a["h"])
    assert r.json()["state"] == "pending"
    assert _log(b, "social_new_follower") == []


def test_idea_saved_once_not_self(client):
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)
    client.post(f"/api/social/ideas/{i}/save", headers=b["h"])
    client.delete(f"/api/social/ideas/{i}/save", headers=b["h"])
    client.post(f"/api/social/ideas/{i}/save", headers=b["h"])
    client.post(f"/api/social/ideas/{i}/save", headers=a["h"])
    assert len(_log(a, "social_idea_saved")) == 1


def test_category_off_is_dropped(client):
    a, b = _mk(client), _mk(client)
    notify_db.put_data(b["id"], {"categories": {"social": False}})
    client.put(f"/api/social/follow/{b['handle']}", headers=a["h"])
    row = _log(b, "social_new_follower")[0]
    assert row["status"] == "dropped" and row["dropped_reason"] == "disabled"


def _h2h(client, a, b):
    r = client.post(
        "/api/play/h2h", json={"handle": b["handle"], "pack": "flags"}, headers=a["h"]
    )
    assert r.status_code == 200, r.text
    return r.json()


def _finish(client, u, sid):
    from app.db import quiz_db

    with get_connection() as c:
        truth = [q["answer"] for q in quiz_db.get_session(c, sid)["questions"]]
    for i, a in enumerate(truth):
        r = client.post(
            f"/api/play/quiz/{sid}/answer",
            json={"index": i, "choice": a if a in qe.OPTION_IDS else qe.OPTION_IDS[0]},
            headers=u["h"],
        )
        assert r.status_code == 200, r.text


def test_h2h_invite_and_result(client):
    a, b = _mk(client), _mk(client)
    m = _h2h(client, a, b)
    assert len(_log(b, "quiz_h2h_invite")) == 1
    assert _log(b, "quiz_h2h_invite")[0]["category"] == "quiz"
    _finish(client, a, m["session_id"])
    assert _log(a, "quiz_h2h_result") == []
    acc = client.post(f"/api/play/h2h/{m['id']}/accept", headers=b["h"]).json()
    _finish(client, b, acc["session_id"])
    assert len(_log(a, "quiz_h2h_result")) == 1  # the waiting side
    assert _log(b, "quiz_h2h_result") == []


def test_quiz_kinds_skip_hidden_game(client):
    b = _mk(client)
    user_settings_db.patch_settings(b["id"], {"hide_game": True})
    social_notify.h2h_invite(b["id"], "m1")
    social_notify.h2h_result(b["id"], "m1")
    assert _log(b) == []
    social_notify.new_follower(b["id"], "someone")  # social still sent
    assert len(_log(b, "social_new_follower")) == 1


def test_failures_never_raise(client, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(notify_center, "enqueue_category", boom)
    with caplog.at_level(logging.WARNING):
        social_notify.new_follower("u1", "u2")
    assert "social notification failed" in caplog.text
    a, b = _mk(client), _mk(client)
    assert (
        client.put(f"/api/social/follow/{b['handle']}", headers=a["h"]).status_code
        == 200
    )


def test_hide_community_suppresses_social_pushes(client):
    from app.db import user_settings_db

    a, b = _mk(client), _mk(client)
    user_settings_db.patch_settings(b["id"], {"hide_community": True})
    client.put(f"/api/social/follow/{b['handle']}", headers=a["h"])
    assert _log(b, "social_new_follower") == []


def test_idea_pushes_link_to_the_idea(client, monkeypatch):
    from app.services import notify_center

    seen = []
    real = notify_center.enqueue_category

    def spy(user_id, device, kind, category, key, title, body, data, now):
        seen.append((kind, data))
        return real(user_id, device, kind, category, key, title, body, data, now)

    monkeypatch.setattr(notify_center, "enqueue_category", spy)
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)
    client.post(f"/api/social/ideas/{i}/save", headers=b["h"])
    assert ("social_idea_saved", {"link": f"/feed/{i}"}) in seen
