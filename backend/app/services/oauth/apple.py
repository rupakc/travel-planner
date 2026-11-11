"""Sign in with Apple (web form_post flow + native ID-token sign-in)."""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import jwt

from app.core.config import settings
from app.services.oauth.base import OAuthError, ProviderProfile, http_client
from app.services.oauth.jwks import verify_jwt

ISSUER = "https://appleid.apple.com"
AUTHORIZE_URL = "https://appleid.apple.com/auth/authorize"
TOKEN_URL = "https://appleid.apple.com/auth/token"
REVOKE_URL = "https://appleid.apple.com/auth/revoke"
JWKS_URL = "https://appleid.apple.com/auth/keys"
CLIENT_SECRET_TTL_SECONDS = 300

# A secret from native sign-in is "<client_id>|<refresh_token>" so revoke can use the
# client that issued it; web secrets are the bare refresh token (the Services ID).
_SEP = "|"


def _private_key() -> str:
    return settings.apple_private_key.strip().replace("\\n", "\n")


def _key_configured() -> bool:
    return bool(
        settings.apple_team_id and settings.apple_key_id and settings.apple_private_key
    )


def client_secret(client_id: str) -> str:
    """ES256 client-secret JWT for `client_id` (Services ID or bundle ID)."""
    now = int(time.time())
    try:
        return jwt.encode(
            {
                "iss": settings.apple_team_id,
                "iat": now,
                "exp": now + CLIENT_SECRET_TTL_SECONDS,
                "aud": ISSUER,
                "sub": client_id,
            },
            _private_key(),
            algorithm="ES256",
            headers={"kid": settings.apple_key_id},
        )
    except Exception as exc:  # bad PEM, wrong key type
        raise OAuthError("provider_error", "apple private key unusable") from exc


def _truthy(value) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _name_from_user_field(raw) -> str | None:
    """Apple sends `user` (JSON) only on the first authorization."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, dict):
        return None
    parts = [
        p.strip()
        for p in (name.get("firstName"), name.get("lastName"))
        if isinstance(p, str) and p.strip()
    ]
    return " ".join(parts) or None


def _profile(claims: dict, display_name: str | None) -> ProviderProfile:
    email = claims.get("email") if isinstance(claims.get("email"), str) else None
    verified = email is not None and _truthy(claims.get("email_verified"))
    return ProviderProfile(
        subject=str(claims["sub"]),
        email=email,
        email_verified=verified,
        email_trusted=verified,
        display_name=display_name,
        picture_url=None,
    )


async def _token_request(form: dict) -> dict:
    try:
        async with http_client() as client:
            resp = await client.post(TOKEN_URL, data=form)
            body = resp.json()
    except Exception as exc:
        raise OAuthError("provider_error", "apple token request failed") from exc
    if resp.status_code != 200 or not isinstance(body, dict) or "error" in body:
        raise OAuthError("provider_error", "apple token request rejected")
    return body


class AppleProvider:
    id = "apple"
    uses_pkce = False
    callback_methods: tuple[str, ...] = ("POST",)

    def configured(self) -> bool:
        return bool(settings.apple_services_id) and _key_configured()

    def native_configured(self) -> bool:
        # The key is needed to redeem the app's authorization code for a refresh
        # token, which account deletion must revoke.
        return bool(settings.apple_native_client_ids) and _key_configured()

    def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "client_id": settings.apple_services_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "form_post",
            "scope": "name email",
            "state": state,
            "nonce": nonce,
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
        if not self.configured():
            raise OAuthError("provider_unavailable")
        client_id = settings.apple_services_id
        body = await _token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret(client_id),
            }
        )
        id_token = body.get("id_token")
        if not isinstance(id_token, str):
            raise OAuthError("provider_error", "apple returned no id token")
        claims = await verify_jwt(
            id_token,
            jwks_url=JWKS_URL,
            issuers={ISSUER},
            audiences={client_id},
            nonce=nonce,
        )
        refresh = body.get("refresh_token")
        return (
            _profile(claims, _name_from_user_field((form or {}).get("user"))),
            refresh if isinstance(refresh, str) and refresh else None,
        )

    async def verify_native(
        self,
        id_token: str,
        *,
        nonce: str | None,
        authorization_code: str | None = None,
        display_name: str | None = None,
    ) -> tuple[ProviderProfile, str | None]:
        """Native sign-in: verify the app's ID token; redeem its code for a secret."""
        if not self.native_configured():
            raise OAuthError("bad_request")
        claims = await verify_jwt(
            id_token,
            jwks_url=JWKS_URL,
            issuers={ISSUER},
            audiences=set(settings.apple_native_client_ids),
            nonce=nonce,
            nonce_is_hash=True,
        )
        secret = None
        if authorization_code:
            aud = claims["aud"]
            client_id = next(
                (
                    a
                    for a in ([aud] if isinstance(aud, str) else aud)
                    if a in settings.apple_native_client_ids
                ),
                None,
            )
            if client_id is None:
                raise OAuthError("provider_error", "id token audience unusable")
            body = await _token_request(
                {
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "client_id": client_id,
                    "client_secret": client_secret(client_id),
                }
            )
            refresh = body.get("refresh_token")
            if isinstance(refresh, str) and refresh:
                secret = f"{client_id}{_SEP}{refresh}"
        name = display_name.strip() if isinstance(display_name, str) else None
        return _profile(claims, name or None), secret

    async def verify_id_token(
        self, id_token: str, *, nonce: str | None
    ) -> ProviderProfile:
        profile, _ = await self.verify_native(id_token, nonce=nonce)
        return profile

    async def revoke(self, secret: str) -> None:
        if not _key_configured():
            raise OAuthError("provider_unavailable")
        client_id, sep, token = secret.rpartition(_SEP)
        if not sep:
            client_id, token = settings.apple_services_id, secret
        if not client_id:
            raise OAuthError("provider_unavailable")
        try:
            async with http_client() as client:
                resp = await client.post(
                    REVOKE_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret(client_id),
                        "token": token,
                        "token_type_hint": "refresh_token",
                    },
                )
        except Exception as exc:
            raise OAuthError("provider_error", "apple revoke failed") from exc
        if resp.status_code != 200:
            raise OAuthError("provider_error", "apple revoke rejected")


PROVIDER = AppleProvider()
