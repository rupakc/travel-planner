"""SQLite persistence for user accounts."""

import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt

from ..core.config import settings
from .database import get_connection

logger = logging.getLogger(__name__)


# ── Schema ────────────────────────────────────────────────────────────────────


def create_users_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id             TEXT PRIMARY KEY,
                username       TEXT UNIQUE NOT NULL,
                email          TEXT UNIQUE,
                password_hash  TEXT NOT NULL,
                is_admin       INTEGER NOT NULL DEFAULT 0,
                is_first_login INTEGER NOT NULL DEFAULT 1,
                is_active      INTEGER NOT NULL DEFAULT 1,
                created_at     TEXT DEFAULT (datetime('now')),
                updated_at     TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        """)
    # Phase 1 columns/tables (idempotent, additive)
    from .accounts_schema import create_account_tables

    create_account_tables()


def seed_admin() -> None:
    """Create the initial admin account on first startup if it doesn't exist."""
    password = settings.admin_password
    if not password:
        logger.warning("ADMIN_PASSWORD not set — skipping admin account seed")
        return

    existing = get_user_by_username(settings.admin_username)
    if existing:
        return

    create_user(
        username=settings.admin_username,
        password=password,
        is_admin=True,
        is_first_login=False,  # admin doesn't need to change password on first login
        email=settings.admin_email or None,
    )
    logger.info(f"Admin account '{settings.admin_username}' created")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify(password: str, hashed: str) -> bool:
    try:
        stored = hashed.encode() if isinstance(hashed, str) else hashed
        return bcrypt.checkpw(password.encode(), stored)
    except Exception:
        return False


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["is_admin"] = bool(d["is_admin"])
    d["is_first_login"] = bool(d["is_first_login"])
    d["is_active"] = bool(d["is_active"])
    if "email_verified" in d:
        d["email_verified"] = bool(d["email_verified"])
    return d


# ── CRUD ──────────────────────────────────────────────────────────────────────


def create_user(
    username: str,
    password: str | None = None,
    *,
    email: str | None = None,
    is_admin: bool = False,
    is_first_login: bool = True,
    signup_method: str = "admin",
    account_status: str = "active",
    email_verified: bool = False,
    display_name: str | None = None,
    locale: str | None = None,
    password_hash: str | None = None,
) -> dict:
    """``password_hash="!"`` marks an account with no password (social only)."""
    # Normalise empty strings to NULL so the UNIQUE constraint on email
    # doesn't reject a second user whose email was omitted.
    if isinstance(email, str):
        email = email.strip().lower() or None
    if password_hash is None:
        if password is None:
            raise ValueError("create_user needs a password or a password_hash")
        password_hash = _hash(password)
    uid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        if conn.execute(
            "SELECT 1 FROM users WHERE lower(username) = ?", (username.lower(),)
        ).fetchone():
            raise UsernameTakenError(username)
        conn.execute(
            """INSERT INTO users
               (id, username, email, password_hash, is_admin, is_first_login, is_active,
                created_at, updated_at, signup_method, account_status, email_verified,
                display_name, locale)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uid,
                username,
                email,
                password_hash,
                int(is_admin),
                int(is_first_login),
                now,
                now,
                signup_method,
                account_status,
                int(email_verified),
                display_name,
                locale,
            ),
        )
    return get_user_by_username(username)


def get_user_by_username(username: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


class EmailInUseError(Exception):
    """Another account already uses this email address."""


class UsernameTakenError(sqlite3.IntegrityError):
    """Another account already holds this username (an IntegrityError so the
    admin route's existing 409 handling covers it)."""


def set_email(username: str, email: str | None) -> None:
    """Set (or clear with None) a user's email; raises EmailInUseError."""
    now = datetime.now(UTC).isoformat()
    if isinstance(email, str):
        email = email.strip().lower() or None
    try:
        with get_connection() as conn:
            conn.execute(
                """UPDATE users SET
                       email_verified = CASE WHEN email IS ? THEN email_verified ELSE 0 END,
                       email = ?, updated_at = ? WHERE username = ?""",
                (email, email, now, username),
            )
    except sqlite3.IntegrityError as exc:
        raise EmailInUseError from exc


def get_all_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def authenticate_user(username: str, password: str) -> dict | None:
    """Return user dict if credentials are valid and account is active, else None."""
    user = get_user_by_username(username)
    if not user or not user["is_active"]:
        return None
    if not _verify(password, user["password_hash"]):
        return None
    return user


def _set_password(
    username: str, new_password: str, *, force_change: bool, bump: bool = False
) -> None:
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE users
               SET password_hash = ?, is_first_login = ?, updated_at = ?,
                   token_version = token_version + ?
               WHERE username = ?""",
            (_hash(new_password), int(force_change), now, int(bump), username),
        )


def change_password(username: str, new_password: str) -> None:
    """Self-service password change — clears the forced-change flag."""
    _set_password(username, new_password, force_change=False)


def admin_reset_password(username: str, new_password: str) -> None:
    """Admin-initiated password reset — forces the user to change on next login."""
    _set_password(username, new_password, force_change=True, bump=True)


def deactivate_user(username: str) -> None:
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0, token_version = token_version + 1,"
            " updated_at = ? WHERE username = ?",
            (now, username),
        )


def reactivate_user(username: str) -> None:
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = 1, updated_at = ? WHERE username = ?",
            (now, username),
        )


# ── Phase 1: sign-up, lookup and session helpers ─────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_user_by_email(email: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(email) = ?", (email.strip().lower(),)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_user_by_login(identifier: str) -> dict | None:
    """Exact username, else case-insensitive username, else lower-cased email."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    with get_connection() as conn:
        row = (
            conn.execute("SELECT * FROM users WHERE username = ?", (ident,)).fetchone()
            or conn.execute(
                "SELECT * FROM users WHERE lower(username) = ?", (ident.lower(),)
            ).fetchone()
            or conn.execute(
                "SELECT * FROM users WHERE lower(email) = ?", (ident.lower(),)
            ).fetchone()
        )
    return _row_to_dict(row) if row else None


def _delete_user_rows(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute("DELETE FROM account_tokens WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def _holder_blocks(conn: sqlite3.Connection, name: str, now: datetime) -> bool:
    """True when a live account holds ``name`` (case-insensitive). A pending
    holder whose newest token has expired is released (deleted). A pending
    holder with no token yet expires ``account_token_ttl_minutes`` after it
    was created."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    ttl = int(getattr(settings, "account_token_ttl_minutes", 30))
    for row in conn.execute(
        "SELECT id, account_status, created_at FROM users WHERE lower(username) = ?",
        (name.strip().lower(),),
    ).fetchall():
        if row["account_status"] != "pending":
            return True
        newest = conn.execute(
            "SELECT MAX(expires_at) AS m FROM account_tokens WHERE user_id = ?",
            (row["id"],),
        ).fetchone()["m"]
        if newest:
            expiry = datetime.fromisoformat(newest)
        else:
            expiry = datetime.fromisoformat(row["created_at"]) + timedelta(minutes=ttl)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry > now:
            return True
        _delete_user_rows(conn, row["id"])
    return False


def username_available(name: str, now: datetime) -> bool:
    with get_connection() as conn:
        return not _holder_blocks(conn, name, now)


def create_pending_user(
    username: str,
    email: str,
    password: str,
    display_name: str | None,
    locale: str | None,
    invite_id: int | None,
) -> dict:
    """Self-service sign-up row (unverified). Replaces a pending row with the
    same email; raises UsernameTakenError / EmailInUseError."""
    email = email.strip().lower()
    now = datetime.now(UTC)
    pw_hash = _hash(password)
    uid = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for row in conn.execute(
            "SELECT id FROM users WHERE lower(email) = ? AND account_status = 'pending'",
            (email,),
        ).fetchall():
            _delete_user_rows(conn, row["id"])
        if _holder_blocks(conn, username, now):
            raise UsernameTakenError
        if conn.execute(
            "SELECT 1 FROM users WHERE lower(email) = ?", (email,)
        ).fetchone():
            raise EmailInUseError
        conn.execute(
            """INSERT INTO users
               (id, username, email, password_hash, is_admin, is_first_login, is_active,
                created_at, updated_at, signup_method, account_status, email_verified,
                display_name, locale, invite_id)
               VALUES (?, ?, ?, ?, 0, 0, 1, ?, ?, 'password', 'pending', 0, ?, ?, ?)""",
            (uid, username, email, pw_hash, now.isoformat(), now.isoformat(),
             display_name, locale, invite_id),
        )  # fmt: skip
    return get_user_by_id(uid)


def activate_user(user_id: str, email: str) -> None:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE users SET account_status = 'active', email_verified = 1,
                   verified_at = COALESCE(verified_at, ?), updated_at = ?
               WHERE id = ?""",
            (now, now, user_id),
        )


def mark_email_verified(user_id: str, email: str) -> bool:
    """False when the account's email is no longer ``email``."""
    now = _now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            """UPDATE users SET email_verified = 1,
                   verified_at = COALESCE(verified_at, ?), updated_at = ?
               WHERE id = ? AND lower(email) = ?""",
            (now, now, user_id, email.strip().lower()),
        )
    return cur.rowcount > 0


def bump_token_version(user_id: str) -> int:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET token_version = token_version + 1 WHERE id = ?",
            (user_id,),
        )
        row = conn.execute(
            "SELECT token_version FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return row["token_version"] if row else 0


def set_display_name(user_id: str, name: str | None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?",
            (name, _now_iso(), user_id),
        )


def set_avatar(user_id: str, source: str | None) -> int:
    """Set (or clear with None) the avatar source; returns the new avatar_rev."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE users SET avatar_source = ?, avatar_rev = avatar_rev + 1,
                   updated_at = ? WHERE id = ?""",
            (source, _now_iso(), user_id),
        )
        row = conn.execute(
            "SELECT avatar_rev FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return row["avatar_rev"] if row else 0


def touch_last_login(user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?", (_now_iso(), user_id)
        )


def count_active_admins() -> int:
    with get_connection() as conn:
        return conn.execute(
            """SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1
               AND account_status = 'active'"""
        ).fetchone()[0]


def delete_user_row(user_id: str) -> None:
    with get_connection() as conn:
        _delete_user_rows(conn, user_id)
