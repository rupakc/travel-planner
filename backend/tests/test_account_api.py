import uuid
from datetime import UTC, datetime

import pytest

from app.core.auth import create_access_token
from app.db.database import get_connection
from app.db.users_db import create_user


@pytest.fixture(autouse=True)
def _fast(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


def _user(**kw):
    u = create_user(f"acc-{uuid.uuid4().hex[:8]}", "pw-123456789", **kw)
    return u, {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


def _identity(uid, provider="github"):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_identities (user_id, provider, subject, email, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                uid,
                provider,
                uuid.uuid4().hex,
                "x@example.com",
                datetime.now(UTC).isoformat(),
            ),
        )


def test_requires_auth(client):
    assert client.get("/api/account").status_code == 401
    assert (
        client.put(
            "/api/account/onboarding", json={"step": 0, "done": False}
        ).status_code
        == 401
    )


def test_get_account_shape(client):
    u, h = _user()
    _identity(u["id"])
    body = client.get("/api/account", headers=h).json()
    assert body["user"]["id"] == u["id"]
    assert body["identities"][0]["provider"] == "github"
    assert body["identities"][0]["email"] == "x@example.com"
    assert body["identities"][0]["linked_at"]
    assert body["settings"] == {
        "language": None,
        "theme": "system",
        "currency": "USD",
        "units": "metric",
        "timezone": None,
        "hide_game": False,
        "hide_community": False,
        "profile_visibility": "public",
        "telemetry_opt_out": False,
        "bucket_list_goal": None,
    }
    assert body["onboarding"] == {
        "step": 0,
        "done": False,
        "skipped": False,
        "traveller_type": None,
        "completed_at": None,
    }


def test_patch_display_name(client):
    _, h = _user()
    r = client.patch("/api/account", json={"display_name": "  Jané Doe "}, headers=h)
    assert r.status_code == 200
    assert r.json()["user"]["display_name"] == "Jané Doe"


@pytest.mark.parametrize("bad", ["a\x07b", "", "   ", "x" * 51])
def test_display_name_invalid(client, bad):
    _, h = _user()
    r = client.patch("/api/account", json={"display_name": bad}, headers=h)
    assert r.status_code == 422
    assert r.json()["error_code"] == "display_name_invalid"


def test_settings_patch_merges(client):
    _, h = _user()
    r = client.patch(
        "/api/account/settings", json={"theme": "dark", "hide_game": True}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["theme"] == "dark" and r.json()["hide_game"] is True
    assert r.json()["currency"] == "USD"
    r = client.patch("/api/account/settings", json={"currency": "EUR"}, headers=h)
    assert r.json()["theme"] == "dark" and r.json()["currency"] == "EUR"
    assert client.get("/api/account/settings", headers=h).json() == r.json()


@pytest.mark.parametrize(
    "bad",
    [
        {"nope": 1},
        {"timezone": "Mars/Base"},
        {"theme": "pink"},
        {"currency": "usd"},
        {"language": "xx"},
        {"profile_visibility": "everyone"},
    ],
)
def test_settings_invalid(client, bad):
    _, h = _user()
    assert client.patch("/api/account/settings", json=bad, headers=h).status_code == 422


def test_settings_valid_timezone_and_null_language(client):
    _, h = _user()
    r = client.patch(
        "/api/account/settings",
        json={"timezone": "Europe/Paris", "language": "de"},
        headers=h,
    )
    assert r.json()["timezone"] == "Europe/Paris" and r.json()["language"] == "de"
    r = client.patch("/api/account/settings", json={"language": None}, headers=h)
    assert r.json()["language"] is None and r.json()["timezone"] == "Europe/Paris"


def test_onboarding_done_awards_once(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.game.hooks.on_onboarding_complete",
        lambda uid: calls.append(uid) or {"xp": 5},
    )
    monkeypatch.setattr("app.game.trip_hooks.on_traveller_type", lambda uid, t: None)
    monkeypatch.setattr("app.game.trip_hooks.on_traveller_type", lambda uid, t: None)
    u, h = _user()
    r = client.put(
        "/api/account/onboarding", json={"step": 2, "done": False}, headers=h
    )
    assert r.json()["game"] is None and calls == []
    r = client.put(
        "/api/account/onboarding",
        json={"step": 5, "done": True, "traveller_type": "foodie"},
        headers=h,
    )
    assert r.json()["game"] == {"xp": 5}
    assert r.json()["onboarding"]["done"] and r.json()["onboarding"]["completed_at"]
    r = client.put("/api/account/onboarding", json={"step": 5, "done": True}, headers=h)
    assert r.json()["game"] is None and calls == [u["id"]]
    r = client.put(
        "/api/account/onboarding", json={"step": 1, "done": False}, headers=h
    )
    assert r.json()["onboarding"]["done"] is True
    assert r.json()["onboarding"]["traveller_type"] == "foodie"


def test_onboarding_skipped_no_award(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.game.hooks.on_onboarding_complete", lambda uid: calls.append(uid)
    )
    _, h = _user()
    r = client.put(
        "/api/account/onboarding",
        json={"step": 0, "done": True, "skipped": True},
        headers=h,
    )
    assert r.status_code == 200 and calls == []
    assert r.json()["onboarding"]["done"] and r.json()["onboarding"]["skipped"]


@pytest.mark.parametrize(
    "bad",
    [
        {"step": 6, "done": False},
        {"step": -1, "done": False},
        {"step": 1},
        {"step": 1, "done": False, "traveller_type": "Bad Type"},
    ],
)
def test_onboarding_invalid(client, bad):
    _, h = _user()
    assert client.put("/api/account/onboarding", json=bad, headers=h).status_code == 422


def test_unlink_last_method_blocked(client):
    u, h = _user(password_hash="!")
    _identity(u["id"])
    r = client.delete("/api/account/identities/github", headers=h)
    assert r.status_code == 409 and r.json()["error_code"] == "last_sign_in_method"


def test_unlink_ok_with_password_or_other_identity(client):
    u, h = _user()
    _identity(u["id"])
    assert client.delete("/api/account/identities/github", headers=h).status_code == 204
    assert client.get("/api/account", headers=h).json()["identities"] == []
    u2, h2 = _user(password_hash="!")
    _identity(u2["id"], "github")
    _identity(u2["id"], "google")
    assert (
        client.delete("/api/account/identities/github", headers=h2).status_code == 204
    )


def test_unlink_unknown(client):
    _, h = _user()
    r = client.delete("/api/account/identities/github", headers=h)
    assert r.status_code == 404 and r.json()["error_code"] == "identity_not_found"


def test_traveller_type_awarded_once_via_onboarding(client):
    u, h = _user()
    r = client.put(
        "/api/account/onboarding",
        json={"step": 1, "done": False, "traveller_type": "foodie"},
        headers=h,
    )
    g = r.json()["game"]
    assert g["awards"] == [{"rule": "traveller_type", "points": 25}]
    assert [b["id"] for b in g["badges"]] == ["traveller"]
    r = client.put(
        "/api/account/onboarding",
        json={"step": 2, "done": True, "traveller_type": "foodie"},
        headers=h,
    )
    awards = r.json()["game"]["awards"]
    assert [a["rule"] for a in awards] == ["onboarding_complete"]
    r = client.put(
        "/api/account/onboarding",
        json={"step": 2, "done": True, "traveller_type": "hiker"},
        headers=h,
    )
    assert r.json()["game"]["awards"] == []
    with get_connection() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM xp_ledger WHERE user_id=? AND rule='traveller_type'",
            (u["id"],),
        ).fetchone()[0]
    assert n == 1


@pytest.mark.parametrize("goal,code", [(0, 422), (251, 422), (30, 200), (None, 200)])
def test_bucket_goal_bounds(client, goal, code):
    _, h = _user()
    r = client.patch(
        "/api/account/settings", json={"bucket_list_goal": goal}, headers=h
    )
    assert r.status_code == code
    if code == 200:
        assert r.json()["bucket_list_goal"] == goal
        assert (
            client.get("/api/account/settings", headers=h).json()["bucket_list_goal"]
            == goal
        )
