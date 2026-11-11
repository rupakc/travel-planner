"""Google sign-in (authorization code + PKCE, OpenID Connect ID token)."""

from __future__ import annotations

from urllib.parse import urlencode

from app.core.config import settings
from app.services.oauth.base import OAuthError, ProviderProfile, http_client
from app.services.oauth.jwks import verify_jwt

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


def _truthy(value) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _profile(claims: dict) -> ProviderProfile:
    email = claims.get("email") or None
    verified = bool(email) and _truthy(claims.get("email_verified"))
    return ProviderProfile(
        subject=str(claims["sub"]),
        email=email,
        email_verified=verified,
        email_trusted=verified,
        display_name=claims.get("name") or None,
        picture_url=claims.get("picture") or None,
    )


class GoogleProvider:
    id = "google"
    uses_pkce = True
    callback_methods = ("GET",)

    def configured(self) -> bool:
        return bool(settings.google_client_id and settings.google_client_secret)

    def native_configured(self) -> bool:
        return bool(settings.google_native_client_ids)

    def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
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
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code_verifier": code_verifier,
        }
        try:
            async with http_client() as client:
                resp = await client.post(TOKEN_URL, data=data)
            if resp.status_code != 200:
                raise OAuthError("provider_error", f"token endpoint {resp.status_code}")
            id_token = resp.json().get("id_token")
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthError("provider_error") from exc
        if not isinstance(id_token, str) or not id_token:
            raise OAuthError("provider_error", "no id_token")
        claims = await verify_jwt(
            id_token,
            jwks_url=JWKS_URL,
            issuers=ISSUERS,
            audiences={settings.google_client_id},
            nonce=nonce,
        )
        return _profile(claims), None

    async def verify_id_token(
        self, id_token: str, *, nonce: str | None
    ) -> ProviderProfile:
        if not self.native_configured():
            raise OAuthError("bad_request")
        claims = await verify_jwt(
            id_token,
            jwks_url=JWKS_URL,
            issuers=ISSUERS,
            audiences=set(settings.google_native_client_ids),
            nonce=nonce,
        )
        return _profile(claims)

    async def revoke(self, secret: str) -> None:
        return None


PROVIDER = GoogleProvider()
