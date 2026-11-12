"""Social ideas, comments, moderation (Phase 5 T2)."""

import json
import uuid

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import game_db, plans_db, social_db, social_ideas_db, users_db
from app.db.users_db import create_user
from app.game import engine
from app.services import feed_rank, idea_snapshot, moderation

_PW = "correct-horse-battery"
HOSTILE = "<img src=x onerror=alert(1)>"


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")


def _user(**kw):
    name = f"idea_{uuid.uuid4().hex[:10]}"
    u = create_user(
        name, _PW, email=f"{name}@example.com", display_name="Real Name", **kw
    )
    u["h"] = {"Authorization": f"Bearer {create_access_token({'sub': name})}"}
    return u


def _mk(client, visibility="public", **kw):
    u = _user(**kw)
    handle = "h" + uuid.uuid4().hex[:10]
    r = client.put(
        "/api/social/profile",
        json={"handle": handle, "visibility": visibility},
        headers=u["h"],
    )
    assert r.status_code == 200, r.text
    u["handle"] = handle
    return u


def _plan(u, **over):
    search = {
        "origin": "Boston",
        "destination": "Lisbon",
        "departure_date": "2026-05-01",
        "return_date": "2026-05-06",
        "interests": ["Food", "history"],
        "nationality": "American",
    }
    sel = {
        "activities": [
            {
                "name": "Pastel tour",
                "price": 40,
                "url": "https://x.test/?date=2026-05-02",
            }
        ],
        "hotels": [{"name": "Casa Azul", "checkin": "2026-05-01"}],
        "itinerary_notes": {"0": "call mum on 555-1234"},
    }
    search.update(over.pop("search", {}))
    sel.update(over.pop("sel", {}))
    return plans_db.save_plan(u["username"], "My trip", search, sel)


def _post(client, u, plan=None, **over):
    plan = plan or _plan(u)
    body = {
        "plan_id": plan["id"],
        "kind": "plan",
        "title": "Lisbon bites",
        "caption": "Great",
    }
    body.update(over)
    return client.post("/api/social/ideas", json=body, headers=u["h"])


def _idea(client, u, **over):
    r = _post(client, u, **over)
    assert r.status_code == 200, r.text
    return r.json()


def _xp(user_id):
    with social_db.get_connection() as c:
        return game_db.total_xp(c, user_id)


# ── flag, auth, guards ────────────────────────────────────────────────────────


def test_flag_off_404(client, monkeypatch):
    u = _mk(client)
    monkeypatch.setattr(settings, "social_enabled", False)
    for m, p in [
        ("get", "/api/social/feed"),
        ("post", "/api/social/ideas"),
        ("get", "/api/social/ideas/1"),
        ("post", "/api/social/reports"),
        ("get", "/api/admin/social/queue"),
    ]:
        r = getattr(client, m)(p, headers=u["h"])
        assert r.status_code == 404 and r.json()["error_code"] == "social_disabled"


def test_requires_sign_in(client):
    assert client.get("/api/social/feed").status_code in (401, 403)


def test_publish_guards(client):
    nop = _user()
    assert _post(client, nop, _plan(nop)).json()["error_code"] == "profile_required"
    priv = _mk(client, "private")
    r = _post(client, priv)
    assert r.status_code == 403 and r.json()["error_code"] == "profile_required"
    unv = _mk(client, signup_method="email")
    r = _post(client, unv)
    assert r.status_code == 403 and r.json()["error_code"] == "email_unverified"
    a, b = _mk(client), _mk(client)
    r = client.post(
        "/api/social/ideas",
        json={"plan_id": _plan(b)["id"], "kind": "plan", "title": "x"},
        headers=a["h"],
    )
    assert r.status_code == 404 and r.json()["error_code"] == "plan_not_found"


# ── moderation ────────────────────────────────────────────────────────────────


def test_filter_outcomes():
    assert moderation.check("Lovely pastries") == "allow"
    assert moderation.check("kill yourself") == "reject"
    assert moderation.check("k1ll y0urself") == "reject"
    assert moderation.check("best casino deals") == "review"
    assert moderation.check("see http://x.test") == "review"
    assert moderation.check("mail me a@b.co") == "review"
    assert moderation.verdict("fine", "scam") == "review"
    assert moderation.verdict("fine", "kys") == "reject"
    assert moderation.classify("anything") is None


def test_hostile_text_stored_plain(client):
    u = _mk(client)
    r = _post(client, u, title=HOSTILE + "\x00\x07 trip", caption="a‮b")
    assert r.status_code == 200
    i = r.json()
    assert "\x00" not in i["title"] and "‮" not in i["caption"]
    assert i["title"].startswith(HOSTILE)  # kept as literal text, never interpreted
    assert r.headers["content-type"].startswith("application/json")
    assert json.loads(r.text)["title"] == i["title"]


def test_reject_and_held(client):
    a, b = _mk(client), _mk(client)
    r = _post(client, a, title="kill yourself")
    assert r.status_code == 422 and r.json()["error_code"] == "content_rejected"
    held = _idea(client, a, title="Join my telegram")
    assert held["status"] == "held"
    # visible to the author and admins only
    assert (
        client.get(f"/api/social/ideas/{held['id']}", headers=a["h"]).status_code == 200
    )
    assert (
        client.get(f"/api/social/ideas/{held['id']}", headers=b["h"]).status_code == 404
    )
    for scope in ("new", "for_you"):
        ids = [
            i["id"]
            for i in client.get(
                f"/api/social/feed?scope={scope}", headers=b["h"]
            ).json()["ideas"]
        ]
        assert held["id"] not in ids
    adm = _user(is_admin=True)
    assert (
        client.get(f"/api/social/ideas/{held['id']}", headers=adm["h"]).status_code
        == 200
    )


def test_idempotent_update(client):
    u = _mk(client)
    p = _plan(u)
    first = _idea(client, u, plan=p)
    second = _idea(client, u, plan=p, title="Renamed")
    assert first["id"] == second["id"] and second["title"] == "Renamed"
    assert social_db.used_today(u["id"], "idea") == 1


def test_idea_limit(client):
    u = _mk(client)
    for _ in range(5):
        assert _post(client, u).status_code == 200
    r = _post(client, u)
    assert r.status_code == 422 and r.json()["error_code"] == "limit_reached"


# ── snapshot ──────────────────────────────────────────────────────────────────


def test_snapshot_is_private_by_construction(client):
    u = _mk(client)
    i = _idea(client, u)
    blob = json.dumps(i["snapshot"])
    for bad in (
        "2026-05",
        "Boston",
        "Real Name",
        "example.com",
        u["username"],
        "555-1234",
        "price",
        "http",
        "40",
    ):
        assert bad not in blob, bad
    assert i["snapshot"]["destinations"] == ["Lisbon"]
    assert i["snapshot"]["days"] == 6
    assert i["snapshot"]["items"]["activities"] == [{"name": "Pastel tour"}]
    assert i["snapshot"]["interests"] == ["food", "history"]


def test_snapshot_drops_origin_destination_and_dated_names():
    plan = {
        "search_data": {"origin": "Boston", "destinations": ["Boston", "Porto"]},
        "selections": {"activities": [{"name": "Tour 2026-05-02"}, {"name": "Wine"}]},
    }
    s = idea_snapshot.build(plan, "plan")
    assert s["destinations"] == ["Porto"]
    assert s["items"]["activities"] == [{"name": "Wine"}]


# ── feed ──────────────────────────────────────────────────────────────────────


def _feed(client, u, scope="new"):
    r = client.get(f"/api/social/feed?scope={scope}&limit=30", headers=u["h"])
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["ideas"]]


def test_feed_visibility_matrix(client):
    pub, fol, viewer = _mk(client, "public"), _mk(client, "followers"), _mk(client)
    ip, ifo = _idea(client, pub)["id"], _idea(client, fol)["id"]
    ids = _feed(client, viewer)
    assert ip in ids and ifo not in ids
    assert (
        client.get(f"/api/social/ideas/{ifo}", headers=viewer["h"]).status_code == 404
    )
    client.put(f"/api/social/follow/{fol['handle']}", headers=viewer["h"])
    assert ifo not in _feed(client, viewer)  # still pending
    client.post(
        f"/api/social/follow-requests/{viewer['handle']}/accept", headers=fol["h"]
    )
    assert ifo in _feed(client, viewer) and ifo in _feed(client, viewer, "following")
    assert ip not in _feed(client, viewer, "following")
    # author goes private: gone for everyone but their own profile list
    client.put("/api/social/profile", json={"visibility": "private"}, headers=pub["h"])
    assert ip not in _feed(client, viewer)
    assert client.get(f"/api/social/ideas/{ip}", headers=viewer["h"]).status_code == 404
    mine = client.get(f"/api/social/profile/{pub['handle']}/ideas", headers=pub["h"])
    assert [i["id"] for i in mine.json()["ideas"]] == [ip]


def test_feed_blocked_pairs_both_ways(client):
    a, b = _mk(client), _mk(client)
    ia, ib = _idea(client, a)["id"], _idea(client, b)["id"]
    client.put(f"/api/social/block/{b['handle']}", headers=a["h"])
    for scope in ("new", "for_you"):
        assert ib not in _feed(client, a, scope)
        assert ia not in _feed(client, b, scope)
    assert client.get(f"/api/social/ideas/{ib}", headers=a["h"]).status_code == 404
    assert client.put(f"/api/social/ideas/{ia}/like", headers=b["h"]).status_code == 404
    assert (
        client.post(
            f"/api/social/ideas/{ia}/comments", json={"text": "hi"}, headers=b["h"]
        ).status_code
        == 404
    )


def test_feed_paging_and_for_you_ranking(client):
    a, v = _mk(client), _mk(client)
    ids = [_idea(client, a)["id"] for _ in range(3)]
    r = client.get("/api/social/feed?scope=new&limit=2", headers=v["h"]).json()
    assert len(r["ideas"]) == 2 and r["next"]
    r2 = client.get(
        f"/api/social/feed?scope=new&limit=2&cursor={r['next']}", headers=v["h"]
    ).json()
    assert {i["id"] for i in r["ideas"] + r2["ideas"]} >= set(ids)
    assert (
        client.get("/api/social/feed?cursor=zz", headers=v["h"]).json()["error_code"]
        == "invalid_cursor"
    )
    # engagement lifts an older idea in for_you
    old = ids[0]
    for _ in range(3):
        x = _mk(client)
        client.put(f"/api/social/ideas/{old}/like", headers=x["h"])
        client.post(f"/api/social/ideas/{old}/save", headers=x["h"])
    rank = _feed(client, v, "for_you")
    assert rank.index(old) < rank.index(ids[1])


def test_for_you_taste_match(client):
    a, v = _mk(client), _mk(client)
    x = _idea(client, a, plan=_plan(a, search={"interests": ["surfing"]}))["id"]
    y = _idea(client, a, plan=_plan(a, search={"interests": ["food"]}))["id"]
    sql, params = feed_rank.score_sql(["Food"])
    assert params and "instr" in sql
    from app.db import preferences_db

    prefs = preferences_db.get_preferences(v["username"])
    prefs["interests"] = ["surfing"]
    prefs.pop("username", None)
    preferences_db.save_preferences(v["username"], prefs)
    rank = _feed(client, v, "for_you")
    assert rank.index(x) < rank.index(y)  # newer y is outranked by taste


# ── likes, saves, remix ───────────────────────────────────────────────────────


def test_like_idempotent_and_counts(client):
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)["id"]
    for _ in range(2):
        assert (
            client.put(f"/api/social/ideas/{i}/like", headers=b["h"]).status_code == 204
        )
    g = client.get(f"/api/social/ideas/{i}", headers=b["h"]).json()
    assert g["likes"] == 1 and g["liked"] is True and g["mine"] is False
    client.delete(f"/api/social/ideas/{i}/like", headers=b["h"])
    assert client.get(f"/api/social/ideas/{i}", headers=b["h"]).json()["likes"] == 0
    assert _xp(a["id"]) == 0  # no XP for likes


def test_save_remixes_and_awards_once(client, monkeypatch):
    monkeypatch.setattr(settings, "game_enabled", True)
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)["id"]
    r = client.post(f"/api/social/ideas/{i}/save", headers=b["h"])
    assert r.status_code == 200
    plan = plans_db.get_plan(r.json()["plan_id"])
    assert plan["username"] == b["username"] and plan["name"] == "Lisbon bites"
    assert plan["selections"]["activities"] == [{"name": "Pastel tour"}]
    assert plan["search_data"]["destination"] == "Lisbon"
    assert (
        "departure_date" not in plan["search_data"]
        and "origin" not in plan["search_data"]
    )
    assert _xp(a["id"]) == 10
    again = client.post(f"/api/social/ideas/{i}/save", headers=b["h"]).json()
    assert again["plan_id"] == plan["id"] and _xp(a["id"]) == 10
    client.delete(f"/api/social/ideas/{i}/save", headers=b["h"])
    client.post(f"/api/social/ideas/{i}/save", headers=b["h"])  # new plan, same XP
    assert _xp(a["id"]) == 10
    # self save: copy but no XP
    client.post(f"/api/social/ideas/{i}/save", headers=a["h"])
    assert _xp(a["id"]) == 10


def test_unverified_saver_gives_no_xp(client, monkeypatch):
    monkeypatch.setattr(settings, "game_enabled", True)
    a, b = _mk(client), _mk(client, signup_method="email")
    i = _idea(client, a)["id"]
    assert client.post(f"/api/social/ideas/{i}/save", headers=b["h"]).status_code == 200
    assert _xp(a["id"]) == 0


def test_delete_idea_author_only(client):
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)["id"]
    assert client.delete(f"/api/social/ideas/{i}", headers=b["h"]).status_code == 404
    assert client.delete(f"/api/social/ideas/{i}", headers=a["h"]).status_code == 204
    assert client.get(f"/api/social/ideas/{i}", headers=a["h"]).status_code == 404


# ── comments ──────────────────────────────────────────────────────────────────


def test_comments_flow(client, monkeypatch):
    monkeypatch.setattr(settings, "game_enabled", True)
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)["id"]
    c = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": HOSTILE}, headers=b["h"]
    )
    assert c.status_code == 200 and c.json()["text"] == HOSTILE
    cid = c.json()["id"]
    assert client.get(f"/api/social/ideas/{i}", headers=a["h"]).json()["comments"] == 1
    lst = client.get(f"/api/social/ideas/{i}/comments", headers=a["h"]).json()
    assert lst["comments"][0]["author"] == {"handle": b["handle"]}
    assert lst["comments"][0]["mine"] is False
    # helpful: idea author only, XP once to the commenter
    assert (
        client.put(f"/api/social/comments/{cid}/helpful", headers=b["h"]).status_code
        == 404
    )
    for _ in range(2):
        assert (
            client.put(
                f"/api/social/comments/{cid}/helpful", headers=a["h"]
            ).status_code
            == 204
        )
    assert _xp(b["id"]) == 5
    assert client.get(f"/api/social/ideas/{i}/comments", headers=b["h"]).json()[
        "comments"
    ][0]["helpful"]
    client.delete(f"/api/social/comments/{cid}/helpful", headers=a["h"])
    client.put(f"/api/social/comments/{cid}/helpful", headers=a["h"])
    assert _xp(b["id"]) == 5
    # delete: commenter or idea author, not a bystander
    x = _mk(client)
    assert (
        client.delete(f"/api/social/comments/{cid}", headers=x["h"]).status_code == 404
    )
    assert (
        client.delete(f"/api/social/comments/{cid}", headers=a["h"]).status_code == 204
    )


def test_comment_filter_and_limits(client):
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)["id"]
    r = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "kys"}, headers=b["h"]
    )
    assert r.status_code == 422 and r.json()["error_code"] == "content_rejected"
    held = client.post(
        f"/api/social/ideas/{i}/comments",
        json={"text": "see www.x.test"},
        headers=b["h"],
    ).json()
    assert held["status"] == "held"
    assert (
        client.get(f"/api/social/ideas/{i}/comments", headers=a["h"]).json()["comments"]
        == []
    )
    assert (
        len(
            client.get(f"/api/social/ideas/{i}/comments", headers=b["h"]).json()[
                "comments"
            ]
        )
        == 1
    )
    assert client.get(f"/api/social/ideas/{i}", headers=a["h"]).json()["comments"] == 0
    r = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "  "}, headers=b["h"]
    )
    assert r.status_code == 422
    for _ in range(29):
        assert (
            client.post(
                f"/api/social/ideas/{i}/comments", json={"text": "nice"}, headers=b["h"]
            ).status_code
            == 200
        )
    r = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "nice"}, headers=b["h"]
    )
    assert r.status_code == 422 and r.json()["error_code"] == "limit_reached"


def test_unverified_cannot_comment(client):
    a, b = _mk(client), _mk(client, signup_method="email")
    i = _idea(client, a)["id"]
    r = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "hi"}, headers=b["h"]
    )
    assert r.status_code == 403 and r.json()["error_code"] == "email_unverified"


# ── reports and admin ─────────────────────────────────────────────────────────


def _report(client, u, target, tid, reason="spam"):
    return client.post(
        "/api/social/reports",
        json={"target": target, "id": str(tid), "reason": reason},
        headers=u["h"],
    )


def test_auto_hide_at_three_verified_reporters(client):
    a = _mk(client)
    i = _idea(client, a)["id"]
    unv = _mk(client, signup_method="email")
    assert _report(client, unv, "idea", i).status_code == 204  # accepted, not counted
    assert _report(client, a, "idea", i).status_code == 204  # own content, not counted
    reporters = [_mk(client) for _ in range(3)]
    for n, r in enumerate(reporters):
        assert _report(client, r, "idea", i).status_code == 204
        if n == 0:  # duplicate is a no-op
            assert _report(client, r, "idea", i).status_code == 204
        status = client.get(f"/api/social/ideas/{i}", headers=a["h"]).json()["status"]
        assert status == ("hidden" if n == 2 else "published")
    viewer = _mk(client)
    assert i not in _feed(client, viewer)
    assert client.get(f"/api/social/ideas/{i}", headers=viewer["h"]).status_code == 404


def test_report_comment_and_profile_and_errors(client):
    a, b = _mk(client), _mk(client)
    i = _idea(client, a)["id"]
    cid = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "meh"}, headers=b["h"]
    ).json()["id"]
    xs = [_mk(client) for _ in range(3)]
    for x in xs:
        assert _report(client, x, "comment", cid, "abuse").status_code == 204
    assert (
        client.get(f"/api/social/ideas/{i}/comments", headers=a["h"]).json()["comments"]
        == []
    )
    assert _report(client, a, "profile", b["handle"]).status_code == 204
    assert _report(client, a, "idea", 999999).status_code == 404
    assert _report(client, a, "idea", "abc").status_code == 404
    assert _report(client, a, "profile", "nobody_here").status_code == 404
    bad = client.post(
        "/api/social/reports",
        json={"target": "idea", "id": "1", "reason": "nope"},
        headers=a["h"],
    )
    assert bad.status_code == 422


def test_report_daily_cap(client):
    a = _mk(client)
    ideas = [_idea(client, _mk(client))["id"] for _ in range(1)]
    for _ in range(20):
        social_db.consume_daily(a["id"], "report", 20)
    assert _report(client, a, "idea", ideas[0]).json()["error_code"] == "limit_reached"


def test_admin_queue_decide_restrict(client):
    adm = _user(is_admin=True)
    a, b = _mk(client), _mk(client)
    held = _idea(client, a, title="free casino")["id"]
    pub = _idea(client, a, plan=_plan(a))["id"]
    for r in [_mk(client) for _ in range(3)]:
        _report(client, r, "idea", pub, "spam")
    assert client.get("/api/admin/social/queue", headers=a["h"]).status_code == 403
    q = client.get("/api/admin/social/queue?status=held", headers=adm["h"]).json()
    item = next(x for x in q["items"] if x["id"] == held)
    assert item["target"] == "idea" and item["author_handle"] == a["handle"]
    assert "_ref" not in item and item["excerpt"] == "free casino"
    q = client.get("/api/admin/social/queue?status=hidden", headers=adm["h"]).json()
    hid = next(x for x in q["items"] if x["id"] == pub)
    assert hid["reason_counts"] == {"spam": 3}
    # approve the held one -> published and in the feed
    r = client.post(
        f"/api/admin/social/idea/{held}/decide",
        json={"action": "approve"},
        headers=adm["h"],
    )
    assert r.status_code == 200 and held in _feed(client, b)
    # remove the hidden one
    client.post(
        f"/api/admin/social/idea/{pub}/decide",
        json={"action": "remove"},
        headers=adm["h"],
    )
    assert client.get(f"/api/social/ideas/{pub}", headers=a["h"]).status_code == 404
    # reported queue: a published item with open reports
    c = _idea(client, a, plan=_plan(a))["id"]
    _report(client, b, "idea", c)
    q = client.get("/api/admin/social/queue?status=reported", headers=adm["h"]).json()
    assert any(x["id"] == c for x in q["items"])
    client.post(
        f"/api/admin/social/idea/{c}/decide",
        json={"action": "approve"},
        headers=adm["h"],
    )
    q = client.get("/api/admin/social/queue?status=reported", headers=adm["h"]).json()
    assert not any(x["id"] == c for x in q["items"])
    # restrict: no posting or commenting; lift restores
    r = client.post(
        f"/api/admin/social/users/{a['handle']}/restrict",
        json={"days": 3},
        headers=adm["h"],
    )
    assert r.status_code == 200
    assert _post(client, a, _plan(a)).json()["error_code"] == "restricted"
    assert (
        client.post(
            f"/api/social/ideas/{c}/comments", json={"text": "x"}, headers=a["h"]
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/admin/social/users/{a['handle']}/restrict", headers=adm["h"]
        ).status_code
        == 204
    )
    assert _post(client, a, _plan(a)).status_code == 200
    bad = client.post(
        f"/api/admin/social/users/{a['handle']}/restrict",
        json={"days": 0},
        headers=adm["h"],
    )
    assert bad.status_code == 422
    assert (
        client.post(
            "/api/admin/social/users/nobody1/restrict",
            json={"days": 2},
            headers=adm["h"],
        ).status_code
        == 404
    )


def test_admin_profile_decision(client):
    adm = _user(is_admin=True)
    a = _mk(client)
    social_db.save_profile(a["id"], {"bio": "spam bio", "show_avatar": True})
    r = client.post(
        f"/api/admin/social/profile/{a['handle']}/decide",
        json={"action": "remove"},
        headers=adm["h"],
    )
    assert r.status_code == 200
    prof = social_db.get_profile(a["id"])
    assert prof["visibility"] == "private" and prof["bio"] == ""
    assert prof["show_avatar"] is False


def test_expired_restriction_is_not_active(client):
    u = _mk(client)
    social_ideas_db.restrict(u["id"], 1)
    assert social_ideas_db.is_restricted(u["id"])
    with social_db.get_connection() as c:
        c.execute("UPDATE restrictions SET until = '2000-01-01T00:00:00Z'")
    assert not social_ideas_db.is_restricted(u["id"])


# ── profile counts, rules, deletion, limits ───────────────────────────────────


def test_profile_ideas_count_and_listing(client):
    a, v = _mk(client), _mk(client)
    _idea(client, a)
    p = client.get(f"/api/social/profile/{a['handle']}", headers=v["h"]).json()
    assert p["ideas_count"] == 1
    lst = client.get(f"/api/social/profile/{a['handle']}/ideas", headers=v["h"]).json()
    assert len(lst["ideas"]) == 1 and lst["ideas"][0]["author"]["handle"] == a["handle"]


def test_game_rules_present():
    rules = engine.get_rules()
    assert (
        rules.rules["idea_saved"].points == 10
        and rules.rules["idea_saved"].daily_cap == 5
    )
    assert rules.rules["comment_helpful"].points == 5
    assert {"inspirer", "muse", "helpful_voice"} <= set(rules.badges)


def test_account_deletion_removes_idea_rows(client):
    from app.services import account_data

    a, b = _mk(client), _mk(client)
    i = _idea(client, a)["id"]
    client.put(f"/api/social/ideas/{i}/like", headers=b["h"])
    cid = client.post(
        f"/api/social/ideas/{i}/comments", json={"text": "hi"}, headers=b["h"]
    ).json()["id"]
    _report(client, b, "comment", cid)
    j = _idea(client, b)["id"]
    account_data.delete_rows(a)
    assert social_ideas_db.get_idea_raw(i) is None
    assert social_ideas_db.get_comment(cid) is None
    with social_db.get_connection() as c:
        assert not c.execute(
            "SELECT 1 FROM idea_likes WHERE idea_id = ?", (i,)
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM reports WHERE target = 'comment' AND target_id = ?",
            (str(cid),),
        ).fetchone()
    assert social_ideas_db.get_idea_raw(j) is not None


def test_rate_limit_applies(client, monkeypatch):
    from app.core import rate_limit as rl

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_social_read", 2)
    rl.limiter._hits.clear()
    u = _mk(client)
    codes = [
        client.get("/api/social/feed", headers=u["h"]).status_code for _ in range(3)
    ]
    assert codes[:2] == [200, 200] and codes[2] == 429
