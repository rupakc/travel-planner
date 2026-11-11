import hashlib
import time

import pytest

from app.core.config import settings
from app.services.oauth import base, jwks, registry, secrets_box
from tests.oauth_fakes import FakeIdP

JWKS_URL = "https://idp.test/jwks"
ISS = "https://idp.test"
AUD = "client-1"


@pytest.fixture
def idp():
    idp = FakeIdP(ISS, AUD)
    calls = {"n": 0}

    def serve(_req):
        calls["n"] += 1
        return idp.jwks()

    idp.calls = calls
    jwks.clear_cache()
    base.set_transport(idp.transport({JWKS_URL: serve}))
    yield idp
    base.set_transport(None)
    jwks.clear_cache()


def test_pkce_rfc7636_vector():
    assert (
        base.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_pkce_verifier_length_and_uniqueness():
    a, b = base.pkce_verifier(), base.pkce_verifier()
    assert 43 <= len(a) <= 128 and a != b


async def verify(token, **kw):
    kw.setdefault("issuers", {ISS})
    kw.setdefault("audiences", {AUD})
    return await jwks.verify_jwt(token, jwks_url=JWKS_URL, **kw)


async def test_verify_ok(idp):
    claims = await verify(idp.id_token(nonce="n1", email="a@b.c"), nonce="n1")
    assert claims["sub"] == "sub-1" and claims["email"] == "a@b.c"


async def test_verify_hashed_nonce(idp):
    h = hashlib.sha256(b"raw").hexdigest()
    await verify(idp.id_token(nonce=h), nonce="raw", nonce_is_hash=True)
    with pytest.raises(base.OAuthError):
        await verify(idp.id_token(nonce="raw"), nonce="raw", nonce_is_hash=True)


@pytest.mark.parametrize(
    "claims,kw",
    [
        ({"aud": "other"}, {}),
        ({"iss": "https://evil"}, {}),
        ({"nonce": "wrong"}, {"nonce": "n1"}),
        ({}, {"nonce": "n1"}),
        ({"exp": int(time.time()) - 3600}, {}),
    ],
)
async def test_verify_rejects(idp, claims, kw):
    with pytest.raises(base.OAuthError) as e:
        await verify(idp.id_token(**claims), **kw)
    assert e.value.code == "provider_error"


async def test_verify_rejects_hs256_and_garbage(idp):
    import jwt

    tok = jwt.encode(
        {"iss": ISS, "aud": AUD, "sub": "x", "exp": int(time.time()) + 60},
        "k" * 40,
        algorithm="HS256",
        headers={"kid": "k1"},
    )
    with pytest.raises(base.OAuthError):
        await verify(tok)
    with pytest.raises(base.OAuthError):
        await verify("not-a-jwt")


async def test_keys_cached_and_unknown_kid_refetches_once(idp):
    await verify(idp.id_token())
    await verify(idp.id_token())
    assert idp.calls["n"] == 1
    idp.rotate("k2")
    await verify(idp.id_token())
    assert idp.calls["n"] == 2
    idp.kid = "ghost"
    ghost = idp.id_token()
    idp.kid = "k2"
    with pytest.raises(base.OAuthError):
        await verify(ghost)
    assert idp.calls["n"] == 3  # one refetch, not a loop


def test_get_provider_missing_module_is_none(monkeypatch):
    registry.clear_overrides()
    import importlib

    real = importlib.import_module

    def fake(name, *a, **k):
        if name == "app.services.oauth.google":
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake)
    assert registry.get_provider("google") is None
    assert registry.get_provider("nope") is None
    assert registry.PROVIDER_ORDER == ("apple", "google", "facebook", "github")


def test_override():
    sentinel = object()
    registry.override("github", sentinel)
    try:
        assert registry.get_provider("github") is sentinel
    finally:
        registry.clear_overrides()


def test_secrets_box_roundtrip_and_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "secret-one-secret-one-secret-one!")
    token = secrets_box.seal("refresh-token")
    assert "refresh-token" not in token
    assert secrets_box.open_(token) == "refresh-token"
    monkeypatch.setattr(settings, "jwt_secret_key", "secret-two-secret-two-secret-two!")
    assert secrets_box.open_(token) is None
    assert secrets_box.open_("garbage") is None
