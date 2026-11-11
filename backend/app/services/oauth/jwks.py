"""ID-token verification against a provider's JWKS (RS256/ES256 only)."""

from __future__ import annotations

import hashlib
import hmac
import time

import jwt

from app.services.oauth.base import OAuthError, http_client

ALGORITHMS = ["RS256", "ES256"]
LEEWAY_SECONDS = 60
CACHE_TTL_SECONDS = 3600

_cache: dict[str, tuple[float, dict[str, dict]]] = {}


def clear_cache() -> None:
    _cache.clear()


async def _fetch(jwks_url: str) -> dict[str, dict]:
    try:
        async with http_client() as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            keys = resp.json().get("keys", [])
    except Exception as exc:
        raise OAuthError("provider_error") from exc
    by_kid = {k["kid"]: k for k in keys if isinstance(k, dict) and "kid" in k}
    _cache[jwks_url] = (time.monotonic(), by_kid)
    return by_kid


async def _key_for(jwks_url: str, kid: str):
    entry = _cache.get(jwks_url)
    keys = (
        entry[1]
        if entry and time.monotonic() - entry[0] < CACHE_TTL_SECONDS
        else await _fetch(jwks_url)
    )
    if kid not in keys:
        keys = await _fetch(jwks_url)  # unknown kid: refetch once
    jwk = keys.get(kid)
    if jwk is None:
        raise OAuthError("provider_error", "unknown signing key")
    return jwt.PyJWK.from_dict(jwk).key


async def verify_jwt(
    token: str,
    *,
    jwks_url: str,
    issuers: set[str],
    audiences: set[str],
    nonce: str | None = None,
    nonce_is_hash: bool = False,
) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise OAuthError("provider_error", "malformed id token") from exc
    kid = header.get("kid")
    if header.get("alg") not in ALGORITHMS or not kid:
        raise OAuthError("provider_error", "unacceptable id token header")
    key = await _key_for(jwks_url, kid)
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=ALGORITHMS,
            audience=list(audiences),
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthError("provider_error", "id token rejected") from exc
    if claims.get("iss") not in issuers:
        raise OAuthError("provider_error", "bad issuer")
    if nonce is not None:
        expected = (
            hashlib.sha256(nonce.encode("utf-8")).hexdigest()
            if nonce_is_hash
            else nonce
        )
        got = claims.get("nonce")
        if not isinstance(got, str) or not hmac.compare_digest(
            got.encode(), expected.encode()
        ):
            raise OAuthError("provider_error", "nonce mismatch")
    return claims


__all__ = ["verify_jwt", "clear_cache"]
