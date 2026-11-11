"""Task 27: native sign-up, email verification and password reset."""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.api.routes import signup as signup_routes
from app.core.config import settings
from app.db import invites_db, users_db
from app.services import account_email

PW = "Correct-Horse-Battery-9"
NEW_PW = "Another-Long-Phrase-42"


def _name() -> str:
    return "u" + uuid.uuid4().hex[:10]


def _email() -> str:
    return f"{_name()}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sent(monkeypatch):
    """Capture account emails; email delivery counts as available."""
    out: list[dict] = []

    async def fake(kind, to, *, link, locale, username):
        out.append(
            {"kind": kind, "to": to, "link": link, "locale": locale, "user": username}
        )
        return True

    monkeypatch.setattr(account_email, "send_account_email", fake)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "email_log_links", True)
    monkeypatch.setattr(settings, "signup_mode", "open")
    return out


@pytest.fixture
def clock(monkeypatch):
    class _Clock:
        now = datetime.now(UTC)

        def advance(self, seconds: float) -> None:
            self.now += timedelta(seconds=seconds)

    c = _Clock()
    monkeypatch.setattr(signup_routes, "_now", lambda: c.now)
    return c


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def _signup(tc, username=None, email=None, **extra):
    body = {"username": username or _name(), "email": email or _email(), "password": PW}
    body.update(extra)
    return tc.post("/api/auth/signup", json=body)


# ── sign-up + verify ─────────────────────────────────────────────────────────


def test_signup_verify_happy_path(client, sent):
    name, email = _name(), _email()
    r = _signup(client, name.upper(), email.upper(), display_name="Jane", locale="fr")
    assert r.status_code == 202, r.text
    assert r.json() == {
        "status": "verification_sent",
        "email": email,
        "expires_in": 1800,
    }
    user = users_db.get_user_by_email(email)
    assert user["username"] == name
    assert user["account_status"] == "pending"
    assert user["signup_method"] == "password"
    assert len(sent) == 1 and sent[0]["kind"] == "verify" and sent[0]["to"] == email
    assert sent[0]["locale"] == "fr"
    assert sent[0]["link"].split("?")[0].endswith("/verify")

    # pending: login is refused
    r = client.post("/api/auth/login", json={"username": name, "password": PW})
    assert r.status_code == 403 and r.json()["error_code"] == "account_pending"

    r = client.post(
        "/api/auth/verify-email",
        json={"token": _token(sent[0]["link"]), "client": "ios", "device_name": "X"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "verified"
    session = body["session"]
    assert session["refresh_token"].startswith("rt_")
    assert session["user"]["username"] == name
    assert session["user"]["account_verified"] is True
    assert session["user"]["display_name"] == "Jane"
    assert body["game"]["awards"][0]["rule"] == "email_verified"
    me = client.get("/api/auth/me", headers=_auth(session["access_token"]))
    assert me.status_code == 200 and me.json()["email_verified"] is True
    r = client.post("/api/auth/login", json={"username": email, "password": PW})
    assert r.status_code == 200


def test_verify_twice_is_token_used(client, sent):
    assert _signup(client).status_code == 202
    token = _token(sent[0]["link"])
    assert (
        client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    )
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 409 and r.json()["error_code"] == "token_used"


def test_verify_unknown_token_is_invalid(client, sent):
    r = client.post("/api/auth/verify-email", json={"token": "nope"})
    assert r.status_code == 400 and r.json()["error_code"] == "token_invalid"


def test_verify_expired_token(client, sent, clock):
    assert _signup(client).status_code == 202
    clock.advance(31 * 60)
    r = client.post("/api/auth/verify-email", json={"token": _token(sent[0]["link"])})
    assert r.status_code == 410 and r.json()["error_code"] == "token_expired"


def test_resend_invalidates_first_token(client, sent):
    email = _email()
    assert _signup(client, email=email).status_code == 202
    r = client.post("/api/auth/verify-email/resend", json={"email": email})
    assert r.status_code == 202 and r.json() == {"status": "verification_sent"}
    assert len(sent) == 2
    first, second = _token(sent[0]["link"]), _token(sent[1]["link"])
    r = client.post("/api/auth/verify-email", json={"token": first})
    assert r.status_code == 400 and r.json()["error_code"] == "token_invalid"
    r = client.post("/api/auth/verify-email", json={"token": second})
    assert r.status_code == 200


def test_resend_unknown_email_is_silent(client, sent):
    r = client.post("/api/auth/verify-email/resend", json={"email": _email()})
    assert r.status_code == 202 and r.json() == {"status": "verification_sent"}
    assert sent == []


def test_signup_existing_email_is_enumeration_safe(client, sent):
    email = _email()
    owner = users_db.create_user(_name(), PW, email=email, is_first_login=False)
    before = len(users_db.get_all_users())
    r = _signup(client, email=email)
    assert r.status_code == 202
    assert r.json() == {
        "status": "verification_sent",
        "email": email,
        "expires_in": 1800,
    }
    assert len(users_db.get_all_users()) == before
    assert [s["kind"] for s in sent] == ["already_registered"]
    assert sent[0]["to"] == email and sent[0]["user"] == owner["username"]


def test_signup_race_one_wins(client, sent):
    name = _name()
    results: list[int] = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        results.append(_signup(client, name).status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [202, 409]


def test_signup_username_taken_case_insensitive(client, sent):
    name = _name()
    users_db.create_user(name.upper(), PW)
    r = _signup(client, name)
    assert r.status_code == 409 and r.json()["error_code"] == "username_taken"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("username", "ab", "username_invalid"),
        ("username", "bad name", "username_invalid"),
        ("username", "Admin", "username_reserved"),
        ("email", "not-an-email", "email_invalid"),
        ("password", "short", "password_too_short"),
        ("password", "password123", "password_common"),
        ("display_name", "   ", "display_name_invalid"),
    ],
)
def test_signup_validation(client, sent, field, value, code):
    r = _signup(client, **{field: value})
    assert r.status_code == 422 and r.json()["error_code"] == code
    assert sent == []


def test_signup_password_matches_identity(client, sent):
    name = "u" + uuid.uuid4().hex[:12]
    r = _signup(client, name, password=name)
    assert r.status_code == 422
    assert r.json()["error_code"] == "password_matches_identity"


def test_invite_mode(client, sent, monkeypatch):
    monkeypatch.setattr(settings, "signup_mode", "invite")
    r = _signup(client)
    assert r.status_code == 403 and r.json()["error_code"] == "invite_required"
    r = _signup(client, invite_code="VOY-AAAA-BBBB")
    assert r.status_code == 403 and r.json()["error_code"] == "invite_invalid"
    invite = invites_db.create_invite(None, max_uses=1)
    email = _email()
    r = _signup(client, email=email, invite_code=invite["code"].lower())
    assert r.status_code == 202
    assert users_db.get_user_by_email(email)["invite_id"] == invite["id"]
    r = _signup(client, invite_code=invite["code"])  # used up
    assert r.status_code == 403 and r.json()["error_code"] == "invite_invalid"


def test_email_unavailable(client, monkeypatch):
    calls = []

    async def fake(*a, **k):
        calls.append(a)
        return True

    monkeypatch.setattr(account_email, "send_account_email", fake)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "email_log_links", False)
    monkeypatch.setattr(settings, "public_base_url", "https://voyager.example")
    r = _signup(client)
    assert r.status_code == 503 and r.json()["error_code"] == "email_unavailable"
    for path in ("/api/auth/verify-email/resend", "/api/auth/password-reset/request"):
        r = client.post(path, json={"email": _email()})
        assert r.status_code == 503 and r.json()["error_code"] == "email_unavailable"
    auth = client.get("/api/config").json()["auth"]
    assert auth["signup_available"] is False
    assert auth["password_reset_available"] is False
    assert calls == []


def test_signup_needs_operator_opt_in(client, sent, monkeypatch):
    """SMTP alone (set for fare alerts) never opens public sign-up: without
    SIGNUP_ENABLED it answers 503 email_unavailable and /config hides it,
    while password reset keeps working."""
    monkeypatch.setattr(settings, "signup_enabled", False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example")
    r = _signup(client)
    assert r.status_code == 503 and r.json()["error_code"] == "email_unavailable"
    auth = client.get("/api/config").json()["auth"]
    assert auth["signup_available"] is False
    assert auth["password_reset_available"] is True
    assert sent == []
    r = client.post("/api/auth/password-reset/request", json={"email": _email()})
    assert r.status_code == 202

    monkeypatch.setattr(settings, "signup_enabled", True)
    assert client.get("/api/config").json()["auth"]["signup_available"] is True
    assert _signup(client).status_code == 202


def test_signup_rate_limited(client, sent, monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_signup", 0)
    monkeypatch.setattr(rate_limit, "limiter", rate_limit.SlidingWindowLimiter())
    r = _signup(client)
    assert r.status_code == 429
    assert r.json()["error_code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1


def test_email_address_limit_is_silent(client, sent, monkeypatch):
    from app.core import rate_limit

    email = _email()
    assert _signup(client, email=email).status_code == 202
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_email_address", 1)
    monkeypatch.setattr(rate_limit, "limiter", rate_limit.SlidingWindowLimiter())
    for _ in range(3):
        r = client.post("/api/auth/verify-email/resend", json={"email": email})
        assert r.status_code == 202
    assert len(sent) == 2  # the sign-up + one resend


# ── password reset ───────────────────────────────────────────────────────────


def test_reset_revokes_other_sessions(client, sent):
    email = _email()
    u = users_db.create_user(_name(), PW, email=email, is_first_login=False)
    old = client.post(
        "/api/auth/login", json={"username": u["username"], "password": PW}
    )
    old_token = old.json()["access_token"]
    r = client.post("/api/auth/password-reset/request", json={"email": email.upper()})
    assert r.status_code == 202 and r.json() == {"status": "reset_sent"}
    assert sent[-1]["kind"] == "reset"
    assert sent[-1]["link"].split("?")[0].endswith("/reset-password")
    token = _token(sent[-1]["link"])
    # a rejected password doesn't use the token up
    r = client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": "x"}
    )
    assert r.status_code == 422 and r.json()["error_code"] == "password_too_short"
    r = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PW},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "password_reset"
    new_token = body["session"]["access_token"]
    r = client.get("/api/auth/me", headers=_auth(old_token))
    assert r.status_code == 401 and r.json()["error_code"] == "session_revoked"
    assert client.get("/api/auth/me", headers=_auth(new_token)).status_code == 200
    r = client.post(
        "/api/auth/login", json={"username": u["username"], "password": NEW_PW}
    )
    assert r.status_code == 200
    r = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PW},
    )
    assert r.status_code == 409 and r.json()["error_code"] == "token_used"


def test_reset_on_pending_account_activates_it(client, sent):
    name, email = _name(), _email()
    assert _signup(client, name, email).status_code == 202
    client.post("/api/auth/password-reset/request", json={"email": email})
    assert sent[-1]["kind"] == "reset"
    r = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": _token(sent[-1]["link"]), "new_password": NEW_PW},
    )
    assert r.status_code == 200
    user = users_db.get_user_by_email(email)
    assert user["account_status"] == "active" and user["email_verified"] is True
    assert r.json()["session"]["user"]["account_verified"] is True


def test_reset_request_unknown_email_sends_nothing(client, sent):
    r = client.post("/api/auth/password-reset/request", json={"email": _email()})
    assert r.status_code == 202 and r.json() == {"status": "reset_sent"}
    assert sent == []


# ── verify an active account's email ─────────────────────────────────────────


def _active_with_token(client, email):
    u = users_db.create_user(_name(), PW, email=email, is_first_login=False)
    tok = client.post(
        "/api/auth/login", json={"username": u["username"], "password": PW}
    ).json()["access_token"]
    return u, tok


def test_account_email_verify(client, sent):
    email = _email()
    u, tok = _active_with_token(client, email)
    r = client.post("/api/account/email/verify", json={}, headers=_auth(tok))
    assert r.status_code == 202
    assert r.json() == {
        "status": "verification_sent",
        "email": email,
        "expires_in": 1800,
    }
    r = client.post("/api/auth/verify-email", json={"token": _token(sent[-1]["link"])})
    assert r.status_code == 200
    assert r.json()["session"] is None
    assert r.json()["game"]["awards"][0]["rule"] == "email_verified"
    assert users_db.get_user_by_id(u["id"])["email_verified"] is True
    r = client.post("/api/account/email/verify", json={}, headers=_auth(tok))
    assert r.status_code == 409 and r.json()["error_code"] == "already_verified"


def test_account_email_verify_without_email(client, sent):
    _, tok = _active_with_token(client, None)
    r = client.post("/api/account/email/verify", json={}, headers=_auth(tok))
    assert r.status_code == 422 and r.json()["error_code"] == "no_email"


def test_verify_after_email_change(client, sent):
    email = _email()
    u, tok = _active_with_token(client, email)
    client.post("/api/account/email/verify", json={}, headers=_auth(tok))
    token = _token(sent[-1]["link"])
    users_db.set_email(u["username"], _email())
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 409 and r.json()["error_code"] == "email_changed"


# ── fix round 1 ──────────────────────────────────────────────────────────────


def test_resubmit_pending_signup_replaces_it(client, sent):
    name, email = _name(), _email()
    assert _signup(client, name, email).status_code == 202
    first = users_db.get_user_by_email(email)
    r = _signup(client, name, email)
    assert r.status_code == 202, r.text
    second = users_db.get_user_by_email(email)
    assert second["id"] != first["id"] and second["username"] == name
    assert [s["kind"] for s in sent] == ["verify", "verify"]
    r = client.post("/api/auth/verify-email", json={"token": _token(sent[0]["link"])})
    assert r.status_code == 400  # the replaced row's link is gone
    r = client.post("/api/auth/verify-email", json={"token": _token(sent[1]["link"])})
    assert r.status_code == 200


def test_pending_username_with_other_email_is_taken(client, sent):
    name = _name()
    assert _signup(client, name).status_code == 202
    r = _signup(client, name)  # another email
    assert r.status_code == 409 and r.json()["error_code"] == "username_taken"


def test_signup_race_loser_hits_db_guard(client, sent, monkeypatch):
    name = _name()
    assert _signup(client, name).status_code == 202
    monkeypatch.setattr(users_db, "username_available", lambda *a: True)
    r = _signup(client, name)
    assert r.status_code == 409 and r.json()["error_code"] == "username_taken"


def test_put_email_respects_address_limit(client, sent, monkeypatch):
    from app.core import rate_limit

    u = users_db.create_user(_name(), PW, is_first_login=False)
    tok = client.post(
        "/api/auth/login", json={"username": u["username"], "password": PW}
    ).json()["access_token"]
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_email_address", 3)
    monkeypatch.setattr(settings, "rate_limit_light_ai", 100)
    monkeypatch.setattr(rate_limit, "limiter", rate_limit.SlidingWindowLimiter())
    victim, own = _email(), _email()
    for _ in range(5):
        for addr in (victim, own):
            r = client.put("/api/auth/email", json={"email": addr}, headers=_auth(tok))
            assert r.status_code == 200
            assert r.json()["verification_sent"] is True
    assert sum(s["to"] == victim for s in sent) == 3
    assert all(s["kind"] == "verify" for s in sent)


def test_account_email_verify_unavailable(client, sent, monkeypatch):
    _, tok = _active_with_token(client, _email())
    monkeypatch.setattr(settings, "email_log_links", False)
    monkeypatch.setattr(settings, "public_base_url", "https://voyager.example")
    r = client.post("/api/account/email/verify", json={}, headers=_auth(tok))
    assert r.status_code == 503 and r.json()["error_code"] == "email_unavailable"


def test_reset_token_expired(client, sent, clock):
    email = _email()
    users_db.create_user(_name(), PW, email=email, is_first_login=False)
    client.post("/api/auth/password-reset/request", json={"email": email})
    clock.advance(31 * 60)
    r = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": _token(sent[-1]["link"]), "new_password": NEW_PW},
    )
    assert r.status_code == 410 and r.json()["error_code"] == "token_expired"
