"""Task 7: revocable sessions, mobile refresh tokens, additive auth routes."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.api.routes import sessions as sessions_routes
from app.core.auth import ALGORITHM, _secret
from app.db import users_db

PW = "Correct-Horse-Battery-9"


def _name() -> str:
    return "s" + uuid.uuid4().hex[:10]


def _user(**kw) -> dict:
    name = kw.pop("username", None) or _name()
    kw.setdefault("is_first_login", False)
    return users_db.create_user(name, kw.pop("password", PW), **kw)


def _login(tc, username, password=PW, **extra):
    return tc.post(
        "/api/auth/login", json={"username": username, "password": password, **extra}
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def clock(monkeypatch):
    """Freeze the refresh route's clock; ``clock.advance(seconds)``."""

    class _Clock:
        now = datetime.now(UTC)

        def advance(self, seconds: float) -> None:
            self.now += timedelta(seconds=seconds)

    c = _Clock()
    monkeypatch.setattr(sessions_routes, "_now", lambda: c.now)
    return c


# ── login ────────────────────────────────────────────────────────────────────


def test_login_response_keeps_legacy_keys(client):
    u = _user(email=f"{_name()}@example.com")
    r = _login(client, u["username"])
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] == 86400
    assert "refresh_token" not in body  # web
    user = body["user"]
    assert user["username"] == u["username"]
    assert user["is_admin"] is False
    assert user["requires_password_change"] is False
    assert user["email"] == u["email"]
    # additive User keys
    assert user["id"] == u["id"]
    assert user["has_password"] is True
    assert user["account_verified"] is True  # admin-created
    claims = jwt.decode(body["access_token"], _secret(), algorithms=[ALGORITHM])
    assert claims["sub"] == u["username"]
    assert claims["uid"] == u["id"]
    assert claims["tv"] == 0
    assert "iat" in claims and "exp" in claims
    assert claims["is_admin"] is False and claims["is_first_login"] is False


def test_first_login_flag_is_reported(client):
    u = _user(is_first_login=True)
    r = _login(client, u["username"])
    assert r.json()["user"]["requires_password_change"] is True


def test_login_with_email(client):
    email = f"{_name()}@Example.com"
    u = _user(email=email)
    r = _login(client, email.upper())
    assert r.status_code == 200
    assert r.json()["user"]["username"] == u["username"]


def test_mobile_login_gets_refresh_token(client):
    u = _user()
    r = _login(client, u["username"], client="ios", device_name="Jane's iPhone")
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] == 3600
    assert body["refresh_token"].startswith("rt_")
    claims = jwt.decode(body["access_token"], _secret(), algorithms=[ALGORITHM])
    assert claims["exp"] - claims["iat"] == 3600
    assert (
        client.get("/api/auth/me", headers=_auth(body["access_token"])).status_code
        == 200
    )


def test_login_rejects_long_device_name(client):
    u = _user()
    r = _login(client, u["username"], client="android", device_name="x" * 65)
    assert r.status_code == 422


def test_pending_login_403_only_with_right_password(client):
    name = _name()
    users_db.create_pending_user(name, f"{name}@example.com", PW, None, None, None)
    bad = _login(client, name, "wrong-password-123")
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Invalid username or password"
    r = _login(client, name)
    assert r.status_code == 403
    body = r.json()
    assert body["error_code"] == "account_pending"
    assert body["email_hint"] == f"{name[0]}•••@example.com"
    assert isinstance(body["detail"], str) and body["detail"]
    assert "access_token" not in body


def test_pending_user_token_is_rejected(client):
    name = _name()
    u = users_db.create_pending_user(name, f"{name}@example.com", PW, None, None, None)
    from app.core.auth import create_access_token

    tok = create_access_token({"sub": name, "uid": u["id"], "tv": 0})
    assert client.get("/api/auth/me", headers=_auth(tok)).status_code == 401


# ── token version ────────────────────────────────────────────────────────────


def test_old_token_without_tv_still_works(client):
    u = _user()
    legacy = jwt.encode(
        {
            "sub": u["username"],
            "is_admin": False,
            "is_first_login": False,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        _secret(),
        algorithm=ALGORITHM,
    )
    r = client.get("/api/auth/me", headers=_auth(legacy))
    assert r.status_code == 200
    assert r.json()["username"] == u["username"]
    # ... until the version moves on
    users_db.bump_token_version(u["id"])
    r = client.get("/api/auth/me", headers=_auth(legacy))
    assert r.status_code == 401
    assert r.json()["error_code"] == "session_revoked"


def test_stale_tv_makes_optional_user_anonymous(client):
    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.auth import get_optional_user

    u = _user()
    tok = _login(client, u["username"]).json()["access_token"]
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
    assert get_optional_user(creds)["id"] == u["id"]
    users_db.bump_token_version(u["id"])
    assert get_optional_user(creds) is None


def test_me_returns_contract_user(client):
    u = _user(email=f"{_name()}@example.com", display_name="Jane")
    tok = _login(client, u["username"]).json()["access_token"]
    me = client.get("/api/auth/me", headers=_auth(tok)).json()
    for key in (
        "id", "username", "display_name", "email", "email_verified", "is_admin",
        "requires_password_change", "account_verified", "has_password",
        "signup_method", "avatar_url",
    ):  # fmt: skip
        assert key in me
    assert me["display_name"] == "Jane"
    assert me["avatar_url"] is None


# ── logout ───────────────────────────────────────────────────────────────────


def test_logout_all_revokes_access_and_refresh(client):
    u = _user()
    a = _login(client, u["username"], client="android").json()
    b = _login(client, u["username"], client="ios").json()
    r = client.post("/api/auth/logout-all", headers=_auth(a["access_token"]))
    assert r.status_code == 204
    for s in (a, b):
        me = client.get("/api/auth/me", headers=_auth(s["access_token"]))
        assert me.status_code == 401
        assert me.json()["error_code"] == "session_revoked"
        rr = client.post(
            "/api/auth/refresh", json={"refresh_token": s["refresh_token"]}
        )
        assert rr.status_code == 401
        assert rr.json()["error_code"] == "refresh_invalid"


def test_logout_all_needs_auth(client):
    assert client.post("/api/auth/logout-all").status_code == 401


def test_logout_revokes_family(client):
    u = _user()
    s = _login(client, u["username"], client="ios").json()
    r = client.post("/api/auth/logout", json={"refresh_token": s["refresh_token"]})
    assert r.status_code == 204
    rr = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert rr.json()["error_code"] == "refresh_invalid"
    # no body, unknown token: still 204
    assert client.post("/api/auth/logout").status_code == 204
    assert (
        client.post("/api/auth/logout", json={"refresh_token": "rt_nope"}).status_code
        == 204
    )


# ── refresh ──────────────────────────────────────────────────────────────────


def test_refresh_rotates(client, clock):
    u = _user()
    s = _login(client, u["username"], client="ios").json()
    r = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "refresh_token"}
    assert body["token_type"] == "bearer" and body["expires_in"] == 3600
    assert body["refresh_token"].startswith("rt_")
    assert body["refresh_token"] != s["refresh_token"]
    assert (
        client.get("/api/auth/me", headers=_auth(body["access_token"])).status_code
        == 200
    )
    # the new token rotates again
    clock.advance(5)
    r2 = client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r2.status_code == 200


def test_refresh_unknown_token_is_invalid(client):
    r = client.post("/api/auth/refresh", json={"refresh_token": "rt_unknown"})
    assert r.status_code == 401
    assert r.json()["error_code"] == "refresh_invalid"


def test_refresh_reuse_within_grace_keeps_family(client, clock):
    u = _user()
    s = _login(client, u["username"], client="android").json()
    first = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert first.status_code == 200
    clock.advance(30)  # the concurrent loser, inside the 30 s grace window
    loser = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert loser.status_code == 401
    assert loser.json()["error_code"] == "refresh_stale"
    # the winner's token still works: the family was not revoked
    nxt = client.post(
        "/api/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
    )
    assert nxt.status_code == 200


def test_refresh_reuse_after_grace_revokes_family(client, clock):
    u = _user()
    s = _login(client, u["username"], client="android").json()
    first = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert first.status_code == 200
    clock.advance(31)
    replay = client.post(
        "/api/auth/refresh", json={"refresh_token": s["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["error_code"] == "refresh_invalid"
    # the whole family is gone, including the legitimate successor
    nxt = client.post(
        "/api/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
    )
    assert nxt.status_code == 401
    assert nxt.json()["error_code"] == "refresh_invalid"


def test_refresh_expired_is_invalid(client, clock):
    from app.core.config import settings

    u = _user()
    s = _login(client, u["username"], client="ios").json()
    clock.advance(settings.refresh_token_days * 86400 + 60)
    r = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert r.json()["error_code"] == "refresh_invalid"


def test_refresh_for_inactive_user_is_invalid(client):
    u = _user()
    s = _login(client, u["username"], client="ios").json()
    users_db.deactivate_user(u["username"])
    r = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert r.status_code == 401
    assert r.json()["error_code"] == "refresh_invalid"


def test_refresh_token_stored_only_as_hash(client):
    from app.db.database import get_connection

    u = _user()
    s = _login(client, u["username"], client="ios", device_name="Pixel").json()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM refresh_tokens WHERE user_id = ?", (u["id"],)
        ).fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert s["refresh_token"] not in row.values()
    assert len(row["token_hash"]) == 64
    assert row["client"] == "ios" and row["device_name"] == "Pixel"


# ── change password ──────────────────────────────────────────────────────────


def test_change_password_bumps_version_keeps_current_session(client):
    u = _user()
    other = _login(client, u["username"], client="ios").json()
    mine = _login(client, u["username"], client="android").json()
    r = client.post(
        "/api/auth/change-password",
        json={
            "current_password": PW,
            "new_password": "Brand-New-Secret-77",
            "client": "android",
        },
        headers=_auth(mine["access_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["refresh_token"].startswith("rt_")
    # the new token keeps this session alive
    assert (
        client.get("/api/auth/me", headers=_auth(body["access_token"])).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/refresh", json={"refresh_token": body["refresh_token"]}
        ).status_code
        == 200
    )
    # every other session is gone
    for s in (other, mine):
        me = client.get("/api/auth/me", headers=_auth(s["access_token"]))
        assert me.json()["error_code"] == "session_revoked"
        rr = client.post(
            "/api/auth/refresh", json={"refresh_token": s["refresh_token"]}
        )
        assert rr.json()["error_code"] == "refresh_invalid"
    assert users_db.get_user_by_id(u["id"])["token_version"] == 1


def test_change_password_web_has_no_refresh_token(client):
    u = _user()
    tok = _login(client, u["username"]).json()["access_token"]
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": PW, "new_password": "Brand-New-Secret-77"},
        headers=_auth(tok),
    )
    assert r.status_code == 200
    assert set(r.json()) == {"access_token", "token_type", "expires_in"}
    assert r.json()["expires_in"] == 86400


def test_change_password_rejects_common(client):
    u = _user()
    tok = _login(client, u["username"]).json()["access_token"]
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": PW, "new_password": "password123"},
        headers=_auth(tok),
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "password_common"
    assert users_db.get_user_by_id(u["id"])["token_version"] == 0


def test_change_password_wrong_current_keeps_legacy_text(client):
    u = _user()
    tok = _login(client, u["username"]).json()["access_token"]
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "nope", "new_password": "Brand-New-Secret-77"},
        headers=_auth(tok),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Current password is incorrect"


def test_set_password_when_no_password(client):
    from app.core.auth import create_access_token

    u = _user(password=None, password_hash="!", signup_method="oauth")
    tok = create_access_token({"sub": u["username"], "uid": u["id"], "tv": 0})
    assert (
        client.get("/api/auth/me", headers=_auth(tok)).json()["has_password"] is False
    )
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "", "new_password": "Brand-New-Secret-77"},
        headers=_auth(tok),
    )
    assert r.status_code == 200
    new_tok = r.json()["access_token"]
    me = client.get("/api/auth/me", headers=_auth(new_tok)).json()
    assert me["has_password"] is True
    assert _login(client, u["username"], "Brand-New-Secret-77").status_code == 200


def test_has_password_account_needs_current_password(client):
    u = _user()
    tok = _login(client, u["username"]).json()["access_token"]
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "", "new_password": "Brand-New-Secret-77"},
        headers=_auth(tok),
    )
    assert r.status_code == 400


# ── email ────────────────────────────────────────────────────────────────────


def test_update_email_additive_response(client, monkeypatch):
    import sys

    # no account-email sender available → no link
    monkeypatch.setitem(sys.modules, "app.services.account_email", None)
    u = _user()
    tok = _login(client, u["username"]).json()["access_token"]
    email = f"{_name()}@example.com"
    r = client.put("/api/auth/email", json={"email": email}, headers=_auth(tok))
    assert r.status_code == 200
    assert r.json() == {
        "email": email,
        "email_verified": False,
        "verification_sent": False,
    }
    r = client.put("/api/auth/email", json={"email": ""}, headers=_auth(tok))
    assert r.json() == {
        "email": None,
        "email_verified": False,
        "verification_sent": False,
    }


def test_update_email_sends_link_when_available(client, monkeypatch):
    import sys
    import types

    sent = []

    async def send_account_email(kind, to, *, link, locale, username):
        sent.append((kind, to, link))
        return True

    fake_email = types.ModuleType("app.services.account_email")
    fake_email.email_delivery_available = lambda: True
    fake_email.send_account_email = send_account_email
    fake_tokens = types.ModuleType("app.db.account_tokens_db")
    fake_tokens.issue_token = lambda user_id, purpose, email: "tok123"
    monkeypatch.setitem(sys.modules, "app.services.account_email", fake_email)
    monkeypatch.setitem(sys.modules, "app.db.account_tokens_db", fake_tokens)

    u = _user()
    tok = _login(client, u["username"]).json()["access_token"]
    email = f"{_name()}@example.com"
    r = client.put("/api/auth/email", json={"email": email}, headers=_auth(tok))
    assert r.json() == {
        "email": email,
        "email_verified": False,
        "verification_sent": True,
    }
    assert len(sent) == 1
    kind, to, link = sent[0]
    assert kind == "verify" and to == email
    assert link.endswith("/verify?token=tok123")
    # unchanged email → nothing new is sent
    r = client.put("/api/auth/email", json={"email": email}, headers=_auth(tok))
    assert r.json()["verification_sent"] is False
    assert len(sent) == 1


# ── admin-set passwords ──────────────────────────────────────────────────────


def test_admin_temporary_password_follows_policy(client, admin_headers):
    r = client.post(
        "/api/admin/users",
        json={"username": _name(), "password": "password123"},
        headers=admin_headers,
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "password_common"
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]


def test_admin_reset_revokes_sessions(client, admin_headers):
    u = _user()
    s = _login(client, u["username"], client="ios").json()
    bad = client.post(
        f"/api/admin/users/{u['username']}/reset-password",
        json={"new_password": u["username"]},
        headers=admin_headers,
    )
    assert bad.json()["error_code"] == "password_matches_identity"
    r = client.post(
        f"/api/admin/users/{u['username']}/reset-password",
        json={"new_password": "Fresh-Temporary-42"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=_auth(s["access_token"]))
    assert me.json()["error_code"] == "session_revoked"
    rr = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert rr.json()["error_code"] == "refresh_invalid"


# ── login hardening ──────────────────────────────────────────────────────────


@pytest.fixture
def verify_spy(monkeypatch):
    from app.api.routes import auth as auth_routes

    calls = []
    real = auth_routes._verify

    def spy(password, hashed):
        calls.append(hashed)
        return real(password, hashed)

    monkeypatch.setattr(auth_routes, "_verify", spy)
    return calls, auth_routes._DUMMY_HASH


def test_unknown_login_runs_dummy_bcrypt(client, verify_spy):
    calls, dummy = verify_spy
    r = _login(client, "nobody-" + _name())
    assert r.status_code == 401
    assert calls == [dummy]


def test_inactive_and_passwordless_logins_run_dummy_bcrypt(client, verify_spy):
    calls, dummy = verify_spy
    u = _user()
    users_db.deactivate_user(u["username"])
    oauth = _user(password=None, password_hash="!", signup_method="oauth")
    assert _login(client, u["username"]).status_code == 401
    assert _login(client, oauth["username"], "anything-at-all").status_code == 401
    assert calls == [dummy, dummy]


def test_failure_lock_is_per_account_across_username_and_email(client, monkeypatch):
    from app.core import rate_limit
    from app.core.config import settings
    from app.core.rate_limit import SlidingWindowLimiter

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit, "limiter", SlidingWindowLimiter())
    monkeypatch.setattr(settings, "rate_limit_login", 99)
    monkeypatch.setattr(settings, "rate_limit_login_failures", 4)
    email = f"{_name()}@example.com"
    u = _user(email=email)
    idents = [u["username"], email.upper(), u["username"].upper(), email]
    assert [_login(client, i, "wrong-pass-123").status_code for i in idents] == [
        401
    ] * 4
    # locked at the limit, whichever identifier is used (even the right password)
    assert _login(client, u["username"]).status_code == 429
    assert _login(client, email).status_code == 429
