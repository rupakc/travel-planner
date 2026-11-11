from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import settings
from app.services.oauth import base, registry
from app.services.oauth.base import OAuthError
from app.services.oauth.github import PROVIDER

TOKEN = "https://github.com/login/oauth/access_token"
USER = "https://api.github.com/user"
EMAILS = "https://api.github.com/user/emails"


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setattr(settings, "github_client_id", "gh-id")
    monkeypatch.setattr(settings, "github_client_secret", "gh-secret")
    yield
    base.set_transport(None)


def serve(routes, seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        fn = routes.get(str(request.url).split("?")[0])
        if fn is None:
            return httpx.Response(404)
        out = fn(request)
        return out if isinstance(out, httpx.Response) else httpx.Response(200, json=out)

    base.set_transport(httpx.MockTransport(handler))


async def run_exchange():
    return await PROVIDER.exchange(
        code="c1",
        redirect_uri="https://app.test/cb",
        code_verifier="ver",
        nonce="n",
        form={},
    )


def test_registry_finds_provider():
    assert registry.get_provider("github") is PROVIDER


@pytest.mark.parametrize("field", ["github_client_id", "github_client_secret"])
def test_not_configured_when_credential_empty(monkeypatch, field):
    monkeypatch.setattr(settings, field, "")
    assert PROVIDER.configured() is False


def test_configured_and_flags():
    assert PROVIDER.configured() is True
    assert PROVIDER.native_configured() is False
    assert PROVIDER.uses_pkce is True
    assert PROVIDER.callback_methods == ("GET",)


def test_authorize_url_exact_params():
    url = PROVIDER.authorize_url(
        redirect_uri="https://app.test/cb", state="st", nonce="n", code_challenge="ch"
    )
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://github.com/login/oauth/authorize"
    )
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q == {
        "client_id": "gh-id",
        "redirect_uri": "https://app.test/cb",
        "scope": "read:user user:email",
        "state": "st",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "allow_signup": "true",
    }


async def test_exchange_builds_requests_and_maps_profile():
    seen: list[httpx.Request] = []
    serve(
        {
            TOKEN: lambda r: {"access_token": "tok", "token_type": "bearer"},
            USER: lambda r: {
                "id": 4242,
                "login": "octo",
                "name": "Octo Cat",
                "avatar_url": "https://av.test/o.png",
            },
            EMAILS: lambda r: [
                {"email": "a@x.com", "primary": False, "verified": True},
                {"email": "p@x.com", "primary": True, "verified": True},
            ],
        },
        seen,
    )
    profile, secret = await run_exchange()
    assert secret is None
    assert profile.subject == "4242"
    assert profile.email == "p@x.com"
    assert profile.email_verified and profile.email_trusted
    assert profile.display_name == "Octo Cat"
    assert profile.picture_url == "https://av.test/o.png"

    tok = seen[0]
    assert tok.method == "POST" and str(tok.url) == TOKEN
    assert tok.headers["accept"] == "application/json"
    assert {k: v[0] for k, v in parse_qs(tok.content.decode()).items()} == {
        "client_id": "gh-id",
        "client_secret": "gh-secret",
        "code": "c1",
        "redirect_uri": "https://app.test/cb",
        "code_verifier": "ver",
    }
    for req in seen[1:]:
        assert req.headers["authorization"] == "Bearer tok"
        assert req.headers["accept"] == "application/vnd.github+json"
        assert req.headers["x-github-api-version"] == "2022-11-28"
    assert [str(r.url) for r in seen[1:]] == [USER, EMAILS]


async def test_first_verified_email_when_none_primary_verified():
    serve(
        {
            TOKEN: lambda r: {"access_token": "tok"},
            USER: lambda r: {"id": 1, "login": "octo", "name": None},
            EMAILS: lambda r: [
                {"email": "p@x.com", "primary": True, "verified": False},
                {"email": "v@x.com", "primary": False, "verified": True},
            ],
        },
        [],
    )
    profile, _ = await run_exchange()
    assert profile.email == "v@x.com"
    assert profile.display_name == "octo"


async def test_only_unverified_email_gives_none():
    serve(
        {
            TOKEN: lambda r: {"access_token": "tok"},
            USER: lambda r: {"id": 1, "login": "octo"},
            EMAILS: lambda r: [
                {"email": "p@x.com", "primary": True, "verified": False}
            ],
        },
        [],
    )
    profile, _ = await run_exchange()
    assert profile.email is None
    assert not profile.email_verified and not profile.email_trusted
    assert profile.picture_url is None


@pytest.mark.parametrize(
    "token_resp",
    [
        httpx.Response(200, json={"error": "bad_verification_code"}),
        httpx.Response(401, json={"message": "no"}),
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
    ],
)
async def test_token_errors_are_provider_error(token_resp):
    serve({TOKEN: lambda r: token_resp}, [])
    with pytest.raises(OAuthError) as ei:
        await run_exchange()
    assert ei.value.code == "provider_error"


@pytest.mark.parametrize("failing", [USER, EMAILS])
async def test_api_errors_are_provider_error(failing):
    routes = {
        TOKEN: lambda r: {"access_token": "tok"},
        USER: lambda r: {"id": 1, "login": "o"},
        EMAILS: lambda r: [],
    }
    routes[failing] = lambda r: httpx.Response(403, json={"message": "x"})
    serve(routes, [])
    with pytest.raises(OAuthError) as ei:
        await run_exchange()
    assert ei.value.code == "provider_error"
