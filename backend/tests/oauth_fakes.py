"""In-process fake identity provider for OAuth tests."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


class FakeIdP:
    def __init__(self, issuer: str, audience: str, kid: str = "k1"):
        self.issuer = issuer
        self.audience = audience
        self.kid = kid
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def rotate(self, kid: str) -> None:
        self.kid = kid
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict:
        import json

        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def id_token(self, **claims) -> str:
        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": "sub-1",
            "iat": now,
            "exp": now + 600,
        }
        payload.update(claims)
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(
            payload, self._key, algorithm="RS256", headers={"kid": self.kid}
        )

    def transport(self, routes: dict[str, Callable]) -> httpx.MockTransport:
        """routes maps a URL (no query) to a handler(request) -> httpx.Response | dict."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url).split("?")[0]
            fn = routes.get(url)
            if fn is None:
                return httpx.Response(404)
            out = fn(request)
            return (
                out
                if isinstance(out, httpx.Response)
                else httpx.Response(200, json=out)
            )

        return httpx.MockTransport(handler)
