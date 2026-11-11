"""Facebook Login (authorization code + PKCE, Graph API)."""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.oauth.base import (
    OAuthError,
    OAuthProvider,
    ProviderProfile,
    http_client,
)

_ME_FIELDS = "id,name,email,picture.width(256).height(256)"


def _ver() -> str:
    return settings.facebook_graph_version


class FacebookProvider(OAuthProvider):
    id = "facebook"
    uses_pkce = True
    callback_methods = ("GET",)

    def configured(self) -> bool:
        return bool(settings.facebook_app_id and settings.facebook_app_secret)

    def native_configured(self) -> bool:
        return False

    def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        query = urlencode(
            {
                "client_id": settings.facebook_app_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "public_profile,email",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"https://www.facebook.com/{_ver()}/dialog/oauth?{query}"

    async def exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        nonce: str,
        form: dict,
    ) -> tuple[ProviderProfile, str | None]:
        base = f"https://graph.facebook.com/{_ver()}"
        try:
            async with http_client() as client:
                token_resp = await client.get(
                    f"{base}/oauth/access_token",
                    params={
                        "client_id": settings.facebook_app_id,
                        "client_secret": settings.facebook_app_secret,
                        "redirect_uri": redirect_uri,
                        "code": code,
                        "code_verifier": code_verifier,
                    },
                )
                token = _json(token_resp).get("access_token")
                if token_resp.status_code != 200 or not token:
                    raise OAuthError("provider_error", "facebook token exchange failed")
                proof = hmac.new(
                    settings.facebook_app_secret.encode(),
                    token.encode(),
                    hashlib.sha256,
                ).hexdigest()
                me_resp = await client.get(
                    f"{base}/me",
                    params={
                        "fields": _ME_FIELDS,
                        "access_token": token,
                        "appsecret_proof": proof,
                    },
                )
        except httpx.HTTPError as exc:
            raise OAuthError("provider_error", "facebook request failed") from exc
        me = _json(me_resp)
        if me_resp.status_code != 200 or not me.get("id"):
            raise OAuthError("provider_error", "facebook profile failed")
        email = me.get("email") or None
        picture = None
        data = (me.get("picture") or {}).get("data") or {}
        if data.get("url") and not data.get("is_silhouette"):
            picture = data["url"]
        profile = ProviderProfile(
            subject=str(me["id"]),
            email=email,
            email_verified=email is not None,
            email_trusted=bool(settings.facebook_email_trusted),
            display_name=me.get("name") or None,
            picture_url=picture,
        )
        return profile, None


def _json(resp: httpx.Response) -> dict:
    try:
        out = resp.json()
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


PROVIDER = FacebookProvider()
