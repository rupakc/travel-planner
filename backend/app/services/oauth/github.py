"""GitHub OAuth provider (authorization code + PKCE S256)."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.oauth.base import (
    OAuthError,
    OAuthProvider,
    ProviderProfile,
    http_client,
)

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
EMAILS_URL = "https://api.github.com/user/emails"


def _pick_email(emails: object) -> str | None:
    """Primary + verified, else the first verified, else None."""
    if not isinstance(emails, list):
        return None
    verified = [
        e
        for e in emails
        if isinstance(e, dict) and e.get("verified") is True and e.get("email")
    ]
    for e in verified:
        if e.get("primary") is True:
            return str(e["email"])
    return str(verified[0]["email"]) if verified else None


class GitHubProvider(OAuthProvider):
    id = "github"
    uses_pkce = True
    callback_methods: tuple[str, ...] = ("GET",)

    def configured(self) -> bool:
        return bool(settings.github_client_id and settings.github_client_secret)

    def native_configured(self) -> bool:
        return False

    def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "client_id": settings.github_client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "allow_signup": "true",
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        nonce: str,
        form: dict,
    ) -> tuple[ProviderProfile, str | None]:
        api_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with http_client() as client:
                resp = await client.post(
                    TOKEN_URL,
                    data={
                        "client_id": settings.github_client_id,
                        "client_secret": settings.github_client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "code_verifier": code_verifier,
                    },
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    raise OAuthError("provider_error")
                body = resp.json()
                token = body.get("access_token") if isinstance(body, dict) else None
                if not token:  # GitHub reports bad codes as 200 + {"error": ...}
                    raise OAuthError("provider_error")
                auth = {**api_headers, "Authorization": f"Bearer {token}"}
                user_resp = await client.get(USER_URL, headers=auth)
                if user_resp.status_code != 200:
                    raise OAuthError("provider_error")
                user = user_resp.json()
                emails_resp = await client.get(EMAILS_URL, headers=auth)
                if emails_resp.status_code != 200:
                    raise OAuthError("provider_error")
                emails = emails_resp.json()
        except OAuthError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthError("provider_error") from exc

        if not isinstance(user, dict) or user.get("id") is None:
            raise OAuthError("provider_error")
        email = _pick_email(emails)
        verified = email is not None
        return (
            ProviderProfile(
                subject=str(user["id"]),
                email=email,
                email_verified=verified,
                email_trusted=verified,
                display_name=user.get("name") or user.get("login"),
                picture_url=user.get("avatar_url"),
            ),
            None,
        )


PROVIDER = GitHubProvider()
