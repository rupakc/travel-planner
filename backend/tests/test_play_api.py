import json
import uuid
from datetime import UTC, datetime

import pytest

from app.core import rate_limit
from app.core.config import settings
from app.db import users_db
from app.db.database import get_connection
from app.game.quiz import engine as qe
from app.game.quiz import service


@pytest.fixture(autouse=True)
def _play_on(monkeypatch):
    monkeypatch.setattr(settings, "play_enabled", True)
    monkeypatch.setattr(settings, "game_enabled", True)


@pytest.fixture
def clock(monkeypatch):
    t = {"ms": 1_800_000_000_000}  # a fixed UTC instant; each test gets a fresh day
    t["ms"] += (uuid.uuid4().int % 3000) * 86_400_000
    monkeypatch.setattr(service, "_now_ms", lambda: t["ms"])
    return t


def _login(client):
    name = f"pl{uuid.uuid4().hex[:8]}"
    u = users_db.create_user(name, "pw-long-enough-1", is_first_login=False)
    r = client.post(
        "/api/auth/login", json={"username": name, "password": "pw-long-enough-1"}
    )
    return u["id"], {"Authorization": f"Bearer {r.json()['access_token']}"}


def _start(client, h, **body):
    return client.post("/api/play/quiz", json=body, headers=h)


def _truth(session_id):
    with get_connection() as c:
        from app.db import quiz_db

        return [q["answer"] for q in quiz_db.get_session(c, session_id)["questions"]]


def _wrong(answer):
    return next(i for i in qe.OPTION_IDS if i != answer)


def _play(client, h, sid, picks, step_ms=0, clock=None):
    out = []
    truth = _truth(sid)
    for i, kind in enumerate(picks):
        if clock:
            clock["ms"] += step_ms
        choice = truth[i] if kind == "right" else _wrong(truth[i])
        r = client.post(
            f"/api/play/quiz/{sid}/answer",
            json={"index": i, "choice": choice},
            headers=h,
        )
        out.append(r)
    return out


def test_flag_off_404_and_features(client, monkeypatch):
    _, h = _login(client)
    monkeypatch.setattr(settings, "play_enabled", False)
    for path in ("/api/play/state", "/api/play/history"):
        r = client.get(path, headers=h)
        assert r.status_code == 404 and r.json()["error_code"] == "play_disabled"
    assert _start(client, h, mode="daily").status_code == 404
    assert client.get("/api/config").json()["features"]["play"] == 0
    monkeypatch.setattr(settings, "play_enabled", True)
    assert client.get("/api/config").json()["features"]["play"] == 1
    monkeypatch.setattr(settings, "game_enabled", False)
    assert client.get("/api/config").json()["features"]["play"] == 0
    assert client.get("/api/play/state", headers=h).status_code == 404


def test_default_flag_is_on():
    from app.core.config import Settings

    assert Settings(_env_file=None).play_enabled is True


def test_requires_auth(client):
    assert client.get("/api/play/state").status_code in (401, 403)
    assert client.post("/api/play/quiz", json={"mode": "daily"}).status_code in (
        401,
        403,
    )


def test_hidden_game_403_everywhere(client):
    uid, h = _login(client)
    with get_connection() as c:
        c.execute(
            "INSERT INTO user_settings (user_id, data, updated_at) VALUES (?, ?, ?)",
            (uid, json.dumps({"hide_game": True}), datetime.now(UTC).isoformat()),
        )
    for r in (
        client.get("/api/play/state", headers=h),
        client.get("/api/play/history", headers=h),
        client.get("/api/play/quiz/x", headers=h),
        _start(client, h, mode="daily"),
        client.post(
            "/api/play/quiz/x/answer", json={"index": 0, "choice": "a"}, headers=h
        ),
    ):
        assert r.status_code == 403 and r.json()["error_code"] == "game_hidden"


def test_state_shape(client, clock):
    _, h = _login(client)
    d = client.get("/api/play/state", headers=h).json()
    assert set(d) == {"daily", "packs", "challenge", "open_h2h"}
    assert d["challenge"]["done"] is False and d["open_h2h"] == 0
    assert d["daily"] == {
        "available": True, "done": False, "score": None,
        "streak": {"current": 0, "longest": 0, "freeze_available": True},
    }  # fmt: skip
    assert [p["id"] for p in d["packs"]] == [
        "flags",
        "capitals",
        "landmarks",
        "cuisine",
    ]
    assert d["packs"][0]["title_key"] == "play.pack.flags"


def test_start_shape_hides_answers(client, clock):
    _, h = _login(client)
    r = _start(client, h, mode="pack", pack="flags")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "pack" and d["pack"] == "flags" and len(d["questions"]) == 5
    assert d["expires_at"].endswith("Z") and d["answers"] == [] and d["done"] is False
    assert "answer" not in json.dumps(d["questions"])
    assert all(len(q["options"]) == 4 for q in d["questions"])


def test_validation(client, clock):
    _, h = _login(client)
    r = _start(client, h, mode="pack", pack="etiquette")
    assert r.status_code == 422 and r.json()["error_code"] == "invalid_pack"
    assert _start(client, h, mode="pack").status_code == 422
    assert _start(client, h, mode="h2h").status_code == 422
    assert _start(client, h, mode="bogus").status_code == 422


def test_daily_same_for_everyone_and_resumes(client, clock):
    _, h1 = _login(client)
    _, h2 = _login(client)
    a = _start(client, h1, mode="daily").json()
    b = _start(client, h2, mode="daily").json()
    assert a["questions"] == b["questions"]
    assert a["session_id"] != b["session_id"]
    again = _start(client, h1, mode="daily").json()
    assert again["session_id"] == a["session_id"] and again["resumed"] is True
    clock["ms"] += 86_400_000
    nxt = _start(client, h1, mode="daily").json()
    assert nxt["questions"] != a["questions"]


def test_daily_once(client, clock):
    _, h = _login(client)
    sid = _start(client, h, mode="daily").json()["session_id"]
    rs = _play(client, h, sid, ["right"] * 5)
    assert [r.status_code for r in rs] == [200] * 5
    r = _start(client, h, mode="daily")
    assert r.status_code == 409 and r.json()["error_code"] == "already_done"
    st = client.get("/api/play/state", headers=h).json()["daily"]
    assert st["done"] is True and st["available"] is False and st["score"] == 750
    assert st["streak"]["current"] == 1


def test_answer_correct_and_wrong_server_timed(client, clock):
    _, h = _login(client)
    sid = _start(client, h, mode="pack", pack="capitals").json()["session_id"]
    truth = _truth(sid)
    clock["ms"] += 3000
    r = client.post(
        f"/api/play/quiz/{sid}/answer", json={"index": 0, "choice": truth[0]}, headers=h
    ).json()
    assert r == {
        "correct": True, "correct_choice": truth[0], "points": 140,
        "elapsed_ms": 3000, "done": False,
    }  # fmt: skip
    clock["ms"] += 20000  # slow: no bonus
    r = client.post(
        f"/api/play/quiz/{sid}/answer", json={"index": 1, "choice": truth[1]}, headers=h
    ).json()
    assert r["points"] == 100 and r["elapsed_ms"] == 20000
    r = client.post(
        f"/api/play/quiz/{sid}/answer",
        json={"index": 2, "choice": _wrong(truth[2])},
        headers=h,
    ).json()
    assert (
        r["correct"] is False and r["points"] == 0 and r["correct_choice"] == truth[2]
    )


def test_reanswer_returns_first_result(client, clock):
    _, h = _login(client)
    sid = _start(client, h, mode="pack", pack="flags").json()["session_id"]
    truth = _truth(sid)
    clock["ms"] += 1000
    first = client.post(
        f"/api/play/quiz/{sid}/answer",
        json={"index": 0, "choice": _wrong(truth[0])},
        headers=h,
    ).json()
    clock["ms"] += 5000
    again = client.post(
        f"/api/play/quiz/{sid}/answer", json={"index": 0, "choice": truth[0]}, headers=h
    ).json()
    assert again == first and first["correct"] is False


def test_answer_errors(client, clock):
    _, h = _login(client)
    _, h2 = _login(client)
    sid = _start(client, h, mode="pack", pack="flags").json()["session_id"]

    def post(headers, body, s=sid):
        return client.post(f"/api/play/quiz/{s}/answer", json=body, headers=headers)

    assert post(h, {"index": 5, "choice": "a"}).json()["error_code"] == "invalid_index"
    assert post(h, {"index": 0, "choice": "z"}).json()["error_code"] == "invalid_choice"
    r = post(h, {"index": 2, "choice": "a"})
    assert r.status_code == 422 and r.json()["error_code"] == "out_of_order"
    r = post(h2, {"index": 0, "choice": "a"})
    assert r.status_code == 404 and r.json()["error_code"] == "session_not_found"
    assert client.get(f"/api/play/quiz/{sid}", headers=h2).status_code == 404
    assert post(h, {"index": 0, "choice": "a"}, s="nope").status_code == 404


def test_summary_xp_perfect_and_badge(client, clock):
    uid, h = _login(client)
    sid = _start(client, h, mode="daily").json()["session_id"]
    rs = _play(client, h, sid, ["right"] * 5)
    last = rs[-1].json()
    assert last["done"] is True
    s = last["summary"]
    assert s["score"] == 750 and s["correct"] == 5 and s["total"] == 5
    assert {a["rule"] for a in s["xp"]["awards"]} == {"quiz_daily", "quiz_perfect"}
    assert s["xp"]["xp"] == 30
    assert s["streak"]["current"] == 1
    assert "quiz_ace" in [b["id"] for b in s["xp"]["badges"]]
    # a repeated final answer reports the same summary
    again = client.post(
        f"/api/play/quiz/{sid}/answer", json={"index": 4, "choice": "a"}, headers=h
    ).json()
    assert again["summary"] == s


def test_imperfect_daily_gets_only_daily_xp(client, clock):
    _, h = _login(client)
    sid = _start(client, h, mode="daily").json()["session_id"]
    rs = _play(client, h, sid, ["right"] * 4 + ["wrong"])
    s = rs[-1].json()["summary"]
    assert [a["rule"] for a in s["xp"]["awards"]] == ["quiz_daily"]
    assert s["correct"] == 4


def test_pack_xp_cap_three_per_day(client, clock):
    _, h = _login(client)
    awarded = []
    for _ in range(5):
        sid = _start(client, h, mode="pack", pack="landmarks").json()["session_id"]
        rs = _play(client, h, sid, ["right", "wrong", "right", "wrong", "wrong"])
        s = rs[-1].json()["summary"]
        awarded.append(len(s["xp"]["awards"]) if s.get("xp") else 0)
    assert awarded == [1, 1, 1, 0, 0]
    clock["ms"] += 86_400_000
    sid = _start(client, h, mode="pack", pack="landmarks").json()["session_id"]
    s = _play(client, h, sid, ["wrong"] * 5)[-1].json()["summary"]
    assert len(s["xp"]["awards"]) == 1  # new day, cap reset


def test_pack_resumes_unfinished_then_fresh(client, clock):
    _, h = _login(client)
    a = _start(client, h, mode="pack", pack="cuisine").json()
    _play(client, h, a["session_id"], ["right"] * 2)
    b = _start(client, h, mode="pack", pack="cuisine").json()
    assert b["session_id"] == a["session_id"] and len(b["answers"]) == 2
    c = _start(client, h, mode="pack", pack="flags").json()
    assert c["session_id"] != a["session_id"]
    _play(client, h, a["session_id"], ["x"] * 0)
    for i in range(2, 5):
        client.post(
            f"/api/play/quiz/{a['session_id']}/answer",
            json={"index": i, "choice": "a"},
            headers=h,
        )
    d = _start(client, h, mode="pack", pack="cuisine").json()
    assert d["session_id"] != a["session_id"] and d["answers"] == []


def test_get_session_shows_answers_so_far(client, clock):
    _, h = _login(client)
    sid = _start(client, h, mode="pack", pack="flags").json()["session_id"]
    _play(client, h, sid, ["right", "wrong"])
    d = client.get(f"/api/play/quiz/{sid}", headers=h).json()
    assert [a["correct"] for a in d["answers"]] == [True, False]
    assert d["done"] is False and "summary" not in d
    assert {"index", "choice", "correct_choice", "points", "elapsed_ms"} <= set(
        d["answers"][0]
    )


def test_expiry_finalizes_and_daily_stays_done(client, clock):
    _, h = _login(client)
    sid = _start(client, h, mode="daily").json()["session_id"]
    _play(client, h, sid, ["right", "right"])
    clock["ms"] += 21 * 60 * 1000
    r = client.post(
        f"/api/play/quiz/{sid}/answer", json={"index": 2, "choice": "a"}, headers=h
    )
    assert r.status_code == 410 and r.json()["error_code"] == "session_expired"
    r = client.post(
        f"/api/play/quiz/{sid}/answer", json={"index": 2, "choice": "a"}, headers=h
    )
    assert r.status_code == 410
    d = client.get(f"/api/play/quiz/{sid}", headers=h).json()
    assert d["done"] is True and d["summary"]["correct"] == 2
    assert "xp" not in d["summary"]
    assert _start(client, h, mode="daily").status_code == 409


def test_expired_pack_starts_fresh_and_unanswered_resumes(client, clock):
    _, h = _login(client)
    a = _start(client, h, mode="pack", pack="flags").json()
    clock["ms"] += 30 * 60 * 1000  # nothing answered: nothing revealed, resume
    b = _start(client, h, mode="pack", pack="flags").json()
    assert b["session_id"] == a["session_id"]
    first = _play(client, h, a["session_id"], ["right"])[0].json()
    assert first["points"] == 100  # slow: no speed bonus
    clock["ms"] += 30 * 60 * 1000
    c = _start(client, h, mode="pack", pack="flags").json()
    assert c["session_id"] != a["session_id"]


def test_history(client, clock):
    _, h = _login(client)
    assert client.get("/api/play/history", headers=h).json() == {"sessions": []}
    ids = []
    for _ in range(3):
        sid = _start(client, h, mode="pack", pack="flags").json()["session_id"]
        _play(client, h, sid, ["right"] * 5, clock=clock, step_ms=1000)
        ids.append(sid)
        clock["ms"] += 1000
    _start(client, h, mode="pack", pack="capitals")  # unfinished: not listed
    rows = client.get("/api/play/history?limit=2", headers=h).json()["sessions"]
    assert [r["session_id"] for r in rows] == [ids[2], ids[1]]
    assert set(rows[0]) == {
        "session_id",
        "mode",
        "pack",
        "score",
        "correct",
        "finished_at",
    }
    assert rows[0]["correct"] == 5 and rows[0]["pack"] == "flags"
    assert client.get("/api/play/history?limit=0", headers=h).status_code == 422


def test_history_is_private(client, clock):
    _, h = _login(client)
    _, h2 = _login(client)
    sid = _start(client, h, mode="pack", pack="flags").json()["session_id"]
    _play(client, h, sid, ["right"] * 5)
    assert client.get("/api/play/history", headers=h2).json() == {"sessions": []}


def test_streak_continues_across_days(client, clock):
    _, h = _login(client)
    for day in range(3):
        sid = _start(client, h, mode="daily").json()["session_id"]
        s = _play(client, h, sid, ["wrong"] * 5)[-1].json()["summary"]
        assert s["streak"]["current"] == day + 1
        clock["ms"] += 86_400_000
    d = client.get("/api/play/state", headers=h).json()["daily"]
    assert d["streak"]["current"] == 3 and d["done"] is False


def test_rate_limit_play_bucket(client, monkeypatch):
    _, h = _login(client)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_play", 2)
    rate_limit.limiter._hits.clear()
    codes = [client.get("/api/play/state", headers=h).status_code for _ in range(3)]
    rate_limit.limiter._hits.clear()
    assert codes == [200, 200, 429]
