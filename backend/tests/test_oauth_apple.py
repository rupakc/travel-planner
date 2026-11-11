import hashlib
import json
import time
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import settings
from app.services.oauth import base, jwks, registry
from app.services.oauth.apple import PROVIDER
from app.services.oauth.base import OAuthError
from tests.oauth_fakes import FakeIdP

ISS = "https://appleid.apple.com"
AUTHORIZE = "https://appleid.apple.com/auth/authorize"
TOKEN = "https://appleid.apple.com/auth/token"
REVOKE = "https://appleid.apple.com/auth/revoke"
KEYS = "https://appleid.apple.com/auth/keys"
SERVICES_ID = "com.example.voyager.web"
BUNDLE_ID = "com.example.voyager.ios"
REDIRECT = "https://voyager.test/api/auth/oauth/apple/callback"

# Freshly generated for this test run; never a real key.
_EC_KEY = ec.generate_private_key(ec.SECP256R1())
PEM = _EC_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode("ascii")
PUBLIC = _EC_KEY.public_key()


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(settings, "apple_services_id", SERVICES_ID)
    monkeypatch.setattr(settings, "apple_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apple_key_id", "KEY1234567")
    monkeypatch.setattr(settings, "apple_private_key", PEM)
    monkeypatch.setattr(settings, "apple_native_client_ids", [BUNDLE_ID])


@pytest.fixture
def idp(creds):
    idp = FakeIdP(ISS, SERVICES_ID)
    idp.requests = []
    idp.token_response = None
    idp.revoke_status = 200

    def token(req):
        idp.requests.append(req)
        if idp.token_response is not None:
            return idp.token_response
        return {
            "access_token": "at",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "rt-web",
            "id_token": idp.id_token(
                nonce="n-1", email="jane@example.com", email_verified="true"
            ),
        }

    def revoke(req):
        idp.requests.append(req)
        return httpx.Response(idp.revoke_status)

    jwks.clear_cache()
    base.set_transport(
        idp.transport({TOKEN: token, REVOKE: revoke, KEYS: lambda _r: idp.jwks()})
    )
    yield idp
    base.set_transport(None)
    jwks.clear_cache()


def _form(req: httpx.Request) -> dict:
    assert req.method == "POST"
    assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
    return dict(parse_qsl(req.content.decode()))


def _secret_claims(client_secret: str, aud_client: str) -> dict:
    header = jwt.get_unverified_header(client_secret)
    assert header["alg"] == "ES256" and header["kid"] == "KEY1234567"
    claims = jwt.decode(
        client_secret,
        PUBLIC,
        algorithms=["ES256"],
        audience="https://appleid.apple.com",
    )
    assert claims["iss"] == "TEAM123456"
    assert claims["sub"] == aud_client
    assert claims["exp"] - claims["iat"] == 300
    assert abs(claims["iat"] - time.time()) < 30
    return claims


# --- configuration -----------------------------------------------------------


def test_registry_finds_apple():
    assert registry.get_provider("apple") is PROVIDER
    assert PROVIDER.id == "apple"
    assert PROVIDER.uses_pkce is False
    assert PROVIDER.callback_methods == ("POST",)


def test_configured_needs_every_credential(creds, monkeypatch):
    assert PROVIDER.configured() is True
    for name in (
        "apple_services_id",
        "apple_team_id",
        "apple_key_id",
        "apple_private_key",
    ):
        with monkeypatch.context() as m:
            m.setattr(settings, name, "")
            assert PROVIDER.configured() is False, name


def test_unconfigured_by_default():
    assert PROVIDER.configured() is False
    assert PROVIDER.native_configured() is False


def test_native_configured(creds, monkeypatch):
    assert PROVIDER.native_configured() is True
    with monkeypatch.context() as m:
        m.setattr(settings, "apple_native_client_ids", [])
        assert PROVIDER.native_configured() is False
    with monkeypatch.context() as m:
        m.setattr(settings, "apple_private_key", "")
        assert PROVIDER.native_configured() is False


# --- authorize ---------------------------------------------------------------


def test_authorize_url_has_exactly_the_listed_params(creds):
    url = PROVIDER.authorize_url(
        redirect_uri=REDIRECT, state="st-1", nonce="n-1", code_challenge="ignored"
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == AUTHORIZE
    q = parse_qs(parts.query)
    assert {k: v[0] for k, v in q.items()} == {
        "client_id": SERVICES_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "response_mode": "form_post",
        "scope": "name email",
        "state": "st-1",
        "nonce": "n-1",
    }
    assert all(len(v) == 1 for v in q.values())


# --- client secret -----------------------------------------------------------


def test_client_secret_verifies_with_public_key(creds):
    from app.services.oauth.apple import client_secret

    _secret_claims(client_secret(SERVICES_ID), SERVICES_ID)


def test_escaped_newline_pem_works(creds, monkeypatch):
    from app.services.oauth.apple import client_secret

    escaped = PEM.strip().replace("\n", "\\n")
    assert "\n" not in escaped
    monkeypatch.setattr(settings, "apple_private_key", escaped)
    _secret_claims(client_secret(SERVICES_ID), SERVICES_ID)


def test_bad_private_key_is_provider_error(creds, monkeypatch):
    from app.services.oauth.apple import client_secret

    monkeypatch.setattr(settings, "apple_private_key", "not a pem")
    with pytest.raises(OAuthError) as exc:
        client_secret(SERVICES_ID)
    assert exc.value.code == "provider_error"


# --- web exchange ------------------------------------------------------------


async def test_exchange_builds_token_request_and_maps_profile(idp):
    user = json.dumps(
        {"name": {"firstName": "Jane", "lastName": "Doe"}, "email": "jane@example.com"}
    )
    profile, secret = await PROVIDER.exchange(
        code="c-1",
        redirect_uri=REDIRECT,
        code_verifier="unused",
        nonce="n-1",
        form={"code": "c-1", "state": "st-1", "user": user},
    )
    (req,) = idp.requests
    assert str(req.url) == TOKEN
    form = _form(req)
    assert set(form) == {
        "grant_type",
        "code",
        "redirect_uri",
        "client_id",
        "client_secret",
    }
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "c-1"
    assert form["redirect_uri"] == REDIRECT
    assert form["client_id"] == SERVICES_ID
    _secret_claims(form["client_secret"], SERVICES_ID)

    assert profile == base.ProviderProfile(
        subject="sub-1",
        email="jane@example.com",
        email_verified=True,
        email_trusted=True,
        display_name="Jane Doe",
        picture_url=None,
    )
    assert secret == "rt-web"


async def test_exchange_without_user_field_has_no_name(idp):
    idp.token_response = {
        "refresh_token": "rt-2",
        "id_token": idp.id_token(
            nonce="n-1", email="x@example.com", email_verified=True
        ),
    }
    profile, secret = await PROVIDER.exchange(
        code="c", redirect_uri=REDIRECT, code_verifier="", nonce="n-1", form={}
    )
    assert profile.display_name is None and profile.email_verified is True
    assert secret == "rt-2"


@pytest.mark.parametrize(
    "user", ["{not json", json.dumps({"name": {}}), json.dumps(["x"]), ""]
)
async def test_malformed_user_field_gives_no_name(idp, user):
    profile, _ = await PROVIDER.exchange(
        code="c",
        redirect_uri=REDIRECT,
        code_verifier="",
        nonce="n-1",
        form={"user": user},
    )
    assert profile.display_name is None


async def test_first_name_only(idp):
    profile, _ = await PROVIDER.exchange(
        code="c",
        redirect_uri=REDIRECT,
        code_verifier="",
        nonce="n-1",
        form={"user": json.dumps({"name": {"firstName": "Jane"}})},
    )
    assert profile.display_name == "Jane"


async def test_unverified_email_is_untrusted(idp):
    idp.token_response = {
        "id_token": idp.id_token(
            nonce="n-1", email="x@example.com", email_verified="false"
        )
    }
    profile, secret = await PROVIDER.exchange(
        code="c", redirect_uri=REDIRECT, code_verifier="", nonce="n-1", form={}
    )
    assert profile.email_verified is False and profile.email_trusted is False
    assert secret is None


async def test_exchange_rejects_wrong_nonce(idp):
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.exchange(
            code="c", redirect_uri=REDIRECT, code_verifier="", nonce="other", form={}
        )
    assert exc.value.code == "provider_error"


async def test_exchange_rejects_wrong_audience(idp):
    idp.token_response = {"id_token": idp.id_token(nonce="n-1", aud="someone-else")}
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.exchange(
            code="c", redirect_uri=REDIRECT, code_verifier="", nonce="n-1", form={}
        )
    assert exc.value.code == "provider_error"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": "invalid_grant"}),
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"error": "invalid_client"}),
        httpx.Response(200, json={"refresh_token": "rt"}),
    ],
)
async def test_provider_error_responses(idp, response):
    idp.token_response = response
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.exchange(
            code="c", redirect_uri=REDIRECT, code_verifier="", nonce="n-1", form={}
        )
    assert exc.value.code == "provider_error"


async def test_network_failure_is_provider_error(creds):
    def boom(_req):
        raise httpx.ConnectError("down")

    base.set_transport(httpx.MockTransport(boom))
    try:
        with pytest.raises(OAuthError) as exc:
            await PROVIDER.exchange(
                code="c", redirect_uri=REDIRECT, code_verifier="", nonce="n", form={}
            )
        assert exc.value.code == "provider_error"
    finally:
        base.set_transport(None)


async def test_exchange_unconfigured_is_provider_unavailable():
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.exchange(
            code="c", redirect_uri=REDIRECT, code_verifier="", nonce="n", form={}
        )
    assert exc.value.code == "provider_unavailable"


# --- native ------------------------------------------------------------------


def _native_token(idp, raw_nonce="raw-n", **claims):
    claims.setdefault("aud", BUNDLE_ID)
    claims.setdefault("email", "jane@privaterelay.appleid.com")
    claims.setdefault("email_verified", True)
    return idp.id_token(nonce=hashlib.sha256(raw_nonce.encode()).hexdigest(), **claims)


async def test_native_verify_hashed_nonce(idp):
    profile = await PROVIDER.verify_id_token(_native_token(idp), nonce="raw-n")
    assert profile.subject == "sub-1"
    assert profile.email == "jane@privaterelay.appleid.com"
    assert profile.email_verified and profile.email_trusted
    assert profile.display_name is None and profile.picture_url is None
    assert idp.requests == []


async def test_native_rejects_raw_nonce_claim(idp):
    token = idp.id_token(nonce="raw-n", aud=BUNDLE_ID)
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.verify_id_token(token, nonce="raw-n")
    assert exc.value.code == "provider_error"


async def test_native_rejects_web_audience(idp):
    token = _native_token(idp, aud=SERVICES_ID)
    with pytest.raises(OAuthError):
        await PROVIDER.verify_id_token(token, nonce="raw-n")


async def test_native_not_configured_is_bad_request(idp, monkeypatch):
    monkeypatch.setattr(settings, "apple_native_client_ids", [])
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.verify_id_token(_native_token(idp), nonce="raw-n")
    assert exc.value.code == "bad_request"


async def test_native_authorization_code_exchanged_with_token_aud(idp):
    idp.token_response = {"refresh_token": "rt-native", "id_token": "ignored"}
    profile, secret = await PROVIDER.verify_native(
        _native_token(idp),
        nonce="raw-n",
        authorization_code="ac-1",
        display_name="Jane Doe",
    )
    (req,) = idp.requests
    assert str(req.url) == TOKEN
    form = _form(req)
    assert set(form) == {"grant_type", "code", "client_id", "client_secret"}
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "ac-1"
    assert form["client_id"] == BUNDLE_ID
    _secret_claims(form["client_secret"], BUNDLE_ID)
    assert profile.subject == "sub-1" and profile.display_name == "Jane Doe"
    assert secret is not None and secret.endswith("rt-native")


async def test_native_without_code_has_no_secret(idp):
    profile, secret = await PROVIDER.verify_native(_native_token(idp), nonce="raw-n")
    assert secret is None and idp.requests == []
    assert profile.subject == "sub-1"


async def test_native_code_failure_is_provider_error(idp):
    idp.token_response = httpx.Response(400, json={"error": "invalid_grant"})
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.verify_native(
            _native_token(idp), nonce="raw-n", authorization_code="ac"
        )
    assert exc.value.code == "provider_error"


# --- revoke ------------------------------------------------------------------


async def test_revoke_web_secret(idp):
    await PROVIDER.revoke("rt-web")
    (req,) = idp.requests
    assert str(req.url) == REVOKE
    form = _form(req)
    assert form["token"] == "rt-web"
    assert form["token_type_hint"] == "refresh_token"
    assert form["client_id"] == SERVICES_ID
    _secret_claims(form["client_secret"], SERVICES_ID)


async def test_revoke_native_secret_uses_its_client(idp):
    idp.token_response = {"refresh_token": "rt-native"}
    _, secret = await PROVIDER.verify_native(
        _native_token(idp), nonce="raw-n", authorization_code="ac"
    )
    idp.requests.clear()
    await PROVIDER.revoke(secret)
    (req,) = idp.requests
    form = _form(req)
    assert form["token"] == "rt-native"
    assert form["client_id"] == BUNDLE_ID
    _secret_claims(form["client_secret"], BUNDLE_ID)


async def test_revoke_failure_is_provider_error(idp):
    idp.revoke_status = 400
    with pytest.raises(OAuthError) as exc:
        await PROVIDER.revoke("rt-web")
    assert exc.value.code == "provider_error"
