"""Short-lived OAuth tickets (state, handoff, signup, link) and provider identities.

Only the SHA-256 of a ticket is stored; the plaintext is returned once. A
ticket is single use: ``take_ticket`` marks it used in one conditional UPDATE.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from .database import get_connection

KINDS = ("state", "handoff", "signup", "link")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def _now() -> datetime:
    return datetime.now(UTC)


# ── Tickets ──────────────────────────────────────────────────────────────────


def put_ticket(
    kind: str,
    *,
    ttl_s: int,
    provider: str | None = None,
    user_id: str | None = None,
    data: dict | None = None,
    binding: str | None = None,
    binding_hash: str | None = None,
    client_challenge: str | None = None,
) -> str:
    """Store a ticket and return its plaintext. ``binding`` is hashed;
    ``binding_hash`` carries an already hashed binding forward."""
    if kind not in KINDS:
        raise ValueError(f"unknown ticket kind {kind!r}")
    token = secrets.token_urlsafe(32)
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO oauth_tickets
               (hash, kind, provider, user_id, data, binding_hash, client_challenge,
                created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sha256_hex(token),
                kind,
                provider,
                user_id,
                json.dumps(data or {}),
                sha256_hex(binding) if binding is not None else binding_hash,
                client_challenge,
                iso(now),
                iso(now + timedelta(seconds=ttl_s)),
            ),
        )
    return token


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    return d


def peek_ticket(kind: str, token: str, now: datetime) -> dict | None:
    """The unused, unexpired ticket without consuming it, else None."""
    if not token:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM oauth_tickets WHERE hash = ? AND kind = ?
               AND used_at IS NULL AND expires_at > ?""",
            (sha256_hex(token), kind, iso(now)),
        ).fetchone()
    return _row(row)


def take_ticket(kind: str, token: str, now: datetime) -> dict | None:
    """Consume the ticket atomically; None when unknown, used or expired."""
    if not token or len(token) > 512:
        return None
    h = sha256_hex(token)
    with get_connection() as conn:
        cur = conn.execute(
            """UPDATE oauth_tickets SET used_at = ? WHERE hash = ? AND kind = ?
               AND used_at IS NULL AND expires_at > ?""",
            (iso(now), h, kind, iso(now)),
        )
        if cur.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM oauth_tickets WHERE hash = ?", (h,)
        ).fetchone()
    return _row(row)


def release_ticket(kind: str, token: str) -> None:
    """Undo a take (the operation it guarded failed and may be retried)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE oauth_tickets SET used_at = NULL WHERE hash = ? AND kind = ?",
            (sha256_hex(token), kind),
        )


def binding_matches(binding: str | None, binding_hash: str | None) -> bool:
    if not binding or not binding_hash:
        return False
    return hmac.compare_digest(sha256_hex(binding), binding_hash)


# ── Identities ───────────────────────────────────────────────────────────────


def get_identity(provider: str, subject: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_identities WHERE provider = ? AND subject = ?",
            (provider, subject),
        ).fetchone()
    return dict(row) if row else None


def add_identity(
    user_id: str,
    provider: str,
    subject: str,
    *,
    email: str | None,
    email_verified: bool,
    display_name: str | None,
    picture_url: str | None,
    secret_enc: str | None,
) -> None:
    """Raises sqlite3.IntegrityError when (provider, subject) is already linked."""
    now = iso(_now())
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_identities
               (user_id, provider, subject, email, email_verified, display_name,
                picture_url, secret_enc, created_at, last_used_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, provider, subject, email, int(email_verified), display_name,
             picture_url, secret_enc, now, now),
        )  # fmt: skip


def touch_identity(
    identity_id: int,
    *,
    email: str | None,
    email_verified: bool,
    secret_enc: str | None,
) -> None:
    """Record a sign-in; a None ``secret_enc`` keeps the stored secret."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE user_identities SET last_used_at = ?, email = ?,
                   email_verified = ?, secret_enc = COALESCE(?, secret_enc)
               WHERE id = ?""",
            (iso(_now()), email, int(email_verified), secret_enc, identity_id),
        )
