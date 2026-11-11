from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import settings
from app.services.oauth import base, jwks, registry
from app.services.oauth.base import OAuthError
from app.services.oauth.google import JWKS_URL, PROVIDER, TOKEN_URL
from tests.oauth_fakes import FakeIdP

CID = "gid.apps.googleusercontent.com"


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", CID)
    monkeypatch.setattr(settings, "google_client_secret", "gsecret")
    monkeypatch.setattr(settings, "google_native_client_ids", [])
    jwks.clear_cache()
    yield
    base.set_transport(None)
    jwks.clear_cache()


def _idp(token_handler):
    idp = FakeIdP("https://accounts.google.com", CID)
    base.set_transport(
        idp.transport({JWKS_URL: lambda r: idp.jwks(), TOKEN_URL: token_handler})
    )
    return idp


def test_registry_discovers_provider():
    assert registry.get_provider("google") is PROVIDER


@pytest.mark.parametrize("cid,secret", [("", "s"), ("c", ""), ("", "")])
def test_configured_false_when_credential_empty(monkeypatch, cid, secret):
    monkeypatch.setattr(settings, "google_client_id", cid)
    monkeypatch.setattr(settings, "google_client_secret", secret)
    assert PROVIDER.configured() is False


def test_configured_true():
    assert PROVIDER.configured() is True


def test_authorize_url_params():
    url = PROVIDER.authorize_url(
        redirect_uri="https://app/cb", state="st", nonce="no", code_challenge="ch"
    )
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q == {
        "client_id": CID,
        "redirect_uri": "https://app/cb",
        "response_type": "code",
        "scope": "openid email profile",
        "state": "st",
        "nonce": "no",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }


async def test_exchange_builds_request_and_maps_profile():
    seen = {}
    idp = None

    def token(req: httpx.Request):
        seen["method"] = req.method
        seen["form"] = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        return {
            "id_token": idp.id_token(
                sub="g-1",
                email="a@b.com",
                email_verified="true",
                name="Ann",
                picture="https://img/a.png",
                nonce="n1",
            )
        }

    idp = _idp(token)
    profile, secret = await PROVIDER.exchange(
        code="c1",
        redirect_uri="https://app/cb",
        code_verifier="v1",
        nonce="n1",
        form={},
    )
    assert seen["method"] == "POST"
    assert seen["form"] == {
        "grant_type": "authorization_code",
        "code": "c1",
        "redirect_uri": "https://app/cb",
        "client_id": CID,
        "client_secret": "gsecret",
        "code_verifier": "v1",
    }
    assert secret is None
    assert profile.subject == "g-1"
    assert profile.email == "a@b.com"
    assert profile.email_verified and profile.email_trusted
    assert profile.display_name == "Ann"
    assert profile.picture_url == "https://img/a.png"


async def test_unverified_email_not_trusted():
    idp = None
    idp = _idp(
        lambda r: {
            "id_token": idp.id_token(email="a@b.com", email_verified=False, nonce="n")
        }
    )
    profile, _ = await PROVIDER.exchange(
        code="c", redirect_uri="r", code_verifier="v", nonce="n", form={}
    )
    assert profile.email == "a@b.com"
    assert not profile.email_verified and not profile.email_trusted


async def test_provider_error_response():
    _idp(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(OAuthError) as ei:
        await PROVIDER.exchange(
            code="c", redirect_uri="r", code_verifier="v", nonce="n", form={}
        )
    assert ei.value.code == "provider_error"


async def test_nonce_mismatch_and_wrong_audience_rejected():
    idp = None
    idp = _idp(lambda r: {"id_token": idp.id_token(nonce="other")})
    with pytest.raises(OAuthError) as ei:
        await PROVIDER.exchange(
            code="c", redirect_uri="r", code_verifier="v", nonce="n", form={}
        )
    assert ei.value.code == "provider_error"
    idp2 = _idp(lambda r: {"id_token": idp2.id_token(aud="someone-else", nonce="n")})
    with pytest.raises(OAuthError):
        await PROVIDER.exchange(
            code="c", redirect_uri="r", code_verifier="v", nonce="n", form={}
        )


async def test_alt_issuer_accepted(monkeypatch):
    idp = FakeIdP("accounts.google.com", CID)
    base.set_transport(idp.transport({JWKS_URL: lambda r: idp.jwks()}))
    monkeypatch.setattr(settings, "google_native_client_ids", [CID])
    p = await PROVIDER.verify_id_token(idp.id_token(email="x@y.z"), nonce=None)
    assert p.email == "x@y.z"


def test_native_configured(monkeypatch):
    assert PROVIDER.native_configured() is False
    monkeypatch.setattr(settings, "google_native_client_ids", ["ios-id"])
    assert PROVIDER.native_configured() is True


async def test_verify_id_token_native_audience(monkeypatch):
    monkeypatch.setattr(settings, "google_native_client_ids", ["ios-id", "and-id"])
    idp = FakeIdP("https://accounts.google.com", "ios-id")
    base.set_transport(idp.transport({JWKS_URL: lambda r: idp.jwks()}))
    p = await PROVIDER.verify_id_token(
        idp.id_token(sub="s9", email="n@x.io", email_verified=True, nonce="nn"),
        nonce="nn",
    )
    assert p.subject == "s9" and p.email_verified
    # the web client id is not a native audience
    bad = FakeIdP("https://accounts.google.com", CID)
    base.set_transport(bad.transport({JWKS_URL: lambda r: bad.jwks()}))
    with pytest.raises(OAuthError):
        await PROVIDER.verify_id_token(bad.id_token(), nonce=None)


async def test_verify_id_token_unconfigured_native():
    with pytest.raises(OAuthError):
        await PROVIDER.verify_id_token("x.y.z", nonce=None)
