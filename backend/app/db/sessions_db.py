"""Mobile refresh tokens: rotating, single-use, grouped into families.

Only the SHA-256 hex of a token is stored. Each refresh rotates the token
(the old row gets ``rotated_at``, a new row joins the same family). Reusing
an already-rotated token within ``REFRESH_GRACE_SECONDS`` is the loser of a
concurrent refresh (``stale``, family kept); later reuse is treated as theft
and revokes the whole family (``invalid``).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..core.config import settings
from .database import get_connection

REFRESH_GRACE_SECONDS = 30
TOKEN_PREFIX = "rt_"


@dataclass(frozen=True)
class RefreshError:
    reason: str  # "stale" | "invalid"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _insert(
    conn,
    *,
    user_id: str,
    family_id: str,
    client: str,
    device_name: str | None,
    token_version: int,
    now: datetime,
    family_expires_at: datetime,
) -> str:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires = min(now + timedelta(days=settings.refresh_token_days), family_expires_at)
    conn.execute(
        """INSERT INTO refresh_tokens
           (id, user_id, family_id, token_hash, client, device_name, token_version,
            created_at, expires_at, family_expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), user_id, family_id, _hash(token), client, device_name,
         token_version, _iso(now), _iso(expires), _iso(family_expires_at)),
    )  # fmt: skip
    return token


def create_refresh(
    user_id: str,
    client: str,
    device_name: str | None,
    token_version: int,
    *,
    now: datetime | None = None,
) -> str:
    """Start a new family; returns the plaintext token (never stored)."""
    now = now or datetime.now(UTC)
    with get_connection() as conn:
        return _insert(
            conn,
            user_id=user_id,
            family_id=str(uuid.uuid4()),
            client=client,
            device_name=device_name,
            token_version=token_version,
            now=now,
            family_expires_at=now + timedelta(days=settings.refresh_family_max_days),
        )


def _revoke_family(conn, family_id: str, now: datetime) -> None:
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE family_id = ? AND revoked_at IS NULL",
        (_iso(now), family_id),
    )


def rotate_refresh(token: str, now: datetime) -> tuple[str, dict] | RefreshError:
    """Swap ``token`` for a new one in its family; returns (new token, user row).

    Runs inside ``BEGIN IMMEDIATE`` so two concurrent refreshes with the same
    token serialise: one rotates, the other sees ``rotated_at`` → ``stale``.
    """
    if not token or not token.startswith(TOKEN_PREFIX):
        return RefreshError("invalid")
    from .users_db import _row_to_dict

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ?", (_hash(token),)
        ).fetchone()
        if row is None or row["revoked_at"]:
            return RefreshError("invalid")
        if row["rotated_at"]:
            if now - _parse(row["rotated_at"]) <= timedelta(
                seconds=REFRESH_GRACE_SECONDS
            ):
                return RefreshError("stale")
            _revoke_family(conn, row["family_id"], now)
            return RefreshError("invalid")
        if _parse(row["expires_at"]) <= now or _parse(row["family_expires_at"]) <= now:
            return RefreshError("invalid")
        urow = conn.execute(
            "SELECT * FROM users WHERE id = ?", (row["user_id"],)
        ).fetchone()
        user = _row_to_dict(urow) if urow else None
        if (
            user is None
            or not user["is_active"]
            or user.get("account_status", "active") != "active"
            or int(user.get("token_version") or 0) != row["token_version"]
        ):
            _revoke_family(conn, row["family_id"], now)
            return RefreshError("invalid")
        conn.execute(
            "UPDATE refresh_tokens SET rotated_at = ?, last_used_at = ? WHERE id = ?",
            (_iso(now), _iso(now), row["id"]),
        )
        new = _insert(
            conn,
            user_id=row["user_id"],
            family_id=row["family_id"],
            client=row["client"],
            device_name=row["device_name"],
            token_version=row["token_version"],
            now=now,
            family_expires_at=_parse(row["family_expires_at"]),
        )
    return new, user


def revoke_family_of(token: str) -> None:
    """Revoke every token in ``token``'s family (unknown tokens: no-op)."""
    if not token:
        return
    now = datetime.now(UTC)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT family_id FROM refresh_tokens WHERE token_hash = ?",
            (_hash(token),),
        ).fetchone()
        if row:
            _revoke_family(conn, row["family_id"], now)


def revoke_all(user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (_iso(datetime.now(UTC)), user_id),
        )


def list_families(user_id: str, now: datetime) -> list[dict]:
    """Live refresh families of a user (not revoked, not expired), newest first.

    A family is live while it has an unrotated, unrevoked, unexpired token.
    ``created_at`` is the family's first token, ``last_used_at`` its latest use.
    ``token_hash`` is the live token's hash (for the ``current`` comparison only).
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT family_id, client, device_name, token_hash, expires_at,
                      family_expires_at,
                      (SELECT MIN(created_at) FROM refresh_tokens f
                        WHERE f.family_id = t.family_id) AS first_at,
                      (SELECT MAX(last_used_at) FROM refresh_tokens f
                        WHERE f.family_id = t.family_id) AS used_at
               FROM refresh_tokens t
               WHERE user_id = ? AND revoked_at IS NULL AND rotated_at IS NULL""",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        if _parse(r["expires_at"]) <= now or _parse(r["family_expires_at"]) <= now:
            continue
        out.append(
            {
                "id": r["family_id"],
                "client": r["client"],
                "device_name": r["device_name"],
                "created_at": r["first_at"],
                "last_used_at": r["used_at"] or r["first_at"],
                "token_hash": r["token_hash"],
            }
        )
    out.sort(key=lambda s: s["last_used_at"], reverse=True)
    return out


def hash_token(token: str) -> str:
    return _hash(token)


def revoke_family(user_id: str, family_id: str, now: datetime) -> bool:
    """Revoke a live family owned by ``user_id``; False if there is none."""
    with get_connection() as conn:
        live = conn.execute(
            """SELECT 1 FROM refresh_tokens
               WHERE user_id = ? AND family_id = ? AND revoked_at IS NULL
               LIMIT 1""",
            (user_id, family_id),
        ).fetchone()
        if not live:
            return False
        _revoke_family(conn, family_id, now)
        return True
