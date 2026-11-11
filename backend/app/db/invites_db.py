"""Invite codes for SIGNUP_MODE=invite. Only the SHA-256 of the normalised
code is stored; the plaintext is returned once, at creation."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from .database import get_connection

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch not in " -\t\n")


def _hash(code: str) -> str:
    return hashlib.sha256(_norm(code).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _group() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(4))


def create_invite(
    created_by: str | None,
    max_uses: int = 1,
    expires_in_days: int = 14,
    note: str | None = None,
) -> dict:
    now = datetime.now(UTC)
    expires = (now + timedelta(days=expires_in_days)).isoformat()
    for _ in range(10):
        a, b = _group(), _group()
        code = f"VOY-{a}-{b}"
        try:
            with get_connection() as conn:
                cur = conn.execute(
                    "INSERT INTO invite_codes (code_hash, code_prefix, note, max_uses,"
                    " uses, created_by, created_at, expires_at) VALUES (?,?,?,?,0,?,?,?)",
                    (
                        _hash(code),
                        f"VOY-{a}",
                        note,
                        max_uses,
                        created_by,
                        now.isoformat(),
                        expires,
                    ),
                )
                invite_id = cur.lastrowid
        except Exception as exc:  # unique collision on code_hash: retry
            if "UNIQUE" in str(exc):
                continue
            raise
        return {
            "id": invite_id,
            "code": code,
            "code_prefix": f"VOY-{a}",
            "max_uses": max_uses,
            "uses": 0,
            "expires_at": expires,
            "note": note,
        }
    raise RuntimeError("could not generate a unique invite code")


def check_invite(code: str) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM invite_codes WHERE code_hash = ? AND uses < max_uses"
            " AND revoked_at IS NULL AND expires_at > ?",
            (_hash(code), _now()),
        ).fetchone()
    return row["id"] if row else None


def consume_invite(code: str) -> int | None:
    h = _hash(code)
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE invite_codes SET uses = uses + 1 WHERE code_hash = ?"
            " AND uses < max_uses AND revoked_at IS NULL AND expires_at > ?",
            (h, _now()),
        )
        if cur.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT id FROM invite_codes WHERE code_hash = ?", (h,)
        ).fetchone()
    return row["id"]


def list_invites() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, code_prefix, max_uses, uses, expires_at, revoked_at, note,"
            " created_at FROM invite_codes ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_invite(invite_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE invite_codes SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
            (_now(), invite_id),
        )
        return cur.rowcount == 1
