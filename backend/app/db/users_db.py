"""SQLite persistence for user accounts."""

import logging
import uuid
from datetime import datetime, timezone

import bcrypt

from .database import get_connection
from ..core.config import settings

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
        email=None,
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
    return d


# ── CRUD ──────────────────────────────────────────────────────────────────────


def create_user(
    username: str,
    password: str,
    *,
    email: str | None = None,
    is_admin: bool = False,
    is_first_login: bool = True,
) -> dict:
    # Normalise empty strings to NULL so the UNIQUE constraint on email
    # doesn't reject a second user whose email was omitted.
    if isinstance(email, str):
        email = email.strip() or None
    uid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO users
               (id, username, email, password_hash, is_admin, is_first_login, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                uid,
                username,
                email,
                _hash(password),
                int(is_admin),
                int(is_first_login),
                now,
                now,
            ),
        )
    return get_user_by_username(username)


def get_user_by_username(username: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return _row_to_dict(row) if row else None


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


def change_password(username: str, new_password: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE users
               SET password_hash = ?, is_first_login = 0, updated_at = ?
               WHERE username = ?""",
            (_hash(new_password), now, username),
        )


def deactivate_user(username: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0, updated_at = ? WHERE username = ?",
            (now, username),
        )


def reactivate_user(username: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = 1, updated_at = ? WHERE username = ?",
            (now, username),
        )
