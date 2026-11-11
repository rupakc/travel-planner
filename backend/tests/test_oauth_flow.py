"""OAuth authorization-code flow, handoff codes, linking and native ID tokens.
Providers are fakes installed through registry.override (no network)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.urls import public_url
from app.db import invites_db, oauth_db, users_db
from app.db.database import get_connection
from app.services.oauth import flow, registry
from app.services.oauth.base import OAuthError, ProviderProfile, pkce_challenge
from app.services.oauth.secrets_box import open_

BASE_FINAL = public_url("/auth/callback")


class FakeProvider:
    uses_pkce = True
    callback_methods = ("GET",)

    def __init__(self, pid, *, configured=True, native=False, secret=None):
        self.id = pid
        self._configured = configured
        self._native = native
        self.profile = None
        self.secret = secret
        self.error = None
        self.calls = []
        self.authorize_calls = []

    def configured(self):
        return self._configured

    def native_configured(self):
        return self._native

    def authorize_url(self, *, redirect_uri, state, nonce, code_challenge):
        self.authorize_calls.append(
            {"redirect_uri": redirect_uri, "state": state, "nonce": nonce,
             "code_challenge": code_challenge}
        )  # fmt: skip
        return "https://idp.example/authorize?" + urlencode({"state": state})

    async def exchange(self, *, code, redirect_uri, code_verifier, nonce, form):
        self.calls.append(
            {"code": code, "redirect_uri": redirect_uri,
             "code_verifier": code_verifier, "nonce": nonce, "form": dict(form)}
        )  # fmt: skip
        if self.error:
            raise OAuthError(self.error)
        return self.profile, self.secret

    async def verify_id_token(self, id_token, *, nonce):
        if id_token != "good":
            raise OAuthError("bad_request")
        return self.profile

    async def revoke(self, secret):
        return None


class FakeApple(FakeProvider):
    callback_methods = ("POST",)
    uses_pkce = False

    async def exchange(self, *, code, redirect_uri, code_verifier, nonce, form):
        await super().exchange(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier,
            nonce=nonce, form=form,
        )  # fmt: skip
        name = None
        if form.get("user"):
            n = json.loads(form["user"]).get("name", {})
            name = " ".join(x for x in (n.get("firstName"), n.get("lastName")) if x)
        from dataclasses import replace

        return replace(self.profile, display_name=name or None), self.secret

    async def verify_native(
        self, id_token, *, nonce, authorization_code=None, display_name=None
    ):
        self.native_calls = getattr(self, "native_calls", [])
        self.native_calls.append(
            {"id_token": id_token, "nonce": nonce, "code": authorization_code}
        )
        if id_token != "good":
            raise OAuthError("bad_request")
        secret = f"svc.native|rt-{authorization_code}" if authorization_code else None
        return self.profile, secret


def _profile(email=None, *, verified=True, trusted=True, name="Jane Doe", sub=None,
             picture=None):  # fmt: skip
    return ProviderProfile(
        subject=sub or uuid.uuid4().hex,
        email=email,
        email_verified=verified,
        email_trusted=trusted,
        display_name=name,
        picture_url=picture,
    )


def _email():
    return f"j{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture(autouse=True)
def providers(client, monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    fakes = {
        "apple": FakeApple("apple"),
        "google": FakeProvider("google", native=True),
        "facebook": FakeProvider("facebook"),
        "github": FakeProvider("github"),
    }
    for pid, fake in fakes.items():
        registry.override(pid, fake)
    yield fakes
    registry.clear_overrides()


@pytest.fixture
def c(client):
    from app.main import app

    return TestClient(app)


@pytest.fixture
def sent(monkeypatch):
    out = []

    async def fake_send(kind, to, *, link, locale, username):
        out.append({"kind": kind, "to": to, "link": link})
        return True

    monkeypatch.setattr("app.services.account_email.send_account_email", fake_send)
    return out


def _q(location):
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def _start(c, p="google", **params):
    r = c.get(f"/api/auth/oauth/{p}/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    return r


def _round_trip(c, p="google", method="GET", extra=None, **params):
    """start → callback; returns the final redirect's location."""
    r = _start(c, p, **params)
    loc = r.headers["location"]
    assert loc.startswith("https://idp.example/"), loc
    state = _q(loc)["state"]
    data = {"code": "provider-code", "state": state, **(extra or {})}
    if method == "POST":
        r = c.post(f"/api/auth/oauth/{p}/callback", data=data, follow_redirects=False)
    else:
        r = c.get(f"/api/auth/oauth/{p}/callback", params=data, follow_redirects=False)
    assert r.status_code == 302
    return r.headers["location"]


def _web_code(c, p="google", **params):
    loc = _round_trip(c, p, **params)
    assert loc.startswith(BASE_FINAL + "?"), loc
    q = _q(loc)
    assert "code" in q, loc
    return q["code"]


def _identity_rows(user_id):
    with get_connection() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM user_identities WHERE user_id = ?", (user_id,)
            )
        ]


def _verified_user(email):
    u = users_db.create_user(f"u{uuid.uuid4().hex[:8]}", "pw-1234567890", email=email)
    users_db.mark_email_verified(u["id"], email)
    return users_db.get_user_by_id(u["id"])


def _auth(user):
    return {
        "Authorization": "Bearer "
        + create_access_token({"sub": user["username"], "uid": user["id"]})
    }


# ── Web round trip ───────────────────────────────────────────────────────────


def test_web_round_trip(c, providers, sent, monkeypatch):
    photos = []

    async def fake_photo(user_id, url):
        photos.append((user_id, url))
        return True

    monkeypatch.setattr("app.services.avatar.import_provider_photo", fake_photo)
    g = providers["google"]
    email = _email()
    g.profile = _profile(email, picture="https://lh3.googleusercontent.com/a/x")

    r = _start(c, "google", return_to="/plans?x=1")
    cookie = r.headers["set-cookie"]
    assert "tp_oauth=" in cookie and "HttpOnly" in cookie
    assert "Path=/api/auth/oauth" in cookie and "Max-Age=600" in cookie
    assert "samesite=lax" in cookie.lower()
    call = g.authorize_calls[-1]
    assert call["redirect_uri"] == public_url("/api/auth/oauth/google/callback")
    state = _q(r.headers["location"])["state"]
    r = c.get(
        "/api/auth/oauth/google/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )
    q = _q(r.headers["location"])
    assert r.headers["location"].startswith(BASE_FINAL + "?code=")
    # PKCE: the provider got the verifier whose S256 challenge went to authorize
    assert pkce_challenge(g.calls[-1]["code_verifier"]) == call["code_challenge"]
    assert g.calls[-1]["nonce"] == call["nonce"]

    res = c.post("/api/auth/oauth/exchange", json={"code": q["code"], "client": "web"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "needs_username"
    assert body["email"] == email
    assert body["display_name"] == "Jane Doe"
    assert body["invite_required"] is False
    assert body["return_to"] == "/plans?x=1"
    assert body["suggested_username"] == email.split("@")[0]

    # the handoff code is single use
    again = c.post("/api/auth/oauth/exchange", json={"code": q["code"]})
    assert again.status_code == 400
    assert again.json()["error_code"] == "code_invalid"

    done = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": body["signup_token"], "username": "Jane_" + email[1:6]},
    )
    assert done.status_code == 201, done.text
    out = done.json()
    assert out["status"] == "signed_in"
    user = out["session"]["user"]
    assert user["username"] == ("jane_" + email[1:6]).lower()
    assert user["signup_method"] == "oauth"
    assert user["has_password"] is False
    assert user["email_verified"] is True and user["account_verified"] is True
    assert "refresh_token" not in out["session"]
    assert out["game"] is None or "awards" in out["game"]
    row = users_db.get_user_by_id(user["id"])
    assert row["password_hash"] == "!" and row["verified_at"]
    assert [i["provider"] for i in _identity_rows(user["id"])] == ["google"]
    assert photos == [(user["id"], "https://lh3.googleusercontent.com/a/x")]
    assert sent == []  # trusted email: no verify mail

    # the signup token is single use
    reuse = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": body["signup_token"], "username": "someone_else"},
    )
    assert reuse.json()["error_code"] == "signup_token_invalid"

    # the next sign-in with the same subject signs straight in
    code = _web_code(c, "google")
    res = c.post("/api/auth/oauth/exchange", json={"code": code}).json()
    assert res["status"] == "signed_in"
    assert res["session"]["user"]["id"] == user["id"]
    assert res["return_to"] == "/"
    assert "game" in res


def test_trusted_signup_awards_email_verified(c, providers, sent, monkeypatch):
    monkeypatch.setattr(settings, "game_enabled", True)
    providers["google"].profile = _profile(_email())
    body = c.post("/api/auth/oauth/exchange", json={"code": _web_code(c)}).json()
    out = c.post(
        "/api/auth/oauth/complete",
        json={
            "signup_token": body["signup_token"],
            "username": body["suggested_username"],
        },
    ).json()
    assert out["game"]["awards"][0]["rule"] == "email_verified"


def test_exchange_without_cookie_fails(c, providers):
    providers["google"].profile = _profile(_email())
    code = _web_code(c)
    c.cookies.clear()
    r = c.post("/api/auth/oauth/exchange", json={"code": code})
    assert r.status_code == 400
    assert r.json()["error_code"] == "code_invalid"


def test_wrong_cookie_fails(c, providers):
    providers["google"].profile = _profile(_email())
    code = _web_code(c)
    c.cookies.clear()
    c.cookies.set("tp_oauth", "forged", path="/api/auth/oauth")
    r = c.post("/api/auth/oauth/exchange", json={"code": code})
    assert r.json()["error_code"] == "code_invalid"


def test_complete_username_errors_keep_the_token(c, providers):
    _verified_user(f"x{uuid.uuid4().hex[:6]}@example.com")
    taken = users_db.create_user(f"tk{uuid.uuid4().hex[:6]}", "pw-1234567890")
    providers["google"].profile = _profile(_email())
    body = c.post("/api/auth/oauth/exchange", json={"code": _web_code(c)}).json()
    tok = body["signup_token"]
    r = c.post("/api/auth/oauth/complete", json={"signup_token": tok, "username": "a!"})
    assert (r.status_code, r.json()["error_code"]) == (422, "username_invalid")
    r = c.post(
        "/api/auth/oauth/complete", json={"signup_token": tok, "username": "admin"}
    )
    assert (r.status_code, r.json()["error_code"]) == (422, "username_reserved")
    r = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": tok, "username": taken["username"].upper()},
    )
    assert (r.status_code, r.json()["error_code"]) == (409, "username_taken")
    r = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": tok, "username": f"ok_{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 201


# ── Mobile ───────────────────────────────────────────────────────────────────


def test_mobile_requires_challenge_and_verifier(c, providers):
    providers["github"].profile = _profile(_email())
    r = _start(c, "github", client="ios")
    assert r.headers["location"] == BASE_FINAL + "?error=bad_request"
    r = _start(c, "github", client="ios", challenge="short")
    assert _q(r.headers["location"])["error"] == "bad_request"

    verifier = "v" * 43
    challenge = pkce_challenge(verifier)
    loc = _round_trip(
        c, "github", client="ios", challenge=challenge,
        redirect_uri="voyager://auth/callback",
    )  # fmt: skip
    assert loc.startswith("voyager://auth/callback?code=")
    code = _q(loc)["code"]
    c.cookies.clear()  # the app has no browser cookie
    r = c.post("/api/auth/oauth/exchange", json={"code": code, "verifier": "w" * 43})
    assert (r.status_code, r.json()["error_code"]) == (400, "code_invalid")
    # a failed attempt burns the code
    r = c.post("/api/auth/oauth/exchange", json={"code": code, "verifier": verifier})
    assert r.status_code == 400
    r = c.post("/api/auth/oauth/exchange", json={"code": code})
    assert r.status_code == 400

    loc = _round_trip(c, "github", client="android", challenge=challenge)
    assert loc.startswith(BASE_FINAL + "?code=")
    c.cookies.clear()
    r = c.post(
        "/api/auth/oauth/exchange",
        json={"code": _q(loc)["code"], "verifier": verifier},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "needs_username"
    out = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": r.json()["signup_token"], "client": "android",
              "username": f"m_{uuid.uuid4().hex[:8]}", "device_name": "Pixel"},
    ).json()  # fmt: skip
    assert out["session"]["refresh_token"].startswith("rt_")
    assert out["session"]["expires_in"] == 3600


def test_mobile_redirect_allowlist(c, providers):
    challenge = pkce_challenge("v" * 43)
    for bad in ("evil://auth/callback", "https://evil.com/auth/callback",
                "voyager://auth/callback/extra"):  # fmt: skip
        r = _start(c, "google", client="ios", challenge=challenge, redirect_uri=bad)
        assert r.headers["location"] == BASE_FINAL + "?error=bad_request"
        assert "set-cookie" not in r.headers
    r = _start(c, "google", client="ios", challenge=challenge, redirect_uri=BASE_FINAL)
    assert r.headers["location"].startswith("https://idp.example/")
    # an unconfigured provider reports to the app's own redirect
    providers["facebook"]._configured = False
    r = _start(
        c, "facebook", client="ios", challenge=challenge,
        redirect_uri="voyager://auth/callback",
    )  # fmt: skip
    assert r.headers["location"] == "voyager://auth/callback?error=provider_unavailable"


# ── State ────────────────────────────────────────────────────────────────────


def test_state_single_use_and_10_min_expiry(c, providers, monkeypatch):
    providers["google"].profile = _profile(_email())
    state = _q(_start(c).headers["location"])["state"]
    cb = {"code": "x", "state": state}
    r = c.get("/api/auth/oauth/google/callback", params=cb, follow_redirects=False)
    assert "code=" in r.headers["location"]
    r = c.get("/api/auth/oauth/google/callback", params=cb, follow_redirects=False)
    assert r.headers["location"] == BASE_FINAL + "?error=state_invalid"

    state = _q(_start(c).headers["location"])["state"]
    later = datetime.now(UTC) + timedelta(seconds=601)
    monkeypatch.setattr("app.api.routes.oauth._now", lambda: later)
    r = c.get(
        "/api/auth/oauth/google/callback",
        params={"code": "x", "state": state},
        follow_redirects=False,
    )
    assert r.headers["location"] == BASE_FINAL + "?error=state_invalid"

    # a state issued for one provider is not accepted by another
    monkeypatch.undo()
    state = _q(_start(c, "google").headers["location"])["state"]
    r = c.get(
        "/api/auth/oauth/github/callback",
        params={"code": "x", "state": state},
        follow_redirects=False,
    )
    assert r.headers["location"] == BASE_FINAL + "?error=state_invalid"


def test_handoff_expires_after_120_s(c, providers, monkeypatch):
    providers["google"].profile = _profile(_email())
    code = _web_code(c)
    later = datetime.now(UTC) + timedelta(seconds=121)
    monkeypatch.setattr("app.api.routes.oauth._now", lambda: later)
    r = c.post("/api/auth/oauth/exchange", json={"code": code})
    assert r.json()["error_code"] == "code_invalid"


def test_provider_errors_redirect(c, providers):
    state = _q(_start(c).headers["location"])["state"]
    r = c.get(
        "/api/auth/oauth/google/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )
    assert r.headers["location"] == BASE_FINAL + "?error=cancelled"
    providers["google"].error = "provider_error"
    loc = _round_trip(c)
    assert loc == BASE_FINAL + "?error=provider_error"
    # an unexpected adapter crash is still a redirect, never a 5xx
    providers["google"].error = None
    providers["google"].profile = None  # resolve_identity will blow up
    loc = _round_trip(c)
    assert loc == BASE_FINAL + "?error=provider_error"


# ── Linking rules ────────────────────────────────────────────────────────────


def test_pending_native_account_is_replaced_not_linked(c, providers):
    email = _email()
    pending = users_db.create_pending_user(
        f"p{uuid.uuid4().hex[:8]}", email, "pw-1234567890", None, None, None
    )
    providers["google"].profile = _profile(email)
    body = c.post("/api/auth/oauth/exchange", json={"code": _web_code(c)}).json()
    assert body["status"] == "needs_username"
    assert users_db.get_user_by_id(pending["id"]) is None
    assert _identity_rows(pending["id"]) == []
    out = c.post(
        "/api/auth/oauth/complete",
        json={
            "signup_token": body["signup_token"],
            "username": f"n_{uuid.uuid4().hex[:8]}",
        },
    ).json()
    assert out["session"]["user"]["email"] == email
    assert out["session"]["user"]["id"] != pending["id"]


def test_untrusted_email_never_links(c, providers, sent):
    email = _email()
    owner = _verified_user(email)
    fb = providers["facebook"]
    fb.profile = _profile(email, trusted=False)
    loc = _round_trip(c, "facebook")
    assert loc == BASE_FINAL + "?error=email_in_use_unverified"
    assert _identity_rows(owner["id"]) == []

    # a new untrusted email makes an unverified account and sends a verify mail
    email2 = _email()
    fb.profile = _profile(email2, trusted=False)
    body = c.post(
        "/api/auth/oauth/exchange", json={"code": _web_code(c, "facebook")}
    ).json()
    out = c.post(
        "/api/auth/oauth/complete",
        json={
            "signup_token": body["signup_token"],
            "username": f"f_{uuid.uuid4().hex[:8]}",
        },
    ).json()
    user = out["session"]["user"]
    assert user["email"] == email2
    assert user["email_verified"] is False and user["account_verified"] is False
    assert [s["kind"] for s in sent] == ["verify"]
    assert sent[0]["to"] == email2
    assert sent[0]["link"].startswith(public_url("/verify?token="))


def test_unverified_existing_email_is_refused(c, providers):
    email = _email()
    admin_made = users_db.create_user(
        f"a{uuid.uuid4().hex[:8]}", "pw-1234567890", email=email
    )
    providers["google"].profile = _profile(email)
    assert _round_trip(c) == BASE_FINAL + "?error=email_in_use_unverified"
    assert _identity_rows(admin_made["id"]) == []


def test_trusted_email_links_verified_account(c, providers):
    email = _email()
    owner = _verified_user(email)
    providers["google"].profile = _profile(email.upper())
    res = c.post("/api/auth/oauth/exchange", json={"code": _web_code(c)}).json()
    assert res["status"] == "signed_in"
    assert res["session"]["user"]["id"] == owner["id"]
    assert [i["provider"] for i in _identity_rows(owner["id"])] == ["google"]


def test_inactive_user_is_refused(c, providers):
    email = _email()
    owner = _verified_user(email)
    users_db.deactivate_user(owner["username"])
    providers["google"].profile = _profile(email)
    assert _round_trip(c) == BASE_FINAL + "?error=account_inactive"


def test_link_ticket_attaches_identity(c, providers):
    user = _verified_user(_email())
    gh = providers["github"]
    gh.profile = _profile("other@example.org", name="Octo")
    r = c.post(
        "/api/auth/oauth/link-ticket", json={"provider": "github", "client": "web"},
        headers=_auth(user),
    )  # fmt: skip
    assert r.status_code == 200
    start_url = r.json()["start_url"]
    assert start_url.startswith("/api/auth/oauth/github/start?link=")
    assert start_url.endswith("&client=web")
    r = c.get(start_url, follow_redirects=False)
    state = _q(r.headers["location"])["state"]
    r = c.get(
        "/api/auth/oauth/github/callback",
        params={"code": "x", "state": state},
        follow_redirects=False,
    )
    res = c.post(
        "/api/auth/oauth/exchange", json={"code": _q(r.headers["location"])["code"]}
    )
    assert res.json() == {
        "status": "linked",
        "provider": "github",
        "return_to": "/account",
    }
    rows = _identity_rows(user["id"])
    assert [(i["provider"], i["email"]) for i in rows] == [
        ("github", "other@example.org")
    ]
    # the ticket is single use
    r = c.get(start_url, follow_redirects=False)
    assert r.headers["location"] == BASE_FINAL + "?error=bad_request"


def test_link_ticket_errors(c, providers):
    user = _verified_user(_email())
    h = _auth(user)
    r = c.post("/api/auth/oauth/link-ticket", json={"provider": "myspace"}, headers=h)
    assert (r.status_code, r.json()["error_code"]) == (404, "provider_unknown")
    providers["github"]._configured = False
    r = c.post("/api/auth/oauth/link-ticket", json={"provider": "github"}, headers=h)
    assert (r.status_code, r.json()["error_code"]) == (409, "provider_unavailable")
    assert (
        c.post("/api/auth/oauth/link-ticket", json={"provider": "google"}).status_code
        == 401
    )
    # a ticket for one provider can't start another
    tick = c.post(
        "/api/auth/oauth/link-ticket", json={"provider": "google"}, headers=h
    ).json()["start_url"]
    ticket = parse_qs(urlparse(tick).query)["link"][0]
    r = _start(c, "facebook", link=ticket)
    assert r.headers["location"] == BASE_FINAL + "?error=bad_request"


def test_identity_in_use(c, providers):
    sub = uuid.uuid4().hex
    a = _verified_user(_email())
    oauth_db.add_identity(a["id"], "github", sub, email=None, email_verified=False,
                          display_name=None, picture_url=None, secret_enc=None)  # fmt: skip
    b = _verified_user(_email())
    providers["github"].profile = _profile(None, sub=sub)
    url = c.post(
        "/api/auth/oauth/link-ticket", json={"provider": "github"}, headers=_auth(b)
    ).json()["start_url"]
    state = _q(c.get(url, follow_redirects=False).headers["location"])["state"]
    r = c.get(
        "/api/auth/oauth/github/callback",
        params={"code": "x", "state": state},
        follow_redirects=False,
    )
    assert r.headers["location"] == BASE_FINAL + "?error=identity_in_use"
    assert _identity_rows(b["id"]) == []


# ── Availability ─────────────────────────────────────────────────────────────


def test_unconfigured_provider_redirects_with_provider_unavailable(c, providers):
    for p in registry.PROVIDER_ORDER:
        registry.override(p, None)
    for p in registry.PROVIDER_ORDER:
        r = _start(c, p)
        assert r.headers["location"] == BASE_FINAL + "?error=provider_unavailable"
        r = c.get(f"/api/auth/oauth/{p}/callback", params={"code": "x", "state": "y"},
                  follow_redirects=False)  # fmt: skip
        assert r.status_code == 302
        r = c.post(f"/api/auth/oauth/{p}/callback", data={"code": "x"},
                   follow_redirects=False)  # fmt: skip
        assert r.status_code == 302
    listing = c.get("/api/auth/providers").json()["providers"]
    assert all(not p["configured"] and p["start_url"] is None for p in listing)
    assert all(p["id_token"] is False for p in listing)
    assert (
        c.get("/api/auth/oauth/myspace/start", follow_redirects=False).status_code
        == 404
    )
    r = c.post(
        "/api/auth/oauth/apple/id-token", json={"id_token": "good", "client": "ios"}
    )
    assert r.status_code == 404

    # configured at start, removed before the callback
    fake = FakeProvider("google")
    fake.profile = _profile(_email())
    registry.override("google", fake)
    state = _q(_start(c).headers["location"])["state"]
    fake._configured = False
    r = c.get("/api/auth/oauth/google/callback", params={"code": "x", "state": state},
              follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == BASE_FINAL + "?error=provider_unavailable"


def test_broken_provider_never_5xx(c, providers):
    class Broken(FakeProvider):
        def configured(self):
            raise RuntimeError("boom")

    registry.override("github", Broken("github"))
    r = _start(c, "github")
    assert r.headers["location"] == BASE_FINAL + "?error=provider_unavailable"
    listing = {p["id"]: p for p in c.get("/api/auth/providers").json()["providers"]}
    assert listing["github"]["configured"] is False


def test_providers_listing_order_and_flags(c, providers, caplog):
    providers["facebook"]._configured = False
    providers["apple"]._native = True
    import app.api.routes.oauth as routes

    routes._logged_config = False
    with caplog.at_level("INFO", logger="app.api.routes.oauth"):
        body = c.get("/api/auth/providers").json()
        c.get("/api/auth/providers")
    assert body == {
        "providers": [
            {"id": "apple", "configured": True, "start_url": "/api/auth/oauth/apple/start", "id_token": True},
            {"id": "google", "configured": True, "start_url": "/api/auth/oauth/google/start", "id_token": True},
            {"id": "facebook", "configured": False, "start_url": None, "id_token": False},
            {"id": "github", "configured": True, "start_url": "/api/auth/oauth/github/start", "id_token": False},
        ]
    }  # fmt: skip
    lines = [
        r.getMessage() for r in caplog.records if "oauth.configured" in r.getMessage()
    ]
    assert len(lines) == 1
    assert "'apple', 'google', 'github'" in lines[0]
    assert public_url("/api/auth/oauth/github/callback") in lines[0]


# ── Apple ────────────────────────────────────────────────────────────────────


def test_apple_form_post_callback(c, providers):
    apple = providers["apple"]
    apple.profile = _profile(_email(), name=None)
    apple.secret = "apple-refresh-token"
    user_json = json.dumps({"name": {"firstName": "Jane", "lastName": "Appleseed"}})
    loc = _round_trip(c, "apple", method="POST", extra={"user": user_json})
    assert loc.startswith(BASE_FINAL + "?code=")
    assert apple.calls[-1]["form"]["user"] == user_json
    body = c.post("/api/auth/oauth/exchange", json={"code": _q(loc)["code"]}).json()
    assert body["display_name"] == "Jane Appleseed"
    out = c.post(
        "/api/auth/oauth/complete",
        json={
            "signup_token": body["signup_token"],
            "username": f"ap_{uuid.uuid4().hex[:8]}",
        },
    ).json()
    rows = _identity_rows(out["session"]["user"]["id"])
    assert out["session"]["user"]["display_name"] == "Jane Appleseed"
    assert rows[0]["secret_enc"] and "apple-refresh-token" not in rows[0]["secret_enc"]
    assert open_(rows[0]["secret_enc"]) == "apple-refresh-token"


def test_native_apple_id_token_stores_sealed_secret(c, providers):
    apple = providers["apple"]
    apple._native = True
    email = _email()
    apple.profile = _profile(email, name=None)
    r = c.post(
        "/api/auth/oauth/apple/id-token",
        json={"id_token": "good", "nonce": "raw-nonce", "authorization_code": "ac1",
              "display_name": "Jane", "client": "ios", "device_name": "iPhone"},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "needs_username" and body["display_name"] == "Jane"
    assert apple.native_calls[-1] == {
        "id_token": "good",
        "nonce": "raw-nonce",
        "code": "ac1",
    }
    out = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": body["signup_token"], "client": "ios",
              "username": f"na_{uuid.uuid4().hex[:8]}"},
    ).json()  # fmt: skip
    assert out["session"]["refresh_token"]
    row = _identity_rows(out["session"]["user"]["id"])[0]
    assert open_(row["secret_enc"]) == "svc.native|rt-ac1"

    # a later native sign-in signs in and refreshes the stored secret
    r = c.post(
        "/api/auth/oauth/apple/id-token",
        json={"id_token": "good", "authorization_code": "ac2", "client": "ios"},
    ).json()
    assert r["status"] == "signed_in"
    row = _identity_rows(out["session"]["user"]["id"])[0]
    assert open_(row["secret_enc"]) == "svc.native|rt-ac2"

    bad = c.post(
        "/api/auth/oauth/apple/id-token", json={"id_token": "bad", "client": "ios"}
    )
    assert (bad.status_code, bad.json()["error_code"]) == (400, "id_token_invalid")


def test_native_google_id_token(c, providers):
    email = _email()
    owner = _verified_user(email)
    providers["google"].profile = _profile(email)
    r = c.post(
        "/api/auth/oauth/google/id-token",
        json={"id_token": "good", "client": "android"},
    )
    body = r.json()
    assert (
        body["status"] == "signed_in" and body["session"]["user"]["id"] == owner["id"]
    )
    assert body["session"]["refresh_token"]
    # web clients can't use the native route; github has none
    assert c.post("/api/auth/oauth/google/id-token",
                  json={"id_token": "good", "client": "web"}).status_code == 422  # fmt: skip
    assert c.post("/api/auth/oauth/github/id-token",
                  json={"id_token": "good", "client": "ios"}).status_code == 404  # fmt: skip


# ── return_to ────────────────────────────────────────────────────────────────


def test_return_to_rejects_offsite(c, providers):
    for bad in ("//evil.com", "https://evil.com", "/\\evil.com", "evil"):
        r = _start(c, "google", return_to=bad)
        assert r.headers["location"] == BASE_FINAL + "?error=bad_request", bad
        assert "evil" not in r.headers["location"]
    providers["google"].profile = _profile(_email())
    code = _web_code(c, "google")  # no return_to → "/"
    assert (
        c.post("/api/auth/oauth/exchange", json={"code": code}).json()["return_to"]
        == "/"
    )


# ── Invite mode ──────────────────────────────────────────────────────────────


def test_invite_mode(c, providers, monkeypatch):
    monkeypatch.setattr(settings, "signup_mode", "invite")
    providers["google"].profile = _profile(_email())
    body = c.post("/api/auth/oauth/exchange", json={"code": _web_code(c)}).json()
    assert body["invite_required"] is True
    tok = body["signup_token"]
    name = f"i_{uuid.uuid4().hex[:8]}"
    r = c.post("/api/auth/oauth/complete", json={"signup_token": tok, "username": name})
    assert (r.status_code, r.json()["error_code"]) == (403, "invite_required")
    r = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": tok, "username": name, "invite_code": "VOY-NOPE-NOPE"},
    )
    assert (r.status_code, r.json()["error_code"]) == (403, "invite_invalid")
    inv = invites_db.create_invite(None, max_uses=1)
    r = c.post(
        "/api/auth/oauth/complete",
        json={"signup_token": tok, "username": name, "invite_code": inv["code"]},
    )
    assert r.status_code == 201
    assert invites_db.check_invite(inv["code"]) is None  # consumed
    uid = r.json()["session"]["user"]["id"]
    assert users_db.get_user_by_id(uid)["invite_id"] == inv["id"]


# ── Units ────────────────────────────────────────────────────────────────────


def test_suggest_username(client):
    assert flow.suggest_username("Ünïcode.Name+tag@x.com", None) == "unicode_name_tag"
    assert flow.suggest_username(None, "Jo") == "jo0"
    assert flow.suggest_username(None, None) == "traveller"
    assert flow.suggest_username("!!!@x.com", "Zoë Q") == "zoe_q"
    assert flow.suggest_username("admin@x.com", None) == "admin_2"  # reserved + taken
    assert flow.suggest_username("a" * 40 + "@x.com", None) == "a" * 20
    base = f"dup{uuid.uuid4().hex[:6]}"
    users_db.create_user(base, "pw-1234567890")
    assert flow.suggest_username(f"{base}@x.com", None) == f"{base}_2"
    users_db.create_user(f"{base}_2", "pw-1234567890")
    assert flow.suggest_username(f"{base}@x.com", None) == f"{base}_3"


def test_tickets_are_single_use_and_hashed(client):
    tok = oauth_db.put_ticket("link", ttl_s=60, provider="github", user_id="u1")
    with get_connection() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM oauth_tickets WHERE hash = ?", (tok,)
            ).fetchone()
            is None
        )
    now = datetime.now(UTC)
    assert oauth_db.take_ticket("state", tok, now) is None  # wrong kind
    assert oauth_db.take_ticket("link", tok, now)["user_id"] == "u1"
    assert oauth_db.take_ticket("link", tok, now) is None
    tok2 = oauth_db.put_ticket("link", ttl_s=60)
    assert oauth_db.take_ticket("link", tok2, now + timedelta(seconds=61)) is None
