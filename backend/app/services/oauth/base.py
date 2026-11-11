"""Provider protocol, shared types, PKCE helpers and the outbound HTTP client."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class ProviderProfile:
    subject: str
    email: str | None
    email_verified: bool
    email_trusted: bool
    display_name: str | None
    picture_url: str | None


class OAuthError(Exception):
    """A provider failure; `code` is a contract callback error code."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


class OAuthProvider(Protocol):
    id: str
    uses_pkce: bool
    callback_methods: tuple[str, ...]

    def configured(self) -> bool: ...

    def native_configured(self) -> bool: ...

    def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    async def exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        nonce: str,
        form: dict,
    ) -> tuple[ProviderProfile, str | None]: ...

    async def verify_id_token(
        self, id_token: str, *, nonce: str | None
    ) -> ProviderProfile:
        raise OAuthError("bad_request")

    async def revoke(self, secret: str) -> None:
        return None


def pkce_verifier() -> str:
    """43-character URL-safe verifier (32 random bytes)."""
    return secrets.token_urlsafe(32)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Test hook: route every provider call through `transport` (None restores the network)."""
    global _transport
    _transport = transport


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": "Voyager/1"},
        transport=_transport,
    )
