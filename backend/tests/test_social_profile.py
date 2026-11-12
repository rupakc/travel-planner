"""Social core (Phase 5 T1): profiles, privacy projection, follows, blocks."""

import uuid

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import social_db, user_settings_db, users_db
from app.db.users_db import create_user
from app.services import social_profile

_PW = "correct-horse-battery"
HOSTILE = "<img src=x onerror=alert(1)>"


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")


def _user(handle=None, **profile):
    name = f"soc_{uuid.uuid4().hex[:10]}"
    u = create_user(name, _PW, email=f"{name}@example.com", display_name="Real Name")
    h = {"Authorization": f"Bearer {create_access_token({'sub': name})}"}
    u["h"] = h
    if handle is not None:
        u["handle"] = handle
    return u


def _mk(client, visibility="public", **extra):
    u = _user()
    handle = "h" + uuid.uuid4().hex[:10]
    r = client.put(
        "/api/social/profile",
        json={"handle": handle, "visibility": visibility, **extra},
        headers=u["h"],
    )
    assert r.status_code == 200, r.text
    u["handle"] = handle
    return u


# ── flag / auth ───────────────────────────────────────────────────────────────


def test_flag_off_404(client, monkeypatch):
    u = _user()
    monkeypatch.setattr(settings, "social_enabled", False)
    for method, path in [
        ("get", "/api/social/profile"),
        ("put", "/api/social/profile"),
        ("get", "/api/social/blocks"),
        ("put", "/api/social/follow/x"),
    ]:
        r = getattr(client, method)(path, headers=u["h"])
        assert r.status_code == 404 and r.json()["error_code"] == "social_disabled"


def test_anonymous_401(client):
    assert client.get("/api/social/profile").status_code == 401
    assert client.get("/api/social/profile/someone").status_code == 401


# ── own profile / handles ─────────────────────────────────────────────────────


def test_no_profile_defaults(client):
    u = _user()
    body = client.get("/api/social/profile", headers=u["h"]).json()
    assert body["handle"] is None and body["visibility"] == "private"
    assert not any(body[k] for k in body if k.startswith("show_"))
    assert body["leaderboard_opt_in"] is False


def test_create_requires_handle(client):
    u = _user()
    r = client.put("/api/social/profile", json={"bio": "hi"}, headers=u["h"])
    assert r.status_code == 422 and r.json()["error_code"] == "handle_invalid"


def test_new_profile_defaults_private_and_all_off(client):
    u = _user()
    r = client.put(
        "/api/social/profile", json={"handle": "Trail_Hiker"}, headers=u["h"]
    )
    b = r.json()
    assert b["handle"] == "trail_hiker" and b["visibility"] == "private"
    assert (
        not any(b[k] for k in b if k.startswith("show_"))
        and not b["leaderboard_opt_in"]
    )
    assert client.get("/api/social/profile", headers=u["h"]).json() == b


@pytest.mark.parametrize(
    "handle,code",
    [
        ("ab", "handle_invalid"),
        ("a" * 21, "handle_invalid"),
        ("bad-handle", "handle_invalid"),
        ("has space", "handle_invalid"),
        ("émile", "handle_invalid"),
        ("admin", "handle_reserved"),
        ("feed", "handle_reserved"),
        ("moderator", "handle_reserved"),
    ],
)
def test_handle_rules(client, handle, code):
    u = _user()
    r = client.put("/api/social/profile", json={"handle": handle}, headers=u["h"])
    assert r.status_code == 422 and r.json()["error_code"] == code, r.text


def test_handle_taken_case_insensitive(client):
    a = _mk(client)
    b = _user()
    r = client.put(
        "/api/social/profile", json={"handle": a["handle"].upper()}, headers=b["h"]
    )
    assert r.status_code == 409 and r.json()["error_code"] == "handle_taken"


def test_handle_check(client):
    a = _mk(client)
    me = _user()

    def chk(h):
        return client.get(
            f"/api/social/handles/check?handle={h}", headers=me["h"]
        ).json()

    assert chk(a["handle"]) == {"available": False, "reason": "taken"}
    assert chk("admin") == {"available": False, "reason": "reserved"}
    assert chk("x") == {"available": False, "reason": "invalid"}
    assert chk("free_" + uuid.uuid4().hex[:8]) == {"available": True}
    # own handle counts as available to its owner
    r = client.get(f"/api/social/handles/check?handle={a['handle']}", headers=a["h"])
    assert r.json() == {"available": True}


def test_handle_change_once_per_30_days(client):
    u = _mk(client)
    first = u["handle"]
    new1 = "n" + uuid.uuid4().hex[:8]
    assert (
        client.put(
            "/api/social/profile", json={"handle": new1}, headers=u["h"]
        ).status_code
        == 200
    )
    r = client.put(
        "/api/social/profile",
        json={"handle": "m" + uuid.uuid4().hex[:8]},
        headers=u["h"],
    )
    assert r.status_code == 422 and r.json()["error_code"] == "handle_rate_limited"
    assert r.json()["retry_after"] > 0
    # the same handle again is a no-op, not a change
    assert (
        client.put(
            "/api/social/profile", json={"handle": new1}, headers=u["h"]
        ).status_code
        == 200
    )
    # after 30 days it may change
    prof = social_db.get_profile(u["id"])
    assert social_profile.handle_change_wait(prof) > 0
    with social_db.get_connection() as c:
        c.execute(
            "UPDATE social_profiles SET handle_changed_at = '2020-01-01T00:00:00Z' WHERE user_id = ?",
            (u["id"],),
        )
    new2 = "o" + uuid.uuid4().hex[:8]
    assert (
        client.put(
            "/api/social/profile", json={"handle": new2}, headers=u["h"]
        ).status_code
        == 200
    )
    assert first != new2


def test_bio_filter_and_plain_text(client):
    u = _mk(client)
    r = client.put(
        "/api/social/profile", json={"bio": "visit www.spam.com"}, headers=u["h"]
    )
    assert r.status_code == 422 and r.json()["error_code"] == "content_rejected"
    r = client.put("/api/social/profile", json={"bio": "x" * 161}, headers=u["h"])
    assert r.status_code == 422
    r = client.put(
        "/api/social/profile",
        json={"bio": f"  hi\x00 \n  there {HOSTILE}"},
        headers=u["h"],
    )
    assert r.status_code == 200
    # stored as plain text (no control chars, collapsed), never interpreted
    assert r.json()["bio"] == f"hi there {HOSTILE}"


def test_home_country_validation(client):
    u = _mk(client)
    assert (
        client.put(
            "/api/social/profile", json={"home_country": "pt"}, headers=u["h"]
        ).json()["home_country"]
        == "PT"
    )
    r = client.put("/api/social/profile", json={"home_country": "QQ"}, headers=u["h"])
    assert r.status_code == 422 and r.json()["error_code"] == "country_invalid"
    assert (
        client.put(
            "/api/social/profile", json={"home_country": None}, headers=u["h"]
        ).json()["home_country"]
        is None
    )


def test_partial_update_keeps_other_fields(client):
    u = _mk(client, bio="hello", show_countries=True)
    b = client.put(
        "/api/social/profile", json={"visibility": "followers"}, headers=u["h"]
    ).json()
    assert (
        b["bio"] == "hello"
        and b["show_countries"] is True
        and b["visibility"] == "followers"
    )


# ── privacy matrix ────────────────────────────────────────────────────────────


def _view(client, viewer, target):
    return client.get(f"/api/social/profile/{target['handle']}", headers=viewer["h"])


def test_private_profile_is_404_for_others_not_self(client):
    p = _mk(client, visibility="private")
    v = _user()
    r = _view(client, v, p)
    assert r.status_code == 404 and r.json()["error_code"] == "profile_not_found"
    assert _view(client, p, p).status_code == 200
    assert (
        client.get("/api/social/profile/nobody_here", headers=v["h"]).status_code == 404
    )


def test_public_defaults_show_only_handle_bio_counts(client):
    p = _mk(client, visibility="public", bio="hi")
    v = _user()
    b = _view(client, v, p).json()
    assert set(b) == {
        "handle", "bio", "ideas_count", "followers_count", "following_count", "you",
    }  # fmt: skip
    assert b["you"] == {
        "following": False,
        "pending": False,
        "follows_you": False,
        "blocked": False,
    }
    txt = str(b)
    assert p["username"] not in txt and p["email"] not in txt and "Real Name" not in txt
    assert p["id"] not in txt


def test_opt_in_fields_each_appear_only_when_enabled(client, monkeypatch):
    p = _mk(client, visibility="public")
    from app.db import user_countries_db

    user_countries_db.add_countries(p["id"], ["PT", "JP"], 1, "checkin")
    v = _user()
    client.put("/api/social/profile", json={"home_country": "PT"}, headers=p["h"])
    assert "home_country" not in _view(client, v, p).json()  # stored, not shared
    for flag, key in [
        ("show_home_country", "home_country"),
        ("show_countries", "countries"),
        ("show_level", "level"),
        ("show_badges", "badges"),
    ]:
        client.put("/api/social/profile", json={flag: True}, headers=p["h"])
        assert key in _view(client, v, p).json(), flag
        client.put("/api/social/profile", json={flag: False}, headers=p["h"])
        assert key not in _view(client, v, p).json(), flag
    client.put("/api/social/profile", json={"show_countries": True}, headers=p["h"])
    assert _view(client, v, p).json()["countries"] == ["JP", "PT"]


def test_hidden_game_omits_level_and_badges(client):
    p = _mk(client, visibility="public", show_level=True, show_badges=True)
    v = _user()
    assert "level" in _view(client, v, p).json()
    user_settings_db.patch_settings(p["id"], {"hide_game": True})
    b = _view(client, v, p).json()
    assert "level" not in b and "badges" not in b
    own = client.get("/api/social/profile", headers=p["h"]).json()
    assert "level" not in own and "badges" not in own


def test_game_disabled_omits_game_fields(client, monkeypatch):
    p = _mk(client, visibility="public", show_level=True)
    monkeypatch.setattr(settings, "game_enabled", False)
    assert "level" not in _view(client, _user(), p).json()


def test_followers_profile_shows_non_followers_only_handle_and_counts(client):
    p = _mk(client, visibility="followers", bio="secret bio", show_countries=True)
    v = _user()
    b = _view(client, v, p).json()
    assert set(b) == {
        "handle",
        "ideas_count",
        "followers_count",
        "following_count",
        "you",
    }
    assert "secret bio" not in str(b)


def test_followers_profile_full_for_approved_follower(client):
    p = _mk(client, visibility="followers", bio="secret bio")
    f = _mk(client)
    assert client.put(f"/api/social/follow/{p['handle']}", headers=f["h"]).json() == {
        "state": "pending"
    }
    assert "bio" not in _view(client, f, p).json()  # pending is not approved
    assert (
        client.post(
            f"/api/social/follow-requests/{f['handle']}/accept", headers=p["h"]
        ).status_code
        == 204
    )
    b = _view(client, f, p).json()
    assert b["bio"] == "secret bio" and b["you"]["following"] is True
    assert _view(client, p, f).json()["you"]["follows_you"] is True


def test_hostile_text_returned_as_json_string(client):
    p = _mk(client, visibility="public", bio=HOSTILE)
    r = _view(client, _user(), p)
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["bio"] == HOSTILE


# ── follow ────────────────────────────────────────────────────────────────────


def test_follow_public_immediate_and_counts(client):
    a, b = _mk(client, "public"), _mk(client, "public")
    r = client.put(f"/api/social/follow/{b['handle']}", headers=a["h"])
    assert r.status_code == 200 and r.json() == {"state": "following"}
    assert client.put(f"/api/social/follow/{b['handle']}", headers=a["h"]).json() == {
        "state": "following"
    }
    v = _view(client, a, b).json()
    assert v["followers_count"] == 1 and v["you"]["following"] is True
    assert _view(client, b, a).json()["following_count"] == 1
    lst = client.get("/api/social/followers", headers=b["h"]).json()
    assert lst == {"users": [{"handle": a["handle"]}], "next": None}
    assert client.get("/api/social/following", headers=a["h"]).json()["users"] == [
        {"handle": b["handle"]}
    ]
    assert (
        client.delete(f"/api/social/follow/{b['handle']}", headers=a["h"]).status_code
        == 204
    )
    assert (
        client.delete(f"/api/social/follow/{b['handle']}", headers=a["h"]).status_code
        == 204
    )
    assert _view(client, a, b).json()["followers_count"] == 0


def test_follow_requests_flow(client):
    owner, a, b = _mk(client, "followers"), _mk(client, "public"), _mk(client, "public")
    for u in (a, b):
        assert client.put(
            f"/api/social/follow/{owner['handle']}", headers=u["h"]
        ).json() == {"state": "pending"}
    reqs = client.get("/api/social/follow-requests", headers=owner["h"]).json()[
        "requests"
    ]
    assert {r["handle"] for r in reqs} == {a["handle"], b["handle"]}
    assert all("created_at" in r for r in reqs)
    assert (
        client.post(
            f"/api/social/follow-requests/{a['handle']}/accept", headers=owner["h"]
        ).status_code
        == 204
    )
    assert (
        client.post(
            f"/api/social/follow-requests/{b['handle']}/decline", headers=owner["h"]
        ).status_code
        == 204
    )
    assert client.get("/api/social/follow-requests", headers=owner["h"]).json() == {
        "requests": []
    }
    assert client.get("/api/social/followers", headers=owner["h"]).json()["users"] == [
        {"handle": a["handle"]}
    ]
    r = client.post(
        f"/api/social/follow-requests/{b['handle']}/accept", headers=owner["h"]
    )
    assert r.status_code == 404 and r.json()["error_code"] == "request_not_found"
    # cancel own pending request
    c = _mk(client, "public")
    client.put(f"/api/social/follow/{owner['handle']}", headers=c["h"])
    assert (
        client.delete(
            f"/api/social/follow/{owner['handle']}", headers=c["h"]
        ).status_code
        == 204
    )
    assert client.get("/api/social/follow-requests", headers=owner["h"]).json() == {
        "requests": []
    }


def test_follow_errors(client):
    a = _mk(client, "public")
    priv = _mk(client, "private")
    nop = _user()
    r = client.put(f"/api/social/follow/{a['handle']}", headers=a["h"])
    assert r.status_code == 422 and r.json()["error_code"] == "cannot_follow_self"
    r = client.put(f"/api/social/follow/{priv['handle']}", headers=a["h"])
    assert r.status_code == 404 and r.json()["error_code"] == "profile_not_found"
    assert (
        client.put("/api/social/follow/ghost_user", headers=a["h"]).status_code == 404
    )
    r = client.put(f"/api/social/follow/{a['handle']}", headers=nop["h"])
    assert r.status_code == 403 and r.json()["error_code"] == "profile_required"


def test_follow_daily_cap(client, monkeypatch):
    from app.api.routes import social

    monkeypatch.setattr(social, "FOLLOW_DAILY_CAP", 2)
    a = _mk(client, "public")
    targets = [_mk(client, "public") for _ in range(3)]
    codes = [
        client.put(f"/api/social/follow/{t['handle']}", headers=a["h"]) for t in targets
    ]
    assert [c.status_code for c in codes] == [200, 200, 422]
    assert codes[2].json()["error_code"] == "limit_reached"
    # repeating an existing follow does not count
    assert (
        client.put(
            f"/api/social/follow/{targets[0]['handle']}", headers=a["h"]
        ).status_code
        == 200
    )


def test_lists_hide_private_profiles_and_paginate(client):
    t = _mk(client, "public")
    fans = [_mk(client, "public") for _ in range(3)]
    for f in fans:
        client.put(f"/api/social/follow/{t['handle']}", headers=f["h"])
    client.put(
        "/api/social/profile", json={"visibility": "private"}, headers=fans[0]["h"]
    )
    seen, cursor = [], None
    while True:
        q = "?limit=1" + (f"&cursor={cursor}" if cursor else "")
        page = client.get("/api/social/followers" + q, headers=t["h"]).json()
        seen += [u["handle"] for u in page["users"]]
        cursor = page["next"]
        if not cursor:
            break
    assert set(seen) == {fans[1]["handle"], fans[2]["handle"]}
    assert (
        client.get("/api/social/followers?cursor=abc", headers=t["h"]).status_code
        == 422
    )
    assert _view(client, _user(), t).json()["followers_count"] == 2


# ── block ─────────────────────────────────────────────────────────────────────


def test_block_removes_follows_both_ways_and_hides_both(client):
    a, b = _mk(client, "public"), _mk(client, "public")
    client.put(f"/api/social/follow/{b['handle']}", headers=a["h"])
    client.put(f"/api/social/follow/{a['handle']}", headers=b["h"])
    assert (
        client.put(f"/api/social/block/{b['handle']}", headers=a["h"]).status_code
        == 204
    )
    assert client.get("/api/social/followers", headers=a["h"]).json()["users"] == []
    assert client.get("/api/social/following", headers=a["h"]).json()["users"] == []
    assert client.get("/api/social/following", headers=b["h"]).json()["users"] == []
    # silent and two-way: neither sees the other, neither can follow
    for x, y in ((a, b), (b, a)):
        assert _view(client, x, y).status_code == 404
        assert (
            client.put(f"/api/social/follow/{y['handle']}", headers=x["h"]).status_code
            == 404
        )
    assert client.get("/api/social/blocks", headers=a["h"]).json() == {
        "users": [{"handle": b["handle"]}]
    }
    assert client.get("/api/social/blocks", headers=b["h"]).json() == {"users": []}
    # idempotent, then unblock restores visibility
    assert (
        client.put(f"/api/social/block/{b['handle']}", headers=a["h"]).status_code
        == 204
    )
    assert (
        client.delete(f"/api/social/block/{b['handle']}", headers=a["h"]).status_code
        == 204
    )
    assert _view(client, a, b).status_code == 200
    assert client.get("/api/social/blocks", headers=a["h"]).json() == {"users": []}


def test_block_self_and_unknown(client):
    a = _mk(client, "public")
    r = client.put(f"/api/social/block/{a['handle']}", headers=a["h"])
    assert r.status_code == 422 and r.json()["error_code"] == "cannot_block_self"
    assert client.put("/api/social/block/ghost_user", headers=a["h"]).status_code == 404


def test_block_private_profile_allowed(client):
    a, priv = _mk(client, "public"), _mk(client, "private")
    assert (
        client.put(f"/api/social/block/{priv['handle']}", headers=a["h"]).status_code
        == 204
    )


# ── rate limit / account deletion ─────────────────────────────────────────────


def test_rate_limit_buckets(client, monkeypatch):
    from app.core import rate_limit as rl

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_social_read", 2)
    monkeypatch.setattr(settings, "rate_limit_social_write", 1)
    rl.limiter._hits.clear()
    u = _user()
    codes = [
        client.get("/api/social/profile", headers=u["h"]).status_code for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    ok = client.put(
        "/api/social/profile",
        json={"handle": "w" + uuid.uuid4().hex[:8]},
        headers=u["h"],
    )
    limited = client.put("/api/social/profile", json={"bio": "x"}, headers=u["h"])
    assert ok.status_code == 200 and limited.status_code == 429
    assert "Retry-After" in limited.headers


def test_account_deletion_removes_social_rows(client):
    from app.services import account_data

    a, b = _mk(client, "public"), _mk(client, "public")
    client.put(f"/api/social/follow/{b['handle']}", headers=a["h"])
    client.put(f"/api/social/follow/{a['handle']}", headers=b["h"])
    client.put(f"/api/social/block/{b['handle']}", headers=a["h"])
    client.put(f"/api/social/block/{a['handle']}", headers=b["h"])
    social_db.consume_daily(a["id"], "follow", 5)
    account_data.delete_rows(a)
    assert social_db.get_profile(a["id"]) is None
    assert social_db.used_today(a["id"], "follow") == 0
    with social_db.get_connection() as c:
        for t, cols in (
            ("social_follows", "follower_id, followee_id"),
            ("social_blocks", "blocker_id, blocked_id"),
        ):
            n = c.execute(
                f"SELECT COUNT(*) FROM {t} WHERE ? IN ({cols})",
                (a["id"],),  # noqa: S608
            ).fetchone()[0]
            assert n == 0
    assert social_db.get_profile(b["id"]) is not None
