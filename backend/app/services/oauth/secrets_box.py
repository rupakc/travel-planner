"""Fernet box for stored provider secrets; key HKDF-derived from JWT_SECRET_KEY."""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

_INFO = b"voyager-identity-secret"


def _fernet() -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        settings.jwt_secret_key.encode("utf-8")
    )
    return Fernet(base64.urlsafe_b64encode(key))


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def open_(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return None
