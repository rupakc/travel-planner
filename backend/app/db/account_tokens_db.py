"""Single-use email tokens: verify an email address, reset a password.

Only the SHA-256 hex of a token is stored. Each token expires
``account_token_ttl_minutes`` after issue. Issuing a token deletes the
user's earlier unused tokens of the same purpose, so an older link then
reads as ``invalid``; used tokens are kept (until the hourly purge) so a
second click reads as ``used``.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from ..core.config import settings
from .database import get_connection

Purpose = Literal["verify_email", "reset_password"]


@dataclass(frozen=True)
class TokenError:
    reason: str  # "invalid" | "expired" | "used"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def issue_token(
    user_id: str, purpose: Purpose, email: str, *, now: datetime | None = None
) -> str:
    """A new token for ``email``; returns the plaintext (never stored)."""
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(minutes=settings.account_token_ttl_minutes)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM account_tokens WHERE user_id = ? AND purpose = ?"
            " AND used_at IS NULL",
            (user_id, purpose),
        )
        conn.execute(
            """INSERT INTO account_tokens
               (user_id, purpose, token_hash, email, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, purpose, _hash(token), email.strip().lower(), _iso(now),
             _iso(expires)),
        )  # fmt: skip
    return token


def _check(row, now: datetime) -> TokenError | None:
    if row is None:
        return TokenError("invalid")
    if row["used_at"]:
        return TokenError("used")
    if _parse(row["expires_at"]) <= now:
        return TokenError("expired")
    return None


def _result(row) -> dict:
    return {"user_id": row["user_id"], "email": row["email"], "purpose": row["purpose"]}


def peek_token(token: str, purpose: Purpose, now: datetime) -> dict | TokenError:
    """Like redeem_token, without using the token up."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM account_tokens WHERE token_hash = ? AND purpose = ?",
            (_hash(token or ""), purpose),
        ).fetchone()
    return _check(row, now) or _result(row)


def redeem_token(token: str, purpose: Purpose, now: datetime) -> dict | TokenError:
    """Use a token up: ``{"user_id", "email", "purpose"}`` or a TokenError
    (``invalid`` / ``expired`` / ``used``). Exactly one concurrent redeem wins."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM account_tokens WHERE token_hash = ? AND purpose = ?",
            (_hash(token or ""), purpose),
        ).fetchone()
        err = _check(row, now)
        if err:
            return err
        conn.execute(
            "UPDATE account_tokens SET used_at = ? WHERE id = ?", (_iso(now), row["id"])
        )
    return _result(row)
