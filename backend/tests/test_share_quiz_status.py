"""Phase 5 share kinds ``quiz`` and ``status``."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import quiz_db, users_db
from app.db.database import get_connection
from app.db.plans_db import save_plan

_PW = "correct-horse-battery"


def _user(display_name=None):
    name = f"shq_{uuid.uuid4().hex[:10]}"
    u = users_db.create_user(
        name, _PW, email=f"{name}@example.com", display_name=display_name
    )
    return u, {"Authorization": f"Bearer {create_access_token({'sub': name})}"}


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "sharing_v2_enabled", True)
    monkeypatch.setattr(settings, "play_enabled", True)
    monkeypatch.setattr(settings, "game_enabled", True)
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")


def _session(user_id, finished=True, correct=4, pack="flags", mode="pack"):
    sid = secrets.token_urlsafe(12)
    qs = [{"kind": "flag", "prompt": {"SECRET_PROMPT": 1}, "options": []}] * 5
    with get_connection() as conn:
        quiz_db.create_session(conn, sid, user_id, mode, pack, "2026-11-12", "s", qs, 1)
        if finished:
            conn.execute(
                "UPDATE quiz_sessions SET finished_ms=99999, correct=?, score=?"
                " WHERE id=?",
                (correct, 777, sid),
            )
    return sid


def _post(client, h, **body):
    return client.post("/api/shares", json=body, headers=h)


def test_quiz_share_card_has_no_time_or_answers(client):
    u, h = _user()
    sid = _session(u["id"])
    r = _post(client, h, kind="quiz", session_id=sid)
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    pub = client.get(f"/api/share/{tok}").json()
    assert pub["kind"] == "quiz"
    assert pub["card"]["headline"] == "Flags quiz: 4/5"
    assert pub["card"]["stats"] == [{"key": "correct", "count": 4}]
    blob = str(pub)
    for bad in ("SECRET_PROMPT", "777", "99999", sid, "questions"):
        assert bad not in blob
    assert pub["search_data"] == {} and pub["selections"] == {}
    page = client.get(f"/api/share/{tok}/page").text
    assert "Flags quiz: 4/5" in page and "777" not in page
    assert client.get(f"/api/share/{tok}/card.png").status_code == 200


def test_quiz_share_idempotent_per_session_distinct_across_sessions(client):
    u, h = _user()
    a, b = _session(u["id"]), _session(u["id"])
    t1 = _post(client, h, kind="quiz", session_id=a).json()["token"]
    assert _post(client, h, kind="quiz", session_id=a).json()["token"] == t1
    assert _post(client, h, kind="quiz", session_id=b).json()["token"] != t1


def test_quiz_not_yours_unfinished_missing_404(client):
    u, h = _user()
    other, _ = _user()
    assert (
        _post(client, h, kind="quiz", session_id=_session(other["id"])).status_code
        == 404
    )
    assert (
        _post(
            client, h, kind="quiz", session_id=_session(u["id"], finished=False)
        ).status_code
        == 404
    )
    assert _post(client, h, kind="quiz", session_id="nope").status_code == 404
    assert _post(client, h, kind="quiz").status_code == 404


def test_quiz_needs_play_enabled(client, monkeypatch):
    u, h = _user()
    sid = _session(u["id"])
    tok = _post(client, h, kind="quiz", session_id=sid).json()["token"]
    monkeypatch.setattr(settings, "play_enabled", False)
    assert _post(client, h, kind="quiz", session_id=sid).status_code == 404
    assert client.get(f"/api/share/{tok}").status_code == 404


def test_quiz_name_hidden_unless_show_name(client):
    u, h = _user(display_name="Ada Lovelace")
    sid = _session(u["id"])
    tok = _post(client, h, kind="quiz", session_id=sid).json()["token"]
    assert "Ada" not in str(client.get(f"/api/share/{tok}").json())
    tok = _post(
        client, h, kind="quiz", session_id=sid, options={"show_name": True}
    ).json()["token"]
    assert client.get(f"/api/share/{tok}").json()["owner_name"] == "Ada Lovelace"


def _trip(user, start, end, destination="Lisbon"):
    return save_plan(
        user["username"],
        "Secret trip name",
        {
            "destination": destination,
            "origin": "NYC",
            "departure_date": start,
            "return_date": end,
        },
        {},
    )


def _d(offset):
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def test_status_needs_active_trip(client):
    u, h = _user()
    assert _post(client, h, kind="status").status_code == 422
    assert _post(client, h, kind="status").json()["error_code"] == "no_active_trip"
    p = _trip(u, _d(30), _d(35))
    r = _post(client, h, kind="status", plan_id=p["id"])
    assert r.status_code == 422
    assert r.json()["error_code"] == "no_active_trip"


def test_status_other_users_plan_404(client):
    u, h = _user()
    other, _ = _user()
    p = _trip(other, _d(-1), _d(3))
    assert _post(client, h, kind="status", plan_id=p["id"]).status_code == 404


def test_status_card_day_n_and_privacy(client):
    u, h = _user()
    p = _trip(u, _d(-2), _d(3))
    r = _post(client, h, kind="status")  # picks the active trip
    assert r.status_code == 200, r.text
    assert r.json()["plan_id"] == p["id"]
    tok = r.json()["token"]
    pub = client.get(f"/api/share/{tok}").json()
    assert pub["card"]["headline"] == "Day 3 in Lisbon"
    blob = str(pub)
    assert "Secret trip name" not in blob and "NYC" not in blob
    assert _d(-2) not in blob and _d(3) not in blob
    assert "Day 3 in Lisbon" in client.get(f"/api/share/{tok}/page").text
    assert client.get(f"/api/share/{tok}/card.png?size=story").status_code == 200


def test_status_dies_when_trip_over(client):
    u, h = _user()
    p = _trip(u, _d(-2), _d(3))
    tok = _post(client, h, kind="status", plan_id=p["id"]).json()["token"]
    with get_connection() as conn:
        conn.execute(
            "UPDATE plans SET start_date=?, end_date=?, search_data=? WHERE id=?",
            (_d(-20), _d(-10), '{"destination": "Lisbon"}', p["id"]),
        )
    assert client.get(f"/api/share/{tok}").status_code == 404


def test_unknown_kind_still_422(client):
    _, h = _user()
    assert _post(client, h, kind="zzz").status_code == 422


def test_telemetry_accepts_new_kinds():
    from app.telemetry.registry import EVENTS

    spec = EVENTS["share_create"]["kind"]
    assert "quiz" in spec and "status" in spec
