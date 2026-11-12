"""Phase 5 T4: head-to-head, leaderboards, weekly challenge."""

import uuid
from datetime import UTC, date, datetime

import pytest

from app.core import rate_limit
from app.core.config import settings
from app.db import game_db, social_db, trips_db, user_settings_db, users_db
from app.db.database import get_connection
from app.game import engine as game_engine
from app.game.quiz import engine as qe
from app.game.quiz import service
from app.services import challenge, leaderboard

DAY = 86_400_000


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "play_enabled", True)
    monkeypatch.setattr(settings, "game_enabled", True)


def _ms(y, m, d, hh=12):
    return int(datetime(y, m, d, hh, tzinfo=UTC).timestamp() * 1000)


@pytest.fixture
def clock(monkeypatch):
    t = {"ms": _ms(2030, 3, 6)}  # a Wednesday, ISO 2030-W10
    t["ms"] += (uuid.uuid4().int % 2000) * 7 * DAY  # same weekday, unique week
    monkeypatch.setattr(service, "_now_ms", lambda: t["ms"])
    return t


def _user(client, handle=True, visibility="public", opt_in=False):
    name = f"h2h{uuid.uuid4().hex[:8]}"
    u = users_db.create_user(name, "pw-long-enough-1", is_first_login=False)
    r = client.post(
        "/api/auth/login", json={"username": name, "password": "pw-long-enough-1"}
    )
    u["h"] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    if handle:
        u["handle"] = "p" + uuid.uuid4().hex[:10]
        social_db.save_profile(
            u["id"],
            {
                "handle": u["handle"],
                "visibility": visibility,
                "leaderboard_opt_in": opt_in,
            },
        )
    return u


def _truth(sid):
    with get_connection() as c:
        from app.db import quiz_db

        return [q["answer"] for q in quiz_db.get_session(c, sid)["questions"]]


def _finish(client, u, sid, right=5):
    truth = _truth(sid)
    last = None
    for i, a in enumerate(truth):
        choice = a if i < right else next(o for o in qe.OPTION_IDS if o != a)
        last = client.post(
            f"/api/play/quiz/{sid}/answer",
            json={"index": i, "choice": choice},
            headers=u["h"],
        )
        assert last.status_code == 200, last.text
    return last.json()


def _create(client, a, b, pack="flags"):
    return client.post(
        "/api/play/h2h", json={"handle": b["handle"], "pack": pack}, headers=a["h"]
    )


def _matches(client, u):
    return client.get("/api/play/h2h", headers=u["h"]).json()["matches"]


# ── head-to-head ──────────────────────────────────────────────────────────────


def test_flag_off_404(client, monkeypatch):
    u = _user(client)
    monkeypatch.setattr(settings, "play_enabled", False)
    for method, path in [
        ("get", "/api/play/h2h"),
        ("post", "/api/play/h2h"),
        ("post", "/api/play/h2h/x/accept"),
        ("post", "/api/play/h2h/x/decline"),
        ("get", "/api/play/leaderboard"),
        ("get", "/api/play/challenge"),
    ]:
        r = getattr(client, method)(path, headers=u["h"])
        assert r.status_code == 404 and r.json()["error_code"] == "play_disabled"


def test_hidden_game_403(client, clock):
    u = _user(client)
    user_settings_db.patch_settings(u["id"], {"hide_game": True})
    for method, path in [
        ("get", "/api/play/h2h"),
        ("get", "/api/play/leaderboard"),
        ("get", "/api/play/challenge"),
        ("post", "/api/play/h2h/x/accept"),
    ]:
        r = getattr(client, method)(path, headers=u["h"])
        assert r.status_code == 403 and r.json()["error_code"] == "game_hidden"


def test_lifecycle(client, clock):
    a, b = _user(client), _user(client)
    r = _create(client, a, b)
    assert r.status_code == 200, r.text
    body = r.json()
    mid, sid_a = body["id"], body["session_id"]
    assert len(body["questions"]) == 5
    assert "answer" not in str(body["questions"])
    assert _matches(client, a)[0]["state"] == "waiting_you"
    assert _matches(client, b)[0]["state"] == "waiting_you"
    assert client.get("/api/play/state", headers=b["h"]).json()["open_h2h"] == 1

    clock["ms"] += 1000
    _finish(client, a, sid_a, right=5)
    ma = _matches(client, a)[0]
    assert ma["state"] == "waiting_them" and ma["you"] >= 500 and ma["them"] is None
    assert ma["opponent"] == {"handle": b["handle"]}

    acc = client.post(f"/api/play/h2h/{mid}/accept", headers=b["h"]).json()
    sid_b = acc["session_id"]
    assert sid_b != sid_a
    assert [q["prompt"] for q in acc["questions"]] == [
        q["prompt"] for q in body["questions"]
    ]
    assert _truth(sid_a) == _truth(sid_b)
    # the opponent's score stays hidden until both finish
    assert _matches(client, a)[0]["them"] is None
    clock["ms"] += 1000
    done = _finish(client, b, sid_b, right=2)
    assert done["summary"]["xp"]["awards"][0]["rule"] == "h2h_complete"
    ma, mb = _matches(client, a)[0], _matches(client, b)[0]
    assert ma["state"] == mb["state"] == "done"
    assert ma["winner"] == "you" and mb["winner"] == "them"
    assert ma["them"] == mb["you"] and ma["you"] == mb["them"]
    # both earned the XP; replaying changes nothing
    for u in (a, b):
        with get_connection() as c:
            n = game_db.count_rule(c, u["id"], "h2h_complete")
        assert n == 1
    hist = client.get(f"/api/play/quiz/{sid_a}", headers=a["h"]).json()
    assert hist["summary"]["xp"]["awards"][0]["rule"] == "h2h_complete"
    assert client.get("/api/play/state", headers=b["h"]).json()["open_h2h"] == 0


def test_draw_and_decline_and_expiry(client, clock):
    a, b, c = _user(client), _user(client), _user(client)
    m1 = _create(client, a, b).json()
    assert (
        client.post(f"/api/play/h2h/{m1['id']}/decline", headers=a["h"]).status_code
        == 404
    )
    assert (
        client.post(f"/api/play/h2h/{m1['id']}/decline", headers=b["h"]).status_code
        == 204
    )
    assert _matches(client, a)[0]["state"] == "declined"
    r = client.post(f"/api/play/h2h/{m1['id']}/accept", headers=b["h"])
    assert r.status_code == 409 and r.json()["error_code"] == "invalid_state"

    m2 = _create(client, a, c).json()
    clock["ms"] += 49 * 3600 * 1000
    assert {m["state"] for m in _matches(client, a) if m["id"] == m2["id"]} == {
        "expired"
    }
    r = client.post(f"/api/play/h2h/{m2['id']}/accept", headers=c["h"])
    assert r.status_code == 410 and r.json()["error_code"] == "match_expired"


def test_tie_is_draw(client, clock):
    a, b = _user(client), _user(client)
    m = _create(client, a, b).json()
    acc = client.post(f"/api/play/h2h/{m['id']}/accept", headers=b["h"]).json()
    _finish(client, a, m["session_id"], right=0)
    _finish(client, b, acc["session_id"], right=0)
    assert _matches(client, a)[0]["winner"] == "draw"


def test_accept_is_resumable_and_only_opponent(client, clock):
    a, b, c = _user(client), _user(client), _user(client)
    m = _create(client, a, b).json()
    for u in (a, c):  # creator and strangers: not found
        assert (
            client.post(f"/api/play/h2h/{m['id']}/accept", headers=u["h"]).status_code
            == 404
        )
    s1 = client.post(f"/api/play/h2h/{m['id']}/accept", headers=b["h"]).json()
    s2 = client.post(f"/api/play/h2h/{m['id']}/accept", headers=b["h"]).json()
    assert s1["session_id"] == s2["session_id"] and s2["resumed"] is True


def test_create_validation(client, clock):
    a = _user(client)
    priv = _user(client, visibility="private")
    nop = _user(client, handle=False)
    pub = _user(client)
    hid = _user(client)
    user_settings_db.patch_settings(hid["id"], {"hide_game": True})
    blk = _user(client)
    social_db.block(blk["id"], a["id"])
    for target in (priv, hid, blk):
        assert _create(client, a, target).status_code == 404
    r = client.post(
        "/api/play/h2h", json={"handle": "nobody_x", "pack": "flags"}, headers=a["h"]
    )
    assert r.status_code == 404
    assert nop.get("handle") is None
    r = _create(client, a, a)
    assert r.status_code == 422 and r.json()["error_code"] == "cannot_challenge_self"
    r = client.post(
        "/api/play/h2h", json={"handle": pub["handle"], "pack": "x"}, headers=a["h"]
    )
    assert r.status_code == 422 and r.json()["error_code"] == "invalid_pack"
    r = client.post(
        "/api/play/h2h",
        json={"handle": "@" + pub["handle"].upper(), "pack": "flags"},
        headers=a["h"],
    )
    assert r.status_code == 200  # @ and case tolerated


def test_block_after_create_hides_match(client, clock):
    a, b = _user(client), _user(client)
    m = _create(client, a, b).json()
    social_db.block(b["id"], a["id"])
    assert _matches(client, a) == [] and _matches(client, b) == []
    assert (
        client.post(f"/api/play/h2h/{m['id']}/accept", headers=b["h"]).status_code
        == 404
    )


def test_open_limit_and_daily_limit(client, clock):
    a = _user(client)
    others = [_user(client) for _ in range(6)]
    for o in others[:5]:
        assert _create(client, a, o).status_code == 200
    r = _create(client, a, others[5])
    assert r.status_code == 422 and r.json()["error_code"] == "limit_reached"
    # a declined match frees a slot
    mid = _matches(client, others[0])[0]["id"]
    client.post(f"/api/play/h2h/{mid}/decline", headers=others[0]["h"])
    assert _create(client, a, others[5]).status_code == 200

    # daily cap 10: finish matches so "open" never trips
    b, c = _user(client), _user(client)
    for _ in range(4):
        m = _create(client, b, c).json()
        acc = client.post(f"/api/play/h2h/{m['id']}/accept", headers=c["h"]).json()
        _finish(client, b, m["session_id"])
        _finish(client, c, acc["session_id"])
    for _ in range(6):
        r = _create(client, b, c)
        assert r.status_code == 200
        client.post(f"/api/play/h2h/{r.json()['id']}/decline", headers=c["h"])
    r = _create(client, b, c)
    assert r.status_code == 422 and r.json()["error_code"] == "limit_reached"
    # next UTC day resets it
    clock["ms"] += DAY
    assert _create(client, b, c).status_code == 200


def test_h2h_xp_cap_three_per_day(client, clock):
    a, b = _user(client), _user(client)
    for _ in range(4):
        m = _create(client, a, b).json()
        acc = client.post(f"/api/play/h2h/{m['id']}/accept", headers=b["h"]).json()
        _finish(client, a, m["session_id"])
        _finish(client, b, acc["session_id"])
    with get_connection() as c:
        assert game_db.count_rule(c, a["id"], "h2h_complete") == 3


def test_rate_limit_bucket(client, monkeypatch):
    u = _user(client)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_play", 2)
    rate_limit.limiter._hits.clear()
    codes = [client.get("/api/play/h2h", headers=u["h"]).status_code for _ in range(3)]
    rate_limit.limiter._hits.clear()
    assert codes == [200, 200, 429]


def test_account_delete_covers_matches():
    from app.services import account_data

    assert "h2h_matches" in account_data.KEYED_TABLES


# ── leaderboards ──────────────────────────────────────────────────────────────


def _score(client, u, pack="flags", right=5):
    s = client.post(
        "/api/play/quiz", json={"mode": "pack", "pack": pack}, headers=u["h"]
    ).json()
    _finish(client, u, s["session_id"], right=right)


def _board(client, u, **q):
    r = client.get("/api/play/leaderboard", params=q, headers=u["h"])
    assert r.status_code == 200, r.text
    return r.json()


def test_global_board_is_opt_in_handles_only(client, clock):
    a = _user(client, opt_in=True)
    b = _user(client, opt_in=True)
    c = _user(client, opt_in=False)
    priv = _user(client, visibility="private", opt_in=True)
    hid = _user(client, opt_in=True)
    user_settings_db.patch_settings(hid["id"], {"hide_game": True})
    _score(client, a)
    _score(client, b, right=2)
    _score(client, c)
    _score(client, priv)
    with get_connection() as conn:  # a hidden user's sessions still exist
        from app.db import quiz_db

        quiz_db.create_session(
            conn, "hid1", hid["id"], "pack", "flags", "d", "s", [], clock["ms"]
        )
        quiz_db.finish(conn, "hid1", 900, 5, clock["ms"])
    out = _board(client, a)
    assert out["week"] == challenge.iso_week(
        datetime.fromtimestamp(clock["ms"] / 1000, UTC).date()
    )
    handles = [r["handle"] for r in out["rows"]]
    assert handles == [a["handle"], b["handle"]]
    assert [r["rank"] for r in out["rows"]] == [1, 2]
    assert out["rows"][0]["you"] is True
    text = str(out)
    assert a["username"] not in text and "level" not in out["rows"][0]
    assert out["you"] == {"rank": 1, "score": out["rows"][0]["score"], "opted_in": True}
    # not opted in: no rank, own score still reported
    mine = _board(client, c)
    assert mine["you"]["rank"] is None and mine["you"]["opted_in"] is False
    assert mine["you"]["score"] > 0
    assert hid["handle"] not in str(out)
    # hidden-game user never sees the board
    assert client.get("/api/play/leaderboard", headers=hid["h"]).status_code == 403


def test_board_level_only_when_opted_in(client, clock):
    a = _user(client, opt_in=True)
    social_db.save_profile(a["id"], {"show_level": True})
    _score(client, a)
    row = _board(client, a)["rows"][0]
    assert row["level"] >= 1


def test_board_blocks_and_no_profile(client, clock):
    a = _user(client, opt_in=True)
    b = _user(client, opt_in=True)
    nop = _user(client, handle=False)
    _score(client, a)
    _score(client, b)
    _score(client, nop)
    assert {r["handle"] for r in _board(client, a)["rows"]} == {
        a["handle"],
        b["handle"],
    }
    social_db.block(a["id"], b["id"])
    assert [r["handle"] for r in _board(client, a)["rows"]] == [a["handle"]]
    assert [r["handle"] for r in _board(client, b)["rows"]] == [b["handle"]]
    assert _board(client, nop)["you"] is None


def test_friends_scope(client, clock):
    me = _user(client)  # not opted in: still on own friends board
    f1 = _user(client, opt_in=True)
    f2 = _user(client, opt_in=False)  # followed but not opted in
    pend = _user(client, opt_in=True)  # request not approved
    stranger = _user(client, opt_in=True)
    social_db.set_follow(me["id"], f1["id"], "following")
    social_db.set_follow(me["id"], f2["id"], "following")
    social_db.set_follow(me["id"], pend["id"], "pending")
    for u in (me, f1, f2, pend, stranger):
        _score(client, u)
    rows = _board(client, me, scope="friends")["rows"]
    assert {r["handle"] for r in rows} == {me["handle"], f1["handle"]}
    assert {r["handle"] for r in _board(client, me)["rows"]} == {
        f1["handle"], pend["handle"], stranger["handle"],
    }  # fmt: skip
    # followed users hiding in private profiles stay off
    social_db.save_profile(f1["id"], {"visibility": "private"})
    assert {r["handle"] for r in _board(client, me, scope="friends")["rows"]} == {
        me["handle"]
    }


def test_week_boundaries(client, monkeypatch):
    a = _user(client, opt_in=True)
    t = {"ms": _ms(2031, 5, 4, 23)}  # Sunday 2031-05-04 (W18), end of the week
    monkeypatch.setattr(service, "_now_ms", lambda: t["ms"])
    _score(client, a)
    sun_score = _board(client, a)["rows"][0]["score"]
    t["ms"] = _ms(2031, 5, 5, 0)  # Monday 00:00 UTC: new week
    nxt = _board(client, a)
    assert nxt["rows"] == [] and nxt["week"].endswith("W19")
    prev = _board(client, a, week="previous")
    assert prev["week"].endswith("W18") and prev["rows"][0]["score"] == sun_score
    _score(client, a, pack="capitals", right=1)
    cur = _board(client, a)["rows"][0]["score"]
    assert 0 < cur < sun_score  # only this week's points


def test_board_bad_params_422(client, clock):
    a = _user(client)
    r = client.get("/api/play/leaderboard", params={"scope": "world"}, headers=a["h"])
    assert r.status_code == 422


def test_week_helpers():
    assert challenge.iso_week(date(2026, 12, 31)) == "2026-W53"
    assert challenge.iso_week(date(2027, 1, 3)) == "2026-W53"
    assert challenge.iso_week(date(2027, 1, 4)) == "2027-W01"
    s, e = challenge.week_bounds_ms(date(2026, 11, 12))
    assert s == _ms(2026, 11, 9, 0) and e - s == 7 * DAY


# ── weekly challenge ──────────────────────────────────────────────────────────


def _trip(u, dest, start, end=None):
    trips_db.create_trip(u["username"], f"Trip {dest}", dest, start, end)


def test_challenge_featured_without_trips(client, clock):
    u = _user(client)
    ch = client.get("/api/play/challenge", headers=u["h"]).json()
    assert ch["kind"] == "featured" and "country" not in ch and ch["done"] is False
    assert ch["id"].split(":")[1] in qe.PACKS
    assert client.get("/api/play/state", headers=u["h"]).json()["challenge"] == ch


def test_challenge_featured_is_deterministic_and_rotates():
    p = [
        challenge.featured_pack(
            date(2027, 1, 4) + (date(2027, 1, 11) - date(2027, 1, 4)) * i
        )
        for i in range(8)
    ]
    assert set(p) == set(qe.PACKS)
    assert challenge.featured_pack(date(2027, 1, 4)) == challenge.featured_pack(
        date(2027, 1, 10)
    )


def test_challenge_uses_next_trip_country(client, clock):
    u = _user(client)
    today = datetime.fromtimestamp(clock["ms"] / 1000, UTC).date()
    _trip(u, "Rome, Italy", date(today.year - 1, 1, 1).isoformat())  # past: ignored
    _trip(u, "Tokyo, Japan", date(today.year + 1, 6, 1).isoformat())
    _trip(u, "Paris, France", date(today.year + 2, 6, 1).isoformat())
    ch = client.get("/api/play/challenge", headers=u["h"]).json()
    assert ch["kind"] == "destination" and ch["country"] == "JP"
    assert ch["id"].endswith(":JP")
    s = client.post("/api/play/quiz", json={"mode": "challenge"}, headers=u["h"]).json()
    assert s["mode"] == "challenge" and len(s["questions"]) == 5
    qs = " ".join(str(q["prompt"]) for q in s["questions"])
    assert "Sushi" in qs or "Japan" in qs or "Tokyo" in qs or "🇯🇵" in qs


def test_challenge_skips_country_the_bank_lacks(client, clock):
    u = _user(client)
    today = datetime.fromtimestamp(clock["ms"] / 1000, UTC).date()
    _trip(u, "Reykjavik, Iceland", date(today.year + 1, 1, 1).isoformat())
    assert qe.country_entries("IS") < 3 if "IS" in qe.load_bank()["by_code"] else True
    _trip(u, "Rome, Italy", date(today.year + 1, 2, 1).isoformat())
    ch = client.get("/api/play/challenge", headers=u["h"]).json()
    assert ch["country"] == "IT"
    u2 = _user(client)
    _trip(u2, "Reykjavik, Iceland", date(today.year + 1, 1, 1).isoformat())
    assert (
        client.get("/api/play/challenge", headers=u2["h"]).json()["kind"] == "featured"
    )


def test_country_questions_are_deterministic_and_about_the_country():
    a = qe.build_country_questions("JP", "s1")
    assert a == qe.build_country_questions("JP", "s1")
    assert len(a) == 5 and [q["index"] for q in a] == list(range(5))
    for q in a:
        assert len(q["options"]) == 4 and q["answer"] in qe.OPTION_IDS


def test_challenge_lifecycle_xp_once_per_week(client, clock):
    u = _user(client)
    first = client.post(
        "/api/play/quiz", json={"mode": "challenge"}, headers=u["h"]
    ).json()
    again = client.post(
        "/api/play/quiz", json={"mode": "challenge"}, headers=u["h"]
    ).json()
    assert again["session_id"] == first["session_id"] and again["resumed"] is True
    done = _finish(client, u, first["session_id"])
    rules = [a["rule"] for a in done["summary"]["xp"]["awards"]]
    assert "challenge_complete" in rules and "quiz_perfect" in rules
    r = client.post("/api/play/quiz", json={"mode": "challenge"}, headers=u["h"])
    assert r.status_code == 409 and r.json()["error_code"] == "already_done"
    assert client.get("/api/play/challenge", headers=u["h"]).json()["done"] is True
    # a trip added mid-week changes the id but the week stays done
    today = datetime.fromtimestamp(clock["ms"] / 1000, UTC).date()
    _trip(u, "Tokyo, Japan", date(today.year + 1, 6, 1).isoformat())
    assert (
        client.post(
            "/api/play/quiz", json={"mode": "challenge"}, headers=u["h"]
        ).status_code
        == 409
    )
    with get_connection() as c:
        assert game_db.count_rule(c, u["id"], "challenge_complete") == 1
    # next week: available again
    clock["ms"] += 7 * DAY
    assert client.get("/api/play/challenge", headers=u["h"]).json()["done"] is False
    assert (
        client.post(
            "/api/play/quiz", json={"mode": "challenge"}, headers=u["h"]
        ).status_code
        == 200
    )


def test_challenge_same_questions_for_same_id(client, clock):
    a, b = _user(client), _user(client)
    qa = client.post(
        "/api/play/quiz", json={"mode": "challenge"}, headers=a["h"]
    ).json()
    qb = client.post(
        "/api/play/quiz", json={"mode": "challenge"}, headers=b["h"]
    ).json()
    assert [q["prompt"] for q in qa["questions"]] == [
        q["prompt"] for q in qb["questions"]
    ]


def test_rules_and_badges_in_catalog():
    cat = game_engine.catalog()
    text = str(cat)
    for k in ("h2h_complete", "challenge_complete", "h2h_rival", "challenge_explorer"):
        assert k in text
    r = game_engine.get_rules().rules
    assert r["h2h_complete"].points == 10 and r["h2h_complete"].daily_cap == 3
    assert r["challenge_complete"].points == 50


def test_leaderboard_module_has_no_network():
    import inspect

    src = inspect.getsource(leaderboard) + inspect.getsource(challenge)
    for bad in ("httpx", "requests", "llm", "anthropic"):
        assert bad not in src


def test_create_requires_own_handle_and_no_restriction(client, clock):
    from app.db import social_ideas_db

    a, b = _user(client), _user(client)
    nop = _user(client, handle=False)
    r = _create(client, nop, b)
    assert r.status_code == 409 and r.json()["error_code"] == "profile_required"
    social_ideas_db.restrict(a["id"], 1)
    r = _create(client, a, b)
    assert r.status_code == 403 and r.json()["error_code"] == "restricted"
    social_ideas_db.lift(a["id"])
    assert _create(client, a, b).status_code == 200


def test_board_only_verified_users(client, clock):
    a = _user(client, opt_in=True)
    b = _user(client, opt_in=True)
    _score(client, a)
    _score(client, b)
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET signup_method = 'self', verified_at = NULL WHERE id = ?",
            (b["id"],),
        )
    assert [r["handle"] for r in _board(client, a)["rows"]] == [a["handle"]]
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET verified_at = '2030-01-01T00:00:00Z' WHERE id = ?",
            (b["id"],),
        )
    assert len(_board(client, a)["rows"]) == 2


def test_weekly_pack_cap_and_ranking_ties(client, clock):
    from app.db import quiz_db

    a = _user(client, opt_in=True)
    b = _user(client, opt_in=True)
    with get_connection() as conn:
        for i in range(25):
            sid = f"cap{a['handle']}{i}"
            quiz_db.create_session(
                conn, sid, a["id"], "pack", "flags", "d", "s", [], clock["ms"]
            )
            quiz_db.finish(conn, sid, 100, 1, clock["ms"] + i)
        quiz_db.create_session(
            conn, "capb", b["id"], "pack", "flags", "d", "s", [], clock["ms"]
        )
        quiz_db.finish(conn, "capb", 2000, 1, clock["ms"])
    out = _board(client, a)
    assert [r["score"] for r in out["rows"]] == [2000, 2000]
    assert [r["rank"] for r in out["rows"]] == [1, 1]
