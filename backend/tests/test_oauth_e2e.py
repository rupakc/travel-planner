"""End-to-end OAuth for every provider: the REAL adapters (no registry.override)
with fake credentials, every provider call routed through a FakeIdP transport
that mimics that provider's token, profile and JWKS endpoints.

start → provider redirect → callback → exchange → complete → /api/auth/me,
plus Apple and Google native ID-token sign-in."""

import hashlib
import hmac
import json
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.urls import public_url
from app.db.database import get_connection
from app.services.oauth import base, jwks, registry
from app.services.oauth.base import pkce_challenge
from app.services.oauth.secrets_box import open_
from tests.oauth_fakes import FakeIdP

WEB_FINAL = public_url("/auth/callback")

# Freshly generated for this run; never a real key.
_APPLE_KEY = ec.generate_private_key(ec.SECP256R1())
APPLE_PEM = _APPLE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode("ascii")
APPLE_PUBLIC = _APPLE_KEY.public_key()


def _q(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _split(url: str) -> tuple[str, dict]:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}", _q(url)


def _form(req: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


def _uniq() -> str:
    return uuid.uuid4().hex[:10]


def _identity(provider: str, subject: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_identities WHERE provider = ? AND subject = ?",
            (provider, subject),
        ).fetchone()
    assert row is not None
    return dict(row)


@pytest.fixture(autouse=True)
def real_adapters(client, monkeypatch):
    registry.clear_overrides()
    jwks.clear_cache()
    monkeypatch.setattr(settings, "game_enabled", False)
    monkeypatch.setattr(settings, "signup_mode", "open")
    yield
    base.set_transport(None)
    jwks.clear_cache()
    registry.clear_overrides()


@pytest.fixture
def c(client):
    from app.main import app

    return TestClient(app)


@pytest.fixture
def side_effects(monkeypatch):
    out = {"mail": [], "photos": []}

    async def fake_send(kind, to, *, link, locale, username):
        out["mail"].append({"kind": kind, "to": to})
        return True

    async def fake_photo(user_id, url):
        out["photos"].append((user_id, url))
        return True

    monkeypatch.setattr("app.services.account_email.send_account_email", fake_send)
    monkeypatch.setattr("app.services.avatar.import_provider_photo", fake_photo)
    return out


def _start(c, p, **params) -> tuple[str, dict]:
    r = c.get(f"/api/auth/oauth/{p}/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    return _split(r.headers["location"])


def _callback(c, p, *, method="GET", **data) -> dict:
    url = f"/api/auth/oauth/{p}/callback"
    if method == "POST":
        r = c.post(url, data=data, follow_redirects=False)
    else:
        r = c.get(url, params=data, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(WEB_FINAL + "?"), loc
    q = _q(loc)
    assert "code" in q, loc
    return q


def _complete(c, body, **extra) -> dict:
    assert body["status"] == "needs_username", body
    r = c.post(
        "/api/auth/oauth/complete",
        json={
            "signup_token": body["signup_token"],
            "username": "e2e_" + _uniq(),
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "signed_in"
    return out


def _me(c, session) -> dict:
    r = c.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {session['access_token']}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── Google ───────────────────────────────────────────────────────────────────

G_CLIENT = "g-web.apps.googleusercontent.com"
G_ANDROID = "g-android.apps.googleusercontent.com"
G_TOKEN = "https://oauth2.googleapis.com/token"
G_JWKS = "https://www.googleapis.com/oauth2/v3/certs"


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", G_CLIENT)
    monkeypatch.setattr(settings, "google_client_secret", "g-secret")
    monkeypatch.setattr(settings, "google_native_client_ids", [G_ANDROID])
    idp = FakeIdP("https://accounts.google.com", G_CLIENT)
    idp.token_requests = []
    idp.claims = {}

    def token(req):
        form = _form(req)
        idp.token_requests.append(form)
        return {
            "access_token": "g-at",
            "token_type": "Bearer",
            "expires_in": 3599,
            "id_token": idp.id_token(**idp.claims),
        }

    base.set_transport(idp.transport({G_TOKEN: token, G_JWKS: lambda _r: idp.jwks()}))
    return idp


def test_google_web_flow(c, google, side_effects):
    url, params = _start(c, "google", return_to="/plans")
    assert url == "https://accounts.google.com/o/oauth2/v2/auth"
    callback = public_url("/api/auth/oauth/google/callback")
    assert params["client_id"] == G_CLIENT
    assert params["redirect_uri"] == callback
    assert params["response_type"] == "code"
    assert params["scope"] == "openid email profile"
    assert params["code_challenge_method"] == "S256"
    assert params["state"] and params["nonce"]

    sub, email = "g-" + _uniq(), f"g{_uniq()}@gmail.com"
    google.claims = dict(
        sub=sub,
        nonce=params["nonce"],
        email=email,
        email_verified=True,
        name="Grace Hopper",
        picture="https://lh3.googleusercontent.com/a/gh",
    )
    q = _callback(c, "google", code="g-code", state=params["state"])

    form = google.token_requests[-1]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "g-code"
    assert form["redirect_uri"] == callback
    assert form["client_id"] == G_CLIENT
    assert form["client_secret"] == "g-secret"
    assert pkce_challenge(form["code_verifier"]) == params["code_challenge"]

    body = c.post("/api/auth/oauth/exchange", json={"code": q["code"]}).json()
    assert body["email"] == email and body["display_name"] == "Grace Hopper"
    assert body["return_to"] == "/plans"
    out = _complete(c, body)
    me = _me(c, out["session"])
    assert me["id"] == out["session"]["user"]["id"]
    assert me["email"] == email and me["email_verified"] is True
    assert me["signup_method"] == "oauth"
    assert side_effects["mail"] == []
    assert side_effects["photos"] == [(me["id"], google.claims["picture"])]
    assert _identity("google", sub)["user_id"] == me["id"]

    # second sign-in with the same subject goes straight in
    _, params = _start(c, "google")
    google.claims["nonce"] = params["nonce"]
    q = _callback(c, "google", code="g-code-2", state=params["state"])
    res = c.post("/api/auth/oauth/exchange", json={"code": q["code"]}).json()
    assert res["status"] == "signed_in"
    assert _me(c, res["session"])["id"] == me["id"]


def test_google_web_rejects_wrong_nonce(c, google):
    _, params = _start(c, "google")
    google.claims = dict(sub="g-" + _uniq(), nonce="not-the-nonce")
    r = c.get(
        "/api/auth/oauth/google/callback",
        params={"code": "x", "state": params["state"]},
        follow_redirects=False,
    )
    assert _q(r.headers["location"]) == {"error": "provider_error"}


def test_google_native_id_token(c, google, side_effects):
    sub, email = "g-" + _uniq(), f"g{_uniq()}@gmail.com"
    token = google.id_token(
        aud=G_ANDROID, sub=sub, nonce="raw-nonce", email=email, email_verified="true"
    )
    r = c.post(
        "/api/auth/oauth/google/id-token",
        json={"id_token": token, "nonce": "raw-nonce", "client": "android"},
    )
    assert r.status_code == 200, r.text
    out = _complete(c, r.json(), client="android", device_name="Pixel")
    assert out["session"]["refresh_token"]
    me = _me(c, out["session"])
    assert me["email"] == email and me["email_verified"] is True
    assert _identity("google", sub)["secret_enc"] is None

    # the web client id is not a native audience
    web_token = google.id_token(aud=G_CLIENT, sub=sub, nonce="raw-nonce")
    r = c.post(
        "/api/auth/oauth/google/id-token",
        json={"id_token": web_token, "nonce": "raw-nonce", "client": "android"},
    )
    assert r.status_code == 400 and r.json()["error_code"] == "id_token_invalid"

    # next native sign-in returns a session directly
    again = google.id_token(aud=G_ANDROID, sub=sub, nonce="n2")
    r = c.post(
        "/api/auth/oauth/google/id-token",
        json={"id_token": again, "nonce": "n2", "client": "android"},
    )
    assert r.status_code == 200 and r.json()["status"] == "signed_in"
    assert _me(c, r.json()["session"])["id"] == me["id"]


# ── GitHub ───────────────────────────────────────────────────────────────────

GH_TOKEN = "https://github.com/login/oauth/access_token"
GH_USER = "https://api.github.com/user"
GH_EMAILS = "https://api.github.com/user/emails"


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setattr(settings, "github_client_id", "gh-client")
    monkeypatch.setattr(settings, "github_client_secret", "gh-secret")
    idp = FakeIdP("https://github.com", "gh-client")
    idp.token_requests = []
    idp.api_auth = []
    idp.user = {}
    idp.emails = []

    def token(req):
        assert req.method == "POST"
        assert req.headers["accept"] == "application/json"
        idp.token_requests.append(_form(req))
        return {"access_token": "gho_fake", "token_type": "bearer", "scope": ""}

    def api(payload_attr):
        def handler(req):
            idp.api_auth.append(req.headers.get("authorization"))
            return getattr(idp, payload_attr)

        return handler

    base.set_transport(
        idp.transport({GH_TOKEN: token, GH_USER: api("user"), GH_EMAILS: api("emails")})
    )
    return idp


def test_github_web_flow(c, github, side_effects):
    url, params = _start(c, "github")
    assert url == "https://github.com/login/oauth/authorize"
    callback = public_url("/api/auth/oauth/github/callback")
    assert params["client_id"] == "gh-client"
    assert params["redirect_uri"] == callback
    assert params["scope"] == "read:user user:email"
    assert params["code_challenge_method"] == "S256"

    gid, email = 9_000_000 + int(_uniq()[:6], 16), f"gh{_uniq()}@example.com"
    github.user = {
        "id": gid,
        "login": "octo",
        "name": None,
        "avatar_url": "https://avatars.githubusercontent.com/u/1",
    }
    github.emails = [
        {"email": f"other{_uniq()}@example.com", "verified": True, "primary": False},
        {"email": email, "verified": True, "primary": True},
    ]
    q = _callback(c, "github", code="gh-code", state=params["state"])
    form = github.token_requests[-1]
    assert form["code"] == "gh-code"
    assert form["redirect_uri"] == callback
    assert form["client_secret"] == "gh-secret"
    assert pkce_challenge(form["code_verifier"]) == params["code_challenge"]
    assert github.api_auth == ["Bearer gho_fake", "Bearer gho_fake"]

    body = c.post("/api/auth/oauth/exchange", json={"code": q["code"]}).json()
    assert body["email"] == email and body["display_name"] == "octo"
    out = _complete(c, body)
    me = _me(c, out["session"])
    assert me["email"] == email and me["email_verified"] is True
    assert side_effects["photos"] == [(me["id"], github.user["avatar_url"])]
    assert _identity("github", str(gid))["user_id"] == me["id"]


def test_github_bad_code_is_provider_error(c, github):
    _, params = _start(c, "github")
    base.set_transport(
        github.transport({GH_TOKEN: lambda _r: {"error": "bad_verification_code"}})
    )
    r = c.get(
        "/api/auth/oauth/github/callback",
        params={"code": "x", "state": params["state"]},
        follow_redirects=False,
    )
    assert _q(r.headers["location"]) == {"error": "provider_error"}


# ── Facebook ─────────────────────────────────────────────────────────────────

FB_VER = "v24.0"
FB_TOKEN = f"https://graph.facebook.com/{FB_VER}/oauth/access_token"
FB_ME = f"https://graph.facebook.com/{FB_VER}/me"


@pytest.fixture
def facebook(monkeypatch):
    monkeypatch.setattr(settings, "facebook_app_id", "fb-app")
    monkeypatch.setattr(settings, "facebook_app_secret", "fb-secret")
    monkeypatch.setattr(settings, "facebook_graph_version", FB_VER)
    monkeypatch.setattr(settings, "facebook_email_trusted", False)
    idp = FakeIdP("https://www.facebook.com", "fb-app")
    idp.token_params = []
    idp.me_params = []
    idp.me = {}

    def token(req):
        assert req.method == "GET"
        idp.token_params.append(dict(req.url.params))
        return {"access_token": "fb-at", "token_type": "bearer", "expires_in": 5183}

    def me(req):
        idp.me_params.append(dict(req.url.params))
        return idp.me

    base.set_transport(idp.transport({FB_TOKEN: token, FB_ME: me}))
    return idp


def test_facebook_web_flow_untrusted_email(c, facebook, side_effects):
    url, params = _start(c, "facebook")
    assert url == f"https://www.facebook.com/{FB_VER}/dialog/oauth"
    callback = public_url("/api/auth/oauth/facebook/callback")
    assert params["client_id"] == "fb-app"
    assert params["redirect_uri"] == callback
    assert params["response_type"] == "code"
    assert params["scope"] == "public_profile,email"
    assert params["code_challenge_method"] == "S256"

    fid, email = "fb-" + _uniq(), f"fb{_uniq()}@example.com"
    facebook.me = {
        "id": fid,
        "name": "Fran Bee",
        "email": email,
        "picture": {"data": {"url": "https://x/silhouette", "is_silhouette": True}},
    }
    q = _callback(c, "facebook", code="fb-code", state=params["state"])
    tp = facebook.token_params[-1]
    assert tp["client_id"] == "fb-app" and tp["client_secret"] == "fb-secret"
    assert tp["code"] == "fb-code" and tp["redirect_uri"] == callback
    assert pkce_challenge(tp["code_verifier"]) == params["code_challenge"]
    mp = facebook.me_params[-1]
    assert mp["access_token"] == "fb-at"
    assert (
        mp["appsecret_proof"]
        == hmac.new(b"fb-secret", b"fb-at", hashlib.sha256).hexdigest()
    )

    body = c.post("/api/auth/oauth/exchange", json={"code": q["code"]}).json()
    assert body["email"] == email and body["display_name"] == "Fran Bee"
    out = _complete(c, body)
    me = _me(c, out["session"])
    # FACEBOOK_EMAIL_TRUSTED=false: the address must be verified by mail
    assert me["email"] == email and me["email_verified"] is False
    assert side_effects["mail"] == [{"kind": "verify", "to": email}]
    assert side_effects["photos"] == []  # silhouettes are not imported
    assert _identity("facebook", fid)["user_id"] == me["id"]


# ── Apple ────────────────────────────────────────────────────────────────────

A_ISS = "https://appleid.apple.com"
A_SERVICES = "com.example.voyager.web"
A_BUNDLE = "com.example.voyager.ios"
A_TOKEN = "https://appleid.apple.com/auth/token"
A_KEYS = "https://appleid.apple.com/auth/keys"


@pytest.fixture
def apple(monkeypatch):
    monkeypatch.setattr(settings, "apple_services_id", A_SERVICES)
    monkeypatch.setattr(settings, "apple_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apple_key_id", "KEY1234567")
    monkeypatch.setattr(settings, "apple_private_key", APPLE_PEM)
    monkeypatch.setattr(settings, "apple_native_client_ids", [A_BUNDLE])
    idp = FakeIdP(A_ISS, A_SERVICES)
    idp.token_requests = []
    idp.claims = {}
    idp.refresh = "rt-web"

    def token(req):
        form = _form(req)
        idp.token_requests.append(form)
        # the client secret is an ES256 JWT signed with the configured key
        secret = jwt.decode(
            form["client_secret"],
            APPLE_PUBLIC,
            algorithms=["ES256"],
            audience=A_ISS,
        )
        assert secret["iss"] == "TEAM123456"
        assert secret["sub"] == form["client_id"]
        assert jwt.get_unverified_header(form["client_secret"])["kid"] == "KEY1234567"
        return {
            "access_token": "a-at",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": idp.refresh,
            "id_token": idp.id_token(aud=form["client_id"], **idp.claims),
        }

    base.set_transport(idp.transport({A_TOKEN: token, A_KEYS: lambda _r: idp.jwks()}))
    return idp


def test_apple_web_form_post_flow(c, apple, side_effects):
    url, params = _start(c, "apple")
    assert url == "https://appleid.apple.com/auth/authorize"
    callback = public_url("/api/auth/oauth/apple/callback")
    assert params["client_id"] == A_SERVICES
    assert params["redirect_uri"] == callback
    assert params["response_type"] == "code"
    assert params["response_mode"] == "form_post"
    assert params["scope"] == "name email"
    assert "code_challenge" not in params  # Apple: no PKCE

    sub, email = "a-" + _uniq(), f"{_uniq()}@privaterelay.appleid.com"
    apple.claims = dict(
        sub=sub, nonce=params["nonce"], email=email, email_verified="true"
    )
    user_field = json.dumps({"name": {"firstName": "Ada", "lastName": "Lovelace"}})
    q = _callback(
        c,
        "apple",
        method="POST",
        code="a-code",
        state=params["state"],
        user=user_field,
    )
    form = apple.token_requests[-1]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "a-code"
    assert form["redirect_uri"] == callback
    assert form["client_id"] == A_SERVICES

    body = c.post("/api/auth/oauth/exchange", json={"code": q["code"]}).json()
    assert body["email"] == email and body["display_name"] == "Ada Lovelace"
    out = _complete(c, body)
    me = _me(c, out["session"])
    assert me["email"] == email and me["email_verified"] is True
    row = _identity("apple", sub)
    assert row["user_id"] == me["id"]
    # web secret: the bare refresh token (revoked with the Services ID), sealed
    assert row["secret_enc"] and "rt-web" not in row["secret_enc"]
    assert open_(row["secret_enc"]) == "rt-web"


def test_apple_native_id_token_stores_sealed_secret(c, apple, side_effects):
    sub, email = "a-" + _uniq(), f"{_uniq()}@privaterelay.appleid.com"
    raw_nonce = "raw-" + _uniq()
    token = apple.id_token(
        aud=A_BUNDLE,
        sub=sub,
        nonce=hashlib.sha256(raw_nonce.encode()).hexdigest(),
        email=email,
        email_verified=True,
    )
    apple.refresh = "rt-native"
    r = c.post(
        "/api/auth/oauth/apple/id-token",
        json={
            "id_token": token,
            "nonce": raw_nonce,
            "authorization_code": "native-code",
            "display_name": "Ada Lovelace",
            "client": "ios",
            "device_name": "iPhone",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Ada Lovelace" and body["email"] == email
    form = apple.token_requests[-1]
    assert form["code"] == "native-code"
    assert form["client_id"] == A_BUNDLE  # redeemed with the app's own client
    assert "redirect_uri" not in form

    out = _complete(c, body, client="ios", device_name="iPhone")
    assert out["session"]["refresh_token"]
    me = _me(c, out["session"])
    assert me["email"] == email and me["email_verified"] is True
    row = _identity("apple", sub)
    assert row["user_id"] == me["id"]
    assert row["secret_enc"] and "rt-native" not in row["secret_enc"]
    assert open_(row["secret_enc"]) == f"{A_BUNDLE}|rt-native"

    # a raw (unhashed) nonce in the token is rejected
    bad = apple.id_token(aud=A_BUNDLE, sub=sub, nonce=raw_nonce)
    r = c.post(
        "/api/auth/oauth/apple/id-token",
        json={"id_token": bad, "nonce": raw_nonce, "client": "ios"},
    )
    assert r.status_code == 400 and r.json()["error_code"] == "id_token_invalid"

    # the next native sign-in (no code) signs straight in
    n2 = "raw-" + _uniq()
    again = apple.id_token(
        aud=A_BUNDLE, sub=sub, nonce=hashlib.sha256(n2.encode()).hexdigest()
    )
    r = c.post(
        "/api/auth/oauth/apple/id-token",
        json={"id_token": again, "nonce": n2, "client": "ios"},
    )
    assert r.status_code == 200 and r.json()["status"] == "signed_in"
    assert _me(c, r.json()["session"])["id"] == me["id"]


# ── Discovery reflects configuration ─────────────────────────────────────────


def test_providers_listed_when_env_set(c, google, github, facebook, apple):
    got = {
        p["id"]: (p["configured"], p["id_token"])
        for p in c.get("/api/auth/providers").json()["providers"]
    }
    assert got == {
        "apple": (True, True),
        "google": (True, True),
        "facebook": (True, False),
        "github": (True, False),
    }
