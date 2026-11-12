"""GET /api/auth/sessions and DELETE /api/auth/sessions/{id}."""

import uuid

from app.db import users_db

PW = "Correct-Horse-Battery-9"


def _user() -> dict:
    return users_db.create_user(
        "l" + uuid.uuid4().hex[:10], PW, is_first_login=False
    )


def _login(tc, u, **extra):
    r = tc.post(
        "/api/auth/login", json={"username": u["username"], "password": PW, **extra}
    )
    assert r.status_code == 200
    return r.json()


def _h(s: dict, **extra) -> dict:
    return {"Authorization": f"Bearer {s['access_token']}", **extra}


def test_requires_auth(client):
    assert client.get("/api/auth/sessions").status_code == 401
    assert client.delete("/api/auth/sessions/x").status_code == 401


def test_web_login_not_listed(client):
    s = _login(client, _user())
    assert "refresh_token" not in s
    assert client.get("/api/auth/sessions", headers=_h(s)).json() == {"sessions": []}


def test_lists_own_families_and_current_flag(client):
    u = _user()
    a = _login(client, u, client="android", device_name="Pixel")
    b = _login(client, u, client="ios", device_name="iPhone")
    r = client.get(
        "/api/auth/sessions", headers=_h(a, **{"X-Refresh-Token": a["refresh_token"]})
    )
    assert r.status_code == 200
    rows = r.json()["sessions"]
    assert len(rows) == 2
    by_name = {x["device_name"]: x for x in rows}
    assert by_name["Pixel"]["current"] is True and by_name["Pixel"]["client"] == "android"
    assert by_name["iPhone"]["current"] is False
    assert set(rows[0]) == {
        "id", "client", "device_name", "created_at", "last_used_at", "current"
    }
    assert b["refresh_token"] not in r.text and a["refresh_token"] not in r.text
    # no header: nothing is current
    r = client.get("/api/auth/sessions", headers=_h(a))
    assert not any(x["current"] for x in r.json()["sessions"])


def test_current_survives_rotation_with_stable_id(client):
    u = _user()
    a = _login(client, u, client="android", device_name="Pixel")
    before = client.get("/api/auth/sessions", headers=_h(a)).json()["sessions"][0]
    rot = client.post("/api/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert rot.status_code == 200
    new = rot.json()
    r = client.get(
        "/api/auth/sessions", headers=_h(new, **{"X-Refresh-Token": new["refresh_token"]})
    )
    rows = r.json()["sessions"]
    assert len(rows) == 1
    assert rows[0]["id"] == before["id"] and rows[0]["current"] is True
    assert rows[0]["created_at"] == before["created_at"]


def test_other_users_sessions_hidden_and_404(client):
    u1, u2 = _user(), _user()
    a = _login(client, u1, client="android")
    b = _login(client, u2, client="android")
    sid = client.get("/api/auth/sessions", headers=_h(a)).json()["sessions"][0]["id"]
    r = client.delete(f"/api/auth/sessions/{sid}", headers=_h(b))
    assert r.status_code == 404 and r.json()["error_code"] == "session_not_found"
    # still alive for the owner
    assert len(client.get("/api/auth/sessions", headers=_h(a)).json()["sessions"]) == 1
    assert len(client.get("/api/auth/sessions", headers=_h(b)).json()["sessions"]) == 1
    assert client.post(
        "/api/auth/refresh", json={"refresh_token": a["refresh_token"]}
    ).status_code == 200


def test_revoke_removes_family_and_blocks_refresh(client):
    u = _user()
    a = _login(client, u, client="android", device_name="Pixel")
    _login(client, u, client="ios", device_name="iPhone")
    sid = next(
        x["id"]
        for x in client.get("/api/auth/sessions", headers=_h(a)).json()["sessions"]
        if x["device_name"] == "Pixel"
    )
    assert client.delete(f"/api/auth/sessions/{sid}", headers=_h(a)).status_code == 204
    rows = client.get("/api/auth/sessions", headers=_h(a)).json()["sessions"]
    assert [x["device_name"] for x in rows] == ["iPhone"]
    assert client.post(
        "/api/auth/refresh", json={"refresh_token": a["refresh_token"]}
    ).status_code == 401
    # a revoked family is now a 404
    assert client.delete(f"/api/auth/sessions/{sid}", headers=_h(a)).status_code == 404


def test_logout_and_logout_all_remove_families(client):
    u = _user()
    a = _login(client, u, client="android")
    _login(client, u, client="android")
    client.post("/api/auth/logout", json={"refresh_token": a["refresh_token"]})
    assert len(client.get("/api/auth/sessions", headers=_h(a)).json()["sessions"]) == 1
    client.post("/api/auth/logout-all", headers=_h(a))
    # token_version bumped: the old access token is now revoked
    assert client.get("/api/auth/sessions", headers=_h(a)).status_code == 401


def test_expired_family_excluded(client):
    from app.db.database import get_connection

    u = _user()
    a = _login(client, u, client="android")
    with get_connection() as conn:
        conn.execute(
            "UPDATE refresh_tokens SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE user_id = ?",
            (u["id"],),
        )
    assert client.get("/api/auth/sessions", headers=_h(a)).json() == {"sessions": []}
