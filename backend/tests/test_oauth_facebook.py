import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import settings
from app.services.oauth import base
from app.services.oauth.base import OAuthError, pkce_challenge
from app.services.oauth.facebook import PROVIDER

TOKEN_URL = "https://graph.facebook.com/v24.0/oauth/access_token"
ME_URL = "https://graph.facebook.com/v24.0/me"


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setattr(settings, "facebook_app_id", "app-1")
    monkeypatch.setattr(settings, "facebook_app_secret", "shh")
    monkeypatch.setattr(settings, "facebook_graph_version", "v24.0")
    yield
    base.set_transport(None)


def _transport(me, token_status=200, me_status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        url = str(request.url).split("?")[0]
        if url == TOKEN_URL:
            if token_status != 200:
                return httpx.Response(token_status, json={"error": {"message": "x"}})
            return httpx.Response(200, json={"access_token": "tok-1"})
        if url == ME_URL:
            return httpx.Response(me_status, json=me)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _exchange():
    return PROVIDER.exchange(
        code="c1", redirect_uri="https://x/cb", code_verifier="ver", nonce="n", form={}
    )


@pytest.mark.parametrize("field", ["facebook_app_id", "facebook_app_secret"])
def test_not_configured_when_credential_empty(monkeypatch, field):
    assert PROVIDER.configured()
    monkeypatch.setattr(settings, field, "")
    assert not PROVIDER.configured()
    assert not PROVIDER.native_configured()


def test_authorize_url_parameters():
    url = PROVIDER.authorize_url(
        redirect_uri="https://x/cb",
        state="st",
        nonce="n",
        code_challenge=pkce_challenge("v"),
    )
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://www.facebook.com/v24.0/dialog/oauth"
    )
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q == {
        "client_id": "app-1",
        "redirect_uri": "https://x/cb",
        "response_type": "code",
        "scope": "public_profile,email",
        "state": "st",
        "code_challenge": pkce_challenge("v"),
        "code_challenge_method": "S256",
    }
    assert PROVIDER.uses_pkce and PROVIDER.callback_methods == ("GET",)


async def test_exchange_builds_requests_and_maps_profile():
    seen = []
    base.set_transport(
        _transport(
            {
                "id": 123,
                "name": "Ada",
                "email": "ada@example.com",
                "picture": {"data": {"url": "https://p/1.jpg", "is_silhouette": False}},
            },
            seen=seen,
        )
    )
    profile, secret = await _exchange()
    assert secret is None
    assert profile.subject == "123"
    assert profile.email == "ada@example.com"
    assert profile.email_verified is True
    assert profile.display_name == "Ada"
    assert profile.picture_url == "https://p/1.jpg"

    tok, me = seen
    assert dict(tok.url.params) == {
        "client_id": "app-1",
        "client_secret": "shh",
        "redirect_uri": "https://x/cb",
        "code": "c1",
        "code_verifier": "ver",
    }
    expected = hmac.new(b"shh", b"tok-1", hashlib.sha256).hexdigest()
    assert dict(me.url.params) == {
        "fields": "id,name,email,picture.width(256).height(256)",
        "access_token": "tok-1",
        "appsecret_proof": expected,
    }


async def test_email_trusted_false_by_default_and_configurable(monkeypatch):
    base.set_transport(_transport({"id": "1", "email": "a@b.co"}))
    profile, _ = await _exchange()
    assert profile.email_trusted is False
    monkeypatch.setattr(settings, "facebook_email_trusted", True)
    profile, _ = await _exchange()
    assert profile.email_trusted is True


async def test_no_email_and_silhouette_picture():
    base.set_transport(
        _transport(
            {
                "id": "1",
                "picture": {"data": {"url": "https://p/s.jpg", "is_silhouette": True}},
            }
        )
    )
    profile, _ = await _exchange()
    assert profile.email is None
    assert profile.email_verified is False
    assert profile.picture_url is None


async def test_token_error_is_provider_error():
    base.set_transport(_transport({}, token_status=400))
    with pytest.raises(OAuthError) as e:
        await _exchange()
    assert e.value.code == "provider_error"


async def test_profile_error_is_provider_error():
    base.set_transport(_transport({"error": {"message": "bad"}}, me_status=400))
    with pytest.raises(OAuthError) as e:
        await _exchange()
    assert e.value.code == "provider_error"


async def test_network_error_is_provider_error():
    def boom(request):
        raise httpx.ConnectError("down")

    base.set_transport(httpx.MockTransport(boom))
    with pytest.raises(OAuthError) as e:
        await _exchange()
    assert e.value.code == "provider_error"


async def test_unsupported_methods_via_registry():
    from app.services.oauth.registry import get_provider

    provider = get_provider("facebook")
    assert provider is PROVIDER
    with pytest.raises(OAuthError) as e:
        await provider.verify_id_token("tok", nonce=None)
    assert e.value.code == "bad_request"
    assert await provider.revoke("secret") is None
